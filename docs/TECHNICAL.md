# Marina AI — Technical Specification

Companion to [`ARCHITECTURE.md`](./ARCHITECTURE.md). That document explains *what* and *why*; this one specifies *how* — module layout, data contracts, algorithms, thresholds, and interfaces. Phase-by-phase execution lives in [`phases/`](./phases/).

Status: **specification (pre-implementation)** · Date: 2026-07-29

---

## 1. Repository layout

Monorepo, uv-managed Python workspace + pnpm frontend.

```
marine_ai_erp/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TECHNICAL.md              ← this file
│   ├── POC.md
│   └── phases/
├── packages/
│   ├── core/                     # shared: models, schemas, config, db
│   │   └── marina_core/
│   │       ├── config.py         # pydantic-settings, env-driven
│   │       ├── db/               # SQLAlchemy models + Alembic
│   │       ├── schemas/          # pydantic: events, API DTOs, Claude I/O
│   │       ├── events.py         # Redis Streams producer/consumer
│   │       └── storage.py        # S3/MinIO abstraction
│   ├── vision/                   # detection, tracking, zones, best-shot
│   │   └── marina_vision/
│   │       ├── sources/          # rtsp.py, file.py  (common interface)
│   │       ├── detector.py       # YOLO wrapper
│   │       ├── tracker.py        # ByteTrack wrapper
│   │       ├── zones.py          # gate lines, berth/queue polygons
│   │       ├── bestshot.py       # crop scoring & selection
│   │       └── embedding.py      # DINOv2 re-ID vectors
│   ├── identity/                 # Claude calls, re-ID matching, merges
│   │   └── marina_identity/
│   │       ├── claude.py         # vision identification client
│   │       ├── prompts.py        # cached system prompts
│   │       ├── matcher.py        # 3-stage re-ID
│   │       ├── provisional.py    # code minting, display names
│   │       └── merge.py          # promotion / merge / revert
│   └── recorder/                 # segmented recording, clip stitching
├── services/
│   ├── ingest/                   # one process per camera
│   ├── processor/                # event consumer → DB
│   ├── identifier/               # identification + follow-up worker
│   └── api/                      # FastAPI
├── web/                          # React + TypeScript + Vite
├── poc/                          # standalone PoC (see POC.md)
├── deploy/
│   ├── docker-compose.yml
│   └── docker-compose.gpu.yml
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/                 # sample clips, labelled ground truth
```

**Rule:** `packages/` holds importable libraries with no side effects at import. `services/` holds process entrypoints that wire packages together. Anything that opens a socket or a file handle at import time belongs in `services/`.

---

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | `uv` for dependency + workspace management |
| Detection | Ultralytics YOLO11 | `boat` class from COCO to start; fine-tuned later |
| Tracking | ByteTrack (via Ultralytics) | BoT-SORT as fallback if ID switches are high |
| Re-ID embedding | DINOv2 ViT-B/14 | 768-dim; swappable behind `embedding.py` |
| Video I/O | PyAV (decode), FFmpeg (record/stitch) | PyAV avoids subprocess overhead in the hot loop |
| Geometry | Shapely 2.x | zone tests |
| DB | PostgreSQL 16 + TimescaleDB + pgvector | |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | |
| Event bus | Redis 7 Streams | consumer groups give at-least-once + replay |
| Object store | MinIO (S3 API) | swap for S3/R2 in cloud deployments |
| Task scheduling | APScheduler (in-process) → Celery if it outgrows it | follow-up loop |
| API | FastAPI + uvicorn | REST + WebSocket |
| LLM | Anthropic Python SDK, `claude-opus-5` | |
| Frontend | React 18, TypeScript, Vite, TanStack Query, Zustand, Tailwind | |
| Video playback | hls.js | |
| Observability | structlog, Prometheus client, OpenTelemetry traces | |

---

## 3. Process model

| Process | Count | Restart policy | Notes |
|---|---|---|---|
| `ingest` | 1 per camera | always | Decodes RTSP, publishes frames to shared GPU queue. Isolated so one bad camera can't stall others. |
| `detector` | 1 per GPU | always | Batches frames across cameras. The only process that touches the GPU for detection. |
| `processor` | 1–2 | always | Redis consumer group; idempotent writes. |
| `identifier` | 1–2 | always | Claude calls + follow-up scheduler. Rate-limited. |
| `recorder` | 1 per camera | always | FFmpeg segment muxer. Runs independently of detection — **recording must never depend on inference being healthy.** |
| `api` | 2+ | always | Stateless. |

