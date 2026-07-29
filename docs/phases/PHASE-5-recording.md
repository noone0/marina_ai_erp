# Phase 5 — Video archive

**Goal:** continuously record marina cameras, produce event clips around every meaningful event, and let operators find and play back footage by time, berth, or vessel.

**Delivers:** requirement #5 (auto-record marina parking slot video).
**Estimate:** ~2 weeks · **Depends on:** Phase 1 (Phase 3 for berth-scoped playback)

---

## In scope

- Segmented continuous recording per camera
- Event clip stitching around transits and berth state changes
- Retention policy with automatic deletion
- In-browser playback: scrub by time, filter by camera / berth / vessel
- Signed, audited media access

## Out of scope

Export/redaction workflows for legal requests (Phase 6), motion-triggered recording (continuous is simpler and more defensible for evidence).

---

## Deliverables

1. Every camera continuously records to object storage in indexed segments.
2. Each transit and berth state change has a playable clip attached.
3. Operators scrub a camera's timeline for any date and jump to events.
4. A vessel's timeline plays the clip for each of its events.
5. Retention deletes expired media automatically and provably.

---

## Tasks

- [ ] `recorder` service: FFmpeg segment muxer, 5-minute fMP4 segments, one process per camera
- [ ] **Recorder runs independently of the inference pipeline** — a detector crash must not stop recording
- [ ] Segment upload to object storage; index rows in `recordings`
- [ ] Clip stitcher: given `(camera, t)`, cut `t-30s … t+120s` across segment boundaries, upload, attach to `transits.clip_uri` / `berth_occupancy`
- [ ] Retention: `expires_at` on write + object-store lifecycle rules + a reconciling sweeper for orphans
- [ ] API: `/recordings` query, `/media/{key}` signed-URL redirect with `audit_log` write
- [ ] Player UI: hls.js, timeline scrubber with event markers, camera/berth/vessel filters
- [ ] Storage metrics and a disk-pressure alert

---

## Acceptance criteria

- [ ] Continuous recording with **no gaps** across a 24 h run — verified by checking segment continuity, not by eyeballing the player.
- [ ] Recording survives a detector/GPU crash: kill the detector, confirm recording continues uninterrupted.
- [ ] Recording survives an RTSP drop: reconnect resumes recording, and the gap is recorded as a gap rather than silently skipped.
- [ ] Event clips correctly span segment boundaries (test with an event deliberately placed 5 s before a segment cut).
- [ ] Every transit in the log has a playable clip.
- [ ] Retention deletes expired media and removes the index rows; verified by a test with a short TTL.
- [ ] Media access issues a short-lived signed URL and writes an audit row **every time** — required for KVKK.
- [ ] Playback starts in < 3 s for any archived time within retention.
- [ ] Storage growth matches the projection (~0.5–1 TB per camera-month at 4 Mbps) within 20%.

---

## Dependencies

- Storage sized for the chosen retention period.
- Retention period decided — this is a legal/policy decision, not a technical default (see Phase 6 and `ARCHITECTURE.md §8`).

---

## Risks

| Risk | Mitigation |
|---|---|
| Disk exhaustion takes down the whole system | Lifecycle rules + disk-pressure alert + recorder refuses to write below a floor rather than filling the volume |
| Recording coupled to inference and stops when detection fails | Explicit architectural separation; tested by killing the detector |
| Clip stitching is CPU-heavy and starves inference | Stitch jobs run at low priority / niced; queue them rather than doing it inline |
| Segment upload backlog on a slow uplink | Local buffer with backpressure; alert on backlog depth |
| Retention deletes footage still needed for a dispute | Legal-hold flag on `recordings` that exempts rows from expiry |
