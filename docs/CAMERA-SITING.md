# Marina AI — Camera Siting Specification

How to place and specify cameras so the system can actually do its job.

Status: **specification** · Date: 2026-07-29

---

## 1. Why this document is load-bearing

With AIS ruled out ([ADR-007](./TECH-STACK.md#adr-007--no-ais-receiver)), **every** piece of vessel identity comes from pixels. No prompt engineering, model upgrade, or amount of code can recover information that was never captured. If a transom crosses the frame at 40 pixels wide, the name is not in the image, and nothing downstream can invent it.

This makes camera siting the single highest-leverage decision in the project — and it is a decision made once, physically, usually by someone who is not on the software team. Getting it wrong is expensive to fix (re-mounting, re-cabling, sometimes re-buying) and the cost is discovered late.

So: **do the arithmetic below before ordering hardware, and validate on site before Phase 2a begins.**

---

## 2. The two numbers that decide everything

### 2.1 Pixels per metre (PPM)

```
PPM = horizontal_resolution ÷ scene_width_at_target
```

Boat name lettering is typically **80–150 mm** tall. Reliable OCR — human or machine — needs roughly **25–30 pixels of character height**.

At 100 mm characters, 25 px means **250 PPM minimum**. Allow headroom for angle and glare: **400 PPM is the comfortable target.**

| Task | PPM needed | Why |
|---|---|---|
| Detect a boat exists | 20–30 | Bounding box only |
| Track it reliably | 40–60 | Stable association between frames |
| Classify type / colour | 60–100 | Coarse shape and hue |
| **Read a name** | **250 min / 400 good** | Character height ≥ 25–30 px |
| Read a small sail number | 400+ | Smaller characters |

The gap between "track it" (50 PPM) and "read its name" (400 PPM) is **8× in linear resolution**. This is why one camera cannot do both jobs well, and why the design calls for a separate identification camera.

### 2.2 Required field of view

At 4K horizontal (3840 px):

| Target PPM | Scene width the frame must cover |
|---|---|
| 250 | 15.4 m |
| 400 | 9.6 m |

Required horizontal angle of view, and the approximate focal length on a 1/2.8″ sensor (5.6 mm wide):

**For 250 PPM (15.4 m scene width):**

| Distance to vessel | Horizontal AFOV | ≈ focal length |
|---|---|---|
| 20 m | 42° | 7 mm |
| 30 m | 29° | 11 mm |
| 40 m | 22° | 15 mm |
| 50 m | 17° | 18 mm |
| 80 m | 11° | 29 mm |

**For 400 PPM (9.6 m scene width):**

| Distance | Horizontal AFOV | ≈ focal length |
|---|---|---|
| 20 m | 27° | 11 mm |
| 30 m | 18° | 17 mm |
| 40 m | 14° | 23 mm |
| 50 m | 11° | 29 mm |

Sensor sizes vary — treat focal lengths as indicative and confirm against the specific camera's FOV table. **Work from AFOV, not focal length.**

The practical consequence: at a 30 m channel, an identification camera needs roughly a **17 mm lens covering under 10 m of scene width**. That is a narrow view — it sees a slice of the channel, not the whole thing. Which is exactly right: its job is to read transoms, and a wide camera does the counting.

### 2.3 The constraint people forget: shutter speed

A moving boat blurs. Blur in pixels is:

```
blur_px = speed(m/s) × exposure(s) × PPM
```

At a 3-knot harbour speed (1.54 m/s) and 250 PPM, keeping blur under 1 px needs:

```
t = 1 ÷ (1.54 × 250) ≈ 2.6 ms  →  1/400 s
```

| Speed | PPM | Max exposure for ≤1 px blur |
|---|---|---|
| 3 kn (1.54 m/s) | 250 | 1/400 s |
| 3 kn | 400 | 1/640 s |
| 5 kn (2.57 m/s) | 250 | 1/640 s |
| 5 kn | 400 | 1/1000 s |

**Specify a minimum shutter of 1/500 s on the identification camera, 1/1000 s preferred**, and configure the camera to prioritise shutter over gain.

This is the binding constraint at dawn, dusk, and night. A fast shutter in low light means high gain, which means noise, which destroys OCR just as effectively as blur. Consequences to accept:

- Choose a **large aperture** (f/1.4–f/1.6) and a **large sensor** (1/1.8″ or larger) on the identification camera. This is where the hardware budget should go.
- **Expect night identification to be poor.** IR illumination is near-useless for reading names: vinyl and painted lettering has low IR contrast, and IR-cut removal loses the colour needed for flags.
- **This is survivable by design.** A boat entering at 23:00 gets a provisional identity, moors, and the follow-up loop reads its name from the berth camera at 09:00 the next morning. The night gap is exactly why the follow-up loop exists — it is not a workaround, it is the intended path.

---

## 3. Camera roles

### 3.1 Gate — wide (counting)

| Property | Specification |
|---|---|
| Purpose | Detect and count every vessel entering/leaving; establish tracks |
| Coverage | Full channel width plus margin on both sides |
| PPM at channel centre | ≥ 50 |
| Resolution | 4 K preferred, 1080p acceptable on a narrow channel |
| Frame rate | ≥ 15 fps native (system samples at 6) |
| Shutter | ≥ 1/250 s |
| Mount height | 4–7 m — high enough to avoid occlusion between passing vessels |
| Aim | Perpendicular to the traffic axis, entire channel in frame |

Occlusion is the failure mode here: two boats passing abreast counted as one. Height is the mitigation. Verify by watching real traffic, not an empty channel.

### 3.2 Gate — identity (name reading) ⭐

**The most important camera in the system.**

| Property | Specification |
|---|---|
| Purpose | Read transom names, registrations, ensigns |
| PPM at the pass line | **≥ 250, target 400** |
| Resolution | 4 K minimum (8 K worth considering on a wide channel) |
| Sensor | 1/1.8″ or larger |
| Aperture | f/1.6 or faster |
| Shutter | ≥ 1/500 s, prioritised over gain |
| Frame rate | ≥ 25 fps — more frames means more chances at a clean one |
| Lens | Narrow, per §2.2. Varifocal so it can be tuned on site |
| Mount height | **2.5–4 m** — deliberately low |
| Aim | As close to perpendicular to the hull as the site allows |
| Filter | **Circular polariser strongly recommended** |
| Focus | Fixed, pre-focused on the pass line. Disable autofocus. |

**Why the low mount.** A transom is a near-vertical surface. Viewing it from 8 m up means looking at the deck and the top edge of the lettering at a steep foreshortening angle — the characters compress vertically and become unreadable. Mount as low as vandalism, spray, and wake allow. **This is the most common siting mistake**: cameras get mounted high out of habit (better for general surveillance) and the transom view is lost.

**Why perpendicular.** Text readability falls off sharply with viewing angle. Beyond ~45° off-perpendicular, effective horizontal resolution is roughly halved and characters begin to overlap. Aim across the channel, not along it.

**Why a polariser.** It cuts specular reflection off the water and off glossy gelcoat — the two things that most often wash out a transom. It costs 1–1.5 stops of light, which trades against the shutter-speed budget, so evaluate it on site rather than assuming.

**Aim at where sterns are, not where boats are.** A boat entering is moving away, so its transom faces back toward the entrance. Position the camera to see boats *after* they pass, not as they approach.

**PTZ?** A PTZ that zooms to a preset on detection is attractive, and worth it if one camera must cover several channels. Two cautions: a moving PTZ produces useless frames for tracking, so it must not be the counting camera; and preset accuracy drifts, requiring periodic recalibration. **Default recommendation is a fixed narrow-FOV camera** — simpler, cheaper, always aimed correctly.

### 3.3 Berth cameras

| Property | Specification |
|---|---|
| Purpose | Occupancy detection; **and the primary surface for the follow-up identification loop** |
| PPM at the far berth | ≥ 100 (occupancy) / ≥ 250 on at least part of the coverage (identification) |
| Resolution | 4 K |
| Coverage | Whole pontoon, both sides where possible |
| Mount height | 5–8 m — needs to see berth boundaries clearly for polygon separation |
| Aim | Along the pontoon at a slight downward angle |

**Do not treat these as occupancy-only cameras.** In the final system they will produce *more* successful identifications than the gate camera does — a moored boat is stationary, available for hours in every light condition, and can be photographed repeatedly. A berth camera that resolves 250 PPM on moored transoms turns the follow-up loop from a fallback into the main identification path.

Adjacent-berth separation is the other constraint: if two berths cannot be visually distinguished from the mounting position, no amount of polygon tuning recovers it. Check sightlines per berth at survey time.

### 3.4 Bay / queue camera

| Property | Specification |
|---|---|
| Purpose | Count and time vessels waiting at the mouth or anchorage |
| PPM at the far edge of the zone | ≥ 25 |
| Resolution | 4 K |
| Coverage | The whole approach/anchorage area |
| Mount height | As high as available — this is a genuine overview camera |

Small craft at the far edge of a wide bay view are the detection limit. Measure recall specifically on this camera; a second camera or a tighter zone boundary may be needed.

---

## 4. Environment

### 4.1 Sun and glare

In Türkiye (northern hemisphere) the sun tracks through the southern sky.

- **Prefer north-facing cameras.** A south-facing camera has the sun in frame for part of every clear day, causing flare and severe backlighting of any vessel between camera and sun.
- **Worst case is a low sun on the water toward the camera** — the specular path creates a band of blown-out highlights across the frame. Common at sunrise and sunset, and precisely when a lot of traffic moves.
- Mitigations, in order of effectiveness: re-aim to face north → circular polariser → sun shroud/hood → WDR (helps least; it compresses dynamic range but cannot recover clipped highlights).
- **Test at the worst hour, not a convenient one.** A site survey at 11:00 on an overcast day proves nothing about 18:30 in July.

### 4.2 Marine environment

| Factor | Requirement |
|---|---|
| Corrosion | IP66/IP67 minimum; 316 stainless or marine-grade aluminium housings. Standard steel brackets will fail within a season. |
| Salt spray on the lens | The dominant maintenance item. Schedule cleaning; site cameras where spray is least. |
| Vibration | Pontoon-mounted cameras move with the pontoon. Prefer fixed structures; if not possible, expect degraded tracking and accept it in the zone tuning. |
| Cabling | Outdoor-rated PoE, UV-resistant. Isolated camera VLAN, no internet exposure. |
| Lightning | Surge protection on long outdoor runs. |
| Power | PoE+ where IR illuminators or heaters are fitted. |

### 4.3 Night

Assume degraded night identification and design around it rather than fighting it:

- White light on the identification camera (where permitted and not a hazard to navigation) preserves colour and gives far better OCR than IR.
- IR is fine for detection, tracking, counting, and occupancy — all of which continue working at night.
- Names read at night, if at all, will have low confidence, which correctly routes them to provisional + follow-up.
- Boats arriving at night are moored by morning. **The follow-up loop covers the night gap by design.**

---

## 5. Commissioning: validate before building on it

Do this before Phase 2a starts. It takes an afternoon and prevents weeks of wasted work.

### 5.1 Measure actual PPM

1. Take a test target of known width — a 1 m calibration board, or a measuring tape held up — to the vessel pass line.
2. Capture a still.
3. Count the pixels the 1 m target spans. **That is your true PPM**, not the number from a spec sheet or a lens calculator.
4. Compare against §2.1. Below 250 at the pass line means names will not be readable, and no software change alters that.

### 5.2 Verify readability directly

Print test text at realistic size (100 mm characters) on a board, photograph it at the pass line, and try to read it in the still. If a person cannot read it on a monitor, the model will not read it either. This is the cheapest, most decisive test available, and it takes ten minutes.

### 5.3 Capture the PoC footage properly

Record **at least 40 vessel transits across three lighting conditions** — morning, midday glare, and evening. A single clean clip produces a flattering PoC number that will not survive the real marina. See [`POC.md §5`](./POC.md).

### 5.4 Checklist

- [ ] Measured PPM at the pass line ≥ 250 (identification camera)
- [ ] Printed 100 mm test text is human-readable from a captured still
- [ ] Shutter ≥ 1/500 s confirmed in camera settings, gain capped
- [ ] Autofocus **disabled**, focus fixed on the pass line
- [ ] No sun in frame at any hour — verified across a full day, not a snapshot
- [ ] Polariser evaluated on site (kept or rejected with a reason recorded)
- [ ] Adjacent berths visually separable from the mounting position
- [ ] Two vessels passing abreast do not occlude one another on the wide gate camera
- [ ] Housings and brackets are marine grade
- [ ] Cameras on an isolated VLAN with no internet route
- [ ] Time synchronised via NTP across all cameras — **timestamps drive transit-to-berth association, so clock drift silently corrupts it**
- [ ] ≥ 40 transits of PoC footage captured across three lighting conditions

---

## 6. If the site cannot meet the specification

Some marinas simply won't allow a good identification view — the channel is too wide, there is nowhere to mount low, or the only sightline faces south. This is a real outcome and it should be reported honestly rather than absorbed as a software problem.

Options, roughly in order of preference:

1. **Move the camera closer to the traffic** — a pole or bracket on the breakwater, even a few metres nearer, changes PPM linearly.
2. **Higher resolution** — 8 K doubles linear PPM for the same view. Costs storage and inference, but it is a direct trade.
3. **Two identification cameras** covering opposite sides of the channel, so at least one gets a favourable angle on each vessel.
4. **Move identification to the berths entirely** — accept that the gate only counts, and let the follow-up loop do all identification from moored vessels. **This is a perfectly viable configuration**, and given the constraints above it may be the better design for many sites.
5. **Reconsider AIS** ([ADR-007](./TECH-STACK.md#adr-007--no-ais-receiver)) — noted for completeness because the decision to exclude it was made before these physical constraints were measured, and a site that cannot support optical identification is exactly the situation that would change the calculus.

Option 4 deserves emphasis: the architecture already treats gate identification as best-effort and berth identification as the reliable path. A site with a poor gate view is not a failed deployment — it just leans harder on a mechanism that was built to carry it.
