# Marina AI — Test Footage

Where to get video for development, and what each kind of footage can and cannot tell you.

Status: **guide** · Date: 2026-07-29

---

## 1. The distinction that matters

There are two completely different jobs footage does here, and confusing them wastes weeks.

| Job | Question it answers | What footage works |
|---|---|---|
| **Build the pipeline** | Does detection → tracking → gate crossing → best-shot → identification run correctly end to end? | Synthetic clips, stock video, public datasets, any marina webcam |
| **Answer the PoC gate** | Can *your* cameras at *your* marina read boat names? | **Only footage from your actual cameras at your actual site** |

**No amount of stock footage answers the second question.** The PoC measures pixels-per-metre on transoms at your pass line, under your glare conditions, at your mounting angle. Footage from a different marina with a different camera measures that other marina's camera. A great result on someone else's 4K harbour footage tells you nothing about whether your installation will work.

So: use everything in §2 and §3 to build, and understand that [`POC.md`](./POC.md)'s go/no-go still requires §4.

---

## 2. Synthetic clips — available immediately

`scripts/generate_synthetic_clips.py` renders marina footage with **known ground truth**, because you specify the vessel names it draws.

```bash
uv run python scripts/generate_synthetic_clips.py --out tests/fixtures/clips
```

Produces a set of clips plus a matching `ground_truth.csv`.

### What it's genuinely good for

- **CI fixtures.** Deterministic, small, committable, no licensing questions.
- **Building the pipeline before any camera exists.** Detection, tracking, gate-crossing logic, best-shot selection, and the identification round-trip can all be developed against it.
- **Validating the measurement harness itself.** This is the underrated use. The generator sweeps PPM from 400 down to 60 — so you can confirm your evaluation script correctly reports high accuracy at 400 PPM and correctly reports failure at 60. If your harness reports 90% accuracy on a 60-PPM clip where the text is physically unreadable, **the harness is broken**, and you want to know that before trusting it on real footage.
- **Testing the specific failure modes** the phase docs call out: two boats abreast, a boat idling on the gate line, a boat manoeuvring through a neighbouring berth polygon. Each is a generator flag.

### What it cannot do

Synthetic transoms are clean rendered text on flat surfaces. Real ones are curved, chromed, scripted, salt-crusted, fender-obscured, and backlit. **A model that reads synthetic names at 95% tells you nothing about real-world recall.** Use it to prove the plumbing works, never to set τ or to claim a PoC result.

---

## 3. Real footage for development

### 3.1 Public maritime datasets

| Dataset | Content | Useful for |
|---|---|---|
| **Singapore Maritime Dataset (SMD)** | On-shore and on-board vessel videos, annotated | Detection/tracking evaluation on real vessels |
| **SeaShips** | ~31k images from coastal surveillance, 6 ship types | Detector fine-tuning; images not video |
| **MODD / MODD2** | Marine obstacle detection, USV-mounted | Small-craft detection |
| **ABOships** | Ship detection, varied conditions | Detector evaluation |
| **Roboflow Universe** | Many community boat/ship sets, some video | Quick fine-tuning experiments |

These are mostly shot from ships or shore at long range — good for detection and tracking, **almost useless for name reading**, because none were captured with OCR in mind. Check each licence before use.

### 3.2 Marina and harbour webcams

Many marinas run public webcams — on their own sites or as YouTube livestreams — often at 1080p, covering entrances. These are the closest freely-available analogue to a real gate camera, and give genuine wake, chop, traffic patterns, and lighting.

**Candidate streams noted for evaluation:**

| Source | URL |
|---|---|
| YouTube livestream | `https://www.youtube.com/watch?v=WYgjhPHIw1k` |
| YouTube livestream | `https://www.youtube.com/watch?v=-p1Xnt9n0yg` |

These are recorded here as leads to assess, not as a committed dependency. Before relying on either, check: is the camera fixed or does it pan? Is the resolution genuinely 1080p+ or upscaled? Does it look across a channel where vessels pass, or down at a static basin? Are transoms ever visible at a readable size?

Standard tooling reads these (`yt-dlp` resolves the manifest, `ffmpeg` captures a segment). **No capture script is provided in this repository** — deliberately, for the reasons below.

Three limits to keep in mind:

- **Terms of service.** Capturing from YouTube is contrary to their ToS. Widely done for local development; a judgement call for whoever runs it, and not something to build into the product.
- **Personal data.** Public webcam footage contains identifiable people, so it is personal data under KVKK/GDPR. Use it locally, delete it after, and do not accumulate an archive. `.gitignore` blocks `*.mp4` so it cannot be committed by accident.
- **It cannot answer the PoC gate.** A webcam measures *that* marina's camera, angle, and optics. Useful for detection, tracking, and gate-crossing development; useless for deciding whether your identification camera will read names. See §4.

### 3.3 Stock video

Pexels, Pixabay, Videvo, and Coverr have free marina, harbour, and yacht clips. Typically short, often drone or handheld rather than fixed-camera, but usable for detector smoke tests. Some are shot close enough to have legible names — those few are worth keeping as an early sanity check on the identification path.

### 3.4 Phone footage from any marina

Genuinely underrated, and often the fastest option. Twenty minutes standing at any marina entrance with a phone on a tripod gives real boats, real wake, real glare, and real transoms. A modern phone at 4K exceeds many fixed cameras in resolution. It won't match your final camera geometry, but it is real vessels with real nameplates — enough to develop and roughly calibrate the identification prompt before installation.

---

## 4. The footage the PoC actually requires

From [`POC.md §5`](./POC.md) and [`CAMERA-SITING.md §5.3`](./CAMERA-SITING.md):

- **≥ 40 vessel transits**
- **Three lighting conditions** — morning, midday glare, evening
- **From the actual identification camera, in its final mounted position**
- **Hand-labelled ground truth**, with the `name_legibility` column (`clear` / `partial` / `illegible`)

That last column is what makes the result interpretable: recall is computed only over `clear` names, so a low number means a camera problem rather than a software one. Without it you get a percentage nobody can act on.

**If the camera isn't installed yet**, capture with a temporary rig at the intended position, height, and angle — a tripod and any 4K camera. The point is to validate the *geometry* before committing to permanent mounting. This is far cheaper than discovering after installation that the mount is 4 m too high.

Twenty minutes of proper footage from the right position beats forty hours of footage from the wrong one.

---

## 5. Repository conventions

```
tests/fixtures/
├── clips/              # synthetic, committed (small, deterministic)
├── ground_truth.csv    # labels for synthetic clips
└── golden_crops/       # committed crops for the prompt regression suite
                        #   including the `illegible` set that must return null

poc/fixtures/
├── clips/              # real footage — GITIGNORED, never committed
└── ground_truth.csv    # hand labels for real footage — commit this
```

**Never commit real footage.** It contains identifiable people, it's large, and it may be someone else's copyright. `.gitignore` already blocks `*.mp4`, `*.jpg`, and `poc/fixtures/clips/`.

**Do commit the labels.** `ground_truth.csv` is small, contains no imagery, and is the most valuable artefact of the whole labelling exercise — it's what every future regression run measures against.

The `golden_crops/` set is the exception to "no images": a small number of deliberately chosen crops, including unreadable ones, that the prompt regression suite asserts against. Review them for identifiable faces before committing, and crop tightly to the hull.