**Backpressure:** ingest drops frames rather than queueing without bound. A camera that outruns the detector loses frames, it does not grow memory. Dropped-frame count is a first-class metric — silent frame loss is how these systems degrade unnoticed.

---

## 4. Configuration

`pydantic-settings`, env-driven, one settings object per service. Camera and zone configuration lives in the **database**, not in files — it is edited from the UI zone editor and must be changeable without a redeploy.

```python
class Settings(BaseSettings):
    database_url: PostgresDsn
    redis_url: RedisDsn
    s3_endpoint: str; s3_bucket: str
    anthropic_api_key: SecretStr

    # inference
    detect_fps: float = 6.0
    detect_conf_threshold: float = 0.35
    detect_imgsz: int = 1280

    # identity
    identify_confidence_threshold: float = 0.85   # τ  — auto-accept
    identify_review_threshold: float = 0.50       # below this: don't even suggest
    followup_max_attempts: int = 8
    reid_auto_merge_similarity: float = 0.90
    reid_suggest_similarity: float = 0.75
    claude_model: str = "claude-opus-5"
    claude_effort: Literal["low","medium","high"] = "medium"

    model_config = SettingsConfigDict(env_prefix="MARINA_", env_file=".env")
```

Every threshold in that block is a tunable that gets **calibrated against labelled data in Phase 2**, not fixed by intuition. They are named constants precisely so the calibration is a config change, not a code change.

---

## 5. Event contracts (Redis Streams)

All events are JSON, versioned, and carry `event_id` (ULID) for idempotency. Stream per event family; consumer groups per service.

### `stream:detections` — produced by detector, consumed by nobody durably (live UI only)
```json
{ "v": 1, "event_id": "01J...", "camera_id": 3, "ts": "2026-07-29T08:14:22.310Z",
  "tracks": [{ "track_ref": "cam3-1721", "bbox": [412,220,780,455],
               "conf": 0.91, "class": "boat" }] }
```

### `stream:transits` — gate crossing detected
```json
{ "v": 1, "event_id": "01J...", "camera_id": 3, "zone_id": 7,
  "track_ref": "cam3-1721", "direction": "in",
  "occurred_at": "2026-07-29T08:14:22.310Z",
  "best_shots": ["s3://frames/2026/07/29/cam3-1721-a.jpg", "...-b.jpg"],
  "attributes_hint": { "est_bbox_px": [368,235] } }
```

### `stream:berth_state` — occupancy state machine transition
```json
{ "v": 1, "event_id": "01J...", "berth_id": 14, "camera_id": 9,
  "track_ref": "cam9-88", "state": "occupied",
  "changed_at": "2026-07-29T08:31:07.000Z", "overlap_ratio": 0.71 }
```

### `stream:identify_requests` — work for the identifier
```json
{ "v": 1, "event_id": "01J...", "vessel_id": 142, "transit_id": 908,
  "trigger": "followup", "attempt_no": 4,
  "crops": ["s3://crops/142/att4-a.jpg", "s3://crops/142/att4-b.jpg"] }
```

**Idempotency contract:** consumers must tolerate redelivery. `processor` writes use `INSERT ... ON CONFLICT (event_id) DO NOTHING` against a `processed_events` table, checked in the same transaction as the domain write.

---

## 6. Vision pipeline

### 6.1 Source interface

```python
class FrameSource(Protocol):
    def __iter__(self) -> Iterator[Frame]: ...
    @property
    def camera_id(self) -> int: ...
    @property
    def is_live(self) -> bool: ...

@dataclass
class Frame:
    camera_id: int
    ts: datetime          # wall-clock for live; synthesised for file playback
    seq: int
    image: np.ndarray     # BGR
```

Two implementations — `RtspSource` and `FileSource` — behind one interface. `FileSource` exists so the entire pipeline is developable and CI-testable without hardware, and so the PoC and regression tests replay identical footage. **This is not throwaway scaffolding; it is permanent test infrastructure.**

`RtspSource` requirements: exponential-backoff reconnect (1s → 60s cap), watchdog that treats "no frame for 10s" as a disconnect, and a `camera.status` heartbeat so the UI can show a camera as offline within ~15 s.

### 6.2 Detection & tracking

Detector runs at `detect_fps` (default 6), not native frame rate — boats are slow, and 6 fps is ample for a 3-knot target while cutting GPU cost ~5×. Frames are batched across cameras into a single inference call.

Tracker: ByteTrack. Config that matters:

