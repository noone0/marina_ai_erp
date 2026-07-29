# Phase 1 — Detect & Count

**Goal:** live RTSP ingest, boat detection and tracking, and accurate entry/exit counting at the marina mouth, visible on a dashboard.

**Delivers:** requirement #1 (count boats entering the marina) and the timestamp half of #6.
**Estimate:** ~2 weeks · **Depends on:** Phase 0

---

## In scope

- `RtspSource` with reconnect, watchdog, and camera heartbeat
- YOLO11 detector, batched across cameras, running at `detect_fps`
- ByteTrack tracking with tuned `track_buffer`
- Zone engine: gate lines with hysteresis guards
- `processor` service writing `transits` rows idempotently
- Live dashboard: camera view with overlaid boxes/track IDs, in/out counters, live transit list
- Nightly reconciliation job
- Core metrics, including dropped frames

## Out of scope

Identification (Phase 2a), berth polygons (3), queue zones (4), recording (5).

---

## Deliverables

1. A camera can be added in the DB and starts producing detections without a restart.
2. Gate lines drawn per camera (config/seed for now; the visual editor lands in Phase 3).
3. Boats crossing the gate produce exactly one `transits` row each, with correct direction.
4. Dashboard shows live video with boxes, running in/out counts, and a transit feed updating over WebSocket.
5. Reconciliation job runs nightly and alerts on drift.

---

## Tasks

- [ ] `RtspSource`: PyAV decode, exponential backoff 1s→60s, 10 s no-frame watchdog, `camera.last_seen_at` heartbeat
- [ ] Frame dropping under backpressure + `ingest_frames_dropped_total` counter
- [ ] `detector.py`: YOLO11 wrapper, cross-camera batching, `imgsz`/conf from settings
- [ ] `tracker.py`: ByteTrack wrapper, `track_buffer=90`, stable `track_ref` format `cam{id}-{n}`
- [ ] `zones.py`: gate-line crossing with signed-normal direction; guards for `min_track_age`, `min_displacement`, per-track cooldown
- [ ] Publish `stream:detections` (ephemeral) and `stream:transits` (durable)
- [ ] `processor`: consume `stream:transits` → `transits` rows, idempotent on `event_id`
- [ ] WebSocket `/ws/live` with `detections.{camera_id}` and `transits` topics
- [ ] React: live camera panel (canvas overlay), counter tiles, transit table
- [ ] Nightly reconciliation: `Σ in − Σ out` vs active occupancy (occupancy is 0 until Phase 3 — the job still runs and records the series)
- [ ] Metrics: dropped frames, last-frame age, inference latency, transits by direction

---

## Acceptance criteria

- [ ] **Counting accuracy ≥ 98%** against a hand-labelled 2-hour clip containing ≥ 30 transits — measured, not asserted.
- [ ] Zero double-counts: no boat produces two transits in the same direction (verified by the cooldown test and by manual review of the labelled clip).
- [ ] A boat that idles on the gate line for 60 s produces exactly one transit, not oscillation. **This is the single most likely counting bug — it gets its own test with a purpose-built clip.**
- [ ] Killing a camera's RTSP feed marks it offline in the UI within 15 s; restoring it resumes without a service restart.
- [ ] Sustained run: 8 cameras × 6 fps for 24 h with flat memory and a stable drop rate.
- [ ] Dashboard detection-to-screen latency p95 < 500 ms.

---

## Dependencies

- At least one gate camera installed and reachable, or representative recorded footage.
- Gate line geometry for that camera.

---

## Risks

| Risk | Mitigation |
|---|---|
| ID switches inflate the count | `track_buffer` tuned to 15 s; measure switch rate on labelled footage; fall back to BoT-SORT |
| COCO `boat` class misses RIBs / small tenders | Raise `imgsz`, lower conf; collect misses as the fine-tuning dataset |
| Two boats crossing abreast counted as one | Detector-level issue; measure explicitly on labelled footage and record the failure mode rather than hiding it in an aggregate |
| Wake, reflections, or moored boats trigger phantom tracks | `min_track_age` + requiring displacement across the line; validate against a clip with heavy chop |
| Silent frame loss degrades counts unnoticed | Dropped-frame metric with an alert threshold — this is why it's in the minimum metric set |
