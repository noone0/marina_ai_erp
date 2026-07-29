# Marina AI — Architecture & Roadmap

AI-supported marina management with visual recognition.
Status: **plan (pre-implementation)** · Date: 2026-07-29

---

## 1. Scope

Six capabilities requested:

| # | Capability | Core technique |
|---|---|---|
| 1 | Count boats entering the marina | Gate line-crossing on tracked detections |
| 2 | Identify **which** boat entered | Best-shot selection → Claude vision (name / flag / registration) |
| 3 | Know which boat parked in which area | Berth polygon occupancy + association to the entry event |
| 4 | Waiting queue at the marina mouth / bay | Loiter-zone tracking, dwell time, queue depth |
| 5 | Auto-record marina parking slot video | Continuous segmented recording + event clips per berth |
| 6 | Log name, flag, serial number, entry time | Vessel registry + immutable transit log |

Out of scope for now, but the data model is built so it can be added: berth contracts, billing, invoicing, customer accounts (the "ERP" in the repo name).

---

## 2. The one hard problem, stated up front

**Reading a boat's name and registration number from video is not a solved problem at arbitrary distance.** Everything else here (counting, tracking, occupancy, queue) is reliable computer vision. Identification is the risky part, for physical reasons:

- OCR needs roughly **≥ 25–30 px of character height** on the target text.
- Boat names sit on the transom (stern) and sometimes the bow — often at an oblique angle to a fixed camera.
- Sun glare on gelcoat, spray, wake, night, and script/cursive fonts all degrade it.
- Flags are small, in motion, and frequently furled.

**Decision: camera-only. No AIS receiver.** That is settled — but it means vision carries 100% of the identification burden, with no independent source to cross-check against. Two things follow that would otherwise be optional and are now mandatory:

Design consequences, baked into the plan below:

1. A **dedicated identification camera** at the gate — narrow field of view, 4K, aimed across the channel at the height where transoms pass, ideally a PTZ with a preset triggered by the wide camera. This is a siting decision, not a software one, and with no AIS fallback it is now the single largest determinant of system accuracy. Budget a site survey.
2. **Confidence is a first-class field, never hidden.** Every identification carries per-field confidence and the source crop, and low-confidence entries land in an **operator review queue** rather than being silently written as fact.
3. **Every boat gets an identity immediately — real or provisional.** No vessel is ever "unknown" in the data. If the name can't be read at the gate, the system mints a provisional identity (`T-0142`) and the boat is tracked, berthed, and logged under it exactly like a named vessel. See §6.
4. **Identification is a loop, not a gate event.** A berthed boat sits still for hours or days in changing light, swinging on its lines. The system keeps re-attempting identification from berth cameras until it succeeds. This is where most identifications will actually happen — the gate is a poor place to read a name (moving target, oblique angle, wake spray); a boat tied up at a pontoon is an excellent one.

Treat identification as *assisted data entry*: the system proposes, an operator confirms in one click for anything under threshold. Accuracy compounds over time as the vessel registry fills with repeat visitors — recognising a returning boat is far easier than reading a name cold.

---

## 3. System architecture

```
┌─ Edge (marina, on-prem GPU box) ──────────────────────────┐
│                                                            │
│  RTSP cameras ──► Ingest workers (FFmpeg/GStreamer decode) │
│       │                    │                               │
│       │                    ▼                               │
│       │            YOLO detect ──► ByteTrack tracker        │
│       │                    │                               │
│       │                    ▼                               │
│       │            Zone engine (gate / berth / queue)       │
│       │                    │                               │
│       │                    ▼                               │
│       │            Redis Streams (event bus)                │
│       │                                                     │
│       └──────────► Recorder (segmented MP4/HLS → object store)
└────────────────────────────┬───────────────────────────────┘
                             │
┌─ Core services ────────────▼───────────────────────────────┐
│  Event processor  ──► PostgreSQL (+ TimescaleDB for series)│
│         │                                                   │
│         ▼                                                   │
│  Identification worker ──► Claude vision API                │
│         │                  (name / flag / registration)     │
│         ▼                                                   │
│  FastAPI  (REST + WebSocket)  ──► MinIO / S3 (frames, video)│
└────────────────────────────┬───────────────────────────────┘
                             │
                    React + TypeScript dashboard
```

