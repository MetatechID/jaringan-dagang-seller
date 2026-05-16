# Beckn-Native Catalog, Orders, Fulfillment & Refunds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make seller's Postgres the system-of-record for all toko catalogs, orders, fulfillment, and refunds; wire all cross-app data flow over signed Beckn HTTP; retire the buyer's JSON catalogs and the `seller_bridge` HTTP shortcut.

**Architecture:** Three apps (`jaringan-dagang-buyer`, `-network`, `-seller`), three Postgres DBs, one Beckn registry. Ed25519-signed envelopes between apps. Buyer keeps a hint-only catalog mirror in its own DB; seller is the only writer to inventory; checkout revalidates live via Beckn `/select` + `/init`.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2 async / asyncpg / Alembic / pytest-asyncio / TypeScript / Next.js 14 / Tailwind / Redis / Xendit / Biteship / Ed25519 (`cryptography` lib).

**Spec:** `jaringan-dagang-seller/docs/superpowers/specs/2026-05-16-beckn-catalog-orders-fulfillment-refunds-design.md`

**Repos referenced by absolute path:**
- `/Users/gogo/Code/jaringan-dagang-buyer` — "buyer" below
- `/Users/gogo/Code/jaringan-dagang-network` — "network" below
- `/Users/gogo/Code/jaringan-dagang-seller` — "seller" below

---

## Conventions (read once, applies to every task)

### Test layout
- **seller**: pytest, tests in `tests/`, configured via `pyproject.toml`. Run: `cd /Users/gogo/Code/jaringan-dagang-seller && pytest tests/<path> -v`
- **buyer**: pytest, tests in `apps/beli-aman-bap/tests/`. Run: `cd /Users/gogo/Code/jaringan-dagang-buyer && pytest apps/beli-aman-bap/tests/<path> -v`
- **network**: pytest, tests in `tests/`. Run: `cd /Users/gogo/Code/jaringan-dagang-network && pytest tests/<path> -v`
- **shared package** `packages/beckn-protocol`: tests live in `packages/beckn-protocol/tests/`. Run from any repo that has it on PYTHONPATH.

### TDD discipline
TDD (write failing test first, then implementation) is **required** for: crypto signing/verification, idempotency dedupe, race-safe DB transactions, refund state machine, Beckn envelope canonicalization. Trivial route handlers, UI scaffolds, migrations, and seeders may skip TDD — just write + smoke-test.

### Alembic migrations (buyer + seller)
```bash
cd <repo> && alembic revision -m "<short description>" --autogenerate
# review the generated file in alembic/versions/, hand-edit if autogen missed things
alembic upgrade head
```

Network doesn't currently use Alembic; if a schema change is needed there, add Alembic in Task 1.x.

### Commit cadence
One commit per task by default (unless task explicitly says "no commit yet — bundled with next task"). Commit format: `<type>(<scope>): <subject>` — e.g. `feat(beckn): sign_request helper`.

### Beckn envelope shape (canonical for this codebase)
Every Beckn request/response body has this structure:
```json
{
  "context": {
    "domain": "retail",
    "country": "IDN",
    "city": "std:000",
    "action": "search|select|init|confirm|status|update|on_search|...",
    "core_version": "1.1.0",
    "bap_id": "<subscriber_id of BAP>",
    "bap_uri": "<url>",
    "bpp_id": "<subscriber_id of BPP>",      // present except on bare /search
    "bpp_uri": "<url>",
    "transaction_id": "<uuid v4, cart-scoped>",
    "message_id": "<uuid v4, request-scoped>",
    "timestamp": "<RFC3339>"
  },
  "message": { ... }
}
```

### Signing
- Algorithm: Ed25519 (via `cryptography.hazmat.primitives.asymmetric.ed25519`).
- Header format mirrors Beckn 1.1 spec: `Authorization: Signature keyId="<subscriber_id>|<key_id>|ed25519",algorithm="ed25519",created="<unix>",expires="<unix>",headers="(created) (expires) digest",signature="<base64>"`
- Signed input is `(created)\n(expires)\ndigest: BLAKE-512=<base64(blake2b-512(body))>`.

### Dev keypairs
- Each repo gets a `dev/keys/<role>.private.pem` (NOT FOR PROD; committed; .gitattributes marks as text) + `.public.pem`.
- Bootstrap script reads pubkey, registers via network's `POST /subscribe` on app startup.

### Cross-repo dependency on `packages/beckn-protocol`
- Today the package is a sibling of `apps/beli-aman-bap` in the buyer repo. Promote it to a real importable package and add it as a path-dep in both seller and network `pyproject.toml`.

### "No commit needed" tasks
Tasks marked **(no commit)** are exploratory — schema dumps, smoke checks, manual verification.

---

## Phase 1: Foundations (Beckn signing, logs, registry)

After this phase: signed Beckn round-trips work between buyer ↔ seller ↔ network. All inbound `/beckn/*` and `/api/v1/beckn/*` traffic is signature-verified and deduped. Outbound traffic is signed and logged. All 4 BPP tokos are registered in the network registry with real pubkeys.

### Task 1.1: Make `packages/beckn-protocol` importable from all three repos

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/pyproject.toml`
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/pyproject.toml`
- Modify: `/Users/gogo/Code/jaringan-dagang-network/pyproject.toml`

- [ ] **Step 1: Inspect current package state**

```bash
ls /Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/
cat /Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/pyproject.toml
```

Expected: see existing `pyproject.toml` with `name = "beckn-protocol"`. If missing, create per Step 2.

- [ ] **Step 2: Ensure `pyproject.toml` exists with version pin**

In `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/pyproject.toml`, ensure:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "beckn-protocol"
version = "0.2.0"
requires-python = ">=3.13"
dependencies = [
    "cryptography>=42.0",
    "httpx>=0.27",
    "pydantic>=2.5",
    "redis>=5.0",
]

[tool.hatch.build.targets.wheel]
packages = ["beckn_protocol"]
```

- [ ] **Step 3: Add as path-dep in seller**

In `/Users/gogo/Code/jaringan-dagang-seller/pyproject.toml` `[project] dependencies`, add:

```toml
"beckn-protocol",
```

And in a new `[tool.uv.sources]` (or your project manager's path-dep equivalent):

```toml
[tool.uv.sources]
beckn-protocol = { path = "../jaringan-dagang-buyer/packages/beckn-protocol", editable = true }
```

(If the seller repo uses Poetry or pip-tools, adapt to that tooling's path-dep syntax — check existing dev-dep entries for the pattern.)

- [ ] **Step 4: Add as path-dep in network**

Same pattern in `/Users/gogo/Code/jaringan-dagang-network/pyproject.toml`.

- [ ] **Step 5: Install in all three repos**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && uv sync   # or pip install -e packages/beckn-protocol
cd /Users/gogo/Code/jaringan-dagang-seller && uv sync
cd /Users/gogo/Code/jaringan-dagang-network && uv sync
```

Expected: no errors; `python -c "import beckn_protocol"` works in each repo's venv.

- [ ] **Step 6: Commit (in each repo separately)**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && git add packages/beckn-protocol/pyproject.toml && git commit -m "chore(beckn-protocol): bump to 0.2.0 with deps for signing"
cd /Users/gogo/Code/jaringan-dagang-seller && git add pyproject.toml && git commit -m "chore: depend on beckn-protocol path package"
cd /Users/gogo/Code/jaringan-dagang-network && git add pyproject.toml && git commit -m "chore: depend on beckn-protocol path package"
```

---

### Task 1.2: Canonical JSON for signing

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/beckn_protocol/canonical.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/tests/test_canonical.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_canonical.py
import json
from beckn_protocol.canonical import canonical_json

def test_keys_sorted_lexicographically():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b
    assert a == b'{"a":2,"b":1}'

def test_no_whitespace():
    out = canonical_json({"x": [1, 2, 3]})
    assert out == b'{"x":[1,2,3]}'

def test_unicode_not_escaped():
    out = canonical_json({"name": "Safiyâ"})
    assert "Safiyâ".encode("utf-8") in out

def test_nested():
    out = canonical_json({"context": {"bap_id": "x", "action": "search"}})
    assert out == b'{"context":{"action":"search","bap_id":"x"}}'
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_canonical.py -v
```
Expected: ImportError / module not found.

- [ ] **Step 3: Implement**

```python
# beckn_protocol/canonical.py
import json
from typing import Any

def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_canonical.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/beckn-protocol/beckn_protocol/canonical.py packages/beckn-protocol/tests/test_canonical.py
git commit -m "feat(beckn): canonical JSON serializer for signing"
```

---

### Task 1.3: Ed25519 sign / verify helpers

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/beckn_protocol/signing.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/tests/test_signing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_signing.py
import time
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from beckn_protocol.signing import (
    sign_request, verify_request, generate_keypair,
    SignatureInvalid, SignatureExpired,
)

@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub

def test_sign_then_verify_roundtrip(keypair):
    priv, pub = keypair
    body = b'{"context":{"action":"search"},"message":{}}'
    auth = sign_request(body, priv, key_id="safiyafood.bpp.metatech.id|k1")
    assert verify_request(auth, body, pub)

def test_tampered_body_rejected(keypair):
    priv, pub = keypair
    body = b'{"x":1}'
    auth = sign_request(body, priv, key_id="x|k1")
    with pytest.raises(SignatureInvalid):
        verify_request(auth, b'{"x":2}', pub)

def test_expired_rejected(keypair):
    priv, pub = keypair
    body = b'{"x":1}'
    past = int(time.time()) - 600  # 10 min ago
    auth = sign_request(body, priv, key_id="x|k1", created=past, expires=past + 1)
    with pytest.raises(SignatureExpired):
        verify_request(auth, body, pub)

def test_generate_keypair_works():
    priv, pub = generate_keypair()
    body = b"hello"
    auth = sign_request(body, priv, key_id="dev|k0")
    assert verify_request(auth, body, pub)
```

- [ ] **Step 2: Run, expect failure (ImportError)**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_signing.py -v
```

- [ ] **Step 3: Implement**

```python
# beckn_protocol/signing.py
import base64
import hashlib
import re
import time
from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization

SIGNATURE_MAX_AGE = 300  # 5 minutes


class SignatureInvalid(Exception): ...
class SignatureExpired(Exception): ...


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def _digest(body: bytes) -> str:
    h = hashlib.blake2b(body, digest_size=64).digest()
    return "BLAKE-512=" + base64.b64encode(h).decode()


def _signing_input(created: int, expires: int, body: bytes) -> bytes:
    return (
        f"(created): {created}\n"
        f"(expires): {expires}\n"
        f"digest: {_digest(body)}"
    ).encode()


def sign_request(
    body: bytes,
    private_key: Ed25519PrivateKey,
    key_id: str,
    created: int | None = None,
    expires: int | None = None,
) -> str:
    created = created or int(time.time())
    expires = expires or (created + SIGNATURE_MAX_AGE)
    sig = private_key.sign(_signing_input(created, expires, body))
    sig_b64 = base64.b64encode(sig).decode()
    return (
        f'Signature keyId="{key_id}",algorithm="ed25519",'
        f'created="{created}",expires="{expires}",'
        f'headers="(created) (expires) digest",signature="{sig_b64}"'
    )


_AUTH_RE = re.compile(r'(\w+)="([^"]+)"')


def _parse(auth: str) -> dict:
    if not auth.startswith("Signature "):
        raise SignatureInvalid("not a Signature header")
    return dict(_AUTH_RE.findall(auth[len("Signature "):]))


def verify_request(auth: str, body: bytes, public_key: Ed25519PublicKey) -> bool:
    parts = _parse(auth)
    try:
        created = int(parts["created"])
        expires = int(parts["expires"])
        sig = base64.b64decode(parts["signature"])
    except (KeyError, ValueError) as e:
        raise SignatureInvalid(f"missing/malformed field: {e}")
    now = int(time.time())
    if now > expires:
        raise SignatureExpired(f"now={now} > expires={expires}")
    if now - created > SIGNATURE_MAX_AGE:
        raise SignatureExpired(f"created={created} too old (max age {SIGNATURE_MAX_AGE}s)")
    try:
        public_key.verify(sig, _signing_input(created, expires, body))
    except Exception as e:
        raise SignatureInvalid(f"signature verification failed: {e}")
    return True


def load_private_pem(path: str) -> Ed25519PrivateKey:
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def load_public_pem(path: str) -> Ed25519PublicKey:
    with open(path, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def public_pem(pub: Ed25519PublicKey) -> bytes:
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def private_pem(priv: Ed25519PrivateKey) -> bytes:
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
```

- [ ] **Step 4: Run, expect 4 passed**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_signing.py -v
```

- [ ] **Step 5: Commit**

```bash
git add packages/beckn-protocol/beckn_protocol/signing.py packages/beckn-protocol/tests/test_signing.py
git commit -m "feat(beckn): Ed25519 sign/verify with replay protection"
```

---

### Task 1.4: Beckn envelope builder

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/beckn_protocol/envelope.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/tests/test_envelope.py`

- [ ] **Step 1: Test**

```python
# tests/test_envelope.py
from beckn_protocol.envelope import envelope, BecknContext

def test_envelope_minimal():
    e = envelope(
        action="search",
        bap_id="beli-aman.bap.metatech.id",
        bap_uri="https://beli-aman.metatech.id/beckn",
        bpp_id=None,
        bpp_uri=None,
        transaction_id="t1",
        message_id="m1",
        payload={"intent": {"category": {"id": "kurma"}}},
    )
    assert e["context"]["action"] == "search"
    assert e["context"]["bap_id"] == "beli-aman.bap.metatech.id"
    assert "bpp_id" not in e["context"]   # absent for bare /search
    assert e["context"]["domain"] == "retail"
    assert e["context"]["country"] == "IDN"
    assert e["context"]["core_version"] == "1.1.0"
    assert e["message"] == {"intent": {"category": {"id": "kurma"}}}

def test_envelope_with_bpp():
    e = envelope(
        action="select",
        bap_id="bap.x", bap_uri="https://x/beckn",
        bpp_id="safiyafood.bpp.metatech.id", bpp_uri="https://seller/beckn",
        transaction_id="t1", message_id="m2",
        payload={"order": {"items": []}},
    )
    assert e["context"]["bpp_id"] == "safiyafood.bpp.metatech.id"
```

- [ ] **Step 2: Implement**

```python
# beckn_protocol/envelope.py
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

DEFAULT_DOMAIN = "retail"
DEFAULT_COUNTRY = "IDN"
DEFAULT_CITY = "std:000"
CORE_VERSION = "1.1.0"


def envelope(
    *,
    action: str,
    bap_id: str,
    bap_uri: str,
    bpp_id: str | None,
    bpp_uri: str | None,
    transaction_id: str,
    message_id: str,
    payload: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "domain": DEFAULT_DOMAIN,
        "country": DEFAULT_COUNTRY,
        "city": DEFAULT_CITY,
        "action": action,
        "core_version": CORE_VERSION,
        "bap_id": bap_id,
        "bap_uri": bap_uri,
        "transaction_id": transaction_id,
        "message_id": message_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    if bpp_id is not None:
        ctx["bpp_id"] = bpp_id
    if bpp_uri is not None:
        ctx["bpp_uri"] = bpp_uri
    return {"context": ctx, "message": payload}
```

- [ ] **Step 3: Run + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_envelope.py -v
# expect 2 passed
git add packages/beckn-protocol/beckn_protocol/envelope.py packages/beckn-protocol/tests/test_envelope.py
git commit -m "feat(beckn): envelope builder with Indonesian retail context"
```

---

### Task 1.5: RegistryClient with Redis caching

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/beckn_protocol/registry.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/tests/test_registry.py`

- [ ] **Step 1: Tests (use fake Redis + fake httpx transport)**

