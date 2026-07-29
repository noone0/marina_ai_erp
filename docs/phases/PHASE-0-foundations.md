# Phase 0 — Foundations

**Goal:** a runnable skeleton that every later phase plugs into, with the database schema, local infrastructure, and test harness in place. Nothing user-visible ships; everything after this is faster because of it.

**Estimate:** ~1 week · **Depends on:** PoC (borrows its pipeline code)

---

## In scope

- Monorepo layout per [`TECHNICAL.md §1`](../TECHNICAL.md#1-repository-layout)
- `uv` Python workspace, `pnpm` frontend workspace
- Docker Compose: Postgres 16 (+ TimescaleDB, pgvector), Redis 7, MinIO
- Full Alembic schema — every table from [`ARCHITECTURE.md §4`](../ARCHITECTURE.md#4-data-model-core-tables), including tables not used until Phase 5
- `packages/core`: settings, DB session, S3 wrapper, Redis Streams producer/consumer with idempotency helper
- `FrameSource` interface with `FileSource` implemented
- Fixture clips + labelled ground truth committed (from the PoC)
- Structured logging, Prometheus registry, `/health` endpoints
- CI: lint (ruff), type-check (mypy/pyright), unit tests, migration up/down check

## Out of scope

Detection, tracking, any UI beyond a placeholder, authentication, RTSP.

---

## Deliverables

1. `docker compose up` brings up Postgres, Redis, MinIO, API, and a worker; all health checks green.
2. `alembic upgrade head` creates the full schema on an empty database; `downgrade base` cleanly reverses it.
3. `FileSource` replays a fixture clip and emits `Frame` objects at a controlled rate.
4. A round-trip test: publish an event to Redis → consumer writes a row → **redelivering the same event writes nothing new**.
5. CI green on a pull request.

---

## Tasks

- [ ] Workspace scaffolding, `pyproject.toml` per package, shared lint/type config
- [ ] `docker-compose.yml` + `docker-compose.gpu.yml` overlay
- [ ] `marina_core.config.Settings` with every threshold from TECHNICAL §4 as a named field
- [ ] SQLAlchemy models for all tables; enums as native Postgres enums
- [ ] Alembic initial migration; enable `timescaledb` + `vector` extensions; `create_hypertable('queue_samples','ts')`
- [ ] Indexes from [`TECHNICAL.md §9`](../TECHNICAL.md#9-database-notes), including the partial index on `status <> 'merged'` and the GIN search index
- [ ] `events.py`: producer, consumer-group helper, `processed_events` idempotency guard
- [ ] `storage.py`: put/get/signed-URL over MinIO
- [ ] `FrameSource` protocol + `FileSource`
- [ ] Seed script: demo cameras, berths, zones for local development
- [ ] GitHub Actions workflow

---

## Acceptance criteria

- [ ] A fresh clone reaches a working local stack with `docker compose up` and one migration command — no manual steps outside the README.
- [ ] Schema round-trips: `upgrade head` → `downgrade base` → `upgrade head` succeeds on a clean DB.
- [ ] Idempotency proven by test: the same `event_id` consumed twice produces exactly one domain row.
- [ ] `FileSource` yields frames from a fixture clip at the configured FPS ±10%.
- [ ] Every setting is env-overridable; **no threshold is hard-coded in a module.**
- [ ] CI runs lint, types, and tests on every PR and blocks merge on failure.

---

## Dependencies

- Fixture clips and `ground_truth.csv` from the PoC — needed as permanent test infrastructure, not just for the PoC.

---

## Risks

| Risk | Mitigation |
|---|---|
| TimescaleDB + pgvector in one image causes version friction | Use `timescale/timescaledb-ha` which bundles pgvector; pin the tag |
| Schema churn in later phases makes Phase 0 migrations look wasted | Expected and fine. Writing the whole schema now forces the modelling decisions while they're cheap to change. |
| `FileSource` treated as throwaway | Documented as permanent: it is how CI tests the pipeline forever, and how every regression run replays footage |
