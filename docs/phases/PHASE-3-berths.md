# Phase 3 — Berth occupancy

**Goal:** know which boat is in which berth, and link it back to the entry that brought it there.

**Delivers:** requirement #3 (which boat parked in which area).
**Estimate:** ~2 weeks · **Depends on:** Phase 1 (Phase 2a strongly recommended — a berth labelled `SERENITY` is far more useful than one labelled `track-1721`)

---

## In scope

- Berth polygon definition via a **visual zone editor** in the browser
- Occupancy state machine with dwell hysteresis
- Transit → berth association
- `berth_occupancy` history with arrival/departure times
- Marina map view with live berth status
- Berth-move detection (boat relocated between berths)

## Out of scope

Berth contracts, pricing, reservations — the ERP layer, deliberately later.

---

## Deliverables

1. An operator draws berth polygons on a live camera image and saves them; no redeploy.
2. A boat mooring is detected and written to `berth_occupancy` within ~1 minute.
3. The arrival is linked to the gate transit that preceded it.
4. Marina map shows occupied/empty berths with occupant names, updating live.
5. Berth history is queryable: who was here, when, for how long.

---

## Tasks

- [ ] Zone editor: camera still + polygon drawing, snap/undo, persisted to `zones` (normalised 0–1 coords)
- [ ] Berth CRUD: code, pontoon, max LOA/beam, services
- [ ] Bind zone → berth
- [ ] Occupancy state machine: `EMPTY→OCCUPIED` at overlap ≥ 0.60 for ≥ 30 s; `OCCUPIED→EMPTY` at overlap < 0.20 for ≥ 60 s
- [ ] Publish `stream:berth_state`; processor writes `berth_occupancy` open/close rows
- [ ] Association: on `EMPTY→OCCUPIED`, find unassigned `transits(direction=in)` in the last 30 min, score by time proximity + size compatibility, assign best; ambiguous → review queue
- [ ] Berth-move detection: close prior occupancy, open new one, same `vessel_id`
- [ ] API: `/berths`, `/berths/{id}/occupancy`
- [ ] Marina map UI: berth grid/plan, colour by state, occupant name, click → vessel detail
- [ ] Reconciliation now meaningful: in − out vs active occupancy count

---

## Acceptance criteria

- [ ] **Occupancy accuracy ≥ 95%** against a labelled multi-hour clip covering arrivals, departures, and at least one berth move.
- [ ] A boat manoeuvring through a neighbouring berth's polygon en route to its own does **not** create a spurious occupancy. This is the characteristic failure of naive polygon tests and gets a dedicated test clip.
- [ ] Departure detected within 90 s of the boat leaving.
- [ ] Association correctness ≥ 90% on the labelled set; ambiguous cases go to review rather than being guessed.
- [ ] Zone editor changes take effect without restarting any service.
- [ ] Polygons survive a camera resolution change (normalised coordinates).
- [ ] Berth moves produce two occupancy rows for one vessel, not a departure and an unrelated arrival.

---

## Dependencies

- Berth cameras installed with usable pontoon coverage.
- Berth inventory (codes, pontoons, dimensions) from the marina.

---

## Risks

| Risk | Mitigation |
|---|---|
| Adjacent berths overlap in the camera's 2D view | Tune polygons conservatively (inner area only); flag berths that cannot be disambiguated as needing a camera change — a software fix cannot recover information the view doesn't contain |
| Boats moored bow-in vs stern-in change apparent footprint | Overlap ratio thresholds tuned per berth if needed; per-zone override in config |
| Wind/swell causes overlap to oscillate near the threshold | Dwell hysteresis (30 s / 60 s) is exactly this mitigation; verify on a windy-day clip |
| Association picks the wrong recent transit when several boats enter together | Size compatibility scoring; ambiguous → review queue; never silently guess |
| Tenders and dinghies inside a berth trigger occupancy | Minimum size filter per berth |