**Why the split:** RTSP decoding and YOLO inference are bandwidth- and GPU-bound and belong next to the cameras. Everything downstream is ordinary web infrastructure and can run on the same box for a single marina, or centrally for a multi-marina deployment. The Redis Streams boundary is what makes that choice reversible later.

### 3.1 Component responsibilities

| Component | Tech | Responsibility |
|---|---|---|
| **Ingest worker** | Python, PyAV / GStreamer | One process per camera. Decodes RTSP, drops to a target inference FPS (5–10), handles reconnect/backoff, publishes frames to the detector. Never blocks the recorder. |
| **Detector** | Ultralytics YOLO11 (`boat` class, fine-tuned) | Bounding boxes per frame. Batched across cameras on one GPU. |
| **Tracker** | ByteTrack / BoT-SORT | Stable track IDs across frames. This is what turns "a boat is visible" into "*this* boat moved from A to B". |
| **Zone engine** | Shapely | Evaluates each track against configured geometry: gate lines (directional crossing), berth polygons (occupancy), queue polygons (dwell). Emits domain events. |
| **Best-shot selector** | OpenCV | Per track, keeps the top-N crops scored on sharpness (variance of Laplacian), bounding-box area, aspect/pose, and exposure. Only these go to Claude — this is the main cost control. |
| **Identification worker** | Anthropic Python SDK | Sends best-shot crops to Claude with a strict output schema. Writes `identifications` rows with per-field confidence. |
| **Re-ID matcher** | DINOv2 embeddings + pgvector | Decides whether a new sighting is a boat already in the registry (named or provisional) or a genuinely new one. Load-bearing: with no AIS, this is the only mechanism that unifies sightings of the same hull over time. |
| **Follow-up scheduler** | Celery / APScheduler | Keeps re-attempting identification on provisional vessels from berth cameras — different light, different angle — until confidence threshold or attempt budget is reached. |
| **Recorder** | FFmpeg segment muxer | Continuous rolling recording per camera (e.g. 5-min segments), plus event-triggered clips (`t-30s … t+120s`) around berth arrivals/departures and gate transits. |
| **Event processor** | Python (asyncio) | Consumes Redis Streams → durable rows; runs the association logic that links a gate transit to a subsequent berth occupancy. |
| **API** | FastAPI | REST for CRUD/reports, WebSocket for the live dashboard, signed URLs for media. |
| **Dashboard** | React + TypeScript + Vite | Live marina map, transit log, review queue, berth grid, queue widget, video playback. |

### 3.2 Storage

- **PostgreSQL 16** — system of record. TimescaleDB extension for `queue_samples` and other high-rate time series; **pgvector** for re-ID embeddings.
- **MinIO** (S3-compatible) — frames, best-shot crops, video segments. Lifecycle rules drive retention.
- **Redis** — event bus (Streams) and short-lived state (current track/zone state).

---

## 4. Data model (core tables)

```
cameras            id, name, kind(gate|identity|berth|bay), rtsp_url,
                   resolution, fps, calibration, status, last_seen_at

zones              id, camera_id, kind(gate_line|berth|queue_area),
                   geometry(jsonb polygon/line in image coords),
                   direction_hint, berth_id?

berths             id, code, pontoon, max_loa_m, max_beam_m, draft_m,
                   power, water, is_active

vessels            id, status(provisional|candidate|confirmed|merged),
                   provisional_code,          -- 'T-0142', assigned at first sighting
                   name, name_source(claude|operator|inherited), flag_country,
                   registration_no, mmsi?, vessel_type,
                   -- physical attributes used for re-ID gating:
                   hull_color, superstructure_color, est_loa_m, distinctive_marks,
                   identity_confidence, merged_into_id?,
                   first_seen_at, last_seen_at, sighting_count, notes
                   -- the registry. EVERY boat has a row here from first sighting,
                   -- named or not. `merged_into_id` points at the surviving row
                   -- after a merge; merged rows are kept, never deleted.

vessel_sightings   id, vessel_id, camera_id, transit_id?, berth_id?, seen_at,
                   crop_uri, embedding vector(768), quality_score
                   -- pgvector index; the substrate for re-ID matching

transits           id, direction(in|out), occurred_at, camera_id, zone_id,
                   track_ref, vessel_id,      -- NOT NULL: always set, even if provisional
                   best_frame_uri, clip_uri, confidence
                   -- requirement #1 (count) and #6 (entry time)

identifications    id, vessel_id, transit_id?, attempt_no,
                   trigger(gate|followup|operator|rematch),
                   source(claude|manual|registry_match),
                   name, flag_country, registration_no, vessel_type,
                   field_confidence(jsonb), model, input_tokens, output_tokens,
                   raw_response(jsonb), created_at
                   -- append-only; one row per attempt, including failed ones.
                   -- attempt_no + trigger drive the follow-up backoff schedule.

vessel_merges      id, source_vessel_id, target_vessel_id, decided_by(system|user_id),
                   method(embedding|claude_compare|operator), similarity,
                   evidence(jsonb), merged_at, reverted_at?, reverted_by?
                   -- full audit of every identity unification; reversible

berth_occupancy    id, berth_id, vessel_id?, transit_id?, started_at,
                   ended_at?, confidence, source(vision|manual)
                   -- requirement #3

queue_samples      ts, zone_id, vessel_count, max_dwell_sec, avg_dwell_sec
                   -- hypertable; requirement #4

recordings         id, camera_id, berth_id?, kind(continuous|event),
                   started_at, ended_at, storage_uri, size_bytes, expires_at
                   -- requirement #5

users / roles / audit_log
```