```python
# tests/test_registry.py
import pytest, httpx, fakeredis.aioredis
from beckn_protocol.registry import RegistryClient, SubscriberNotFound

@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()

@pytest.mark.asyncio
async def test_lookup_hits_network_then_caches(redis):
    calls = []
    def handler(request: httpx.Request):
        calls.append(1)
        return httpx.Response(200, json={
            "subscribers": [{
                "subscriber_id": "safiyafood.bpp.metatech.id",
                "subscriber_url": "https://seller/beckn",
                "signing_public_key": "BASE64PUBKEY==",
                "type": "BPP",
            }]
        })
    transport = httpx.MockTransport(handler)
    client = RegistryClient(
        registry_url="http://network:3030", redis=redis,
        http_client=httpx.AsyncClient(transport=transport),
    )
    r = await client.lookup("safiyafood.bpp.metatech.id")
    assert r.subscriber_url == "https://seller/beckn"
    r2 = await client.lookup("safiyafood.bpp.metatech.id")  # cached
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_missing_subscriber_raises(redis):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"subscribers": []}))
    client = RegistryClient(
        registry_url="http://network:3030", redis=redis,
        http_client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(SubscriberNotFound):
        await client.lookup("ghost.bpp")
```

Add `fakeredis` + `pytest-asyncio` to `packages/beckn-protocol/pyproject.toml` `[project.optional-dependencies] test`.

- [ ] **Step 2: Implement**

```python
# beckn_protocol/registry.py
import base64
from dataclasses import dataclass
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

class SubscriberNotFound(Exception): ...

@dataclass
class Subscriber:
    subscriber_id: str
    subscriber_url: str
    public_key: Ed25519PublicKey
    type: str

class RegistryClient:
    def __init__(self, registry_url: str, redis, http_client: httpx.AsyncClient | None = None, ttl: int = 3600):
        self.registry_url = registry_url.rstrip("/")
        self.redis = redis
        self.http = http_client or httpx.AsyncClient()
        self.ttl = ttl

    def _key(self, sub_id: str) -> str:
        return f"beckn:registry:{sub_id}"

    async def lookup(self, subscriber_id: str) -> Subscriber:
        cached = await self.redis.get(self._key(subscriber_id))
        if cached:
            return self._decode_cached(cached, subscriber_id)
        r = await self.http.post(
            f"{self.registry_url}/lookup",
            json={"subscriber_id": subscriber_id},
            timeout=5.0,
        )
        r.raise_for_status()
        subs = r.json().get("subscribers", [])
        if not subs:
            raise SubscriberNotFound(subscriber_id)
        s = subs[0]
        pub_pem = base64.b64decode(s["signing_public_key"])
        pub = serialization.load_pem_public_key(pub_pem)
        sub = Subscriber(
            subscriber_id=s["subscriber_id"],
            subscriber_url=s["subscriber_url"],
            public_key=pub,
            type=s["type"],
        )
        await self.redis.setex(
            self._key(subscriber_id), self.ttl,
            f"{sub.subscriber_url}|{sub.type}|{s['signing_public_key']}",
        )
        return sub

    def _decode_cached(self, raw: bytes, sub_id: str) -> Subscriber:
        url, typ, pub_b64 = raw.decode().split("|")
        pub = serialization.load_pem_public_key(base64.b64decode(pub_b64))
        return Subscriber(sub_id, url, pub, typ)

    async def invalidate(self, subscriber_id: str):
        await self.redis.delete(self._key(subscriber_id))
```

- [ ] **Step 3: Run + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_registry.py -v
git add packages/beckn-protocol/beckn_protocol/registry.py packages/beckn-protocol/tests/test_registry.py packages/beckn-protocol/pyproject.toml
git commit -m "feat(beckn): RegistryClient with Redis-cached lookups"
```

---

### Task 1.6: Outbound `sign_and_send` helper

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/beckn_protocol/outbound.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/packages/beckn-protocol/tests/test_outbound.py`

- [ ] **Step 1: Test**

```python
# tests/test_outbound.py
import httpx, pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from beckn_protocol.outbound import sign_and_send

@pytest.mark.asyncio
async def test_signs_and_posts():
    captured = {}
    def handler(req: httpx.Request):
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = req.content
        return httpx.Response(200, json={"ack": True})

    priv = Ed25519PrivateKey.generate()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resp = await sign_and_send(
        url="https://seller/beckn/search",
        body={"context": {"action": "search"}, "message": {}},
        private_key=priv,
        key_id="bap.x|k1",
        http_client=client,
    )
    assert resp.status_code == 200
    assert captured["auth"].startswith("Signature ")
```

- [ ] **Step 2: Implement**

```python
# beckn_protocol/outbound.py
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from beckn_protocol.canonical import canonical_json
from beckn_protocol.signing import sign_request

async def sign_and_send(
    *,
    url: str,
    body: dict,
    private_key: Ed25519PrivateKey,
    key_id: str,
    http_client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> httpx.Response:
    raw = canonical_json(body)
    auth = sign_request(raw, private_key, key_id=key_id)
    http = http_client or httpx.AsyncClient()
    return await http.post(
        url,
        content=raw,
        headers={"Authorization": auth, "Content-Type": "application/json"},
        timeout=timeout,
    )
```

- [ ] **Step 3: Run + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest packages/beckn-protocol/tests/test_outbound.py -v
git add packages/beckn-protocol/beckn_protocol/outbound.py packages/beckn-protocol/tests/test_outbound.py
git commit -m "feat(beckn): sign_and_send outbound helper"
```

---

### Task 1.7: `beckn_inbound_log` + `beckn_outbound_log` tables (seller)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/models/beckn_log.py`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/alembic/versions/<auto>_beckn_logs.py`

- [ ] **Step 1: Add model**

```python
# app/models/beckn_log.py
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.db import Base

class BecknInboundLog(Base):
    __tablename__ = "beckn_inbound_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(String, nullable=False, unique=True, index=True)
    action = Column(String, nullable=False)
    bap_id = Column(String, nullable=True)
    bpp_id = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    response_status = Column(Integer, nullable=False)
    response_body = Column(JSON, nullable=True)

class BecknOutboundLog(Base):
    __tablename__ = "beckn_outbound_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    target_url = Column(String, nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    error = Column(String, nullable=True)

Index("ix_beckn_outbound_message_attempt", BecknOutboundLog.message_id, BecknOutboundLog.attempt)
```

- [ ] **Step 2: Generate migration + apply**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
alembic revision -m "beckn logs" --autogenerate
alembic upgrade head
```

Review generated file; ensure both tables present.

- [ ] **Step 3: Commit**

```bash
git add app/models/beckn_log.py alembic/versions/*_beckn_logs.py
git commit -m "feat(seller): beckn inbound/outbound log tables"
```

---

### Task 1.8: Same beckn log tables in buyer

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/models/beckn_log.py`
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/alembic/versions/<auto>_beckn_logs.py`

- [ ] **Step 1: Copy the model file** (same content as Task 1.7's model, but importing from buyer's `database.Base` — usually `from apps.beli_aman_bap.database import Base`).

- [ ] **Step 2: If buyer doesn't have Alembic configured, bootstrap:**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap
alembic init alembic
# edit alembic.ini sqlalchemy.url and env.py target_metadata
```

- [ ] **Step 3: Generate + apply**

```bash
alembic revision -m "beckn logs" --autogenerate
alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add apps/beli-aman-bap/models/beckn_log.py apps/beli-aman-bap/alembic/
git commit -m "feat(buyer): beckn inbound/outbound log tables"
```

---

### Task 1.9: Inbound signature middleware (seller)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/middleware.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_middleware.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/main.py` (mount middleware)

- [ ] **Step 1: Test**

```python
# tests/beckn/test_middleware.py
import json, pytest
from httpx import AsyncClient, ASGITransport
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from beckn_protocol.signing import sign_request
from beckn_protocol.canonical import canonical_json
from app.main import app  # adjust import

@pytest.mark.asyncio
async def test_unsigned_request_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/beckn/search", json={"context": {"action": "search"}})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_signed_request_accepted(monkeypatch, fake_registry_with_known_bap):
    body = {"context": {"action": "search", "bap_id": "bap.x", "message_id": "m1"},
            "message": {}}
    raw = canonical_json(body)
    priv = fake_registry_with_known_bap.private_for("bap.x")
    auth = sign_request(raw, priv, key_id="bap.x|k1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/beckn/search", content=raw,
                         headers={"Authorization": auth, "Content-Type": "application/json"})
    assert r.status_code != 401  # actual response depends on handler
```

(`fake_registry_with_known_bap` is a conftest fixture that monkeypatches `RegistryClient.lookup` to return a Subscriber with a known pubkey — define it in `tests/conftest.py`.)

- [ ] **Step 2: Implement middleware**

```python
# app/beckn/middleware.py
import json
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from beckn_protocol.signing import verify_request, SignatureInvalid, SignatureExpired
from app.deps import get_registry_client  # provided elsewhere

BECKN_PREFIXES = ("/beckn/",)

class BecknSignatureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in BECKN_PREFIXES):
            return await call_next(request)
        auth = request.headers.get("authorization")
        if not auth:
            return JSONResponse({"error": "missing Authorization"}, status_code=401)
        body = await request.body()
        try:
            envelope = json.loads(body)
            sub_id = envelope["context"]["bap_id"]
        except Exception:
            return JSONResponse({"error": "malformed envelope"}, status_code=400)
        registry = await get_registry_client()
        sub = await registry.lookup(sub_id)
        try:
            verify_request(auth, body, sub.public_key)
        except SignatureExpired as e:
            return JSONResponse({"error": f"signature expired: {e}"}, status_code=401)
        except SignatureInvalid as e:
            return JSONResponse({"error": f"signature invalid: {e}"}, status_code=401)
        request.state.bap_id = sub_id
        request.state.beckn_envelope = envelope
        return await call_next(request)
```

- [ ] **Step 3: Mount in `app/main.py`**

Add near other middleware registrations:

```python
from app.beckn.middleware import BecknSignatureMiddleware
app.add_middleware(BecknSignatureMiddleware)
```

- [ ] **Step 4: Run tests, expect pass**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller && pytest tests/beckn/test_middleware.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/beckn/ tests/beckn/ app/main.py
git commit -m "feat(seller): beckn signature middleware for /beckn/*"
```

---

### Task 1.10: Inbound idempotency (seller)

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/middleware.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_idempotency.py`

- [ ] **Step 1: Test — replay returns cached response, no second handler call**

```python
# tests/beckn/test_idempotency.py
import pytest
from sqlalchemy import select
from app.models.beckn_log import BecknInboundLog

@pytest.mark.asyncio
async def test_replayed_message_id_returns_cached(signed_client, db_session):
    body = make_signed_body(action="select", message_id="MID-1", message={"order": {"items": []}})
    r1 = await signed_client.post("/beckn/select", **body)
    r2 = await signed_client.post("/beckn/select", **body)
    assert r1.status_code == r2.status_code
    assert r1.json() == r2.json()
    rows = (await db_session.execute(select(BecknInboundLog).where(BecknInboundLog.message_id == "MID-1"))).scalars().all()
    assert len(rows) == 1  # logged once
```

(`signed_client` + `make_signed_body` are conftest helpers — provide in `tests/conftest.py`.)

- [ ] **Step 2: Extend middleware to dedupe after signature verify**

```python
# in app/beckn/middleware.py BecknSignatureMiddleware.dispatch, after verify_request:
message_id = envelope["context"]["message_id"]
async with get_db() as session:
    existing = (await session.execute(
        select(BecknInboundLog).where(BecknInboundLog.message_id == message_id)
    )).scalar_one_or_none()
    if existing:
        return JSONResponse(existing.response_body, status_code=existing.response_status)

response = await call_next(request)

# capture and persist response
resp_body = b"".join([chunk async for chunk in response.body_iterator])
async with get_db() as session:
    session.add(BecknInboundLog(
        message_id=message_id,
        action=envelope["context"]["action"],
        bap_id=sub_id,
        bpp_id=envelope["context"].get("bpp_id"),
        response_status=response.status_code,
        response_body=json.loads(resp_body) if resp_body else None,
    ))
    await session.commit()
return Response(content=resp_body, status_code=response.status_code, headers=dict(response.headers))
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/beckn/test_idempotency.py -v
git add app/beckn/middleware.py tests/beckn/test_idempotency.py
git commit -m "feat(seller): inbound beckn message idempotency"
```

---

### Task 1.11: Mirror Task 1.9 + 1.10 in buyer

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/beckn/middleware.py`
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/tests/test_beckn_middleware.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/main.py`

Same structure as Tasks 1.9 + 1.10 but:
- `BECKN_PREFIXES = ("/api/v1/beckn/",)`
- `sub_id = envelope["context"]["bpp_id"]` (buyer receives from sellers, so look up BPP pubkey)
- Buyer's session factory and BecknInboundLog model

- [ ] **Step 1: Write copy with the two adjustments above.**
- [ ] **Step 2: Run tests, commit.**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest apps/beli-aman-bap/tests/test_beckn_middleware.py -v
git add apps/beli-aman-bap/beckn/ apps/beli-aman-bap/tests/test_beckn_middleware.py apps/beli-aman-bap/main.py
git commit -m "feat(buyer): beckn signature middleware + idempotency"
```

---

### Task 1.12: Outbound wrapper that logs every send (seller)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/outbound.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_outbound.py`

- [ ] **Step 1: Implement wrapper that calls `beckn_protocol.outbound.sign_and_send` and persists a `BecknOutboundLog` row per attempt (success + failure), with 3 retries on 5xx (1s/4s/16s backoff).**

```python
# app/beckn/outbound.py
import asyncio
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from beckn_protocol.outbound import sign_and_send
from app.models.beckn_log import BecknOutboundLog
from app.deps import get_signing_key

RETRY_BACKOFF = [1.0, 4.0, 16.0]

async def send_beckn(envelope: dict, target_url: str, session: AsyncSession) -> httpx.Response | None:
    priv, key_id = get_signing_key()
    message_id = envelope["context"]["message_id"]
    action = envelope["context"]["action"]
    last_resp = None
    for attempt, delay in enumerate([0.0] + RETRY_BACKOFF, start=1):
        if delay:
            await asyncio.sleep(delay)
        log = BecknOutboundLog(
            message_id=message_id, action=action,
            target_url=target_url, attempt=attempt,
        )
        try:
            resp = await sign_and_send(
                url=target_url, body=envelope,
                private_key=priv, key_id=key_id,
            )
            log.response_status = resp.status_code
            log.response_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            session.add(log); await session.commit()
            last_resp = resp
            if resp.status_code < 500:
                return resp
        except Exception as e:
            log.error = repr(e)
            session.add(log); await session.commit()
    return last_resp
```

- [ ] **Step 2: Test (mock the inner sign_and_send to return 500 twice then 200, assert 3 BecknOutboundLog rows)**

```python
# tests/beckn/test_outbound.py
import pytest
from unittest.mock import patch, AsyncMock
import httpx
from app.beckn.outbound import send_beckn
from app.models.beckn_log import BecknOutboundLog
from sqlalchemy import select

@pytest.mark.asyncio
async def test_retries_on_5xx_logs_each_attempt(db_session):
    responses = [
        httpx.Response(503), httpx.Response(503),
        httpx.Response(200, json={"ack": True}),
    ]
    with patch("app.beckn.outbound.sign_and_send", AsyncMock(side_effect=responses)):
        with patch("app.beckn.outbound.RETRY_BACKOFF", [0, 0, 0]):
            resp = await send_beckn(
                envelope={"context": {"message_id": "X1", "action": "on_search"}, "message": {}},
                target_url="http://buyer/api/v1/beckn/on_search",
                session=db_session,
            )
    assert resp.status_code == 200
    rows = (await db_session.execute(select(BecknOutboundLog).where(BecknOutboundLog.message_id == "X1"))).scalars().all()
    assert len(rows) == 3
    assert [r.response_status for r in rows] == [503, 503, 200]
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/beckn/test_outbound.py -v
git add app/beckn/outbound.py tests/beckn/test_outbound.py
git commit -m "feat(seller): outbound beckn sender with retry + logging"
```

---

