# Phase 2b — Re-identification & follow-up

**Goal:** turn isolated sightings into vessel histories. Keep trying to name provisional boats from berth cameras, recognise boats we've seen before, and unify identities safely when a name finally resolves.

**Delivers:** the "follow up until identified, and keep tracking after" requirement. This is what makes the registry compound in value over a season.
**Estimate:** ~2–3 weeks · **Depends on:** Phase 2a, Phase 3 helps (berth cameras) but is not required

---

## In scope

- DINOv2 embeddings on every stored sighting, indexed in pgvector
- Three-stage re-ID matcher: attribute gate → embedding similarity → Claude pairwise adjudication
- Follow-up scheduler: backoff, opportunistic quality trigger, light diversity
- Promotion (`provisional → candidate → confirmed`) and merge
- Reversible merges with full audit
- Merge-suggestion review queue
- Vessel timeline showing visits across time

## Out of scope

Fine-tuning the embedding model (later), cross-marina identity (multi-tenant concern).

---

## Deliverables

1. A boat that leaves and returns is recognised and attached to its existing record.
2. Provisional boats are re-attempted automatically from berth cameras until named or budget-exhausted.
3. When a name resolves and matches an existing confirmed vessel, histories merge and the boat's record extends backwards through earlier anonymous visits.
4. Every merge is logged, explainable, and reversible in one click.

---

## Tasks

- [ ] `vision/embedding.py`: DINOv2 ViT-B/14, 768-dim, batched; write to `vessel_sightings.embedding`
- [ ] pgvector HNSW index; backfill embeddings for existing sightings
- [ ] `identity/matcher.py` stage 1: SQL attribute gate (type, ±20% LOA, hull-colour family, 180-day recency)
- [ ] Stage 2: cosine top-k over candidates
- [ ] Stage 3: `claude_compare(crop_a, crop_b)` → `{same_vessel, confidence, evidence}` for the 0.75–0.90 band
- [ ] `identity/merge.py`: transactional merge, row-id manifest captured into `vessel_merges.evidence`, transitive `merged_into_id` resolution (depth cap 5)
- [ ] Revert operation restoring `vessel_id` from the manifest
- [ ] Follow-up scheduler: `BACKOFF` table, attempt budget, exhaustion → operator flag
- [ ] Opportunistic trigger on ≥ 15% `quality_score` improvement
- [ ] Light-diversity preference across dayparts
- [ ] Name-match-on-resolve: fuzzy name lookup against confirmed vessels, attribute compatibility check, then merge
- [ ] Merge-suggestion review queue: two crops side by side, similarity, Claude's evidence, accept/reject
- [ ] Vessel timeline UI across visits, showing which visit produced the identification
- [ ] Metrics: `reid_merges_total{method}`, `reid_reverts_total`, follow-up attempts and outcomes

---

## Acceptance criteria

- [ ] **False-merge rate ≤ 1%** on the labelled set. This is the phase's defining metric.
- [ ] **Revert rate tracked and alerted** — a rising revert rate is the honest signal that the matcher has drifted, and it must be visible without anyone running a query.
- [ ] Under uncertainty the matcher creates a **new** vessel rather than merging. Verified by a test with two visually similar but distinct boats: the expected outcome is two records, not one.
- [ ] Auto-merge fires only when embedding similarity ≥ 0.90 **and** the attribute gate passed.
- [ ] Merge is atomic: an induced mid-merge failure leaves no partially re-pointed rows.
- [ ] Revert fully restores prior state, verified by row-level comparison.
- [ ] Follow-up honours the attempt budget — a vessel cannot burn unbounded API calls.
- [ ] A better berth-camera crop triggers an immediate attempt, bypassing backoff.
- [ ] Merged vessels remain resolvable: a URL or report referencing a merged id lands on the surviving record.
- [ ] **Measured uplift:** identification rate after follow-up is materially higher than the gate-only rate from Phase 2a. If it isn't, the follow-up loop isn't earning its cost and the design needs revisiting.

---

## Dependencies

- Berth cameras with usable views of moored boats — the follow-up loop's whole premise.
- Labelled set extended with repeat visits (same boat, different days) to measure re-ID at all.

---

## Risks

| Risk | Mitigation |
|---|---|
| **False merges corrupt histories silently** | Conservative thresholds, Claude adjudication in the ambiguous band, revert-rate alerting, and a code-review rule that lowering `reid_auto_merge_similarity` requires labelled evidence |
| Many similar white motor yachts defeat embedding similarity | Attribute gate first; distinctive-marks field; accept duplicates over bad merges by design |
| DINOv2 generic embeddings underperform on boats | Evaluate against the labelled set before trusting it; the interface is swappable, and the review queue generates the labels for a fine-tune later |
| Follow-up loop costs more than expected | Attempt budget, opportunistic trigger reduces wasted low-quality calls, token metrics tracked live |
| Embedding backfill locks tables | Batched background job with throttling |