| Param | Value | Reason |
|---|---|---|
| `track_thresh` | 0.5 | |
| `match_thresh` | 0.8 | |
| `track_buffer` | 90 frames (≈15 s at 6 fps) | Boats get occluded by pontoons and other vessels; a short buffer causes ID switches, and every ID switch is a phantom extra boat in the count. |

### 6.3 Zone engine

Zones are stored as image-space polygons/lines (normalised 0–1 so they survive resolution changes).

**Gate line crossing:**
```python
def crossed(prev: Point, curr: Point, line: LineString, normal: Vector) -> Direction | None:
    if not segment_intersects(prev, curr, line):
        return None
    side_before = sign(dot(prev - line.centroid, normal))
    side_after  = sign(dot(curr - line.centroid, normal))
    if side_before == side_after:
        return None
    return Direction.IN if side_after > 0 else Direction.OUT
```
Guards, all mandatory:
- `min_track_age`: 12 frames (2 s) before a track may emit a transit — kills detection flicker.
- `min_displacement`: centroid must travel ≥ 40 px past the line — kills oscillation from a boat idling on the line.
- `cooldown`: one transit per `(track_ref, direction)`.

**Berth occupancy state machine** — thresholds absorb boats manoeuvring through a neighbour's polygon:
```
EMPTY    → OCCUPIED : overlap_ratio ≥ 0.60 sustained ≥ 30 s
OCCUPIED → EMPTY    : overlap_ratio < 0.20 sustained ≥ 60 s
```

**Queue dwell:** a track inside a queue polygon for ≥ 120 s with mean speed below threshold is `queued`. Sampler writes `queue_samples` every 30 s.

### 6.4 Best-shot selection

Per track, maintain a bounded heap of the top-N (N=3) crops.

```python
def quality_score(crop: np.ndarray, bbox: Box, frame: Frame) -> float:
    sharp   = cv2.Laplacian(gray(crop), cv2.CV_64F).var()      # focus
    area    = bbox.area / frame.area                            # pixels on target
    expo    = 1.0 - abs(mean(gray(crop)) - 128) / 128           # not blown/crushed
    edge    = margin_from_frame_edge(bbox)                      # not clipped
    aspect  = pose_prior(bbox)                                  # prefer stern-on
    return (0.35*norm(sharp) + 0.30*area + 0.15*expo
            + 0.10*edge + 0.10*aspect)
```

This function is the main cost lever in the whole system: it decides what the API sees. It gets tuned against the PoC's labelled set, with the read-success rate as the objective.

---

## 7. Identity subsystem

### 7.1 Provisional code minting

```sql
-- monotonic, marina-scoped, never reused
CREATE SEQUENCE provisional_code_seq;
-- application formats as 'T-%04d'
```
Collision-free by construction. Codes are never recycled even after a merge — an old radio note or printed report referencing `T-0142` must always resolve.

Display name composition:
```python
def display_name(v: Vessel) -> str:
    if v.name:
        return f"{v.name}" + (f" (was {v.provisional_code})" if v.provisional_code else "")
    parts = [v.provisional_code, v.hull_color, TYPE_LABEL[v.vessel_type]]
    if v.est_loa_m:
        parts.append(f"~{v.est_loa_m:.0f} m")
    return " · ".join(p for p in parts if p)
```

### 7.2 Claude identification call

```python
SYSTEM_PROMPT = """..."""   # long, stable → cached

async def identify(crops: list[bytes], attempt: int) -> VesselID:
    resp = await client.messages.parse(
        model=settings.claude_model,
        max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": settings.claude_effort},
        messages=[{"role": "user", "content": [
            *[{"type": "image",
               "source": {"type": "base64", "media_type": "image/jpeg",
                          "data": b64(c)}} for c in crops],
            {"type": "text", "text": USER_INSTRUCTION},
        ]}],
        output_format=VesselID,
    )
    return resp.parsed_output
```

Prompt engineering requirements, all load-bearing:
- **Ordering for cache hits:** system prompt (stable, cached) → images (volatile) → instruction. Any per-request string in the system prompt destroys the cache; the prompt must contain no timestamps, camera IDs, or attempt numbers.
- **Null is a first-class answer.** The prompt states explicitly that returning `null` with low confidence is correct behaviour and that inventing a plausible name is a failure. Verified by a regression test that feeds deliberately illegible crops and asserts `name is None`.
- **Attributes are unconditional.** Hull colour, type, and size estimate must be returned even when the name is unreadable — they drive the provisional display name and the re-ID gate.
- **Calibrated confidence.** The prompt defines what each confidence band means (e.g. "0.9+ = every character legible and unambiguous"). Calibration is measured in Phase 2 by binning predictions and comparing to ground-truth accuracy.