Design notes:

- `identifications` is **append-only**. `vessels` holds the current resolved truth; every machine guess and every human correction stays on the record. This makes the review queue auditable and yields labelled data for fine-tuning later.
- `transits.vessel_id` is **NOT NULL**. Since every boat receives a provisional identity at first sighting, there is no such thing as a transit without a vessel. This is the schema-level expression of your requirement.
- `berth_occupancy.transit_id` is the link that answers *"which boat that entered is now parked where"* (requirements #2 + #3 joined) — and it works identically for `T-0142` as for `SERENITY`.
- **Nothing is deleted on merge.** A merged vessel row survives with `status='merged'` and `merged_into_id` set. All queries resolve through that pointer, so a stale bookmark or an old report still lands on the right boat. This is what makes merges reversible.

---

## 5. Detection & event logic

### 5.1 Entry / exit counting

A **gate line** is a directed segment drawn on the gate camera's image. A track crossing it increments in or out depending on the sign of the crossing relative to the line normal. Guards against the usual failure modes:

- **Hysteresis** — require the track centroid to travel a minimum distance past the line, not just touch it, so a boat idling on the line doesn't oscillate.
- **Minimum track age** — a track must exist for N frames before it can generate a transit, killing detection flicker.
- **Cooldown per track** — one transit per track per direction.
- **Reconciliation** — a nightly job compares `count(transits in) - count(transits out)` against `count(active berth_occupancy)` and flags drift. Silent miscounting is the failure mode that erodes trust in this kind of system, so it gets an explicit check.

### 5.2 Berth occupancy

Each berth gets a polygon on a berth camera. Occupancy is a state machine, not an instantaneous test:

```
EMPTY --(box overlaps ≥ 60% for ≥ 30s)--> OCCUPIED
OCCUPIED --(no overlap for ≥ 60s)--> EMPTY
```

The dwell thresholds absorb boats manoeuvring through a neighbour's polygon. On `EMPTY → OCCUPIED`, the processor looks back over the last ~30 minutes of `transits(direction=in)` with no assigned berth and associates the most likely one (nearest in time, compatible size). Ambiguous cases go to the review queue rather than guessing.

### 5.3 Queue at the mouth / bay

A **queue polygon** covers the approach/anchorage. A track is "queued" when it has been inside the polygon for ≥ 2 minutes with low mean speed. The sampler writes `queue_samples` every 30 s: current count, max dwell, average dwell. The dashboard shows live depth plus a 24 h trend, and estimated wait derives from the rolling median of observed (enter-queue → cross-gate) durations.

### 5.4 Recording

- **Continuous:** every camera writes 5-minute fMP4 segments to object storage, indexed in `recordings`. Retention by lifecycle policy (default 30 days — this is a legal/policy decision, see §8).
- **Event clips:** on a gate transit or a berth state change, a job stitches `t-30s … t+120s` from the segments into a standalone clip and attaches it to the row. This is what makes the transit log actually reviewable — every entry has playable evidence next to it.

---

## 6. Identity: provisional naming, recognition, follow-up

This is the heart of the system. Cheap local models handle every frame; Claude is called on selected crops only. That ratio is the whole cost model.

### 6.1 Identity lifecycle

```
   first sighting at gate
            │
            ▼
   ┌─────────────────┐   name read with confidence ≥ τ
   │  PROVISIONAL    │ ──────────────────────────────► ┌───────────┐
   │  "T-0142"       │                                 │ CANDIDATE │
   │  fully usable:  │ ◄── follow-up attempts ────┐    │ name      │
   │  berths, logs,  │     (berth cams, better    │    │ proposed  │
   │  transits, video│      light/angle)          │    └─────┬─────┘
   └─────────────────┘ ───────────────────────────┘          │
            │                                       operator confirms
            │ re-ID matches an existing vessel        (or auto above τ_high
            │                                          + registration match)
            ▼                                                │
      ┌──────────┐                                           ▼
      │  MERGED  │ ◄──────────────────────────────────  ┌───────────┐
      │ history  │      identified name matches an      │ CONFIRMED │
      │ inherited│      already-confirmed vessel        │ SERENITY  │
      └──────────┘                                      └───────────┘
```

The critical property: **a provisional vessel is not a degraded record.** `T-0142` berths, gets recorded, appears in reports, and accumulates history exactly like a named boat. Naming it later is an enrichment, not a repair.

### 6.2 Provisional naming

On first sighting with no confident name, the system mints:

- **`provisional_code`** — `T-0142`. Marina-scoped, sequential, never reused. Short and unambiguous over VHF radio, which is what marina staff actually need.
- **`display_name`** — auto-composed from detected attributes so staff can find the boat visually without opening the record:
  `T-0142 · white motor yacht · ~12 m`
- **operator nickname** (optional) — staff can attach a human label (`T-0142 "the blue catamaran on D pontoon"`). Free text, searchable, and preserved through a later merge as an alias.

The code stays visible on the vessel record forever, even after the real name is learned. `SERENITY (was T-0142)` — so anyone reading an old report or an old radio note can still resolve it.

### 6.3 Vision identification

**Model:** `claude-opus-5`. Structured output via a strict schema so the response is always parseable:

```python
class VesselID(BaseModel):
    # --- identity fields (may be null; null is a valid, expected answer) ---
    name: str | None
    name_confidence: float          # 0.0–1.0
    flag_country: str | None        # ISO 3166-1 alpha-2
    flag_confidence: float
    registration_no: str | None     # transom registration / sail number
    registration_confidence: float

    # --- physical attributes: ALWAYS returned, even when the name is not ---
    # these are what make a provisional identity useful and re-ID possible
    vessel_type: Literal["motor_yacht","sailing_yacht","rib","fishing",
                         "catamaran","tender","other"] | None
    hull_color: str | None
    superstructure_color: str | None
    est_loa_m: float | None         # estimated length overall
    distinctive_marks: list[str]    # radar arch, hardtop, davit, stripe, name board
    notes: str | None               # e.g. "name partially occluded by fender"

resp = client.messages.parse(
    model="claude-opus-5",
    max_tokens=2000,
    system=[{"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],   # stable prefix, cached
    output_config={"effort": "medium"},
    messages=[{"role": "user", "content": [
        *[{"type": "image", "source": {"type": "base64",
           "media_type": "image/jpeg", "data": c}} for c in crops],
        {"type": "text", "text": "Identify this vessel."},
    ]}],
    output_format=VesselID,
)
```

Key decisions:

- **Prompt caching on the system prompt.** The instructions (how to read transom text, flag disambiguation rules, when to return null) are long and identical on every call — cached at ~0.1× read cost. The volatile part (images) goes after the breakpoint.
- **`effort: "medium"`** as the starting point, swept against a labelled sample. This is the primary cost/accuracy dial; a sweep of `low`/`medium`/`high` on real marina footage decides it, not a guess.
- **Refuse to guess.** The prompt instructs Claude to return `null` with low confidence rather than inventing a plausible name. A wrong name written confidently into a berth record is worse than a provisional code — the provisional code is honest about what we don't know.
- **Attributes are never null-by-omission.** Even a completely unreadable transom yields hull colour, type, and size estimate from the same call. Those fields do double duty: they compose the provisional display name and they gate re-ID.
- **Never trust a single field blindly.** Anything below the configured threshold (start at 0.85) routes to the review queue.

### 6.4 Re-identification — unifying sightings of the same hull

With no AIS, appearance is the only signal linking a boat seen today to the same boat seen last week. Three-stage matcher, cheapest first:

1. **Attribute gate (SQL).** Candidates must be compatible: `vessel_type` equal, `est_loa_m` within ±20%, hull colour in the same family. Eliminates almost everything for near-zero cost.
2. **Embedding similarity (pgvector).** DINOv2 embedding of the best crop, cosine similarity against surviving candidates' stored sightings. Model is swappable and gets evaluated against a held-out labelled set before it's trusted.
3. **Claude pairwise comparison** — only for the ambiguous band (similarity 0.75–0.90). Two crops, one question: *same vessel? cite the evidence.* This is a genuinely strong use of vision — distinguishing two similar white motor yachts by radar arch shape, stripe detail, or davit configuration is exactly the kind of fine-grained comparison it does well, and it's far cheaper than an operator doing it.

> **Governing principle: a wrong merge is worse than a duplicate.**
> Many white motor yachts look alike. Two duplicate provisional records are a minor annoyance an operator fixes in one click. A bad merge silently fuses two boats' berth histories, arrival times, and video — and nobody notices until it causes a billing or security dispute. So the matcher is deliberately **conservative**: auto-merge only on high similarity *and* a passed attribute gate; everything else becomes a *suggestion* in the review queue, never an automatic action.

### 6.5 Follow-up loop

A boat at the gate is a bad identification target. The same boat tied to a pontoon for three days is an excellent one. The follow-up scheduler exploits this.

For any vessel in `provisional` or `candidate` state, re-attempt identification on:

- **Backoff schedule** — +5 min, +30 min, +2 h, +6 h, then daily; capped at an attempt budget (start at 8) or until `identity_confidence ≥ τ`.
- **Opportunistic trigger** — whenever a berth camera produces a crop whose `quality_score` beats every prior crop for that vessel, attempt immediately regardless of backoff. Better data is the actual signal; the clock is just a fallback.
- **Light diversity** — the scheduler prefers spreading attempts across morning / afternoon / evening. Glare that hides a transom at noon is often gone by 18:00.

Every attempt writes an `identifications` row, including failures, with `attempt_no` and `trigger`. Failed attempts are data: a vessel that has burned 8 attempts across three days of good light is telling us its name genuinely isn't camera-readable, and it should go to an operator rather than keep costing API calls.

### 6.6 Promotion and merge

When a follow-up attempt finally reads a name:

1. **Search the registry for that name.** If a `confirmed` vessel with the same (or fuzzy-matching) name and compatible attributes already exists — this is a returning boat that was identified on a previous visit. Merge the provisional into it. The provisional's transits, berth history, sightings, and recordings all re-point to the surviving record, and the boat's history stretches back through visits when we didn't know its name yet. **This is the payoff of assigning provisional identities in the first place.**
2. **Otherwise promote in place.** `T-0142` becomes `SERENITY`, keeping its id, its history, and `provisional_code` for traceability.

Merges are logged to `vessel_merges` with method, similarity, and evidence, and are **reversible** — a one-click undo re-points the child rows back. Operators will occasionally merge wrongly; the system should make that recoverable rather than pretending it won't happen.

### 6.7 Following a vessel after identification

Identification isn't the end state — it's the point at which tracking becomes meaningful. Each vessel record carries a **timeline**:

```
T-0142 → SERENITY (TR) · reg. TR-34-A-1234 · 12.4 m motor yacht
├─ 2026-07-12 08:14  entered marina        [clip]  ← identified here (attempt 4)
├─ 2026-07-12 08:31  berthed  D-14         [clip]
├─ 2026-07-14 10:02  moved    D-14 → C-07  [clip]
├─ 2026-07-19 16:45  departed marina       [clip]
└─ 2026-07-27 11:20  returned              [clip]  ← auto-matched by re-ID
```

Every row is a real record with playable video. Operator-facing consequences: search by name or provisional code, filter berths by occupant, and alerting on the events that matter — vessel departed, expected vessel returned, vessel moved berth without instruction, vessel still provisional after N days.

### 6.8 Cost

At ~3 images (~1,500 tokens each) plus a cached system prompt, one identification attempt is a fraction of a cent. The follow-up loop multiplies attempts per vessel (budget 8), and re-ID adds occasional pairwise comparisons — call it under 10× a single-shot design, still small next to GPU and storage. The attempt budget and `effort` level are the two dials. Actual figures get measured in Phase 2 with `count_tokens` on real footage, not estimated.

---

## 7. Phased roadmap

Each phase ends with something demonstrable and independently useful.

### Phase 0 — Foundations (build first)
Monorepo layout, Docker Compose (Postgres, Redis, MinIO, API, worker, web), Alembic migrations for the schema above, config/secrets handling, structured logging, CI. **Includes a video-file source adapter and a synthetic clip set so the entire pipeline is developable and testable without camera hardware.**

### Phase 1 — See and count
RTSP ingest with reconnect, YOLO detection, ByteTrack, gate-line crossing, live counts over WebSocket, first dashboard (live view + in/out counters + transit list). **Delivers requirement #1.**

### Phase 2a — Identify + provisional identity
Best-shot selector, Claude identification worker, vessel registry with **provisional code minting**, review queue UI with one-click confirm/correct, transit log with crops, vessel detail timeline. Every boat gets an identity from day one of this phase. **Delivers requirements #2 and #6.**

### Phase 2b — Re-ID and follow-up
pgvector + DINOv2 embeddings, three-stage matcher, follow-up scheduler with backoff and opportunistic triggers, merge/promotion flow with reversible `vessel_merges` audit, merge-suggestion review queue. This is what turns a pile of one-off sightings into a vessel history. **Split from 2a because it is substantial and independently testable — 2a is useful on its own.**

### Phase 3 — Berth occupancy
Zone editor (draw berth polygons on a camera image in the browser), occupancy state machine, transit→berth association, marina map view with live berth status. **Delivers requirement #3.**

### Phase 4 — Queue analytics
Queue polygons, dwell tracking, `queue_samples` hypertable, live queue widget and historical trend, estimated wait time. **Delivers requirement #4.**

### Phase 5 — Video archive
Continuous segmented recording, event-clip stitching, retention policies, in-browser player scrubbing by time and by berth. **Delivers requirement #5.**

### Phase 6 — Production hardening
Auth + RBAC (operator / manager / admin), alerting (camera offline, unusual queue depth, unidentified transit backlog), scheduled reports (daily/monthly occupancy and traffic), Prometheus metrics + health checks, backup/restore, retention & privacy controls.

### Later (not scoped now)
YOLO fine-tuning on marina-specific footage, re-ID embedding model fine-tuned on the labelled data the review queue generates, ERP layer (contracts, berth billing, invoicing). *AIS integration is explicitly excluded by decision — the `mmsi` column remains only as a manual-entry field.*

---

## 8. Operational & legal notes

- **Hardware baseline (single marina):** one GPU box (RTX 4000-class or Jetson Orin) for 8–16 cameras at 5–10 inference FPS. Storage sizing dominated by continuous recording: roughly 0.5–1 TB per camera-month at 4 Mbps — retention length is the main cost lever.
- **Network:** cameras on an isolated VLAN, no direct internet exposure. Only the API egresses (to the Anthropic API and, if used, cloud storage).
- **Camera siting is the accuracy ceiling.** Budget a site survey before Phase 2. Gate cameras want a near-perpendicular view of passing transoms at a height that avoids glare off the water.
- **KVKK / GDPR:** continuous video of a public-facing area is personal data processing. Needed before go-live: signage at the entrance and pontoons, a documented retention period with automatic deletion, access logging on video playback, role-restricted export, and a data-processing record. The `audit_log` table and MinIO lifecycle rules exist for this. Worth a legal review of the retention period specifically — the technical default of 30 days is a placeholder, not advice.

---

## 9. Open questions for you

These don't block starting Phase 0 — they shape Phases 2–5:

1. **How many berths and cameras**, and are cameras already installed or is this a greenfield install where we can specify placement? With AIS ruled out, camera placement is now the accuracy ceiling — if placement is still open, that is the highest-leverage decision available.
2. **Provisional code format** — is `T-0142` right for your staff, or do you want a different prefix/format that fits existing marina conventions and reads well over radio?
3. **Deployment shape** — single marina on-prem, or central cloud serving multiple marinas?
4. **Retention period** for video, and whether a legal/KVKK review has already been done.
5. **Dashboard language** — Turkish, English, or both (i18n from the start is cheap; retrofitting is not).
