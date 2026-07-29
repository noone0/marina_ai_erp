# Marina AI — Operations Runbook

Install, run, monitor, and recover the system. Written to be usable by someone who did not build it — a [Phase 6](./phases/PHASE-6-hardening.md) acceptance criterion.

Status: **draft — fills in as phases land** · Date: 2026-07-29

---

## 1. Development environment

### Prerequisites

| Tool | Version |
|---|---|
| Docker + Compose | 24+ |
| `uv` | latest |
| Node + `pnpm` | Node 20+, pnpm 9+ |
| NVIDIA Container Toolkit | only for GPU inference |

### First run

```bash
git clone https://github.com/noone0/marina_ai_erp.git
cd marina_ai_erp

cp .env.example .env          # set MARINA_ANTHROPIC_API_KEY at minimum

docker compose up -d          # postgres, redis, minio
uv sync                       # python deps across the workspace
uv run alembic upgrade head   # schema
uv run python -m scripts.seed # demo cameras, berths, zones

uv run uvicorn services.api.main:app --reload   # API on :8000
cd web && pnpm install && pnpm dev              # UI on :5173
```

### Running the pipeline against a video file

No cameras needed — this is the normal development loop and the CI path:

```bash
uv run python -m services.ingest \
  --source file --path tests/fixtures/clips/entrance_morning.mp4 \
  --camera-id 1 --loop
```

`FileSource` is permanent test infrastructure, not scaffolding ([Phase 0](./phases/PHASE-0-foundations.md)). Every regression run replays footage through it.

### Tests

```bash
uv run pytest tests/unit                    # fast
uv run pytest tests/integration             # needs docker compose up
uv run pytest tests/regression -m identity  # golden crop set — run on every prompt change
```

---

## 2. Production deployment

### Hardware baseline (single marina, up to 16 cameras)

| Component | Spec |
|---|---|
| GPU | RTX 4000 Ada / A2000, or Jetson Orin |
| CPU | 8+ cores (decode and recording dominate, not inference) |
| RAM | 32 GB |
| System disk | 500 GB NVMe |
| Video storage | Sized from retention: ~0.5–1 TB per camera-month at 4 Mbps |
| Network | 2× NIC — one for the isolated camera VLAN, one for uplink |
| Power | UPS. An unclean shutdown mid-write can corrupt Postgres. |

### Network layout

```
  Cameras ── VLAN 20 (isolated, no internet route) ── NIC 1 ┐
                                                            ├─ Marina AI box
  Office LAN ─────────────────────────────────────── NIC 2 ┘
                                                            │
                                                     uplink ├─ Anthropic API (443)
                                                            └─ NTP
```

Only the `api` and `identifier` processes need outbound access. Cameras must not be routable from the internet — an exposed RTSP stream with default credentials is the most common way these systems are compromised.

### Deploy

```bash
docker compose -f deploy/docker-compose.yml \
               -f deploy/docker-compose.gpu.yml up -d
docker compose exec api alembic upgrade head
```

Migrations must be backwards-compatible for one release so a rollback does not require a database restore.

### Post-deploy verification

```bash
curl -fsS localhost:8000/health/ready       # db, redis, object store
curl -fsS localhost:8000/metrics | grep camera_last_frame_age_seconds
docker compose ps                            # all services up, none restarting
```

Then confirm in the UI: every camera `online`, detections rendering, a test transit appearing in the log.

---

## 3. Monitoring

### The metrics that actually matter

This system's characteristic failure is **silent degradation** — it keeps running and quietly produces wrong numbers. These are the signals that catch it:

| Metric | Alert when | What it means |
|---|---|---|
| `camera_last_frame_age_seconds` | > 30 s | Camera offline — counting is now incomplete |
| `ingest_frames_dropped_total` (rate) | > 5% of frames | GPU saturated or a camera outrunning the pipeline; **counts silently degrade** |
| Reconciliation drift | \|in − out − occupied\| > 3 | Counting is wrong somewhere; investigate before trusting reports |
| `vessels_provisional_current` | rising for 7 days | Review queue is being ignored, or identification has regressed |
| `reid_reverts_total` (rate) | > 5% of merges | **The matcher is drifting** — the honest quality signal |
| `identification_attempts_total{result="error"}` | > 10% | API or credential problem |
| `identification_tokens_total` (rate) | > 2× baseline | Prompt caching broken, or a retry loop |
| Disk free | < 15% | Recording will stop |
| `recorder_segment_gap_seconds` | any non-zero | **Recording gap — a compliance and evidence problem** |

Two of these deserve emphasis because nothing else surfaces them:

- **Dropped frames.** Nothing errors. Boats simply stop being counted, and the daily report looks plausible.
- **Merge revert rate.** A drifting matcher produces confident wrong merges. Nobody notices until someone disputes a berth record months later.

### Dashboards

Grafana on the edge box: pipeline health (frames, drops, inference latency), identification quality (rate, attempts, tokens, cost), storage (capacity, growth, retention), business (transits, occupancy, queue).

---

## 4. Runbook — common failures

### Camera shows offline

1. `docker compose logs ingest-<camera>` — look for reconnect attempts.
2. Reachable? `ping <camera-ip>` from the box.
3. Stream alive? `ffprobe rtsp://user:pass@<ip>/stream`
4. Credentials rotated on the camera? Update via `PATCH /cameras/{id}`.
5. PoE switch port up? A dead port is the most common physical cause.