Error handling: `stop_reason == "refusal"` is checked before reading content (unlikely here, but the check is one line and its absence is a crash). Transient API errors retry with the SDK's built-in backoff; permanent failures write an `identifications` row with `source='claude'` and null fields so the attempt is recorded and counted against the budget.

### 7.3 Re-ID matcher

```python
async def find_match(sighting: Sighting) -> MatchResult:
    # Stage 1 — attribute gate (SQL, near-free)
    candidates = await db.fetch("""
        SELECT v.id, s.embedding FROM vessels v
        JOIN vessel_sightings s ON s.vessel_id = v.id
        WHERE v.status <> 'merged'
          AND v.vessel_type = $1
          AND (v.est_loa_m IS NULL OR v.est_loa_m BETWEEN $2*0.8 AND $2*1.2)
          AND v.hull_color_family = $3
          AND v.last_seen_at > now() - interval '180 days'
    """, sighting.vessel_type, sighting.est_loa_m, sighting.hull_color_family)

    if not candidates:
        return MatchResult.new_vessel()

    # Stage 2 — embedding similarity (pgvector, indexed)
    best, score = top_cosine(sighting.embedding, candidates)

    if score >= settings.reid_auto_merge_similarity:      # 0.90
        return MatchResult.auto_merge(best, score)
    if score >= settings.reid_suggest_similarity:          # 0.75
        # Stage 3 — Claude adjudicates the ambiguous band
        verdict = await claude_compare(sighting.crop, best.reference_crop)
        return (MatchResult.auto_merge(best, score, evidence=verdict)
                if verdict.same_vessel and verdict.confidence >= 0.90
                else MatchResult.suggest(best, score, evidence=verdict))
    return MatchResult.new_vessel()
```

**Asymmetric error policy, enforced in code review:** the matcher must prefer `new_vessel()` under uncertainty. A duplicate is a one-click operator fix; a false merge silently fuses two boats' berth histories and video, and typically surfaces months later as a dispute. Any change that lowers `reid_auto_merge_similarity` requires evidence from the labelled set.

### 7.4 Follow-up scheduler

```python
BACKOFF = [5*60, 30*60, 2*3600, 6*3600, 24*3600, 24*3600, 24*3600, 24*3600]

def schedule_next(v: Vessel) -> datetime | None:
    if v.status in ("confirmed", "merged"):        return None
    if v.identity_confidence >= settings.identify_confidence_threshold: return None
    if v.attempt_count >= settings.followup_max_attempts:
        flag_for_operator(v, reason="attempt budget exhausted"); return None
    return v.last_attempt_at + timedelta(seconds=BACKOFF[v.attempt_count])
```

Plus an **opportunistic trigger** that bypasses the backoff: when a berth camera yields a crop whose `quality_score` exceeds every prior crop for that vessel by ≥ 15%, attempt immediately. Better data is the real signal; the clock is only a fallback.

Plus **light diversity**: the scheduler prefers slots in a different daypart (morning / afternoon / evening) from previous attempts, since glare that hides a transom at noon is often gone by 18:00.

### 7.5 Merge

```python
async def merge(source_id: int, target_id: int, *, method, similarity, evidence, actor):
    async with db.transaction():
        for table in ("transits", "berth_occupancy", "vessel_sightings",
                      "identifications", "recordings"):
            await db.execute(
                f"UPDATE {table} SET vessel_id=$1 WHERE vessel_id=$2", target_id, source_id)
        await db.execute("""UPDATE vessels
                            SET status='merged', merged_into_id=$1 WHERE id=$2""",
                         target_id, source_id)
        await db.execute("""INSERT INTO vessel_merges
                            (source_vessel_id,target_vessel_id,decided_by,method,
                             similarity,evidence) VALUES ($1,$2,$3,$4,$5,$6)""",
                         source_id, target_id, actor, method, similarity, evidence)
        await recompute_aggregates(target_id)
```

Single transaction. Reverse operation restores `vessel_id` from the merge record's captured row-id manifest — so `vessel_merges.evidence` must store the affected row ids, not just a similarity score. Merged rows are never deleted; all reads resolve `merged_into_id` transitively (depth-capped at 5 to catch cycles).

---

## 8. API surface