### Task 1.13: Mirror Task 1.12 in buyer

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/beckn/outbound.py`
- Test: equivalent

Same implementation; same test. Commit.

---

### Task 1.14: Dev keypairs in each repo

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/dev/keys/seller.private.pem`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/dev/keys/seller.public.pem`
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/dev/keys/beli-aman.private.pem`
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/dev/keys/beli-aman.public.pem`
- Create: `/Users/gogo/Code/jaringan-dagang-network/dev/keys/network.private.pem`
- Create: `/Users/gogo/Code/jaringan-dagang-network/dev/keys/network.public.pem`
- Create per-toko keys: `seller/dev/keys/safiyafood.{private,public}.pem`, same for `antarestar`, `gendes`, `yourbrand`.

- [ ] **Step 1: Write a generator script** in `seller/scripts/gen-dev-keys.py`:

```python
import sys
from pathlib import Path
from beckn_protocol.signing import generate_keypair, private_pem, public_pem

def gen(out_dir: Path, name: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    priv, pub = generate_keypair()
    (out_dir / f"{name}.private.pem").write_bytes(private_pem(priv))
    (out_dir / f"{name}.public.pem").write_bytes(public_pem(pub))
    print(f"wrote {out_dir / name}.{{private,public}}.pem")

if __name__ == "__main__":
    out = Path(sys.argv[1])
    for name in sys.argv[2:]:
        gen(out, name)
```

- [ ] **Step 2: Run**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
python scripts/gen-dev-keys.py dev/keys seller safiyafood antarestar gendes yourbrand
python scripts/gen-dev-keys.py ../jaringan-dagang-buyer/dev/keys beli-aman
python scripts/gen-dev-keys.py ../jaringan-dagang-network/dev/keys network
```

- [ ] **Step 3: Add README warning**

`dev/keys/README.md` in each repo: "DEV KEYS — never use in production."

- [ ] **Step 4: Commit each repo**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller && git add dev/keys/ scripts/gen-dev-keys.py && git commit -m "chore: dev ed25519 keys (NOT FOR PROD)"
cd /Users/gogo/Code/jaringan-dagang-buyer && git add dev/keys/ && git commit -m "chore: dev ed25519 keys (NOT FOR PROD)"
cd /Users/gogo/Code/jaringan-dagang-network && git add dev/keys/ && git commit -m "chore: dev ed25519 keys (NOT FOR PROD)"
```

---

### Task 1.15: Subscriber registration (network)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-network/subscribers.yaml`
- Create: `/Users/gogo/Code/jaringan-dagang-network/scripts/register-subscribers.py`

- [ ] **Step 1: subscribers.yaml** — declare all 5 subscribers (beli-aman BAP + 4 toko BPPs):

```yaml
subscribers:
  - subscriber_id: beli-aman.bap.metatech.id
    type: BAP
    domain: retail
    city: std:000
    subscriber_url: http://localhost:8002/api/v1/beckn
    public_key_path: ../jaringan-dagang-buyer/dev/keys/beli-aman.public.pem
  - subscriber_id: safiyafood.bpp.metatech.id
    type: BPP
    domain: retail
    city: std:000
    subscriber_url: http://localhost:8001/beckn
    public_key_path: ../jaringan-dagang-seller/dev/keys/safiyafood.public.pem
  - subscriber_id: antarestar.bpp.metatech.id
    type: BPP
    domain: retail
    city: std:000
    subscriber_url: http://localhost:8001/beckn
    public_key_path: ../jaringan-dagang-seller/dev/keys/antarestar.public.pem
  - subscriber_id: gendes.bpp.metatech.id
    type: BPP
    domain: retail
    city: std:000
    subscriber_url: http://localhost:8001/beckn
    public_key_path: ../jaringan-dagang-seller/dev/keys/gendes.public.pem
  - subscriber_id: yourbrand.bpp.metatech.id
    type: BPP
    domain: retail
    city: std:000
    subscriber_url: http://localhost:8001/beckn
    public_key_path: ../jaringan-dagang-seller/dev/keys/yourbrand.public.pem
```

- [ ] **Step 2: register-subscribers.py** — POSTs each to `POST /subscribe`:

```python
import base64, yaml, asyncio, httpx, sys
from pathlib import Path

async def main(yaml_path: str, registry_url: str = "http://localhost:3030"):
    cfg = yaml.safe_load(Path(yaml_path).read_text())
    async with httpx.AsyncClient() as c:
        for s in cfg["subscribers"]:
            pem = Path(s["public_key_path"]).read_bytes()
            pub_b64 = base64.b64encode(pem).decode()
            payload = {
                "subscriber_id": s["subscriber_id"],
                "type": s["type"],
                "domain": s["domain"],
                "city": s["city"],
                "subscriber_url": s["subscriber_url"],
                "signing_public_key": pub_b64,
            }
            r = await c.post(f"{registry_url}/subscribe", json=payload)
            print(s["subscriber_id"], r.status_code, r.text[:120])

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "subscribers.yaml"))
```

- [ ] **Step 3: Boot network locally + run**

```bash
cd /Users/gogo/Code/jaringan-dagang-network
# start network registry (per repo's existing dev command, e.g. uvicorn registry.main:app --port 3030)
python scripts/register-subscribers.py
```

Expected: 5 lines printed, all 200/201.

- [ ] **Step 4: Sanity check via /subscribers**

```bash
curl http://localhost:3030/subscribers | jq '.subscribers[].subscriber_id'
```

Expected: all 5 subscriber_ids listed.

- [ ] **Step 5: Commit**

```bash
git add subscribers.yaml scripts/register-subscribers.py
git commit -m "feat(network): subscriber registration script + all 4 BPPs"
```

---

### Task 1.16: App startup wiring — each app loads its signing key

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/deps.py` (or wherever DI lives)
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/deps.py`

- [ ] **Step 1: Add `get_signing_key()` and `get_registry_client()` providers** in each app.

Seller:
```python
# app/deps.py
from functools import lru_cache
from pathlib import Path
import os
from redis.asyncio import Redis
from beckn_protocol.signing import load_private_pem
from beckn_protocol.registry import RegistryClient

@lru_cache(maxsize=None)
def get_signing_key():
    # for now seller always signs as the toko that owns the order's store_id.
    # bootstrap: default to safiyafood for dev. Real selection happens
    # per-request in routes using store_id → key map.
    path = os.environ.get("BECKN_SIGNING_KEY", "dev/keys/safiyafood.private.pem")
    return load_private_pem(path), os.environ.get("BECKN_KEY_ID", "safiyafood.bpp.metatech.id|k1")

@lru_cache(maxsize=None)
def _redis() -> Redis:
    return Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

async def get_registry_client() -> RegistryClient:
    return RegistryClient(
        registry_url=os.environ.get("BECKN_REGISTRY_URL", "http://localhost:3030"),
        redis=_redis(),
    )
```

Same shape for buyer (just `beli-aman.private.pem`).

- [ ] **Step 2: Add per-store key lookup helper** in seller (used later in Phase 2+):

```python
# app/deps.py (continued)
TOKO_KEYS = {
    "safiyafood.bpp.metatech.id": ("dev/keys/safiyafood.private.pem", "safiyafood.bpp.metatech.id|k1"),
    "antarestar.bpp.metatech.id": ("dev/keys/antarestar.private.pem", "antarestar.bpp.metatech.id|k1"),
    "gendes.bpp.metatech.id":     ("dev/keys/gendes.private.pem",     "gendes.bpp.metatech.id|k1"),
    "yourbrand.bpp.metatech.id":  ("dev/keys/yourbrand.private.pem",  "yourbrand.bpp.metatech.id|k1"),
}

def signing_key_for(bpp_id: str):
    path, key_id = TOKO_KEYS[bpp_id]
    return load_private_pem(path), key_id
```

- [ ] **Step 3: Add `Store.bpp_id` column** if missing — required so the seller can pick the right key per-store.

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
# edit app/models/store.py to add: bpp_id = Column(String, nullable=True)
alembic revision -m "add store.bpp_id" --autogenerate
alembic upgrade head
```

- [ ] **Step 4: Backfill `bpp_id` for the existing Safiya Food store**

```sql
-- run via psql or in a one-off script
UPDATE stores SET bpp_id = 'safiyafood.bpp.metatech.id' WHERE name ILIKE '%safiya%';
```

- [ ] **Step 5: Commit**

```bash
git add app/deps.py app/models/store.py alembic/versions/*_add_store_bpp_id.py
git commit -m "feat(seller): per-toko signing keys + store.bpp_id"
```

---

### Task 1.17: End-to-end signed ping (smoke test)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/scripts/beckn-ping.py`

- [ ] **Step 1: Script that signs a stub `/search` envelope as buyer + POSTs to seller**

```python
# scripts/beckn-ping.py
import asyncio, uuid, os
from beckn_protocol.envelope import envelope
from beckn_protocol.signing import load_private_pem
from beckn_protocol.outbound import sign_and_send

async def main():
    env = envelope(
        action="search",
        bap_id="beli-aman.bap.metatech.id",
        bap_uri="http://localhost:8002/api/v1/beckn",
        bpp_id=None, bpp_uri=None,
        transaction_id=str(uuid.uuid4()),
        message_id=str(uuid.uuid4()),
        payload={"intent": {"category": {"id": "kurma"}}},
    )
    priv = load_private_pem("../jaringan-dagang-buyer/dev/keys/beli-aman.private.pem")
    r = await sign_and_send(
        url="http://localhost:8001/beckn/search",
        body=env, private_key=priv,
        key_id="beli-aman.bap.metatech.id|k1",
    )
    print(r.status_code, r.text[:300])

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Boot both apps + run**

```bash
# terminal 1: cd network && uvicorn registry.main:app --port 3030
# terminal 2: cd seller && uvicorn app.main:app --port 8001
# terminal 3:
cd /Users/gogo/Code/jaringan-dagang-seller && python scripts/beckn-ping.py
```

Expected: non-401 response (e.g. 200 or 202 — seller's `/beckn/search` returns ACK).

- [ ] **Step 3: Verify both logs have a row**

```bash
psql seller_db -c "SELECT message_id, response_status FROM beckn_inbound_log ORDER BY received_at DESC LIMIT 1;"
# should show the message_id with status 200/202
```

- [ ] **Step 4: Commit (no commit needed — smoke check only)**

---

**Phase 1 complete.** All three apps speak signed Beckn; pubkeys resolve via network registry; replay returns cached responses; outbound sends are logged with retry.

---

## Phase 2: Catalog migration (drop buyer JSON; seller becomes source)

After this phase: buyer storefront for all 4 tokos renders from `mirror_*` tables in the buyer's `beli_aman` Postgres, populated by signed `/on_search` pushes from seller + a 5-minute pull worker. JSON files in `apps/beli-aman-bap/catalog/` are deleted.

### Task 2.1: Generalize the seeder

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/scripts/seed-from-buyer-catalog.py`
- Reference: `/Users/gogo/Code/jaringan-dagang-seller/scripts/seed-safiyafood.py` (existing)

- [ ] **Step 1: Lift the safiyafood seeder into a reusable function**

```python
# scripts/seed-from-buyer-catalog.py
import argparse, asyncio, json, sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session_maker
from app.models.store import Store
from app.models.product import Product
from app.models.sku import SKU
from app.models.sku_image import SKUImage
from app.models.product_image import ProductImage

BUYER_CATALOG_DIR = Path("../jaringan-dagang-buyer/apps/beli-aman-bap/catalog")

STORE_DEFAULTS = {
    "safiyafood": {"id": "30b8c0a7-2ed1-4f8f-9a0e-5c2f9a4d72ee", "name": "Safiya Food", "bpp_id": "safiyafood.bpp.metatech.id"},
    "antarestar": {"id": "fc987547-c790-4d91-903d-41c53a18bfc6", "name": "Antarestar",  "bpp_id": "antarestar.bpp.metatech.id"},
    "gendes":     {"id": "...", "name": "Gendes",     "bpp_id": "gendes.bpp.metatech.id"},
    "yourbrand":  {"id": "...", "name": "YourBrand",  "bpp_id": "yourbrand.bpp.metatech.id"},
}

async def seed_one(slug: str, session: AsyncSession):
    data = json.loads((BUYER_CATALOG_DIR / f"{slug}.json").read_text())
    meta = STORE_DEFAULTS[slug]
    store = await session.get(Store, meta["id"])
    if store is None:
        store = Store(id=meta["id"], name=meta["name"], bpp_id=meta["bpp_id"])
        session.add(store)
        await session.flush()
    for prod_data in data["products"]:
        prod = (await session.execute(
            select(Product).where(Product.store_id == store.id, Product.sku == prod_data["sku"])
        )).scalar_one_or_none()
        if prod is None:
            prod = Product(store_id=store.id, sku=prod_data["sku"], name=prod_data["name"],
                           status="ACTIVE", attributes=prod_data.get("attributes", {}))
            session.add(prod); await session.flush()
        else:
            prod.name = prod_data["name"]; prod.attributes = prod_data.get("attributes", {})
        # product images
        await session.execute(ProductImage.__table__.delete().where(ProductImage.product_id == prod.id))
        for pos, url in enumerate(prod_data.get("gallery", []) or [prod_data.get("image_url", "")]):
            if url:
                session.add(ProductImage(product_id=prod.id, url=url, position=pos, is_primary=(pos == 0)))
        # SKUs
        for variant in prod_data.get("variants", [{"sku_code": prod_data["sku"], "price": prod_data["price"], "stock": prod_data.get("stock", 0)}]):
            sku = (await session.execute(
                select(SKU).where(SKU.product_id == prod.id, SKU.sku_code == variant["sku_code"])
            )).scalar_one_or_none()
            if sku is None:
                sku = SKU(product_id=prod.id, sku_code=variant["sku_code"],
                          variant_name=variant.get("variant_name", "Default"),
                          variant_value=variant.get("variant_value", "Default"),
                          price=variant["price"], stock=variant.get("stock", 0),
                          weight_grams=variant.get("weight_grams", 0))
                session.add(sku); await session.flush()
            else:
                sku.price = variant["price"]; sku.stock = variant.get("stock", sku.stock)
            await session.execute(SKUImage.__table__.delete().where(SKUImage.sku_id == sku.id))
            for pos, url in enumerate(variant.get("images", [])):
                session.add(SKUImage(sku_id=sku.id, url=url, position=pos, is_primary=(pos == 0)))
    await session.commit()
    print(f"seeded {slug}: {len(data['products'])} products")

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    slugs = list(STORE_DEFAULTS) if args.all else (args.slug or [])
    if not slugs:
        ap.error("pass --slug X --slug Y or --all")
    async with async_session_maker() as s:
        for slug in slugs:
            await seed_one(slug, s)

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Look up real UUIDs for Gendes + YourBrand** (or generate new ones with `python -c "import uuid; print(uuid.uuid4())"` if those stores don't exist yet). Fill into `STORE_DEFAULTS`.

- [ ] **Step 3: Run for all 4**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller && python scripts/seed-from-buyer-catalog.py --all
```

Expected output: 4 `seeded <slug>: N products` lines.

- [ ] **Step 4: Verify counts**

```bash
psql seller_db -c "SELECT s.name, COUNT(p.id) AS products, COUNT(sk.id) AS skus FROM stores s LEFT JOIN products p ON p.store_id=s.id LEFT JOIN skus sk ON sk.product_id=p.id GROUP BY s.name;"
```

Expected: 4 rows, product/sku counts matching the JSON files.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed-from-buyer-catalog.py
git commit -m "feat(seller): unified catalog seeder for all 4 tokos"
```

---

### Task 2.2: Buyer mirror tables (migration)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/models/mirror.py`
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/alembic/versions/<auto>_mirror_tables.py`

- [ ] **Step 1: Add models**

```python
# apps/beli-aman-bap/models/mirror.py
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from apps.beli_aman_bap.database import Base

class MirrorStore(Base):
    __tablename__ = "mirror_stores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bpp_id = Column(String, nullable=False, unique=True, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    logo_url = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    city = Column(String, nullable=True)
    last_pushed_at = Column(DateTime, nullable=True)
    last_pulled_at = Column(DateTime, nullable=True)
    catalog_version = Column(String, nullable=True)
    products = relationship("MirrorProduct", back_populates="store", cascade="all, delete-orphan")

class MirrorProduct(Base):
    __tablename__ = "mirror_products"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("mirror_stores.id"), nullable=False, index=True)
    bpp_product_id = Column(String, nullable=False, index=True)  # seller's Product.id as string
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")
    attributes = Column(JSON, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    store = relationship("MirrorStore", back_populates="products")
    skus = relationship("MirrorSKU", back_populates="product", cascade="all, delete-orphan")
    images = relationship("MirrorProductImage", back_populates="product", cascade="all, delete-orphan")

class MirrorSKU(Base):
    __tablename__ = "mirror_skus"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("mirror_products.id"), nullable=False, index=True)
    bpp_sku_id = Column(String, nullable=False, index=True)
    variant_name = Column(String, nullable=True)
    variant_value = Column(String, nullable=True)
    sku_code = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    original_price = Column(Float, nullable=True)
    stock = Column(Integer, nullable=False, default=0)
    weight_grams = Column(Integer, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    product = relationship("MirrorProduct", back_populates="skus")
    images = relationship("MirrorSKUImage", back_populates="sku", cascade="all, delete-orphan")

class MirrorSKUImage(Base):
    __tablename__ = "mirror_sku_images"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku_id = Column(UUID(as_uuid=True), ForeignKey("mirror_skus.id"), nullable=False)
    url = Column(String, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    is_primary = Column(Boolean, nullable=False, default=False)
    sku = relationship("MirrorSKU", back_populates="images")

class MirrorProductImage(Base):
    __tablename__ = "mirror_product_images"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("mirror_products.id"), nullable=False)
    url = Column(String, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    is_primary = Column(Boolean, nullable=False, default=False)
    product = relationship("MirrorProduct", back_populates="images")
```

- [ ] **Step 2: Migrate + apply**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
alembic -c apps/beli-aman-bap/alembic.ini revision -m "mirror tables" --autogenerate
alembic -c apps/beli-aman-bap/alembic.ini upgrade head
```

- [ ] **Step 3: Verify**

```bash
psql beli_aman -c "\dt mirror_*"
```

Expected: 5 mirror tables listed.

- [ ] **Step 4: Commit**

```bash
git add apps/beli-aman-bap/models/mirror.py apps/beli-aman-bap/alembic/versions/*_mirror_tables.py
git commit -m "feat(buyer): mirror tables for catalog hint cache"
```

---

### Task 2.3: Seller `/beckn/search` returns full catalog as `/on_search` payload

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_search.py`

- [ ] **Step 1: Look at the existing `/beckn/search` stub** to understand current shape (might just be a placeholder).

- [ ] **Step 2: Implement — receive /search, immediately respond 202 ACK, then async POST /on_search to BAP with full catalog**

```python
# app/beckn/endpoints.py (add or replace)
from fastapi import APIRouter, Request, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.deps import get_db, get_registry_client, signing_key_for
from app.models.store import Store
from app.models.product import Product
from beckn_protocol.envelope import envelope
from beckn_protocol.outbound import sign_and_send
import uuid

beckn_router = APIRouter(prefix="/beckn")

@beckn_router.post("/search")
async def beckn_search(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope  # set by middleware
    background.add_task(_emit_on_search, env)
    return {"message": {"ack": {"status": "ACK"}}}

async def _emit_on_search(req_env: dict):
    bap_id = req_env["context"]["bap_id"]
    bap_uri = req_env["context"]["bap_uri"]
    # search currently returns ALL catalog from ALL of this seller's BPPs.
    # In a real multi-BPP setup we'd filter by req_env["message"]["intent"]
    async with get_db() as session:
        stores = (await session.execute(
            select(Store).options(
                selectinload(Store.products).selectinload(Product.skus),
                selectinload(Store.products).selectinload(Product.images),
            )
        )).scalars().all()
        for store in stores:
            if not store.bpp_id:
                continue
            payload = _build_on_search_payload(store)
            ctx = envelope(
                action="on_search",
                bap_id=bap_id, bap_uri=bap_uri,
                bpp_id=store.bpp_id,
                bpp_uri=os.environ.get("SELLER_BECKN_URL", "http://localhost:8001/beckn"),
                transaction_id=req_env["context"]["transaction_id"],
                message_id=str(uuid.uuid4()),
                payload=payload,
            )
            priv, key_id = signing_key_for(store.bpp_id)
            target = f"{bap_uri.rstrip('/')}/on_search"
            await sign_and_send(url=target, body=ctx, private_key=priv, key_id=key_id)

def _build_on_search_payload(store) -> dict:
    return {
        "catalog": {
            "bpp/descriptor": {"name": store.name, "images": [store.logo_url] if store.logo_url else []},
            "bpp/providers": [{
                "id": store.bpp_id,
                "descriptor": {"name": store.name},
                "items": [_item(p, sku) for p in store.products for sku in p.skus],
            }],
        }
    }

def _item(product, sku) -> dict:
    return {
        "id": sku.sku_code,
        "parent_item_id": product.sku,
        "descriptor": {
            "name": product.name,
            "code": sku.sku_code,
            "images": [img.url for img in sorted(sku.images, key=lambda i: i.position)] or
                      [img.url for img in sorted(product.images, key=lambda i: i.position)],
        },
        "price": {"currency": "IDR", "value": str(sku.price), "maximum_value": str(sku.original_price or sku.price)},
        "quantity": {"available": {"count": sku.stock}, "maximum": {"count": sku.stock}},
        "matched": True,
        "@ondc/org/statutory_reqs_packaged_commodities": {},  # placeholder for future
        "tags": [
            {"code": "variant", "list": [
                {"code": "name", "value": sku.variant_name or ""},
                {"code": "value", "value": sku.variant_value or ""},
            ]},
        ],
    }
```

- [ ] **Step 3: Test — POST signed /beckn/search, capture outbound /on_search payload, verify shape**

```python
# tests/beckn/test_search.py — outline
@pytest.mark.asyncio
async def test_search_emits_on_search_per_store(signed_client, db_session_with_seeded_stores, captured_outbound):
    r = await signed_client.post("/beckn/search", json_envelope=make_search_envelope())
    assert r.status_code == 200
    # background task ran:
    await asyncio.sleep(0.1)
    sent = captured_outbound.calls
    bpp_ids = {call["body"]["context"]["bpp_id"] for call in sent}
    assert "safiyafood.bpp.metatech.id" in bpp_ids
    item_count = sum(len(call["body"]["message"]["catalog"]["bpp/providers"][0]["items"]) for call in sent)
    assert item_count > 0
```

(`captured_outbound` is a fixture that monkeypatches `app.beckn.outbound.sign_and_send` to append to a list and return `httpx.Response(200, json={"message":{"ack":{"status":"ACK"}}})`.)

- [ ] **Step 4: Run + commit**

```bash
pytest tests/beckn/test_search.py -v
git add app/beckn/endpoints.py tests/beckn/test_search.py
git commit -m "feat(seller): /beckn/search emits per-store /on_search with full catalog"
```

---

### Task 2.4: Buyer `/api/v1/beckn/on_search` handler upserts mirror

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/main.py` (mount router)
- Test: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/tests/test_on_search.py`

- [ ] **Step 1: Implement handler**

```python
# apps/beli-aman-bap/routers/beckn.py
from datetime import datetime
from fastapi import APIRouter, Request
from sqlalchemy import select
from apps.beli_aman_bap.database import get_db
from apps.beli_aman_bap.models.mirror import (
    MirrorStore, MirrorProduct, MirrorSKU, MirrorSKUImage, MirrorProductImage,
)

beckn_router = APIRouter(prefix="/api/v1/beckn")

@beckn_router.post("/on_search")
async def on_search(request: Request):
    env = request.state.beckn_envelope
    catalog = env["message"]["catalog"]
    bpp_id = env["context"]["bpp_id"]
    async with get_db() as session:
        store = (await session.execute(
            select(MirrorStore).where(MirrorStore.bpp_id == bpp_id)
        )).scalar_one_or_none()
        if store is None:
            store = MirrorStore(
                bpp_id=bpp_id,
                slug=bpp_id.split(".")[0],
                name=catalog["bpp/descriptor"]["name"],
            )
            session.add(store); await session.flush()
        store.last_pushed_at = datetime.utcnow()
        # naive full-replace approach for v1; delta optimization later
        await session.execute(MirrorProduct.__table__.delete().where(MirrorProduct.store_id == store.id))
        await session.flush()
        for provider in catalog["bpp/providers"]:
            # group items by parent_item_id → MirrorProduct
            by_parent = {}
            for item in provider["items"]:
                by_parent.setdefault(item["parent_item_id"], []).append(item)
            for parent_sku, items in by_parent.items():
                first = items[0]
                prod = MirrorProduct(
                    store_id=store.id,
                    bpp_product_id=parent_sku,
                    sku=parent_sku,
                    name=first["descriptor"]["name"],
                    status="ACTIVE",
                )
                session.add(prod); await session.flush()
                for item in items:
                    sku = MirrorSKU(
                        product_id=prod.id,
                        bpp_sku_id=item["id"],
                        sku_code=item["descriptor"]["code"],
                        price=float(item["price"]["value"]),
                        original_price=float(item["price"].get("maximum_value", item["price"]["value"])),
                        stock=item["quantity"]["available"]["count"],
                    )
                    for tag in item.get("tags", []):
                        if tag["code"] == "variant":
                            for kv in tag["list"]:
                                if kv["code"] == "name": sku.variant_name = kv["value"]
                                if kv["code"] == "value": sku.variant_value = kv["value"]
                    session.add(sku); await session.flush()
                    for pos, url in enumerate(item["descriptor"].get("images", [])):
                        session.add(MirrorSKUImage(sku_id=sku.id, url=url, position=pos, is_primary=(pos == 0)))
        await session.commit()
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 2: Mount in main.py**

```python
# apps/beli-aman-bap/main.py
from apps.beli_aman_bap.routers.beckn import beckn_router
app.include_router(beckn_router)
```

- [ ] **Step 3: Test**

```python
# tests/test_on_search.py
@pytest.mark.asyncio
async def test_on_search_creates_mirror_rows(signed_client_buyer, db_session):
    env = make_on_search_envelope(
        bpp_id="safiyafood.bpp.metatech.id",
        catalog={
            "bpp/descriptor": {"name": "Safiya Food", "images": []},
            "bpp/providers": [{
                "id": "safiyafood.bpp.metatech.id",
                "descriptor": {"name": "Safiya Food"},
                "items": [{
                    "id": "SAF-SUK-500", "parent_item_id": "SAF-SUK",
                    "descriptor": {"name": "Kurma Sukari", "code": "SAF-SUK-500", "images": ["http://x/img.jpg"]},
                    "price": {"currency": "IDR", "value": "89000", "maximum_value": "89000"},
                    "quantity": {"available": {"count": 200}, "maximum": {"count": 200}},
                    "tags": [{"code": "variant", "list": [{"code": "name", "value": "Size"}, {"code": "value", "value": "500g"}]}],
                }],
            }],
        },
    )
    r = await signed_client_buyer.post("/api/v1/beckn/on_search", json_envelope=env)
    assert r.status_code == 200
    stores = (await db_session.execute(select(MirrorStore))).scalars().all()
    assert any(s.bpp_id == "safiyafood.bpp.metatech.id" for s in stores)
    skus = (await db_session.execute(select(MirrorSKU))).scalars().all()
    assert any(s.sku_code == "SAF-SUK-500" and s.stock == 200 for s in skus)
```

- [ ] **Step 4: Run + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && pytest apps/beli-aman-bap/tests/test_on_search.py -v
git add apps/beli-aman-bap/routers/beckn.py apps/beli-aman-bap/main.py apps/beli-aman-bap/tests/test_on_search.py
git commit -m "feat(buyer): /on_search handler upserts mirror"
```

---

### Task 2.5: Seller emits `/on_search` on product writes (push primary)

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/api/products.py`

- [ ] **Step 1: After commit on POST/PUT/DELETE products, enqueue an emit** — for v1 just call `_emit_on_search` directly with background task.

In `app/api/products.py`, in the create/update/delete handlers, after the DB commit add:

```python
from app.beckn.endpoints import _emit_on_search
from app.deps import resolve_bap_for_push

@router.post("/products")
async def create_product(...):
    # ... existing code that commits ...
    for bap_uri, bap_id in await resolve_bap_for_push():
        await _emit_on_search({
            "context": {"bap_id": bap_id, "bap_uri": bap_uri,
                        "transaction_id": str(uuid.uuid4())},
            "message": {"intent": {}},
        })
    return result
```

`resolve_bap_for_push()` returns a list of `(bap_uri, bap_id)` — for now hardcoded to Beli Aman:

```python
# app/deps.py
async def resolve_bap_for_push():
    return [(os.environ.get("BELI_AMAN_BECKN_URL", "http://localhost:8002/api/v1/beckn"),
             "beli-aman.bap.metatech.id")]
```

- [ ] **Step 2: Smoke** — POST a product via the API, observe buyer mirror update within ~1s. (No automated test for this — it crosses processes.)

- [ ] **Step 3: Commit**

```bash
git add app/api/products.py app/deps.py
git commit -m "feat(seller): emit /on_search to BAPs after product writes"
```

---

### Task 2.6: Buyer pull-worker (5-minute /search safety net)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/workers/catalog_puller.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/main.py` (start worker on lifespan)

- [ ] **Step 1: Implement**

```python
# apps/beli-aman-bap/workers/catalog_puller.py
import asyncio, uuid, logging
from sqlalchemy import select
from apps.beli_aman_bap.database import get_db
from apps.beli_aman_bap.models.mirror import MirrorStore
from apps.beli_aman_bap.beckn.outbound import send_beckn
from beckn_protocol.envelope import envelope

log = logging.getLogger(__name__)

PULL_INTERVAL_SECS = 300

async def pull_once():
    async with get_db() as session:
        stores = (await session.execute(select(MirrorStore))).scalars().all()
        for store in stores:
            env = envelope(
                action="search",
                bap_id="beli-aman.bap.metatech.id",
                bap_uri="http://localhost:8002/api/v1/beckn",
                bpp_id=None, bpp_uri=None,
                transaction_id=str(uuid.uuid4()),
                message_id=str(uuid.uuid4()),
                payload={"intent": {}},
            )
            try:
                await send_beckn(env, target_url="http://localhost:8001/beckn/search", session=session)
            except Exception as e:
                log.warning("pull failed for %s: %s", store.bpp_id, e)

async def run_forever():
    while True:
        try:
            await pull_once()
        except Exception as e:
            log.exception("pull_once failed")
        await asyncio.sleep(PULL_INTERVAL_SECS)
```

- [ ] **Step 2: Start in lifespan**

```python
# apps/beli-aman-bap/main.py
from contextlib import asynccontextmanager
from apps.beli_aman_bap.workers.catalog_puller import run_forever as catalog_puller_loop

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(catalog_puller_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 3: Smoke (no automated test)** — boot buyer, wait 5 min, check mirror's `last_pushed_at` advances OR add a one-shot trigger: `python -c "import asyncio; from apps.beli_aman_bap.workers.catalog_puller import pull_once; asyncio.run(pull_once())"`.

- [ ] **Step 4: Commit**

```bash
git add apps/beli-aman-bap/workers/ apps/beli-aman-bap/main.py
git commit -m "feat(buyer): 5-minute catalog pull worker"
```

---

### Task 2.7: Switch storefront to read from mirror

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/services/catalog.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/brands.py`

- [ ] **Step 1: Rewrite `catalog_service.list_products`**

```python
# apps/beli-aman-bap/services/catalog.py
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from apps.beli_aman_bap.database import get_db
from apps.beli_aman_bap.models.mirror import MirrorStore, MirrorProduct, MirrorSKU

async def list_products(slug: str) -> list[dict]:
    async with get_db() as session:
        store = (await session.execute(
            select(MirrorStore)
            .where(MirrorStore.slug == slug)
            .options(
                selectinload(MirrorStore.products).selectinload(MirrorProduct.skus).selectinload(MirrorSKU.images),
                selectinload(MirrorStore.products).selectinload(MirrorProduct.images),
            )
        )).scalar_one_or_none()
        if store is None:
            return []
        return [_serialize(p) for p in store.products]

def _serialize(p) -> dict:
    return {
        "sku": p.sku,
        "name": p.name,
        "status": p.status,
        "attributes": p.attributes or {},
        "gallery": [img.url for img in sorted(p.images, key=lambda i: i.position)],
        "variants": [
            {
                "sku_code": s.sku_code,
                "variant_name": s.variant_name,
                "variant_value": s.variant_value,
                "price": s.price,
                "original_price": s.original_price,
                "stock": s.stock,
                "weight_grams": s.weight_grams,
                "images": [i.url for i in sorted(s.images, key=lambda i: i.position)],
            }
            for s in p.skus
        ],
    }
```

(Mirror existing storefront's response shape — confirm by comparing to current JSON-reading behavior.)

- [ ] **Step 2: brands.py router unchanged in signature** (`GET /api/v1/brands/{slug}/products` still calls `list_products(slug)`).

- [ ] **Step 3: Manual smoke**

```bash
curl http://localhost:8002/api/v1/brands/safiyafood/products | jq '.[] | .name' | head -5
```

Expected: 5 product names from the mirror.

- [ ] **Step 4: Commit**

```bash
git add apps/beli-aman-bap/services/catalog.py
git commit -m "feat(buyer): storefront reads from mirror instead of JSON"
```

---

### Task 2.8: Delete JSON catalog files

**Files:**
- Delete: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/catalog/safiyafood.json`
- Delete: same for `antarestar.json`, `gendes.json`, `yourbrand.json`

- [ ] **Step 1: Verify storefront still renders all 4 tokos via mirror first**

Visit `http://localhost:3000/safiyafood`, `/antarestar`, `/gendes`, `/yourbrand` in browser (or curl `/api/v1/brands/<slug>/products` for each).

- [ ] **Step 2: Delete files**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
git rm apps/beli-aman-bap/catalog/safiyafood.json apps/beli-aman-bap/catalog/antarestar.json apps/beli-aman-bap/catalog/gendes.json apps/beli-aman-bap/catalog/yourbrand.json
```

- [ ] **Step 3: Remove JSON-loading dead code** in `services/catalog.py` (any remaining `Path(...).read_text()`).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(buyer): retire JSON catalogs — mirror is now sole source"
```

---

**Phase 2 complete.** Buyer storefront serves from `mirror_*` tables. Seller is the source. Catalog edits propagate buyer-ward in <1s via push and have a 5-min pull safety net.

---

## Phase 3: Orders via Beckn (replace seller_bridge)

After this phase: order placement flows `/select → /init → /confirm` over signed Beckn HTTP. Inventory decrements atomically at seller inside a `SELECT ... FOR UPDATE` transaction. The `seller_bridge.py` HTTP shortcut is deleted.

### Task 3.1: `quote_token` infrastructure on seller

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/models/quote.py`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/alembic/versions/<auto>_quote_tokens.py`

- [ ] **Step 1: Model — short-lived signed quote that pins price + shipping for ~10 min**

```python
# app/models/quote.py
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.db import Base

class QuoteToken(Base):
    __tablename__ = "quote_tokens"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    bap_id = Column(String, nullable=False)
    transaction_id = Column(String, nullable=False, index=True)
    items = Column(JSON, nullable=False)            # [{sku_code, qty, unit_price}]
    shipping = Column(JSON, nullable=False)         # {courier_code, service, cost}
    address = Column(JSON, nullable=False)
    subtotal = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 2: Migrate + apply.**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
alembic revision -m "quote tokens" --autogenerate
alembic upgrade head
```

- [ ] **Step 3: Commit.**

```bash
git add app/models/quote.py alembic/versions/*_quote_tokens.py
git commit -m "feat(seller): quote_tokens for /init→/confirm flow"
```

---

### Task 3.2: Seller `/beckn/select` — price + stock preview, NO mutation

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_select.py`

- [ ] **Step 1: Test — request SKUs that exist + one out-of-stock; assert on_select payload**

```python
# tests/beckn/test_select.py — outline
@pytest.mark.asyncio
async def test_select_returns_prices_and_marks_oos(signed_client, seeded_safiyafood, captured_outbound):
    env = make_select_envelope(items=[
        {"id": "SAF-SUK-500", "quantity": {"count": 2}},
        {"id": "SAF-AJW-250", "quantity": {"count": 999}},   # OOS
    ])
    r = await signed_client.post("/beckn/select", json_envelope=env)
    assert r.status_code == 200
    await asyncio.sleep(0.1)
    payload = captured_outbound.calls[0]["body"]["message"]
    items = {i["id"]: i for i in payload["order"]["items"]}
    assert items["SAF-SUK-500"]["price"]["value"] == "89000"
    assert items["SAF-AJW-250"].get("tags", [{}])[0].get("code") == "out_of_stock"
```

- [ ] **Step 2: Implement**

```python
# in app/beckn/endpoints.py
@beckn_router.post("/select")
async def beckn_select(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope
    background.add_task(_emit_on_select, env)
    return {"message": {"ack": {"status": "ACK"}}}

async def _emit_on_select(req_env):
    items_req = req_env["message"]["order"]["items"]
    sku_codes = [i["id"] for i in items_req]
    async with get_db() as session:
        skus = (await session.execute(
            select(SKU).where(SKU.sku_code.in_(sku_codes))
        )).scalars().all()
        by_code = {s.sku_code: s for s in skus}
    items_resp = []
    subtotal = 0
    for item in items_req:
        s = by_code.get(item["id"])
        qty = item["quantity"]["count"]
        if s is None:
            items_resp.append({"id": item["id"], "tags": [{"code": "not_found"}]})
            continue
        oos = s.stock < qty
        tag = [{"code": "out_of_stock"}] if oos else []
        items_resp.append({
            "id": s.sku_code,
            "price": {"currency": "IDR", "value": str(s.price)},
            "quantity": {"selected": {"count": qty}, "available": {"count": s.stock}},
            "tags": tag,
        })
        if not oos:
            subtotal += int(s.price) * qty
    # shipping options — call Biteship rates here in v2; stub for now
    fulfillments = [{"id": "biteship-jne-reg", "type": "Delivery",
                     "provider": {"name": "JNE"},
                     "price": {"currency": "IDR", "value": "15000"}}]
    payload = {"order": {"items": items_resp, "fulfillments": fulfillments,
                         "quote": {"price": {"currency": "IDR", "value": str(subtotal)}}}}
    out_env = envelope(
        action="on_select",
        bap_id=req_env["context"]["bap_id"], bap_uri=req_env["context"]["bap_uri"],
        bpp_id=req_env["context"]["bpp_id"], bpp_uri=req_env["context"].get("bpp_uri"),
        transaction_id=req_env["context"]["transaction_id"],
        message_id=str(uuid.uuid4()),
        payload=payload,
    )
    priv, key_id = signing_key_for(req_env["context"]["bpp_id"])
    await sign_and_send(url=f"{req_env['context']['bap_uri'].rstrip('/')}/on_select",
                        body=out_env, private_key=priv, key_id=key_id)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/beckn/test_select.py -v
git add app/beckn/endpoints.py tests/beckn/test_select.py
git commit -m "feat(seller): /beckn/select returns prices, marks OOS"
```

---

### Task 3.3: Buyer `/api/v1/beckn/on_select` handler

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`

- [ ] **Step 1: Persist response into the in-flight cart**

Add an endpoint that stores `on_select` payload by `transaction_id` so the cart UI can render fresh pricing + OOS flags:

```python
# routers/beckn.py
from apps.beli_aman_bap.models.cart import Cart  # existing or new
@beckn_router.post("/on_select")
async def on_select(request: Request):
    env = request.state.beckn_envelope
    tx_id = env["context"]["transaction_id"]
    async with get_db() as session:
        cart = (await session.execute(select(Cart).where(Cart.transaction_id == tx_id))).scalar_one_or_none()
        if cart is None:
            cart = Cart(transaction_id=tx_id)
            session.add(cart)
        cart.last_on_select = env["message"]
        await session.commit()
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 2: Add `Cart` model + migration if it doesn't already exist**

```python
# apps/beli-aman-bap/models/cart.py
from datetime import datetime
from sqlalchemy import Column, String, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid
from apps.beli_aman_bap.database import Base

class Cart(Base):
    __tablename__ = "carts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(String, nullable=False, unique=True, index=True)
    bpp_id = Column(String, nullable=True)
    last_on_select = Column(JSON, nullable=True)
    last_on_init = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

Migrate + commit:

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
alembic -c apps/beli-aman-bap/alembic.ini revision -m "carts" --autogenerate
alembic -c apps/beli-aman-bap/alembic.ini upgrade head
git add apps/beli-aman-bap/models/cart.py apps/beli-aman-bap/routers/beckn.py apps/beli-aman-bap/alembic/versions/*_carts.py
git commit -m "feat(buyer): Cart + /on_select handler"
```

---

### Task 3.4: Buyer cart flow uses Beckn `/select`

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/services/order_flow.py` (new file or extend existing)

- [ ] **Step 1: When buyer adds to cart, send `/select` over Beckn** (background or sync — for v1 sync OK, cart UI shows spinner)

```python
# services/order_flow.py
import uuid
from apps.beli_aman_bap.beckn.outbound import send_beckn
from beckn_protocol.envelope import envelope

async def add_to_cart(*, bpp_id: str, items: list[dict], session) -> dict:
    tx_id = str(uuid.uuid4())
    env = envelope(
        action="select",
        bap_id="beli-aman.bap.metatech.id",
        bap_uri="http://localhost:8002/api/v1/beckn",
        bpp_id=bpp_id,
        bpp_uri="http://localhost:8001/beckn",
        transaction_id=tx_id,
        message_id=str(uuid.uuid4()),
        payload={"order": {"items": items}},
    )
    await send_beckn(env, target_url="http://localhost:8001/beckn/select", session=session)
    return {"transaction_id": tx_id}
```

- [ ] **Step 2: Wire into existing cart endpoint** in `routers/orders.py` so existing UI path now triggers Beckn.

- [ ] **Step 3: Commit**

```bash
git add apps/beli-aman-bap/services/order_flow.py apps/beli-aman-bap/routers/orders.py
git commit -m "feat(buyer): cart add-to-cart triggers beckn /select"
```

---

### Task 3.5: Seller `/beckn/init` — issue quote_token

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_init.py`

- [ ] **Step 1: Test — init issues a token with TTL, on_init payload carries it**

```python
@pytest.mark.asyncio
async def test_init_issues_quote_token(signed_client, seeded_store, captured_outbound, db_session):
    env = make_init_envelope(items=[{"id": "SAF-SUK-500", "quantity": {"count": 2}}],
                              fulfillment_id="biteship-jne-reg",
                              billing_address={"name": "Andi", "phone": "081"})
    await signed_client.post("/beckn/init", json_envelope=env)
    await asyncio.sleep(0.1)
    payload = captured_outbound.calls[0]["body"]["message"]
    assert payload["order"]["payment"]["params"]["quote_token"]
    token = payload["order"]["payment"]["params"]["quote_token"]
    quote = (await db_session.execute(select(QuoteToken).where(QuoteToken.id == uuid.UUID(token)))).scalar_one()
    assert quote.total == 89000 * 2 + 15000  # subtotal + shipping
```

- [ ] **Step 2: Implement `/beckn/init` + `_emit_on_init`**

```python
# app/beckn/endpoints.py
from datetime import datetime, timedelta
from app.models.quote import QuoteToken
from app.models.store import Store

QUOTE_TTL = timedelta(minutes=10)

@beckn_router.post("/init")
async def beckn_init(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope
    background.add_task(_emit_on_init, env)
    return {"message": {"ack": {"status": "ACK"}}}

async def _emit_on_init(req_env):
    items_req = req_env["message"]["order"]["items"]
    fulfillment_id = req_env["message"]["order"]["fulfillments"][0]["id"]
    billing = req_env["message"]["order"]["billing"]
    bpp_id = req_env["context"]["bpp_id"]
    async with get_db() as session:
        store = (await session.execute(select(Store).where(Store.bpp_id == bpp_id))).scalar_one()
        skus = (await session.execute(
            select(SKU).where(SKU.sku_code.in_([i["id"] for i in items_req]))
        )).scalars().all()
        by_code = {s.sku_code: s for s in skus}
        items_resolved = []
        subtotal = 0
        for it in items_req:
            s = by_code[it["id"]]
            qty = it["quantity"]["count"]
            items_resolved.append({"sku_code": s.sku_code, "qty": qty, "unit_price": int(s.price)})
            subtotal += int(s.price) * qty
        shipping_cost = 15000  # stub; replace with Biteship rate call
        token = QuoteToken(
            store_id=store.id,
            bap_id=req_env["context"]["bap_id"],
            transaction_id=req_env["context"]["transaction_id"],
            items=items_resolved,
            shipping={"id": fulfillment_id, "cost": shipping_cost},
            address=billing,
            subtotal=subtotal,
            total=subtotal + shipping_cost,
            expires_at=datetime.utcnow() + QUOTE_TTL,
        )
        session.add(token); await session.commit()
        token_id = str(token.id)
    payload = {"order": {
        "items": items_req,
        "quote": {"price": {"currency": "IDR", "value": str(subtotal + shipping_cost)},
                  "breakup": [
                      {"title": "Items", "price": {"value": str(subtotal)}},
                      {"title": "Shipping", "price": {"value": str(shipping_cost)}},
                  ]},
        "payment": {"params": {"quote_token": token_id, "amount": str(subtotal + shipping_cost),
                               "currency": "IDR"}},
    }}
    out_env = envelope(action="on_init",
                       bap_id=req_env["context"]["bap_id"], bap_uri=req_env["context"]["bap_uri"],
                       bpp_id=bpp_id, bpp_uri=req_env["context"].get("bpp_uri"),
                       transaction_id=req_env["context"]["transaction_id"],
                       message_id=str(uuid.uuid4()), payload=payload)
    priv, key_id = signing_key_for(bpp_id)
    await sign_and_send(url=f"{req_env['context']['bap_uri'].rstrip('/')}/on_init",
                        body=out_env, private_key=priv, key_id=key_id)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/beckn/test_init.py -v
git add app/beckn/endpoints.py tests/beckn/test_init.py
git commit -m "feat(seller): /beckn/init issues quote_token"
```

---

### Task 3.6: Buyer `/api/v1/beckn/on_init` + binds quote_token to local Order

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/models/order.py` (add `bpp_quote_token`)

- [ ] **Step 1: Add column**

```python
# apps/beli-aman-bap/models/order.py — add
bpp_quote_token = Column(String, nullable=True)
bpp_id = Column(String, nullable=True)
beckn_transaction_id = Column(String, nullable=True, index=True)
bpp_order_id = Column(String, nullable=True, index=True)   # seller's Order.id, set on /on_confirm
amount_total = Column(Integer, nullable=True)              # quoted total from /on_init
failure_reason = Column(String, nullable=True)
```

Migrate.

- [ ] **Step 2: Handler**

```python
@beckn_router.post("/on_init")
async def on_init(request: Request):
    env = request.state.beckn_envelope
    tx_id = env["context"]["transaction_id"]
    payload = env["message"]
    async with get_db() as session:
        order = (await session.execute(
            select(Order).where(Order.beckn_transaction_id == tx_id)
        )).scalar_one_or_none()
        if order:
            order.bpp_quote_token = payload["order"]["payment"]["params"]["quote_token"]
            order.amount_total = int(payload["order"]["payment"]["params"]["amount"])
            await session.commit()
        # also stash on Cart for the UI:
        cart = (await session.execute(select(Cart).where(Cart.transaction_id == tx_id))).scalar_one_or_none()
        if cart:
            cart.last_on_init = payload
            await session.commit()
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 3: Commit**

```bash
git add apps/beli-aman-bap/models/order.py apps/beli-aman-bap/routers/beckn.py apps/beli-aman-bap/alembic/versions/*_order_quote_token.py
git commit -m "feat(buyer): /on_init binds quote_token to Order"
```

---

### Task 3.7: Buyer triggers Beckn `/init` at AUTHED state

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/orders.py:229-276`

- [ ] **Step 1: In the existing `PATCH /api/v1/orders/{order_id}/auth` handler, after stashing address + payment method, send `/init`**

```python
# inside PATCH /orders/{id}/auth, after state transitions to AUTHED:
env = envelope(
    action="init",
    bap_id="beli-aman.bap.metatech.id",
    bap_uri="http://localhost:8002/api/v1/beckn",
    bpp_id=order.bpp_id,
    bpp_uri="http://localhost:8001/beckn",
    transaction_id=order.beckn_transaction_id,
    message_id=str(uuid.uuid4()),
    payload={"order": {
        "items": [{"id": i["sku_code"], "quantity": {"count": i["qty"]}} for i in order.items],
        "billing": order.billing_address,
        "fulfillments": [{"id": order.shipping_choice_id}],
    }},
)
await send_beckn(env, target_url="http://localhost:8001/beckn/init", session=session)
```

- [ ] **Step 2: Smoke** — trigger auth, observe seller logs a `/beckn/init`, buyer's order acquires `bpp_quote_token` within ~500ms.

- [ ] **Step 3: Commit**

```bash
git add apps/beli-aman-bap/routers/orders.py
git commit -m "feat(buyer): AUTHED state triggers beckn /init"
```

---

### Task 3.8: Seller `/beckn/confirm` with race-safe inventory transaction (CRITICAL)

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_confirm_race.py`

- [ ] **Step 1: Test (TDD) — two concurrent `/confirm`s for the last unit; assert exactly one ACK + one NACK + final stock = 0**

```python
# tests/beckn/test_confirm_race.py
import asyncio, uuid, pytest
from sqlalchemy import select
from app.models.sku import SKU
from app.models.order import Order
from app.models.quote import QuoteToken
from app.beckn.endpoints import _emit_on_confirm

@pytest.mark.asyncio
async def test_two_buyers_race_for_last_unit(db_session, store_with_one_unit_sku):
    sku, store = store_with_one_unit_sku  # stock=1
    quote_a = await _issue_quote(db_session, store, sku, qty=1, bap="bap.a")
    quote_b = await _issue_quote(db_session, store, sku, qty=1, bap="bap.b")
    env_a = make_confirm_envelope(bap="bap.a", bpp_id=store.bpp_id, quote_token=quote_a.id, payment_proof="X1")
    env_b = make_confirm_envelope(bap="bap.b", bpp_id=store.bpp_id, quote_token=quote_b.id, payment_proof="X2")
    results = await asyncio.gather(
        _emit_on_confirm(env_a, capture=True),
        _emit_on_confirm(env_b, capture=True),
        return_exceptions=True,
    )
    acks = [r for r in results if r and r["ack"]]
    nacks = [r for r in results if r and not r["ack"]]
    assert len(acks) == 1
    assert len(nacks) == 1
    assert nacks[0]["error"] == "OUT_OF_STOCK"
    sku_after = (await db_session.execute(select(SKU).where(SKU.id == sku.id))).scalar_one()
    assert sku_after.stock == 0
    orders = (await db_session.execute(select(Order).where(Order.store_id == store.id))).scalars().all()
    assert len(orders) == 1
```

- [ ] **Step 2: Implement**

```python
# app/beckn/endpoints.py
from sqlalchemy import select
from app.models.order import Order
from app.models.quote import QuoteToken

class OutOfStock(Exception):
    def __init__(self, sku_id): self.sku_id = sku_id

@beckn_router.post("/confirm")
async def beckn_confirm(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope
    background.add_task(_emit_on_confirm, env)
    return {"message": {"ack": {"status": "ACK"}}}

async def _emit_on_confirm(req_env: dict, capture: bool = False):
    bpp_id = req_env["context"]["bpp_id"]
    payment = req_env["message"]["order"]["payment"]
    quote_token_id = uuid.UUID(payment["params"]["quote_token"])
    payment_proof = payment.get("params", {}).get("payment_proof") or payment.get("status")
    try:
        order_id = await _commit_order(quote_token_id, payment_proof, req_env["context"]["bap_id"])
        ok = True; err = None
    except OutOfStock as e:
        ok = False; err = "OUT_OF_STOCK"; order_id = None
    except QuoteExpired:
        ok = False; err = "QUOTE_EXPIRED"; order_id = None
    payload = {"order": {"id": str(order_id) if order_id else None,
                          "status": "CREATED" if ok else "FAILED",
                          "tags": ([] if ok else [{"code": err}])}}
    if capture:
        return {"ack": ok, "error": err, "order_id": str(order_id) if order_id else None}
    out_env = envelope(action="on_confirm", bap_id=req_env["context"]["bap_id"],
                       bap_uri=req_env["context"]["bap_uri"], bpp_id=bpp_id,
                       bpp_uri=req_env["context"].get("bpp_uri"),
                       transaction_id=req_env["context"]["transaction_id"],
                       message_id=str(uuid.uuid4()), payload=payload)
    priv, key_id = signing_key_for(bpp_id)
    await sign_and_send(url=f"{req_env['context']['bap_uri'].rstrip('/')}/on_confirm",
                        body=out_env, private_key=priv, key_id=key_id)

class QuoteExpired(Exception): ...

async def _commit_order(quote_token_id, payment_proof, bap_id) -> uuid.UUID:
    async with get_db() as session:
        async with session.begin():
            quote = (await session.execute(
                select(QuoteToken).where(QuoteToken.id == quote_token_id).with_for_update()
            )).scalar_one_or_none()
            if quote is None or quote.consumed_at is not None:
                raise QuoteExpired()
            if quote.expires_at < datetime.utcnow():
                raise QuoteExpired()
            sku_codes = [i["sku_code"] for i in quote.items]
            skus = (await session.execute(
                select(SKU).where(SKU.sku_code.in_(sku_codes)).with_for_update()
            )).scalars().all()
            by_code = {s.sku_code: s for s in skus}
            for item in quote.items:
                s = by_code[item["sku_code"]]
                if s.stock < item["qty"]:
                    raise OutOfStock(s.id)
                s.stock -= item["qty"]
            order = Order(
                store_id=quote.store_id,
                bap_id=bap_id,
                beckn_order_id=str(uuid.uuid4()),
                status="CREATED",
                items=quote.items,
                billing_address=quote.address,
                shipping_address=quote.address,
                escrow_status="HELD",
                amount_total=quote.total,
                payment_proof=payment_proof,
            )
            session.add(order)
            quote.consumed_at = datetime.utcnow()
            await session.flush()
            order_id = order.id
        return order_id
```

- [ ] **Step 3: Run race test repeatedly** to gain confidence:

```bash
cd /Users/gogo/Code/jaringan-dagang-seller && pytest tests/beckn/test_confirm_race.py -v --count=20
# install pytest-repeat if needed
```

Expected: 20 passes.

- [ ] **Step 4: Commit**

```bash
git add app/beckn/endpoints.py tests/beckn/test_confirm_race.py
git commit -m "feat(seller): /beckn/confirm with FOR UPDATE inventory txn"
```

---

### Task 3.9: Seller pushes catalog delta after `/confirm`

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`

- [ ] **Step 1: After successful `_commit_order`, fire-and-forget `_emit_on_search` to refresh buyer mirror with new stock.**

```python
# in _emit_on_confirm, after successful path:
if ok:
    bap_uri = req_env["context"]["bap_uri"]
    asyncio.create_task(_emit_on_search({
        "context": {"bap_id": req_env["context"]["bap_id"], "bap_uri": bap_uri,
                    "transaction_id": str(uuid.uuid4())},
        "message": {"intent": {}},
    }))
```

(Cheaper alternative: emit a delta-only payload. For dev, full re-push is fine.)

- [ ] **Step 2: Commit**

```bash
git add app/beckn/endpoints.py
git commit -m "feat(seller): refresh buyer mirror after order confirm"
```

---

### Task 3.10: Buyer `/api/v1/beckn/on_confirm` updates local Order

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`

- [ ] **Step 1: Handler**

```python
@beckn_router.post("/on_confirm")
async def on_confirm(request: Request):
    env = request.state.beckn_envelope
    tx_id = env["context"]["transaction_id"]
    o = env["message"]["order"]
    async with get_db() as session:
        order = (await session.execute(
            select(Order).where(Order.beckn_transaction_id == tx_id)
        )).scalar_one_or_none()
        if order is None:
            return {"message": {"ack": {"status": "NACK"}}}
        if o["status"] == "CREATED":
            order.bpp_order_id = o["id"]
            order.state = "ESCROW_HELD"   # mirror existing FSM
        else:
            order.state = "PRE_AUTH_FAILED"
            for tag in o.get("tags", []):
                if tag["code"] == "OUT_OF_STOCK":
                    order.failure_reason = "OUT_OF_STOCK"
                if tag["code"] == "QUOTE_EXPIRED":
                    order.failure_reason = "QUOTE_EXPIRED"
            # refund the held escrow
            order.escrow_status = "REFUNDED_AUTO"
        await session.commit()
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 2: Commit**

```bash
git add apps/beli-aman-bap/routers/beckn.py
git commit -m "feat(buyer): /on_confirm finalizes order state"
```

---

### Task 3.11: Replace ESCROW_HELD trigger to use `/confirm` (not seller_bridge)

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/payments.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/services/seller_bridge.py` (delete)

- [ ] **Step 1: Find the existing `_notify_seller_bridge`** call in `payments.py` (triggered when escrow becomes HELD) — replace with Beckn `/confirm`.

```python
# in payments.py — replace the seller_bridge call:
env = envelope(
    action="confirm",
    bap_id="beli-aman.bap.metatech.id",
    bap_uri="http://localhost:8002/api/v1/beckn",
    bpp_id=order.bpp_id,
    bpp_uri="http://localhost:8001/beckn",
    transaction_id=order.beckn_transaction_id,
    message_id=str(uuid.uuid4()),
    payload={"order": {
        "payment": {"params": {"quote_token": order.bpp_quote_token,
                               "payment_proof": xendit_payment_id,
                               "amount": str(order.amount_total)},
                    "status": "PAID"},
        "items": [{"id": i["sku_code"], "quantity": {"count": i["qty"]}} for i in order.items],
    }},
)
await send_beckn(env, target_url="http://localhost:8001/beckn/confirm", session=session)
```

- [ ] **Step 2: Delete seller_bridge**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
git rm apps/beli-aman-bap/services/seller_bridge.py
```

Search for any other references and remove:

```bash
grep -r "seller_bridge" apps/beli-aman-bap/
```

Remove found references.

- [ ] **Step 3: Remove the seller-side legacy endpoint**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
# delete or empty app/api/escrow_orders.py
git rm app/api/escrow_orders.py
# remove its inclusion from app/main.py
```

- [ ] **Step 4: Smoke — place an end-to-end order; assert seller `Order` created, stock decremented, buyer ESCROW_HELD → on_confirm → no errors.**

- [ ] **Step 5: Commit both repos**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && git add -u && git commit -m "refactor(buyer): replace seller_bridge with beckn /confirm"
cd /Users/gogo/Code/jaringan-dagang-seller && git add -u && git commit -m "refactor(seller): retire /api/internal/escrow-orders"
```

---

**Phase 3 complete.** Orders flow over Beckn end-to-end. Inventory is race-safe. seller_bridge is gone.

---

## Phase 4: Delivery status pipe (Biteship → seller → buyer)

After this phase: Biteship webhook drives `FulfillmentRecord.status` on seller; seller pushes `/on_status` to buyer; buyer's Order page reflects live delivery state via SSE.

### Task 4.1: Buyer schema — `Order.fulfillment_status` + tracking

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/models/order.py`

- [ ] **Step 1: Add columns**

```python
# apps/beli-aman-bap/models/order.py
fulfillment_status = Column(String, nullable=True)   # PENDING|PICKED_UP|IN_TRANSIT|DELIVERED|RETURNED|CANCELLED
tracking_url = Column(String, nullable=True)
fulfillment_last_event_at = Column(DateTime, nullable=True)
courier_code = Column(String, nullable=True)
awb_number = Column(String, nullable=True)
```

- [ ] **Step 2: Migrate + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
alembic -c apps/beli-aman-bap/alembic.ini revision -m "order fulfillment cols" --autogenerate
alembic -c apps/beli-aman-bap/alembic.ini upgrade head
git add apps/beli-aman-bap/models/order.py apps/beli-aman-bap/alembic/versions/*_order_fulfillment_cols.py
git commit -m "feat(buyer): order fulfillment_status + tracking columns"
```

---

### Task 4.2: Seller Biteship webhook handler

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/api/webhooks/biteship.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/api/test_biteship_webhook.py`

- [ ] **Step 1: Test (TDD — idempotency-critical)**

```python
@pytest.mark.asyncio
async def test_idempotent_on_event_id(client, db_session, order_with_fulfillment, biteship_signing_key):
    event = {"event_id": "biteship-evt-1", "courier_waybill_id": "AWB123",
             "status": "picked_up", "order_id": str(order_with_fulfillment.id)}
    sig = biteship_sign(event, biteship_signing_key)
    r1 = await client.post("/webhooks/biteship", json=event, headers={"X-Biteship-Signature": sig})
    r2 = await client.post("/webhooks/biteship", json=event, headers={"X-Biteship-Signature": sig})
    assert r1.status_code == 200 and r2.status_code == 200
    f = (await db_session.execute(select(FulfillmentRecord).where(FulfillmentRecord.order_id == order_with_fulfillment.id))).scalar_one()
    assert f.status == "PICKED_UP"
    assert f.awb_number == "AWB123"

@pytest.mark.asyncio
async def test_bad_signature_rejected(client):
    r = await client.post("/webhooks/biteship", json={"event_id": "x"}, headers={"X-Biteship-Signature": "wrong"})
    assert r.status_code == 401
```

- [ ] **Step 2: Implement**

```python
# app/api/webhooks/biteship.py
import hmac, hashlib, os
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from sqlalchemy import select
from app.deps import get_db
from app.models.fulfillment import FulfillmentRecord
from app.models.order import Order
from app.models.beckn_log import BecknInboundLog  # reuse for webhook dedupe? or new
# Simpler: create a webhook_events table for dedupe.

router = APIRouter(prefix="/webhooks")

BITESHIP_STATUS_MAP = {
    "confirmed": "PENDING",
    "picked_up": "PICKED_UP",
    "in_transit": "IN_TRANSIT",
    "out_for_delivery": "IN_TRANSIT",
    "delivered": "DELIVERED",
    "returned": "RETURNED",
    "cancelled": "CANCELLED",
}

def _verify(raw: bytes, sig: str) -> bool:
    secret = os.environ.get("BITESHIP_WEBHOOK_SECRET", "dev-secret").encode()
    computed = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sig)

@router.post("/biteship")
async def biteship_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    sig = request.headers.get("X-Biteship-Signature", "")
    if not _verify(raw, sig):
        raise HTTPException(401, "bad signature")
    evt = await request.json()
    async with get_db() as session:
        seen = (await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == evt["event_id"]))).scalar_one_or_none()
        if seen:
            return {"ok": True}
        f = (await session.execute(
            select(FulfillmentRecord).where(FulfillmentRecord.order_id == evt["order_id"])
        )).scalar_one_or_none()
        if f is None:
            return {"ok": True}  # not our order; ignore
        new_status = BITESHIP_STATUS_MAP.get(evt["status"])
        if new_status:
            f.status = new_status
        if evt.get("courier_waybill_id"):
            f.awb_number = evt["courier_waybill_id"]
        if evt.get("tracking_url"):
            f.tracking_url = evt["tracking_url"]
        f.last_event_at = datetime.utcnow()
        session.add(WebhookEvent(event_id=evt["event_id"], received_at=datetime.utcnow()))
        await session.commit()
        order_id = f.order_id
    background.add_task(_emit_on_status, order_id)
    return {"ok": True}
```

Plus a `WebhookEvent` model + migration:

```python
# app/models/webhook_event.py
from datetime import datetime
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.db import Base
class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, nullable=False, unique=True, index=True)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 3: Wire router** in `app/main.py`.

- [ ] **Step 4: Migrate**

```bash
alembic revision -m "webhook_events" --autogenerate && alembic upgrade head
```

- [ ] **Step 5: Test + commit**

```bash
pytest tests/api/test_biteship_webhook.py -v
git add app/api/webhooks/ app/models/webhook_event.py app/main.py tests/api/test_biteship_webhook.py alembic/versions/*_webhook_events.py
git commit -m "feat(seller): biteship webhook updates fulfillment, idempotent"
```

---

### Task 4.3: `_emit_on_status` pushes to BAP

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`

- [ ] **Step 1: Implement**

```python
# app/beckn/endpoints.py
from app.models.order import Order
from app.models.fulfillment import FulfillmentRecord

async def _emit_on_status(order_id):
    async with get_db() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        f = (await session.execute(select(FulfillmentRecord).where(FulfillmentRecord.order_id == order_id))).scalar_one()
        store = (await session.execute(select(Store).where(Store.id == order.store_id))).scalar_one()
    registry = await get_registry_client()
    bap = await registry.lookup(order.bap_id)
    payload = {"order": {
        "id": str(order.id),
        "fulfillments": [{
            "id": str(f.id),
            "type": f.type,
            "state": {"descriptor": {"code": f.status}},
            "tracking": {"url": f.tracking_url, "id": f.awb_number},
        }],
    }}
    env = envelope(action="on_status", bap_id=order.bap_id, bap_uri=bap.subscriber_url,
                   bpp_id=store.bpp_id, bpp_uri=os.environ.get("SELLER_BECKN_URL"),
                   transaction_id=str(uuid.uuid4()), message_id=str(uuid.uuid4()),
                   payload=payload)
    priv, key_id = signing_key_for(store.bpp_id)
    await sign_and_send(url=f"{bap.subscriber_url.rstrip('/')}/on_status",
                        body=env, private_key=priv, key_id=key_id)
```

- [ ] **Step 2: Commit**

```bash
git add app/beckn/endpoints.py
git commit -m "feat(seller): /on_status emitter after fulfillment updates"
```

---

### Task 4.4: Buyer `/api/v1/beckn/on_status` handler + SSE

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/realtime.py`

- [ ] **Step 1: Lightweight in-process pubsub**

```python
# apps/beli-aman-bap/realtime.py
import asyncio
from collections import defaultdict

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

async def publish(channel: str, message: dict):
    for q in list(_subscribers[channel]):
        try: q.put_nowait(message)
        except: pass

def subscribe(channel: str) -> asyncio.Queue:
    q = asyncio.Queue(maxsize=64)
    _subscribers[channel].add(q)
    return q

def unsubscribe(channel: str, q: asyncio.Queue):
    _subscribers[channel].discard(q)
```

(For multi-process / multi-worker dev, swap to Redis pub/sub later. Out of scope.)

- [ ] **Step 2: Handler**

```python
# routers/beckn.py
from datetime import datetime
from apps.beli_aman_bap.realtime import publish

@beckn_router.post("/on_status")
async def on_status(request: Request):
    env = request.state.beckn_envelope
    bpp_order_id = env["message"]["order"]["id"]
    f = env["message"]["order"]["fulfillments"][0]
    new_status = f["state"]["descriptor"]["code"]
    async with get_db() as session:
        order = (await session.execute(select(Order).where(Order.bpp_order_id == bpp_order_id))).scalar_one_or_none()
        if order is None:
            return {"message": {"ack": {"status": "NACK"}}}
        order.fulfillment_status = new_status
        order.tracking_url = f.get("tracking", {}).get("url")
        order.awb_number = f.get("tracking", {}).get("id")
        order.fulfillment_last_event_at = datetime.utcnow()
        await session.commit()
        order_id = str(order.id)
    await publish(f"order:{order_id}:fulfillment",
                  {"status": new_status, "tracking_url": order.tracking_url, "awb": order.awb_number})
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 3: SSE endpoint**

```python
# routers/orders.py — add
from fastapi.responses import StreamingResponse
from apps.beli_aman_bap.realtime import subscribe, unsubscribe
import json as _json

@router.get("/orders/{order_id}/events")
async def order_events(order_id: str):
    q = subscribe(f"order:{order_id}:fulfillment")
    async def stream():
        try:
            while True:
                msg = await q.get()
                yield f"data: {_json.dumps(msg)}\n\n"
        finally:
            unsubscribe(f"order:{order_id}:fulfillment", q)
    return StreamingResponse(stream(), media_type="text/event-stream")
```

- [ ] **Step 4: Frontend consumer** — `sites/partner-demos/app/[brand]/orders/[id]/page.tsx`:

```typescript
useEffect(() => {
  const es = new EventSource(`/api/v1/orders/${orderId}/events`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    setFulfillment(prev => ({ ...prev, ...data }));
  };
  return () => es.close();
}, [orderId]);
```

- [ ] **Step 5: Commit**

```bash
git add apps/beli-aman-bap/realtime.py apps/beli-aman-bap/routers/beckn.py apps/beli-aman-bap/routers/orders.py sites/partner-demos/app/[brand]/orders/[id]/page.tsx
git commit -m "feat(buyer): /on_status + SSE for live delivery updates"
```

---

### Task 4.5: 30-min polling fallback worker (buyer)

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/workers/status_poller.py`
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/main.py`

- [ ] **Step 1: Implement**

```python
# workers/status_poller.py
import asyncio, uuid, logging
from sqlalchemy import select
from apps.beli_aman_bap.database import get_db
from apps.beli_aman_bap.models.order import Order
from apps.beli_aman_bap.beckn.outbound import send_beckn
from beckn_protocol.envelope import envelope

TERMINAL = {"DELIVERED", "RETURNED", "CANCELLED"}
INTERVAL = 30 * 60

async def poll_once():
    async with get_db() as session:
        orders = (await session.execute(
            select(Order).where(Order.bpp_order_id.isnot(None))
            .where((Order.fulfillment_status.is_(None)) | (~Order.fulfillment_status.in_(list(TERMINAL))))
        )).scalars().all()
        for o in orders:
            env = envelope(action="status", bap_id="beli-aman.bap.metatech.id",
                           bap_uri="http://localhost:8002/api/v1/beckn",
                           bpp_id=o.bpp_id, bpp_uri="http://localhost:8001/beckn",
                           transaction_id=o.beckn_transaction_id,
                           message_id=str(uuid.uuid4()),
                           payload={"order_id": o.bpp_order_id})
            try:
                await send_beckn(env, target_url="http://localhost:8001/beckn/status", session=session)
            except Exception:
                logging.exception("status poll failed for order %s", o.id)

async def run_forever():
    while True:
        try: await poll_once()
        except Exception: logging.exception("poll_once")
        await asyncio.sleep(INTERVAL)
```

- [ ] **Step 2: Start in lifespan** (alongside catalog_puller).

- [ ] **Step 3: Implement seller `/beckn/status`** — basically calls `_emit_on_status(order_id_from_payload)`.

```python
# app/beckn/endpoints.py
@beckn_router.post("/status")
async def beckn_status(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope
    background.add_task(_emit_on_status, uuid.UUID(env["message"]["order_id"]))
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 4: Commit (both repos)**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer && git add apps/beli-aman-bap/workers/status_poller.py apps/beli-aman-bap/main.py && git commit -m "feat(buyer): 30-min status poller fallback"
cd /Users/gogo/Code/jaringan-dagang-seller && git add app/beckn/endpoints.py && git commit -m "feat(seller): /beckn/status handler"
```

---

### Task 4.6: Buyer order page renders fulfillment_status + tracking link

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/sites/partner-demos/app/[brand]/orders/[id]/page.tsx`

- [ ] **Step 1: Add a small status pill + tracking link section** (visual; no test needed).

```tsx
<div className="rounded-lg border p-4">
  <div className="flex items-center gap-2">
    <span className="font-semibold">Delivery</span>
    <StatusPill status={fulfillment?.status ?? "PENDING"} />
  </div>
  {fulfillment?.tracking_url && (
    <a href={fulfillment.tracking_url} target="_blank" className="text-sm text-blue-600 underline mt-2 inline-block">
      Track package ({fulfillment.awb})
    </a>
  )}
</div>
```

- [ ] **Step 2: Smoke** — boot all 3 apps, trigger a fake Biteship webhook via `curl`, watch the buyer order page update in <5s.

```bash
curl -X POST http://localhost:8001/webhooks/biteship \
  -H "X-Biteship-Signature: $(python -c '...')" \
  -d '{"event_id":"smoke-1","order_id":"<order-uuid>","status":"in_transit","courier_waybill_id":"AWB001"}'
```

- [ ] **Step 3: Commit**

```bash
git add sites/partner-demos/app/[brand]/orders/[id]/page.tsx
git commit -m "feat(buyer): live delivery status on order page"
```

---

**Phase 4 complete.** Biteship → seller → buyer pipe is live. Push (<5s typical) + 30-min poll fallback.

---

## Phase 5: Refund workflow (buyer requests → seller approves → Xendit refund)

After this phase: buyer can request a refund from their order page; seller sees pending requests in dashboard; approve calls Xendit refund + flips escrow + emits final `/on_update` chain.

### Task 5.1: Seller `RefundRequest` model + migration

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/models/refund.py`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/alembic/versions/<auto>_refund_requests.py`

- [ ] **Step 1: Model**

```python
# app/models/refund.py
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
import uuid, enum
from app.db import Base

class RefundStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"

class RefundReasonCode(str, enum.Enum):
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    ITEM_DAMAGED = "ITEM_DAMAGED"
    WRONG_ITEM = "WRONG_ITEM"
    CHANGED_MIND = "CHANGED_MIND"
    OTHER = "OTHER"

class RefundRequest(Base):
    __tablename__ = "refund_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    requested_by = Column(String, nullable=False)   # buyer|seller
    reason_code = Column(String, nullable=False)
    reason_text = Column(String, nullable=True)
    requested_amount = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    seller_note = Column(String, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String, nullable=True)
    xendit_refund_id = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# only one open request per order
Index(
    "uq_refund_open_per_order", RefundRequest.order_id,
    unique=True,
    postgresql_where=text("status IN ('PENDING','APPROVED')"),
)
```

- [ ] **Step 2: Migrate + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-seller
alembic revision -m "refund requests" --autogenerate
alembic upgrade head
git add app/models/refund.py alembic/versions/*_refund_requests.py
git commit -m "feat(seller): RefundRequest model with open-uniqueness"
```

---

### Task 5.2: Buyer `Dispute` extension

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/models/dispute.py`

- [ ] **Step 1: Add columns** (if model exists; create if not):

```python
bpp_refund_request_id = Column(String, nullable=True, index=True)
# extend status enum if needed: REQUESTED|APPROVED|DENIED|REFUND_PENDING|REFUNDED|REFUND_FAILED
```

- [ ] **Step 2: Migrate + commit**

```bash
cd /Users/gogo/Code/jaringan-dagang-buyer
alembic -c apps/beli-aman-bap/alembic.ini revision -m "dispute bpp_refund_request_id" --autogenerate
alembic -c apps/beli-aman-bap/alembic.ini upgrade head
git add apps/beli-aman-bap/models/dispute.py apps/beli-aman-bap/alembic/versions/*
git commit -m "feat(buyer): Dispute.bpp_refund_request_id correlation"
```

---

### Task 5.3: Seller `/beckn/update` — buyer-initiated refund request

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/beckn/endpoints.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/beckn/test_update_refund.py`

- [ ] **Step 1: Test — `/update` with refund_request creates PENDING RefundRequest + returns id in `/on_update`**

```python
@pytest.mark.asyncio
async def test_update_creates_refund_request(signed_client, order_with_escrow_held, captured_outbound):
    env = make_update_envelope(
        bpp_order_id=str(order_with_escrow_held.id),
        descriptor_code="refund_request",
        reason_code="ITEM_DAMAGED",
        reason_text="received broken jar",
        amount=89000,
    )
    await signed_client.post("/beckn/update", json_envelope=env)
    await asyncio.sleep(0.1)
    sent = captured_outbound.calls[0]["body"]["message"]
    assert sent["order"]["tags"][0]["code"] == "refund_pending"
    assert sent["order"]["tags"][0]["list"][0]["value"]  # refund_request_id present
```

- [ ] **Step 2: Implement**

```python
# app/beckn/endpoints.py
from app.models.refund import RefundRequest

@beckn_router.post("/update")
async def beckn_update(request: Request, background: BackgroundTasks):
    env = request.state.beckn_envelope
    background.add_task(_handle_update, env)
    return {"message": {"ack": {"status": "ACK"}}}

async def _handle_update(req_env):
    desc = req_env["message"]["order"].get("fulfillment_state", {}).get("descriptor", {})
    code = desc.get("code")
    if code != "refund_request":
        return  # other update types out of scope for v1
    payload_order = req_env["message"]["order"]
    bpp_order_id = payload_order["id"]
    bpp_id = req_env["context"]["bpp_id"]
    async with get_db() as session:
        order = (await session.execute(select(Order).where(Order.id == uuid.UUID(bpp_order_id)))).scalar_one()
        existing = (await session.execute(
            select(RefundRequest).where(RefundRequest.order_id == order.id)
            .where(RefundRequest.status.in_(["PENDING", "APPROVED"]))
        )).scalar_one_or_none()
        if existing:
            req_id = existing.id
        else:
            req = RefundRequest(
                order_id=order.id, requested_by="buyer",
                reason_code=desc.get("short_desc", "OTHER"),
                reason_text=desc.get("name"),
                requested_amount=int(payload_order.get("payment", {}).get("params", {}).get("amount", 0)),
                status="PENDING",
            )
            session.add(req); await session.commit()
            req_id = req.id
    payload = {"order": {"id": bpp_order_id,
                          "tags": [{"code": "refund_pending",
                                    "list": [{"code": "refund_request_id", "value": str(req_id)}]}]}}
    out_env = envelope(action="on_update",
                       bap_id=req_env["context"]["bap_id"], bap_uri=req_env["context"]["bap_uri"],
                       bpp_id=bpp_id, bpp_uri=req_env["context"].get("bpp_uri"),
                       transaction_id=req_env["context"]["transaction_id"],
                       message_id=str(uuid.uuid4()), payload=payload)
    priv, key_id = signing_key_for(bpp_id)
    await sign_and_send(url=f"{req_env['context']['bap_uri'].rstrip('/')}/on_update",
                        body=out_env, private_key=priv, key_id=key_id)
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/beckn/test_update_refund.py -v
git add app/beckn/endpoints.py tests/beckn/test_update_refund.py
git commit -m "feat(seller): /beckn/update handles refund_request"
```

---

### Task 5.4: Buyer "Request refund" button + Beckn `/update` trigger

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/disputes.py` (or extend existing)
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/sites/partner-demos/app/[brand]/orders/[id]/page.tsx`

- [ ] **Step 1: POST endpoint that creates Dispute + sends `/update`**

```python
# routers/disputes.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import uuid
from apps.beli_aman_bap.database import get_db
from apps.beli_aman_bap.models.order import Order
from apps.beli_aman_bap.models.dispute import Dispute
from apps.beli_aman_bap.beckn.outbound import send_beckn
from beckn_protocol.envelope import envelope

router = APIRouter()

class RefundReqIn(BaseModel):
    reason_code: str
    reason_text: str | None = None
    amount: int | None = None

@router.post("/api/v1/orders/{order_id}/refund-request")
async def request_refund(order_id: str, body: RefundReqIn):
    async with get_db() as session:
        order = await session.get(Order, uuid.UUID(order_id))
        if order is None or order.escrow_status != "HELD":
            raise HTTPException(400, "order not refundable")
        existing = next((d for d in order.disputes if d.status in ("REQUESTED", "APPROVED", "REFUND_PENDING")), None)
        if existing:
            raise HTTPException(409, "already has open dispute")
        dispute = Dispute(order_id=order.id, status="REQUESTED",
                          reason_code=body.reason_code, reason_text=body.reason_text,
                          requested_amount=body.amount or order.amount_total)
        session.add(dispute); await session.commit()
        env = envelope(
            action="update",
            bap_id="beli-aman.bap.metatech.id",
            bap_uri="http://localhost:8002/api/v1/beckn",
            bpp_id=order.bpp_id, bpp_uri="http://localhost:8001/beckn",
            transaction_id=order.beckn_transaction_id or str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            payload={"order": {
                "id": order.bpp_order_id,
                "fulfillment_state": {"descriptor": {
                    "code": "refund_request",
                    "short_desc": body.reason_code,
                    "name": body.reason_text or "",
                }},
                "payment": {"params": {"amount": str(body.amount or order.amount_total)}},
            }},
        )
        await send_beckn(env, target_url="http://localhost:8001/beckn/update", session=session)
        return {"dispute_id": str(dispute.id)}
```

- [ ] **Step 2: UI button**

```tsx
// orders/[id]/page.tsx
<RequestRefundDialog orderId={orderId} onSubmit={async (reason, amount) => {
  await fetch(`/api/v1/orders/${orderId}/refund-request`, {
    method: "POST", body: JSON.stringify({reason_code: reason, amount}),
  });
  refetch();
}} />
{order.disputes.length > 0 && <DisputeBanner dispute={order.disputes[0]} />}
```

- [ ] **Step 3: Commit**

```bash
git add apps/beli-aman-bap/routers/disputes.py sites/partner-demos/app/[brand]/orders/[id]/page.tsx apps/beli-aman-bap/main.py
git commit -m "feat(buyer): request-refund button + dispute creation"
```

---

### Task 5.5: Buyer `/on_update` handler

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-buyer/apps/beli-aman-bap/routers/beckn.py`

- [ ] **Step 1: Handler**

```python
@beckn_router.post("/on_update")
async def on_update(request: Request):
    env = request.state.beckn_envelope
    o = env["message"]["order"]
    async with get_db() as session:
        order = (await session.execute(select(Order).where(Order.bpp_order_id == o["id"]))).scalar_one_or_none()
        if order is None:
            return {"message": {"ack": {"status": "NACK"}}}
        dispute = next(iter(order.disputes), None)
        for tag in o.get("tags", []):
            code = tag["code"]
            kv = {x["code"]: x["value"] for x in tag.get("list", [])}
            if code == "refund_pending" and dispute:
                dispute.bpp_refund_request_id = kv.get("refund_request_id")
                dispute.status = "REQUESTED"
            elif code == "refund_approved" and dispute:
                dispute.status = "REFUND_PENDING"
                order.escrow_status = "REFUNDED"
            elif code == "refund_denied" and dispute:
                dispute.status = "DENIED"
                dispute.seller_note = kv.get("seller_note")
            elif code == "refund_settled" and dispute:
                dispute.status = "REFUNDED"
        await session.commit()
    return {"message": {"ack": {"status": "ACK"}}}
```

- [ ] **Step 2: Commit**

```bash
git add apps/beli-aman-bap/routers/beckn.py
git commit -m "feat(buyer): /on_update tracks refund lifecycle"
```

---

### Task 5.6: Seller refund approval API

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/api/refunds.py`
- Create: `/Users/gogo/Code/jaringan-dagang-seller/app/services/refund_service.py`
- Test: `/Users/gogo/Code/jaringan-dagang-seller/tests/services/test_refund_service.py`

- [ ] **Step 1: Test (TDD — state transitions + Xendit error handling)**

```python
@pytest.mark.asyncio
async def test_approve_calls_xendit_and_flips_state(db_session, pending_refund, mock_xendit_ok):
    await refund_service.approve(pending_refund.id, decided_by="seller@safiya", session=db_session)
    refreshed = await db_session.get(RefundRequest, pending_refund.id)
    assert refreshed.status == "APPROVED"
    assert refreshed.xendit_refund_id == "REF-001"
    order = await db_session.get(Order, pending_refund.order_id)
    assert order.escrow_status == "REFUNDED"

@pytest.mark.asyncio
async def test_approve_xendit_fails_stays_approved_with_error(db_session, pending_refund, mock_xendit_500):
    await refund_service.approve(pending_refund.id, decided_by="seller@safiya", session=db_session)
    r = await db_session.get(RefundRequest, pending_refund.id)
    assert r.status == "APPROVED"
    assert r.xendit_refund_id is None
    assert "500" in r.error
    order = await db_session.get(Order, r.order_id)
    assert order.escrow_status != "REFUNDED"

@pytest.mark.asyncio
async def test_deny_flips_to_denied(db_session, pending_refund):
    await refund_service.deny(pending_refund.id, "out of policy", "seller@safiya", session=db_session)
    r = await db_session.get(RefundRequest, pending_refund.id)
    assert r.status == "DENIED" and r.seller_note == "out of policy"
```

- [ ] **Step 2: Implement service**

```python
# app/services/refund_service.py
from datetime import datetime
import httpx, os
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.refund import RefundRequest
from app.models.order import Order
from app.models.payment import PaymentRecord

XENDIT_BASE = os.environ.get("XENDIT_BASE", "https://api.xendit.co")
XENDIT_KEY = os.environ.get("XENDIT_SECRET_KEY", "")

async def approve(refund_id, decided_by: str, session: AsyncSession):
    req = await session.get(RefundRequest, refund_id)
    if req.status != "PENDING":
        raise ValueError(f"cannot approve from {req.status}")
    payment = (await session.execute(select(PaymentRecord).where(PaymentRecord.order_id == req.order_id))).scalar_one()
    req.status = "APPROVED"; req.decided_at = datetime.utcnow(); req.decided_by = decided_by
    await session.commit()
    try:
        async with httpx.AsyncClient(auth=(XENDIT_KEY, "")) as c:
            r = await c.post(f"{XENDIT_BASE}/refunds", json={
                "payment_id": payment.xendit_invoice_id,
                "amount": req.requested_amount,
                "reason": req.reason_code,
            }, timeout=15)
            r.raise_for_status()
            req.xendit_refund_id = r.json()["id"]
    except Exception as e:
        req.error = repr(e)
        await session.commit()
        await _emit_refund_status(req, "refund_approved", session)  # buyer hears it; final settled comes later
        return
    order = await session.get(Order, req.order_id)
    order.escrow_status = "REFUNDED"
    payment.status = "REFUNDED"
    await session.commit()
    await _emit_refund_status(req, "refund_approved", session)

async def deny(refund_id, note: str, decided_by: str, session: AsyncSession):
    req = await session.get(RefundRequest, refund_id)
    if req.status != "PENDING":
        raise ValueError(f"cannot deny from {req.status}")
    req.status = "DENIED"; req.seller_note = note
    req.decided_at = datetime.utcnow(); req.decided_by = decided_by
    await session.commit()
    await _emit_refund_status(req, "refund_denied", session)

async def _emit_refund_status(req: RefundRequest, code: str, session: AsyncSession):
    from app.beckn.endpoints import envelope, sign_and_send, signing_key_for
    from app.deps import get_registry_client
    import uuid
    order = await session.get(Order, req.order_id)
    store = await session.get(Store, order.store_id)
    registry = await get_registry_client()
    bap = await registry.lookup(order.bap_id)
    tag_list = [{"code": "refund_request_id", "value": str(req.id)}]
    if req.seller_note:
        tag_list.append({"code": "seller_note", "value": req.seller_note})
    payload = {"order": {"id": str(order.id),
                          "tags": [{"code": code, "list": tag_list}]}}
    env = envelope(action="on_update", bap_id=order.bap_id, bap_uri=bap.subscriber_url,
                   bpp_id=store.bpp_id, bpp_uri=os.environ.get("SELLER_BECKN_URL"),
                   transaction_id=str(uuid.uuid4()), message_id=str(uuid.uuid4()),
                   payload=payload)
    priv, key_id = signing_key_for(store.bpp_id)
    await sign_and_send(url=f"{bap.subscriber_url.rstrip('/')}/on_update",
                        body=env, private_key=priv, key_id=key_id)
```

- [ ] **Step 3: API surface**

```python
# app/api/refunds.py
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel
from app.services import refund_service
from app.deps import get_db

router = APIRouter(prefix="/api/refunds")

class DecideBody(BaseModel):
    note: str | None = None

@router.post("/{refund_id}/approve")
async def approve(refund_id: str, body: DecideBody, session=Depends(get_db)):
    await refund_service.approve(refund_id, decided_by="seller-dashboard", session=session)
    return {"ok": True}

@router.post("/{refund_id}/deny")
async def deny(refund_id: str, body: DecideBody, session=Depends(get_db)):
    await refund_service.deny(refund_id, body.note or "", decided_by="seller-dashboard", session=session)
    return {"ok": True}

@router.get("/")
async def list_refunds(status: str | None = None, session=Depends(get_db)):
    q = select(RefundRequest)
    if status: q = q.where(RefundRequest.status == status)
    rows = (await session.execute(q.order_by(RefundRequest.created_at.desc()))).scalars().all()
    return [{"id": str(r.id), "order_id": str(r.order_id), "status": r.status,
             "reason_code": r.reason_code, "requested_amount": r.requested_amount,
             "created_at": r.created_at.isoformat()} for r in rows]
```

- [ ] **Step 4: Wire router + run tests + commit**

```bash
pytest tests/services/test_refund_service.py -v
git add app/api/refunds.py app/services/refund_service.py tests/services/ app/main.py
git commit -m "feat(seller): refund_service + approve/deny API + on_update emit"
```

---

### Task 5.7: Seller dashboard Refunds UI

**Files:**
- Create: `/Users/gogo/Code/jaringan-dagang-seller/seller-dashboard/app/orders/[id]/refunds/page.tsx`
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/seller-dashboard/app/orders/page.tsx` (refund-pending filter chip)
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/seller-dashboard/app/orders/[id]/page.tsx` (add Refunds tab link)

- [ ] **Step 1: Order detail Refunds page**

```tsx
// seller-dashboard/app/orders/[id]/refunds/page.tsx
"use client";
import { useEffect, useState } from "react";

export default function RefundsPage({ params }: { params: { id: string } }) {
  const [refunds, setRefunds] = useState<any[]>([]);
  const [note, setNote] = useState("");
  async function load() {
    const r = await fetch(`/api/refunds/?order_id=${params.id}`);
    setRefunds(await r.json());
  }
  useEffect(() => { load(); }, []);
  async function decide(refundId: string, action: "approve" | "deny") {
    await fetch(`/api/refunds/${refundId}/${action}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ note }),
    });
    setNote(""); load();
  }
  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Refunds</h1>
      {refunds.map(r => (
        <div key={r.id} className="border rounded p-4 mb-3">
          <div className="flex justify-between">
            <span>{r.reason_code}</span>
            <span className="px-2 py-1 text-sm bg-gray-100 rounded">{r.status}</span>
          </div>
          <div className="text-sm text-gray-600">Amount: Rp {r.requested_amount.toLocaleString()}</div>
          {r.status === "PENDING" && (
            <div className="mt-3 flex gap-2">
              <input value={note} onChange={e => setNote(e.target.value)} placeholder="Note (optional for approve, helpful for deny)" className="border px-2 py-1 flex-1" />
              <button onClick={() => decide(r.id, "approve")} className="px-3 py-1 bg-green-600 text-white rounded">Approve</button>
              <button onClick={() => decide(r.id, "deny")} className="px-3 py-1 bg-red-600 text-white rounded">Deny</button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Refund-pending filter chip in orders list**

```tsx
// in orders/page.tsx — add chip
<Chip selected={filter === "refund_pending"} onClick={() => setFilter("refund_pending")}>
  Refund pending {pendingCount > 0 && <span className="ml-1 px-1 bg-red-500 text-white rounded">{pendingCount}</span>}
</Chip>
```

Backend support: `GET /api/orders?filter=refund_pending` returns orders with a PENDING refund_request.

- [ ] **Step 3: Smoke + commit**

```bash
git add seller-dashboard/app/orders/[id]/refunds/page.tsx seller-dashboard/app/orders/page.tsx seller-dashboard/app/orders/[id]/page.tsx app/api/orders.py
git commit -m "feat(seller-dashboard): refunds UI + pending filter"
```

---

### Task 5.8: Xendit refund-settled webhook (finalization)

**Files:**
- Modify: `/Users/gogo/Code/jaringan-dagang-seller/app/api/webhooks/` add `xendit.py`

- [ ] **Step 1: Handler**

```python
# app/api/webhooks/xendit.py
from fastapi import APIRouter, Request, HTTPException
import hmac, hashlib, os
from sqlalchemy import select
from app.deps import get_db
from app.models.refund import RefundRequest
from app.services import refund_service

router = APIRouter(prefix="/webhooks")

def _verify(raw: bytes, sig: str) -> bool:
    secret = os.environ.get("XENDIT_WEBHOOK_TOKEN", "").encode()
    computed = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sig)

@router.post("/xendit")
async def xendit_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-Callback-Token", "")
    if sig != os.environ.get("XENDIT_WEBHOOK_TOKEN", ""):
        raise HTTPException(401)
    evt = await request.json()
    if evt.get("event") != "refund.succeeded":
        return {"ok": True}
    refund_id = evt["data"]["id"]
    async with get_db() as session:
        req = (await session.execute(select(RefundRequest).where(RefundRequest.xendit_refund_id == refund_id))).scalar_one_or_none()
        if req is None:
            return {"ok": True}
        req.status = "REFUNDED"
        await session.commit()
        await refund_service._emit_refund_status(req, "refund_settled", session)
    return {"ok": True}
```

- [ ] **Step 2: Commit**

```bash
git add app/api/webhooks/xendit.py app/main.py
git commit -m "feat(seller): xendit refund-settled webhook → final on_update"
```

---

### Task 5.9: End-to-end refund test (manual smoke)

**Files:** none (manual checklist).

- [ ] **Step 1: Boot all 3 apps + Xendit sandbox.**
- [ ] **Step 2: Place an order via buyer storefront; pay; verify ESCROW_HELD + seller Order.**
- [ ] **Step 3: Click "Request refund" on buyer order page (ITEM_DAMAGED, full amount).**
- [ ] **Step 4: In seller dashboard, navigate to `/orders/[id]/refunds`. See PENDING request.**
- [ ] **Step 5: Click Approve. Observe:**
   - Seller dashboard shows APPROVED.
   - Buyer order page shows "Refund pending" within 5s.
- [ ] **Step 6: Trigger Xendit sandbox refund-settled webhook to seller `/webhooks/xendit`.**
- [ ] **Step 7: Observe both sides show REFUNDED.**

- [ ] **Step 8: Commit (no commit — manual smoke)**

---

**Phase 5 complete.** Refund flow is end-to-end.

---

## Self-review checklist (engineer running this plan)

After all phases:

- [ ] All 4 tokos render from buyer mirror; `apps/beli-aman-bap/catalog/*.json` files are gone.
- [ ] Adding a product in seller dashboard updates buyer storefront within 5s (push) or 5min (pull fallback).
- [ ] Two concurrent `/confirm`s for the last unit produce exactly one winner (test `test_two_buyers_race_for_last_unit` repeats 20x clean).
- [ ] `seller_bridge.py` and `/api/internal/escrow-orders` are deleted; grep returns nothing.
- [ ] Biteship webhook → buyer order page reflects status within 5s.
- [ ] End-to-end refund (request → approve → Xendit → final) flips both sides to REFUNDED.
- [ ] Every Beckn request in `beckn_inbound_log` has a corresponding 200/202 row; no orphan 401s in dev traffic.
- [ ] All migrations applied cleanly on a fresh DB (`alembic downgrade base && alembic upgrade head` works in seller + buyer).
- [ ] `pytest` is green in all three repos.

---

## Done.








