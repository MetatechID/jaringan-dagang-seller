"""Catalog importer REST endpoints.

POST   /imports                  upload XLSX/CSV, parse + return preview
GET    /imports/{id}             fetch job + preview rows
PATCH  /imports/{id}/mapping     edit column mapping, recompute preview
POST   /imports/{id}/confirm     commit rows to catalog, fire push-on-search
GET    /imports/sources          list available source adapters

All endpoints scope by store_id query param (default DEMO_STORE_ID, matching
the rest of the seller-dashboard API surface). Replace with auth-derived
store when seller auth lands.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.import_job import ImportJob, ImportJobStatus, ImportSource
from app.services.catalog_import.adapters import get_adapter, list_adapters
from app.services.catalog_import.applier import apply as applier_apply
from app.services.catalog_import.normalizer import normalize
from app.services.catalog_import.parser import ParseError, parse_spreadsheet
from app.services.catalog_import.types import ImportedItem, REQUIRED_FIELDS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])

DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
PREVIEW_ROWS_LIMIT = 500


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


class SourceInfo(BaseModel):
    name: str
    display_name: str
    file_extensions: list[str]
    hint: str
    default_column_mapping: dict[str, str]


class ImportJobOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    source: str
    status: str
    filename: str
    column_mapping: dict[str, str] | None
    summary: dict | None
    preview_rows: list[dict] | None
    error_message: str | None
    detected_headers: list[str] | None = None
    confirmed_at: datetime | None
    applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MappingUpdate(BaseModel):
    column_mapping: dict[str, str]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _serialize(job: ImportJob, *, detected_headers: list[str] | None = None) -> dict:
    return {
        "id": str(job.id),
        "store_id": str(job.store_id),
        "source": job.source.value,
        "status": job.status.value,
        "filename": job.filename,
        "column_mapping": job.column_mapping,
        "summary": job.summary,
        "preview_rows": job.preview_rows,
        "error_message": job.error_message,
        "detected_headers": detected_headers,
        "confirmed_at": job.confirmed_at.isoformat() if job.confirmed_at else None,
        "applied_at": job.applied_at.isoformat() if job.applied_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def _get_job(db: AsyncSession, job_id: uuid.UUID) -> ImportJob:
    job = await db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(404, "Import job not found")
    return job


def _missing_required(mapping: dict[str, str]) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not mapping.get(f)]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("/sources")
async def list_sources() -> dict:
    """Return all supported source adapters for the wizard step 1."""
    return {
        "data": [
            SourceInfo(
                name=a.name,
                display_name=a.display_name,
                file_extensions=list(a.file_extensions),
                hint=a.hint,
                default_column_mapping=a.default_column_mapping,
            ).model_dump()
            for a in list_adapters()
        ]
    }


@router.post("", status_code=201)
async def create_import(
    file: UploadFile = File(...),
    source: str = Form(...),
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a file, parse it, run the adapter's default mapping, return preview."""

    if source not in {s.value for s in ImportSource}:
        raise HTTPException(400, f"Unknown source: {source!r}")

    adapter = get_adapter(source)

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File exceeds 10 MB limit ({len(content) // 1024} KB uploaded)"
        )

    job = ImportJob(
        store_id=store_id,
        source=ImportSource(source),
        status=ImportJobStatus.UPLOADED,
        filename=file.filename or "upload",
    )
    db.add(job)
    await db.flush()

    try:
        headers, raw_rows, parse_warnings = parse_spreadsheet(content, file.filename or "")
    except ParseError as e:
        job.status = ImportJobStatus.FAILED
        job.error_message = str(e)
        await db.commit()
        raise HTTPException(400, str(e))

    mapping = dict(adapter.default_column_mapping)
    items, summary = normalize(raw_rows, mapping, source)
    if parse_warnings:
        # Tag the first non-error item with parse warnings so they surface in UI
        for item in items:
            if not item.errors:
                item.warnings = parse_warnings + item.warnings
                break

    job.column_mapping = mapping
    job.preview_rows = [it.to_dict() for it in items[:PREVIEW_ROWS_LIMIT]]
    job.summary = summary
    job.status = ImportJobStatus.PREVIEWED
    await db.commit()

    return {"data": _serialize(job, detected_headers=headers)}


@router.get("/{job_id}")
async def get_import(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _get_job(db, job_id)
    return {"data": _serialize(job)}


@router.patch("/{job_id}/mapping")
async def update_mapping(
    job_id: uuid.UUID,
    body: MappingUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-run normalizer against the cached preview_rows with a new mapping.

    Note: cached preview_rows is a snapshot of *normalized items*, not raw
    parsed rows, so an arbitrary remap can't be perfectly re-run without the
    original file. We approximate by reusing the items: their underlying raw
    fields are not retained. For v1 this endpoint validates the mapping
    structure (required fields present) and stores it for confirm; if the
    seller needs a full re-map they re-upload.
    """
    job = await _get_job(db, job_id)
    if job.status in (ImportJobStatus.CONFIRMED, ImportJobStatus.APPLIED):
        raise HTTPException(400, "Cannot remap a confirmed or applied job")

    missing = _missing_required(body.column_mapping)
    if missing:
        raise HTTPException(
            400, f"Mapping is missing required fields: {', '.join(missing)}"
        )

    job.column_mapping = body.column_mapping
    await db.commit()
    return {"data": _serialize(job)}


@router.post("/{job_id}/confirm")
async def confirm_import(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply the preview rows to the catalog and fire a Beckn catalog push."""
    job = await _get_job(db, job_id)
    if job.status == ImportJobStatus.APPLIED:
        return {"data": _serialize(job)}
    if job.status not in (ImportJobStatus.PREVIEWED, ImportJobStatus.CONFIRMED):
        raise HTTPException(400, f"Job is in state {job.status.value}; cannot confirm")
    if not job.preview_rows:
        raise HTTPException(400, "Job has no preview rows to apply")

    job.status = ImportJobStatus.CONFIRMED
    job.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    items: list[ImportedItem] = [ImportedItem.from_dict(d) for d in job.preview_rows]

    try:
        result = await applier_apply(db, job.store_id, job.source.value, items)
    except Exception as e:
        logger.exception("Import apply failed for job %s", job.id)
        job.status = ImportJobStatus.FAILED
        job.error_message = f"{type(e).__name__}: {e}"
        await db.commit()
        raise HTTPException(500, job.error_message)

    job.applied_at = datetime.now(timezone.utc)
    job.status = ImportJobStatus.APPLIED
    job.summary = {
        **(job.summary or {}),
        "created_products": result.created_products,
        "created_skus": result.created_skus,
        "updated_skus": result.updated_skus,
        "skipped": result.skipped,
        "apply_errors": result.errors[:50],  # cap to avoid bloating JSONB
    }
    await db.commit()

    # Fire Beckn catalog push (best-effort, fire-and-forget)
    try:
        from app.beckn.catalog_push import push_catalog_after_commit
        push_catalog_after_commit(db)
    except Exception:
        logger.warning("Beckn catalog push failed after import %s", job.id, exc_info=True)

    return {"data": _serialize(job)}