REST under `/api/v1`, JWT bearer auth, RBAC per role.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/cameras` · `/cameras/{id}/snapshot` | inventory, live still |
| `GET`/`PUT` | `/cameras/{id}/zones` | zone editor persistence |
| `GET` | `/transits?from&to&direction&vessel_id` | transit log (req. #1, #6) |
| `GET` | `/vessels?q&status` | registry search — matches name **and** provisional code |
| `GET` | `/vessels/{id}` · `/vessels/{id}/timeline` | detail + follow-up history (§6.7 of ARCHITECTURE) |
| `POST` | `/vessels/{id}/confirm` | operator accepts proposed name |
| `POST` | `/vessels/{id}/identify` | force an immediate identification attempt |
| `POST` | `/vessels/{id}/merge` · `/merges/{id}/revert` | identity unification |
| `GET` | `/review-queue?kind=identification\|merge` | operator work list |
| `GET` | `/berths` · `/berths/{id}/occupancy` | requirement #3 |
| `GET` | `/queue/current` · `/queue/history` | requirement #4 |
| `GET` | `/recordings?camera_id&berth_id&from&to` | requirement #5 |
| `GET` | `/media/{key}` | short-lived signed URL redirect |

**WebSocket** `/ws/live`, topic-subscribed: `detections.{camera_id}`, `transits`, `berths`, `queue`, `review_queue`. JSON frames matching the §5 contracts.

Media is **never** served directly by the API. `/media/{key}` issues a 5-minute signed URL and writes an `audit_log` row — required for the KVKK access-logging obligation.

---

## 9. Database notes

Indexes that matter:
```sql
CREATE INDEX ON transits (occurred_at DESC);
CREATE INDEX ON transits (vessel_id, occurred_at DESC);
CREATE INDEX ON vessel_sightings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON vessels (status) WHERE status <> 'merged';
CREATE INDEX ON vessels USING gin (to_tsvector('simple',
        coalesce(name,'') || ' ' || coalesce(provisional_code,'')));
CREATE INDEX ON berth_occupancy (berth_id, started_at DESC);
SELECT create_hypertable('queue_samples', 'ts');
```

The partial index on `status <> 'merged'` matters because merged rows accumulate forever and must not slow the hot path. The GIN index makes one search box match both `SERENITY` and `T-0142`, which is what operators actually need.

---

## 10. Observability

Prometheus metrics, minimum viable set:

| Metric | Type | Why |
|---|---|---|
| `ingest_frames_dropped_total{camera}` | counter | **Silent frame loss is the #1 invisible failure mode.** |
| `camera_last_frame_age_seconds{camera}` | gauge | drives offline alerting |
| `detector_inference_seconds` | histogram | GPU saturation |
| `transits_total{direction}` | counter | business metric + reconciliation |
| `identification_attempts_total{result}` | counter | read-success rate over time |
| `identification_tokens_total{kind}` | counter | live cost tracking |
| `vessels_provisional_current` | gauge | backlog of unnamed boats |
| `reid_merges_total{method}` / `reid_reverts_total` | counter | **revert rate is the honest quality signal for the matcher** |

Traces: one span per transit from detection through identification, so a slow or failed identification is diagnosable end to end.

**Nightly reconciliation job:** compares `Σ transits(in) − Σ transits(out)` against `count(active berth_occupancy)` and raises an alert on drift beyond tolerance. Counting systems fail silently; this is what catches it.

---

## 11. Testing

| Level | Scope |
|---|---|
| Unit | zone geometry (crossing, hysteresis, overlap), quality scoring, provisional formatting, backoff schedule, merge/revert round-trip |
| Integration | `FileSource` → detector → tracker → zone → Redis → processor → DB, asserted against fixture clips with known ground truth |
| Contract | Claude schema conformance; a **golden set of crops with expected outputs**, including illegible ones asserting `name is None` |
| Regression | Replay the labelled fixture set; assert read-success rate and false-name rate do not regress. Runs on every prompt or threshold change. |
| Load | 16 simulated cameras at 6 fps for 24 h; assert zero unbounded memory growth and stable drop rate |

The regression suite is the safety net for prompt changes. A prompt edit that improves recall while introducing confident wrong names must fail CI — which requires false-name rate to be an asserted metric, not a chart someone looks at.

---

## 12. Capacity targets (single marina, 16 cameras)

| Resource | Target |
|---|---|
| GPU | 1× RTX 4000 Ada / Jetson Orin — 16 cams @ 6 fps, 1280 px, batched |
| CPU | 8 cores (decode + record dominate) |
| RAM | 32 GB |
| Storage | ~0.5–1 TB per camera-month @ 4 Mbps; retention is the lever |
| Network | cameras on isolated VLAN; only `api` and `identifier` egress |
| Identification latency | best-shot → name written: p95 < 20 s (gate); follow-up is async |
| Live dashboard latency | detection → WebSocket frame: p95 < 500 ms |
