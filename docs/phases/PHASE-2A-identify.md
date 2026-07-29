# Phase 2a — Identify + provisional identity

**Goal:** every boat that enters gets an identity immediately — its real name if readable, otherwise a provisional code — and that identity is a full-class record from the moment it's created.

**Delivers:** requirements #2 (which boat entered) and #6 (name, flag, serial, time). Implements the "unify unidentified boats under a temp name" requirement.
**Estimate:** ~2 weeks · **Depends on:** Phase 1, PoC (prompt + calibrated thresholds)

---

## In scope

- Best-shot selection wired into live tracks
- `identifier` service: Claude vision calls with cached system prompt
- Provisional code minting (`T-0142`) and composed display names
- Vessel registry with `provisional | candidate | confirmed` lifecycle
- Review queue UI: crop, prediction, confidence, one-click confirm / correct / reject
- Vessel detail page with timeline
- Transit log enriched with vessel identity
- Cost and read-rate metrics

## Out of scope

Re-ID matching across sightings, the follow-up backoff loop, merges — all Phase 2b. Here, identification happens **once per transit** at the gate; a failure leaves a provisional vessel that an operator can name manually.

---

## Deliverables

1. A gate transit produces a vessel record within seconds — named or provisional, never absent.
2. `transits.vessel_id` is populated on every row (`NOT NULL` constraint enforced).
3. Review queue lists low-confidence identifications with the crop that produced them.
4. Operators can search one box and match both `SERENITY` and `T-0142`.
5. Vessel detail page shows the boat's transits with playable evidence frames.

---

## Tasks

- [ ] `bestshot.py`: bounded top-N heap per track, `quality_score` from TECHNICAL §6.4
- [ ] Upload best shots to object storage; publish `stream:identify_requests`
- [ ] `identity/prompts.py`: system prompt (stable, cached) + user instruction, ported from the PoC
- [ ] `identity/claude.py`: `messages.parse` with `VesselID` schema, `effort` from settings, `stop_reason == "refusal"` guard, retry/backoff
- [ ] `identity/provisional.py`: sequence-backed code minting, `display_name()` composition
- [ ] Vessel resolution: confidence ≥ τ → `candidate` with proposed name; below → `provisional`
- [ ] Write `identifications` rows for **every** attempt, including failures and null results
- [ ] `NOT NULL` migration on `transits.vessel_id`
- [ ] API: `/vessels`, `/vessels/{id}`, `/vessels/{id}/timeline`, `/vessels/{id}/confirm`, `/vessels/{id}/identify`, `/review-queue`
- [ ] Full-text search across name + provisional code (GIN index)
- [ ] Review queue UI with keyboard-driven confirm/correct
- [ ] Vessel detail page: attributes, crops, timeline, identification attempt history
- [ ] Metrics: `identification_attempts_total{result}`, `identification_tokens_total`, `vessels_provisional_current`
- [ ] Regression suite: golden crop set, asserting read rate **and false-name rate**

---

## Acceptance criteria

- [ ] **No transit lacks a vessel.** Enforced by the DB constraint and proven by a test that identification failure still yields a usable provisional record.
- [ ] **Name precision ≥ 0.95** at confidence ≥ τ on the labelled set. A confidently wrong name is a release blocker.
- [ ] Provisional vessels are fully functional: they appear in transit logs, search results, reports, and the timeline exactly like named vessels.
- [ ] Provisional code appears on the record permanently after naming (`SERENITY (was T-0142)`).
- [ ] Attributes (type, hull colour, size estimate) are populated even when the name is null — verified on deliberately illegible crops.
- [ ] Operator confirming a name writes an `identifications` row with `source='manual'`; **the original machine guess is preserved, not overwritten.**
- [ ] Prompt-change regression: a prompt edit that raises recall but introduces a false name **fails CI**.
- [ ] Cost per identification measured and reported with real footage.

---

## Dependencies

- PoC complete with calibrated τ and a validated prompt.
- Identification camera sited per the PoC finding — if PoC recall was below target, **this is a blocking prerequisite**, not a parallel workstream.

---

## Risks

| Risk | Mitigation |
|---|---|
| Confidence poorly calibrated → τ wrong for live data | Re-bin against live results in week 2 and adjust; τ is config, not code |
| Model invents plausible names | "Null is correct" prompt instruction + illegible-crop tests in CI from day one |
| Gate crops are all too poor to read | Expected if the PoC said so — this is precisely why provisional identity exists; the system stays useful and Phase 2b's berth-camera follow-up is the real fix |
| Operators ignore the review queue and it grows unbounded | `vessels_provisional_current` gauge + an ageing alert; queue sorted by dwell so old items surface |
| Prompt caching silently breaks, costs jump | Assert `cache_read_input_tokens > 0` in an integration test — a per-request value leaking into the system prompt is the usual cause |
