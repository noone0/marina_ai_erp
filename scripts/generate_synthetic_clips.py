#!/usr/bin/env python3
"""Generate synthetic marina footage with known ground truth.

Renders vessels crossing a camera view at controlled pixels-per-metre, speed,
lighting, and glare, with readable names on the transom. Because the names are
specified rather than observed, ground truth is exact.

Intended use
------------
- CI fixtures for the detection / tracking / gate-crossing pipeline
- Developing the identification round-trip before cameras exist
- Validating the evaluation harness: the PPM sweep produces clips where text is
  physically unreadable, and the harness MUST report failure on those. A harness
  that reports success at 60 PPM is broken.

Not intended for
----------------
Measuring real-world identification accuracy. Synthetic transoms are flat clean
text; real ones are curved, chromed, scripted, salt-crusted and backlit. See
docs/TEST-DATA.md.

Usage
-----
    python scripts/generate_synthetic_clips.py --out tests/fixtures/clips
    python scripts/generate_synthetic_clips.py --out /tmp/x --scenario ppm_sweep
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

KNOTS_TO_MPS = 0.514444
NAME_CHAR_HEIGHT_M = 0.10  # typical transom lettering ~100 mm

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(px: int) -> ImageFont.FreeTypeFont:
    """Load a bold TTF at the requested pixel height, or fall back."""
    size = max(6, int(px))
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------- #
# Specs
# --------------------------------------------------------------------------- #

@dataclass
class Vessel:
    name: str
    flag: str                      # ISO 3166-1 alpha-2
    registration: str | None
    vessel_type: str               # motor_yacht | sailing_yacht | rib | ...
    hull_color: tuple[int, int, int]   # BGR
    hull_color_name: str
    loa_m: float
    speed_kn: float = 3.0
    direction: str = "in"          # 'in' → left-to-right


@dataclass
class Scene:
    clip_id: str
    width: int = 3840
    height: int = 2160
    fps: int = 25
    ppm: float = 400.0             # pixels per metre at the pass line
    lighting: str = "day"          # day | dawn | midday_glare | dusk | night
    glare: bool = False
    shutter: float = 1.0 / 500     # seconds — drives motion blur
    vessels: list[Vessel] = field(default_factory=list)
    stagger_s: float = 3.0         # gap between successive vessels
    abreast: bool = False          # render two vessels side by side (occlusion test)
    idle_on_line: bool = False     # vessel hovers on the gate line (hysteresis test)


LIGHTING = {           # (brightness_scale, colour_shift_BGR, noise_sigma)
    "day":           (1.00, (0, 0, 0), 3.0),
    "dawn":          (0.55, (25, 5, -10), 8.0),
    "midday_glare":  (1.15, (0, 0, 0), 3.0),
    "dusk":          (0.45, (30, 0, -15), 11.0),
    "night":         (0.18, (35, 5, -20), 22.0),
}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_sea(scene: Scene, t: float) -> np.ndarray:
    """Sea background with a horizon, moving chop, and optional sun glare."""
    h, w = scene.height, scene.width
    img = np.zeros((h, w, 3), np.uint8)
    horizon = int(h * 0.28)

    # sky gradient
    for y in range(horizon):
        f = y / max(1, horizon)
        img[y, :] = (int(200 - 40 * f), int(170 - 25 * f), int(140 - 20 * f))

    # water gradient
    for y in range(horizon, h):
        f = (y - horizon) / max(1, h - horizon)
        img[y, :] = (int(120 - 45 * f), int(85 - 30 * f), int(55 - 20 * f))

    # chop: horizontal wave streaks, animated
    rng = np.random.default_rng(7)
    xs = np.arange(w)
    for i in range(90):
        y = horizon + int((h - horizon) * (i / 90.0) ** 1.6)
        amp = 2 + int(7 * (i / 90.0))
        phase = t * (0.6 + 0.05 * i) + i
        ripple = (np.sin(xs / (55.0 + i) + phase) * amp).astype(int)
        yy = np.clip(y + ripple, horizon, h - 1)
        shade = int(18 + 22 * rng.random())
        img[yy, xs] = np.clip(img[yy, xs].astype(int) + shade, 0, 255).astype(np.uint8)

    if scene.glare:
        # specular sun path — a blown-out band, the real-world killer
        overlay = img.copy()
        cx, cy = int(w * 0.62), horizon + int(h * 0.10)
        cv2.ellipse(overlay, (cx, cy), (int(w * 0.20), int(h * 0.16)),
                    0, 0, 360, (255, 255, 255), -1)
        cv2.GaussianBlur(overlay, (0, 0), w * 0.02, dst=overlay)
        img = cv2.addWeighted(img, 0.55, overlay, 0.45, 0)

    return img


def render_vessel(img: np.ndarray, v: Vessel, scene: Scene,
                  cx: float, cy: float) -> tuple[int, int, int, int]:
    """Draw a vessel in stern-quarter view. Returns its bounding box."""
    L = v.loa_m * scene.ppm            # length in px
    H = L * 0.30                       # freeboard + superstructure

    x0, y0 = int(cx - L / 2), int(cy - H / 2)
    x1, y1 = int(cx + L / 2), int(cy + H / 2)

    hull_h = H * 0.45
    hull_top = y1 - hull_h

    # hull: bow raked, stern square
    bow_x = x1 if v.direction == "in" else x0
    stern_x = x0 if v.direction == "in" else x1
    rake = (L * 0.12) * (1 if v.direction == "in" else -1)
    hull = np.array([
        [stern_x, hull_top], [bow_x - rake, hull_top],
        [bow_x, y1 - hull_h * 0.25], [bow_x - rake * 1.4, y1],
        [stern_x, y1],
    ], np.int32)
    cv2.fillPoly(img, [hull], v.hull_color)
    cv2.polylines(img, [hull], True, (40, 40, 40), max(1, int(L * 0.004)))

    # superstructure
    if v.vessel_type in ("motor_yacht", "catamaran", "fishing"):
        sx0 = int(min(stern_x, bow_x) + L * 0.22)
        sx1 = int(min(stern_x, bow_x) + L * 0.68)
        cv2.rectangle(img, (sx0, int(hull_top - H * 0.38)), (sx1, int(hull_top)),
                      (238, 238, 238), -1)
        cv2.rectangle(img, (sx0, int(hull_top - H * 0.38)), (sx1, int(hull_top)),
                      (60, 60, 60), max(1, int(L * 0.003)))
        # windows
        for k in range(4):
            wx = sx0 + int((sx1 - sx0) * (0.12 + 0.20 * k))
            cv2.rectangle(img, (wx, int(hull_top - H * 0.28)),
                          (wx + int((sx1 - sx0) * 0.13), int(hull_top - H * 0.12)),
                          (70, 55, 40), -1)
        # radar arch — a distinctive mark for re-ID testing
        ax = int(sx1 - (sx1 - sx0) * 0.18)
        cv2.line(img, (ax, int(hull_top - H * 0.38)), (ax, int(hull_top - H * 0.60)),
                 (50, 50, 50), max(2, int(L * 0.008)))
    elif v.vessel_type == "sailing_yacht":
        mx = int((x0 + x1) / 2)
        cv2.line(img, (mx, int(hull_top)), (mx, int(y0 - H * 1.1)),
                 (200, 200, 200), max(2, int(L * 0.006)))

    # transom face — where the name goes
    tw = L * 0.26
    tx0 = stern_x if v.direction == "in" else int(stern_x - tw)
    tx1 = int(tx0 + tw)
    ty0, ty1 = int(hull_top + hull_h * 0.10), int(y1 - hull_h * 0.12)
    cv2.rectangle(img, (tx0, ty0), (tx1, ty1),
                  tuple(int(c * 0.88) for c in v.hull_color), -1)

    draw_transom_text(img, v, scene, (tx0, ty0, tx1, ty1))
    draw_ensign(img, v, scene, stern_x, int(hull_top))

    # waterline wash
    cv2.ellipse(img, (int(cx), y1), (int(L * 0.55), int(H * 0.08)),
                0, 0, 180, (215, 215, 215), -1)

    return x0, int(y0 - H * 0.6), x1, y1


def draw_transom_text(img: np.ndarray, v: Vessel, scene: Scene,
                      box: tuple[int, int, int, int]) -> None:
    """Render the vessel name at physically-correct size for the scene PPM."""
    tx0, ty0, tx1, ty1 = box
    char_px = NAME_CHAR_HEIGHT_M * scene.ppm      # THE number that decides readability
    if char_px < 3:
        return

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    font = load_font(char_px)

    try:
        l, t, r, b = d.textbbox((0, 0), v.name, font=font)
        tw, th = r - l, b - t
    except Exception:
        tw, th = len(v.name) * char_px * 0.6, char_px

    cx = tx0 + (tx1 - tx0) / 2 - tw / 2
    cy = ty0 + (ty1 - ty0) * 0.30 - th / 2
    d.text((cx, cy), v.name, font=font, fill=(250, 250, 250))

    if v.registration:
        small = load_font(char_px * 0.5)
        try:
            l, t, r, b = d.textbbox((0, 0), v.registration, font=small)
            rw = r - l
        except Exception:
            rw = len(v.registration) * char_px * 0.3
        d.text((tx0 + (tx1 - tx0) / 2 - rw / 2, cy + th * 1.35),
               v.registration, font=small, fill=(235, 235, 235))

    img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


FLAGS = {  # simplified ensigns, BGR bands
    "TR": [(60, 40, 200)],
    "GB": [(120, 40, 30)],
    "GR": [(200, 120, 40), (255, 255, 255)],
    "IT": [(80, 150, 60), (255, 255, 255), (60, 60, 200)],
    "FR": [(150, 60, 40), (255, 255, 255), (60, 60, 200)],
    "DE": [(40, 40, 40), (60, 60, 200), (60, 190, 230)],
}


def draw_ensign(img: np.ndarray, v: Vessel, scene: Scene, sx: int, sy: int) -> None:
    fw = max(4, int(0.55 * scene.ppm))
    fh = max(3, int(fw * 0.62))
    fx = sx - fw if v.direction == "in" else sx
    fy = sy - int(fh * 2.0)
    bands = FLAGS.get(v.flag, [(150, 150, 150)])
    bh = max(1, fh // len(bands))
    for i, c in enumerate(bands):
        cv2.rectangle(img, (fx, fy + i * bh), (fx + fw, fy + (i + 1) * bh), c, -1)
    if v.flag == "TR":  # crescent hint
        cv2.circle(img, (fx + fw // 2, fy + fh // 2), max(1, fh // 5),
                   (255, 255, 255), max(1, fh // 12))


def apply_conditions(img: np.ndarray, scene: Scene, blur_px: float) -> np.ndarray:
    """Motion blur, lighting, and sensor noise — in capture order."""
    if blur_px >= 1.0:
        k = int(blur_px) | 1
        kern = np.zeros((k, k), np.float32)
        kern[k // 2, :] = 1.0 / k          # horizontal, matching travel
        img = cv2.filter2D(img, -1, kern)

    scale, shift, sigma = LIGHTING[scene.lighting]
    img = np.clip(img.astype(np.float32) * scale + np.array(shift), 0, 255)

    if sigma > 0:
        img += np.random.default_rng().normal(0, sigma, img.shape)

    return np.clip(img, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Clip generation
# --------------------------------------------------------------------------- #

# Codec availability varies by platform and OpenCV build. opencv-python-headless
# on macOS has no FFMPEG backend and falls back to AVFoundation, where 'mp4v'
# fails but 'avc1' works; Linux builds with FFMPEG are the reverse in some
# versions. Negotiate rather than assume.
CODECS = [("avc1", ".mp4"), ("mp4v", ".mp4"), ("MJPG", ".avi"), ("XVID", ".avi")]


def open_writer(base: Path, fps: int, size: tuple[int, int]):
    """Return (writer, path) using the first codec this build actually supports."""
    tried = []
    for fourcc, ext in CODECS:
        path = base.with_suffix(ext)
        w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, size)
        if w.isOpened():
            return w, path
        w.release()
        path.unlink(missing_ok=True)
        tried.append(fourcc)
    raise RuntimeError(
        f"no usable video codec (tried {', '.join(tried)}). "
        "Install ffmpeg, or `pip install opencv-python` instead of the headless build."
    )


def generate_clip(scene: Scene, out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    writer, path = open_writer(out_dir / scene.clip_id, scene.fps,
                               (scene.width, scene.height))

    gate_x = scene.width * 0.5
    cy = scene.height * 0.62
    truth: list[dict] = []

    # schedule each vessel
    plans = []
    for i, v in enumerate(scene.vessels):
        speed_px = v.speed_kn * KNOTS_TO_MPS * scene.ppm
        span = scene.width + v.loa_m * scene.ppm * 2
        dur = span / max(1.0, speed_px)
        start = 0.0 if scene.abreast else i * scene.stagger_s
        plans.append({"v": v, "speed_px": speed_px, "dur": dur, "start": start,
                      "lane": cy + (i - (len(scene.vessels) - 1) / 2) *
                              (v.loa_m * scene.ppm * 0.34 if scene.abreast else 0)})

    total = max(p["start"] + p["dur"] for p in plans) + 1.5
    if scene.idle_on_line:
        total += 60.0

    n_frames = int(total * scene.fps)
    for fi in range(n_frames):
        t = fi / scene.fps
        frame = render_sea(scene, t)
        max_blur = 0.0

        for p in plans:
            v, e = p["v"], t - p["start"]
            if e < 0 or e > p["dur"] + (60.0 if scene.idle_on_line else 0):
                continue

            half = v.loa_m * scene.ppm
            if scene.idle_on_line:
                # approach the line, hover 60 s, then continue — hysteresis test
                if e < p["dur"] * 0.45:
                    x = -half + p["speed_px"] * e
                elif e < p["dur"] * 0.45 + 60.0:
                    x = gate_x + math.sin((e - p["dur"] * 0.45) * 0.8) * half * 0.10
                else:
                    x = gate_x + p["speed_px"] * (e - p["dur"] * 0.45 - 60.0)
            else:
                x = -half + p["speed_px"] * e
                if v.direction == "out":
                    x = scene.width + half - p["speed_px"] * e

            if -half * 2 < x < scene.width + half * 2:
                render_vessel(frame, v, scene, x, p["lane"])
                max_blur = max(max_blur,
                               v.speed_kn * KNOTS_TO_MPS * scene.shutter * scene.ppm)

        writer.write(apply_conditions(frame, scene, max_blur))

    writer.release()

    char_px = NAME_CHAR_HEIGHT_M * scene.ppm
    for p in plans:
        v = p["v"]
        cross = p["start"] + p["dur"] * 0.5
        truth.append({
            "clip": scene.clip_id,
            "t_enter": round(p["start"], 2),
            "t_cross": round(cross, 2),
            "t_exit": round(p["start"] + p["dur"], 2),
            "direction": v.direction,
            "true_name": v.name,
            # the label that makes results interpretable — see POC.md §5
            "name_legibility": ("clear" if char_px >= 25
                                else "partial" if char_px >= 14 else "illegible"),
            "true_flag": v.flag,
            "true_registration": v.registration or "",
            "true_type": v.vessel_type,
            "true_hull_color": v.hull_color_name,
            "true_loa_m": v.loa_m,
            "ppm": scene.ppm,
            "name_char_px": round(char_px, 1),
            "lighting": scene.lighting,
            "glare": scene.glare,
            "motion_blur_px": round(
                v.speed_kn * KNOTS_TO_MPS * scene.shutter * scene.ppm, 2),
            "notes": ("abreast" if scene.abreast else
                      "idles_on_gate_line" if scene.idle_on_line else ""),
        })

    print(f"  {path.name}  {n_frames} frames  "
          f"{scene.ppm:.0f} PPM  {char_px:.0f}px chars  {scene.lighting}")
    return truth


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #

NAMES = [
    ("SERENITY", "TR", "TR 34 A 1234"), ("BLUE HORIZON", "GB", "GB-4471-KL"),
    ("MERIDIAN", "GR", None), ("KISMET", "TR", "TR 07 B 8842"),
    ("ALTHEA", "IT", "IT-2231-RM"), ("NORTH STAR", "DE", None),
    ("SEA BREEZE", "FR", "FR-9087-MA"), ("ODYSSEY", "GB", None),
]
HULLS = [((242, 242, 242), "white"), ((150, 95, 45), "blue"),
         ((70, 70, 70), "dark grey"), ((225, 225, 210), "off-white")]
TYPES = ["motor_yacht", "motor_yacht", "sailing_yacht", "motor_yacht", "rib"]


def make_vessel(rng: random.Random, direction: str = "in") -> Vessel:
    name, flag, reg = rng.choice(NAMES)
    hull, hull_name = rng.choice(HULLS)
    vt = rng.choice(TYPES)
    loa = {"rib": 6.0, "sailing_yacht": 13.0}.get(vt, 12.0) + rng.uniform(-2, 5)
    return Vessel(name, flag, reg, vt, hull, hull_name,
                  round(loa, 1), rng.uniform(2.5, 4.5), direction)


def build(scenario: str, width: int, height: int, seed: int) -> list[Scene]:
    rng = random.Random(seed)
    scenes: list[Scene] = []

    if scenario in ("basic", "all"):
        for i, light in enumerate(["day", "dawn", "midday_glare", "dusk"]):
            scenes.append(Scene(
                clip_id=f"gate_{light}", width=width, height=height,
                ppm=400, lighting=light, glare=(light == "midday_glare"),
                vessels=[make_vessel(rng, "in" if k % 3 else "out") for k in range(3)],
            ))

    if scenario in ("ppm_sweep", "all"):
        # Validates the evaluation harness: 60 PPM = 6 px characters. Text is
        # physically unreadable. A harness reporting success here is BROKEN.
        for ppm in (400, 250, 150, 90, 60):
            scenes.append(Scene(
                clip_id=f"ppm_{ppm:03d}", width=width, height=height,
                ppm=ppm, lighting="day", vessels=[make_vessel(rng)],
            ))

    if scenario in ("edge_cases", "all"):
        scenes.append(Scene(
            clip_id="edge_abreast", width=width, height=height, ppm=300,
            abreast=True, vessels=[make_vessel(rng), make_vessel(rng)],
        ))
        scenes.append(Scene(
            clip_id="edge_idle_on_line", width=width, height=height, ppm=300,
            idle_on_line=True, vessels=[make_vessel(rng)],
        ))
        scenes.append(Scene(
            clip_id="edge_night", width=width, height=height, ppm=400,
            lighting="night", vessels=[make_vessel(rng)],
        ))
        fast = make_vessel(rng)
        fast.speed_kn = 8.0
        scenes.append(Scene(
            clip_id="edge_motion_blur", width=width, height=height, ppm=400,
            shutter=1 / 60, vessels=[fast],
        ))

    return scenes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures/clips"))
    ap.add_argument("--scenario", default="all",
                    choices=["basic", "ppm_sweep", "edge_cases", "all"])
    ap.add_argument("--width", type=int, default=1920,
                    help="1920 keeps fixtures small; use 3840 to mirror a 4K camera")
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    scenes = build(args.scenario, args.width, args.height, args.seed)
    print(f"Generating {len(scenes)} clips → {args.out}")

    rows: list[dict] = []
    for s in scenes:
        rows.extend(generate_clip(s, args.out))

    truth = args.out.parent / "ground_truth.csv"
    truth.parent.mkdir(parents=True, exist_ok=True)
    with truth.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    legible = sum(1 for r in rows if r["name_legibility"] == "clear")
    print(f"\n{len(rows)} transits → {truth}")
    print(f"  clear: {legible}   partial: "
          f"{sum(1 for r in rows if r['name_legibility'] == 'partial')}   "
          f"illegible: {sum(1 for r in rows if r['name_legibility'] == 'illegible')}")
    print("\nSynthetic footage validates the pipeline, NOT real-world accuracy.")
    print("The PoC gate still requires real footage — see docs/TEST-DATA.md §4.")


if __name__ == "__main__":
    main()
