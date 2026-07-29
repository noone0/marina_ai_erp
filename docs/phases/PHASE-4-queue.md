# Phase 4 — Queue analytics

**Goal:** show how many boats are waiting at the marina mouth or in the bay, how long they've been waiting, and how that trends.

**Delivers:** requirement #4 (total waiting queue at marina mouth or bay).
**Estimate:** ~1 week · **Depends on:** Phase 1

---

## In scope

- Queue polygons drawn in the zone editor
- Dwell tracking with speed gating
- `queue_samples` hypertable at 30 s resolution
- Live queue widget + 24 h / 7 d trend
- Estimated wait time from observed queue→gate durations
- Threshold alerting on unusual queue depth

## Out of scope

Predictive queue forecasting, berth-availability-driven queue management. Both are natural follow-ons once there's history.

---

## Deliverables

1. Queue areas defined per camera in the same editor as berths.
2. Live count of waiting vessels with per-vessel dwell time.
3. Historical trend chart.
4. Estimated wait derived from real observed transit times, not a guess.
5. Alert when queue depth or max dwell exceeds a configured threshold.

---

## Tasks

- [ ] Extend zone editor with `queue_area` zone kind
- [ ] Dwell tracker: a track is `queued` after ≥ 120 s inside the polygon with mean speed below threshold
- [ ] Speed estimation from centroid displacement (pixel-space, smoothed) — no camera calibration needed for a relative threshold
- [ ] Sampler writing `queue_samples` every 30 s: `vessel_count`, `max_dwell_sec`, `avg_dwell_sec`
- [ ] Wait-time estimator: rolling median of (first-queued → gate-transit) durations over a trailing window
- [ ] API: `/queue/current`, `/queue/history?from&to&bucket`
- [ ] WebSocket `queue` topic
- [ ] UI: live queue tile (count + longest wait), trend chart, list of waiting vessels with identities
- [ ] Alert rule: depth or dwell over threshold for N consecutive samples

---

## Acceptance criteria

- [ ] Queue count within ±1 vessel of ground truth on a labelled clip containing a genuine queue.
- [ ] A boat merely **transiting** the queue polygon on its way in is not counted as waiting — the dwell + speed gate must exclude it. This is the main false-positive mode and gets a dedicated test.
- [ ] A boat anchored in the bay overnight does not inflate the "waiting" figure indefinitely — a maximum dwell cap reclassifies it as anchored rather than queueing.
- [ ] Dwell time accurate within ±30 s.
- [ ] `queue_samples` is a hypertable; a 30-day range query returns in < 500 ms.
- [ ] Estimated wait derives from real observations, with sample count exposed in the UI so operators can judge whether to trust it.
- [ ] Live widget updates within 30 s of a change.

---

## Dependencies

- A camera covering the approach/anchorage with adequate field of view.
- Phase 2a is not required, but identified vessels in the waiting list make it far more actionable.

---

## Risks

| Risk | Mitigation |
|---|---|
| Wide-area bay camera has too few pixels per boat to detect small craft | Measure detection recall specifically on the bay camera; may need a second camera or higher `imgsz` |
| Moored/anchored boats permanently inside the polygon inflate the count | Max-dwell cap reclassifies as anchored; polygon drawn to exclude known anchorage where possible |
| Passing traffic not intending to enter counted as queued | Dwell + speed gate; validate against labelled footage |
| Estimated wait misleading when sample count is low | Show sample count and suppress the estimate below a minimum |