The ingest process retries with backoff indefinitely — it does not need restarting once the camera returns.

### Counts look wrong

1. Check `ingest_frames_dropped_total` first. **Frame loss is the most common cause** and it is invisible in the UI.
2. Check camera uptime over the period — an offline gate camera means missed boats.
3. Review the annotated live view: are boats being detected at all? Are IDs switching mid-transit?
4. Check the gate line still matches reality — a bumped camera invalidates the zone geometry silently.
5. Run reconciliation manually: `uv run python -m scripts.reconcile --from ... --to ...`

Root causes, in observed order of likelihood: camera moved → zone geometry stale · frames dropped · ID switches from occlusion · two boats abreast counted as one.

### Identification stopped working

1. `identification_attempts_total{result="error"}` — is it API errors or null results?
2. API key valid? Check `identifier` logs for auth failures.
3. Outbound 443 reachable from the box?
4. If results are *null* rather than erroring: this is a **data** problem, not a system problem — check crop quality. Camera dirty, focus drifted, or sun angle changed seasonally.
5. Check `cache_read_input_tokens > 0`. Zero means prompt caching broke — usually a per-request value leaked into the system prompt — and costs ~10×.

### Identification costs spiked

1. Prompt caching broken (see above) — the usual cause.
2. Follow-up loop stuck retrying: check `attempt_no` distribution; the budget should cap at 8.
3. Transit volume genuinely up.
4. `effort` raised in config.

### Berth occupancy wrong

1. Has the camera moved? Polygons are per-camera and a bump invalidates them.
2. Is the boat visible from that camera at all, or occluded by a larger neighbour?
3. Adjacent berths confusable from that mounting position? A survey problem, not a tuning problem — see [`CAMERA-SITING.md`](./CAMERA-SITING.md).
4. Adjust `overlap_enter` / `dwell` in the zone's `config` for that berth specifically before touching global thresholds.

### Recording gaps

1. Disk full? Check first.
2. `recorder` process alive? It runs independently of inference by design — verify that separation actually held.
3. Object-store upload backlog on a slow uplink?
4. **Log the gap and inform the controller.** A recording gap may have compliance implications and should not be quietly absorbed.

### Database full / slow

1. Check `queue_samples` retention policy is active.
2. Check merged vessels aren't degrading queries — confirm the partial indexes exist.
3. `VACUUM ANALYZE` if autovacuum has fallen behind.

---

## 5. Backup and restore

### What is backed up

| Data | Method | Frequency | Retention |
|---|---|---|---|
| Postgres | `pg_dump` + WAL archiving | nightly full, continuous WAL | 30 days |
| Object store (crops, clips) | MinIO versioning + offsite sync | continuous | per retention policy |
| Config (`.env`, compose files) | Version control + encrypted secret store | on change | indefinite |

Continuous recordings are generally **not** backed up offsite — volume makes it impractical and retention is short. This is a deliberate decision and should be stated to the controller so expectations match reality.

### Restore

```bash
docker compose down api processor identifier ingest   # stop writers
docker compose up -d postgres
docker compose exec -T postgres psql -U marina -c "DROP DATABASE marina;"
docker compose exec -T postgres psql -U marina -c "CREATE DATABASE marina;"
gunzip -c backups/marina-2026-07-28.sql.gz | \
  docker compose exec -T postgres psql -U marina marina
docker compose exec api alembic current              # verify schema version
docker compose up -d
```

> **An untested backup is not a backup.** Phase 6 requires a restore rehearsal into a clean environment with the elapsed time recorded. Do it before go-live, and repeat it annually.

---

## 6. Routine maintenance

| Task | Frequency | Notes |
|---|---|---|
| Clean camera lenses | Monthly | **Salt spray is the dominant image-quality problem.** A dirty identification-camera lens looks like a model regression. |
| Verify camera aim | Quarterly, and after any storm | A bumped camera silently invalidates every zone on it |
| Review the review queue | Weekly | Prevents unbounded provisional backlog |
| Check revert rate | Monthly | Rising rate means the matcher needs recalibration |
| Verify retention deletion | Monthly | Confirm expired media is actually gone — a compliance obligation, not a nicety |
| Restore rehearsal | Annually | Record elapsed time |
| Dependency + image updates | Quarterly | Security patches |
| Recalibrate τ | After any model or prompt change | See [`PROMPTS.md §4.2`](./PROMPTS.md) |
| Access review | Quarterly | Deprovision departed staff |

The first row is not filler. On a marine site, lens cleaning has more effect on identification accuracy than most software changes — and its absence presents exactly like a model problem, sending people to debug the wrong layer.

---

## 7. Seasonal considerations

Marinas are strongly seasonal, and several system behaviours track that:

| Period | Effect | Response |
|---|---|---|
| High season | Transit volume up, queue depth up, identification cost up | Verify GPU headroom and API budget before the season |
| High season | Berths full — occupancy association gets harder with more simultaneous arrivals | Expect more review-queue items |
| Low season | Mostly repeat local boats | Re-ID hit rate rises; API cost falls sharply |
| Sun angle shift | A camera fine in April may be sun-blinded in July | Re-verify aim seasonally |
| Winter storms | Camera movement, cabling damage, pontoon reconfiguration | Verify aim and zones after storms |

The sun-angle row catches people out: siting validated in one season can silently fail in another, and it presents as "identification got worse" with no code change to blame.
