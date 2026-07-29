# Marina AI — Proof of Concept

Status: **defined, ready to build** · Date: 2026-07-29
Related: [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TECHNICAL.md`](./TECHNICAL.md)

---

## 1. What this PoC is for

**One question: can we read boat names off camera footage reliably enough to build the rest of the system on?**

Everything else in the plan — counting, berth occupancy, queue depth, recording — is well-understood computer vision that will work. Identification is the part that could fail for physical reasons (pixels on target, angle, glare, cursive fonts). Since the AIS fallback is ruled out, the whole system's value rests on this one capability.

So the PoC deliberately builds **the riskiest slice only**, end to end, and produces a **measured number** rather than an impression. Its output is a go/no-go decision plus, if the answer is "not yet", a specific diagnosis of *why* — which is almost always a camera-siting fix rather than a software one.

### Scope

Detect a boat → track it for as long as it's in view → select best shots → identify it with Claude → attach a stable identity (real name, or provisional `T-0001`) → hold that identity for the whole time the boat is tracked → report what happened.

### Explicitly out of scope

Berth occupancy · queue analytics · continuous recording · web UI · Postgres/Redis/MinIO · authentication · cross-session re-ID · multi-camera. Those are Phases 3–6 and are not what's at risk.

---

## 2. Success criteria

Measured against a hand-labelled ground-truth set (§5). Two of these are hard gates.

| # | Metric | Target | Gate |
|---|---|---|---|
| 1 | **Name precision** at confidence ≥ 0.85 — of the names we assert confidently, how many are correct | **≥ 0.95** | **HARD** |
| 2 | **Name recall** on human-legible names — of the boats whose name a person can read in the footage, how many does the system read | **≥ 0.60** | **HARD** |
| 3 | Detection recall — boats visibly transiting that get detected & tracked | ≥ 0.95 | soft |
| 4 | Track integrity — ID switches per boat | ≤ 0.05 (1 per 20) | soft |
| 5 | Attribute accuracy — vessel type and hull colour | ≥ 0.90 | soft |
| 6 | Cost per identified boat | < $0.05 | soft |
| 7 | Latency — track end → identity written | p95 < 20 s | soft |

**Why precision is the harder gate.** A missed name leaves a provisional code, which is honest and fixable — an operator names it in one click, and the design already handles it gracefully. A *wrong* name written confidently corrupts a berth record and destroys operator trust in the whole system; once staff stop believing the names, they stop using it. Recall can be bought later with better optics; precision lost to a bad prompt is a product failure.

### How to read a failure

| Result | Diagnosis | Action |
|---|---|---|
| High precision, low recall | Physics, not software. Not enough pixels on target, wrong angle, or glare. | Camera siting / optics. Re-shoot footage with a zoomed identification camera and re-run. **Do not tune the prompt.** |
| Low precision | Prompt or threshold problem — the model is guessing. | Strengthen the "null is correct" instruction, raise τ, recalibrate confidence bands. |
| Low detection recall | Detector problem — boats too small, or COCO `boat` class weak on this footage. | Increase `imgsz`, lower conf threshold, consider fine-tuning. |
| High ID-switch rate | Tracker problem — occlusion by pontoons/other vessels. | Raise `track_buffer`, try BoT-SORT. |

That table is the actual deliverable. The PoC exists to tell us which row we're in.

---

## 3. Design

Single Python process. SQLite, local filesystem, no services. Reuses the real `packages/vision` and `packages/identity` code paths where they exist so the PoC is not throwaway — it becomes the Phase 2 regression harness.

```
video file ──► FileSource ──► YOLO11 ──► ByteTrack
   (or short                                  │
    RTSP session)                             ▼
                                    ┌──────────────────────┐
                                    │ per-track state      │
                                    │  · best-shot heap    │
                                    │  · first/last seen   │
                                    │  · path history      │
                                    └──────────┬───────────┘
                        track ends, or quality threshold met
                                               ▼
                                    Claude (claude-opus-5)
                                    name · flag · reg · attributes
                                               │
                            ┌──────────────────┴──────────────────┐
                     conf ≥ 0.85                            conf < 0.85
                            ▼                                    ▼
                     named vessel                        provisional  T-0001
                            └──────────────────┬──────────────────┘
                                               ▼
                            identity attached to the track for its
                            entire lifetime — overlay, log, report
```

### "Track during that period"

Identity binds to the **track**, not to a single frame. Concretely:

- A track is created the moment a boat is first detected and lives until it leaves view (or `track_buffer` expires).
- Best shots accumulate across the *whole* track lifetime, not just the frame that triggered identification.
- Identification may run **more than once per track** — a first attempt when the boat has been tracked for 2 s, and a re-attempt whenever a later frame beats the best prior crop by ≥ 15%. The highest-confidence result wins. This is a miniature of the Phase 2b follow-up loop, so the PoC de-risks that too.
- Once resolved, the name is **back-propagated** across the entire track: the annotated video shows the name from the boat's first appearance, not from the moment it was read. The report likewise records `first_seen` as the true first detection.

That back-propagation is the point of the exercise — it demonstrates that identity attaches to a *vessel over time*, which is what the production design depends on.

---

## 4. Deliverables

```
poc/
├── run.py                 # CLI: process a clip end-to-end
├── evaluate.py            # compare output against ground truth
├── pipeline.py            # source → detect → track → bestshot → identify
├── identify.py            # Claude client + schema (mirrors packages/identity)
├── overlay.py             # annotated video renderer
├── report.py              # HTML report generator
└── fixtures/
    ├── clips/
    └── ground_truth.csv
```

Run:
```bash
uv run poc/run.py --source fixtures/clips/entrance_morning.mp4 \
                  --out runs/2026-08-05-morning
uv run poc/evaluate.py --run runs/2026-08-05-morning \
                       --truth fixtures/ground_truth.csv
```

Output of a run:
```
runs/2026-08-05-morning/
├── annotated.mp4          # boxes + track id + resolved name, back-propagated
├── vessels.json           # one record per tracked boat
├── crops/                 # every best-shot sent to the API
├── attempts.jsonl         # every Claude call: crops, raw response, tokens, latency
├── metrics.json           # the seven numbers from §2
└── report.html            # side-by-side: crop, prediction, confidence, truth
```

`vessels.json` record:
```json
{
  "track_ref": "clip1-0042",
  "identity": "SERENITY",
  "provisional_code": "T-0003",
  "resolved_by": "claude",
  "first_seen": "00:02:14.300",
  "last_seen":  "00:03:01.870",
  "duration_s": 47.6,
  "name": "SERENITY", "name_confidence": 0.93,
  "flag_country": "TR", "flag_confidence": 0.88,
  "registration_no": null, "registration_confidence": 0.0,
  "vessel_type": "motor_yacht", "hull_color": "white",
  "est_loa_m": 12.4,
  "attempts": 2,
  "best_crops": ["crops/clip1-0042-a.jpg", "crops/clip1-0042-b.jpg"],
  "tokens": { "input": 4820, "output": 210, "cached": 1900 },
  "cost_usd": 0.0089
}
```

`attempts.jsonl` matters as much as the result — it's the raw material for prompt iteration and the seed of the Phase 2 regression golden set.

---

## 5. Ground truth (do this first)

**The PoC is worthless without labels.** Before writing pipeline code, someone watches the footage and records, for every boat that transits:

| Column | Values | Notes |
|---|---|---|
| `clip`, `t_enter`, `t_exit` | timestamps | |
| `true_name` | text or blank | |
| `name_legibility` | `clear` / `partial` / `illegible` | **The critical column.** Recall is computed only over `clear`. |
| `true_flag`, `true_registration` | text or blank | |
| `true_type`, `true_hull_color` | | |
| `notes` | e.g. "name obscured by fender", "backlit" | |

`name_legibility` is what separates a software failure from a physics failure. If a human squinting at 4K stills can't read it, the model failing is not a defect and no amount of prompt work will fix it — that's a camera-placement finding.

**Footage requirements:** minimum ~40 boat transits across at least three lighting conditions (morning, midday glare, evening). A single clean clip will produce a flattering number that won't survive contact with a real marina.

---

## 6. Build plan (~8 working days)

| Day | Work | Done when |
|---|---|---|
| 1 | Repo skeleton, `uv` workspace, `FileSource`, YOLO11 wired up | boxes render on a clip |
| 2 | ByteTrack integration, per-track state, path history | stable IDs across a full transit |
| 3 | Best-shot heap + `quality_score`; dump crops to disk | crops are visibly the sharpest/largest frames |
| 4 | Claude client, `VesselID` schema, prompt v1, caching | one crop → structured JSON |
| 5 | Identity binding, provisional minting, re-attempt logic, back-propagation | annotated video shows names from first frame |
| 6 | `evaluate.py`, HTML report, metrics | the seven numbers print |
| 7 | Ground-truth labelling (parallel with 1–6 if someone else does it) | `ground_truth.csv` complete |
| 8 | Prompt + threshold iteration against the labelled set | metrics stabilise; go/no-go written up |

Day 8 is the real work. Days 1–3 are plumbing that will behave predictably; the prompt and threshold calibration is where the outcome is decided.

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Footage has too few legible names to measure anything | medium | Check legibility distribution on day 0, before building. If < 15 `clear` names, get better footage first — measuring on 5 samples tells us nothing. |
| COCO `boat` class underperforms on small craft / RIBs | medium | Raise `imgsz` to 1280+, lower conf threshold. Fine-tuning is a Phase 1 concern, not PoC. |
| Model over-confidently guesses names (precision gate fails) | medium | Explicit "null is correct" instruction + illegible-crop regression tests from day 4, not day 8. |
| Confidence scores are poorly calibrated | high | Expected. Bin predictions by confidence, compare to ground truth, and set τ empirically from the curve rather than using the 0.85 default. |
| Glare/backlight kills the midday clip entirely | medium | This is a finding, not a failure — report per-lighting-condition metrics separately. It directly informs camera siting and possibly polarising filters. |

---

## 8. What the PoC decides

| Outcome | Next step |
|---|---|
| Both hard gates pass | Proceed to Phase 0 → 1 → 2a as planned. Thresholds carry over calibrated. |
| Precision passes, recall < 0.60 | Proceed, but **camera siting becomes a blocking prerequisite for Phase 2a**. Re-run the PoC on footage from a properly sited identification camera before building the follow-up loop. |
| Precision fails | Stop and fix the prompt/threshold. Do not build on top of a system that invents names. |
| Detection or tracking fails | Fix in the PoC before Phase 1 — everything downstream inherits these. |

Whatever the result, the provisional-identity design means the system is **useful even at low recall**: boats get tracked, counted, berthed, and recorded under `T-0001` regardless. Recall determines how much manual naming operators do, not whether the product works. That's the reason the architecture was built that way, and it's why a partial PoC result is still a green light for the counting and occupancy phases.
