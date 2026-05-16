# jaringan-dagang-seller — Claude collaboration notes

## Workflow authorization

- **Work directly on `main`.** No feature branches, no worktrees. Commit and push to main as work progresses. This is a pre-production project with no active users; the safety of branching isn't needed.
- **Don't ask before committing** routine implementation steps. Commit per task; the plan already specifies cadence.
- **Push to main is allowed** without confirmation.
- Skip rollout caution: no feature flags for safe rollback, no shadow/dual-write modes, no daily diff scripts. Rip-and-replace is preferred when migrating.

## Cross-repo work

This repo is one of three sibling repos that work together:
- `~/Code/jaringan-dagang-buyer` — Beli Aman BAP (buyer-protection)
- `~/Code/jaringan-dagang-network` — Beckn registry + gateway
- `~/Code/jaringan-dagang-seller` — BPP / seller dashboard (this repo)

Cross-repo changes commit independently in each repo, no atomic-rollback expectation across repos.

## Active spec + plan

- Spec: `docs/superpowers/specs/2026-05-16-beckn-catalog-orders-fulfillment-refunds-design.md`
- Plan: `docs/superpowers/plans/2026-05-16-beckn-full-implementation.md`
