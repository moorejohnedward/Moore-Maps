"""Draws the map sheets: student map, instructor answer key, exercise sheet, answer sheet.

Map conventions follow U.S. military topographic maps (TC 3-25.26 / FM 3-25.26):
  brown contours (every 5th one heavier and numbered = index contour),
  blue water, green woods, black 1,000-meter grid lines with their numbers in
  the margin, bar scales in meters, yards and miles, and a declination diagram.
Grid coordinates are fictitious. The map says so on its face.
"""

from __future__ import annotations

import io
import math
import random
import textwrap
from dataclasses import dataclass, asdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.collections import LineCollection     # noqa: E402
from matplotlib.colors import LightSource, ListedColormap  # noqa: E402
from matplotlib.path import Path                      # noqa: E402
from matplotlib.patches import Rectangle, Polygon, Circle  # noqa: E402
import numpy as np                                    # noqa: E402
from PIL import Image                                 # noqa: E402

from . import __version__
from .terrain import (TerrainOptions, TerrainFeatures, Feature, make_elevation, analyze,
                      vegetation_mask, gaussian_blur, load_picture)

M_TO_YD = 1.0936133
MILS_PER_DEG = 6400.0 / 360.0

BROWN = "#9a5b2c"
BROWN_DARK = "#7a4119"
BLUE = "#1c6dd0"
GREEN = "#cfe8b8"
PURPLE = "#b0179b"
RED = "#d0201b"
KEY_COLORS = {"Hilltop": "#d0201b", "Saddle": "#d0201b", "Valley": "#d0201b", "Ridge": "#d0201b",
              "Depression": "#d0201b", "Draw": "#e07b00", "Spur": "#e07b00", "Cliff": "#e07b00"}
MAJOR = ("Hilltop", "Saddle", "Valley", "Ridge", "Depression")
MINOR = ("Draw", "Spur", "Cliff")

PAPERS = {  # name: (long side, short side) in inches
    "Letter (11 x 8.5 in)": (11.0, 8.5),
    "Tabloid (17 x 11 in)": (17.0, 11.0),
    "Poster (24 x 18 in)": (24.0, 18.0),
    "Large poster (36 x 24 in)": (36.0, 24.0),
}

DEFINITIONS = [
    ("Hilltop", "Major", "A point or small area of high ground. From a hilltop, the ground slopes down in all directions. Contours: a small closed loop."),
    ("Saddle", "Major", "A dip or low point between two areas of higher ground. Not always the lower ground between two hilltops; it may be a break along a level ridge crest."),
    ("Valley", "Major", "A stretched-out groove in the land, usually formed by streams or rivers, with level ground at the bottom. Contours: U or V shapes whose closed ends point upstream (uphill)."),
    ("Ridge", "Major", "A sloping line of high ground. Walking along its center line you'd have low ground on three sides. Contours: U or V shapes pointing away from high ground."),
    ("Depression", "Major", "A low point in the ground or a sinkhole: ground rises on all sides. Contours: a closed loop with tick marks pointing inward, toward the low point."),
    ("Draw", "Minor", "A less developed stream course than a valley; no level ground, ground slopes up on three sides. Contours: V shapes pointing toward high ground."),
    ("Spur", "Minor", "A short, sloping line of higher ground, normally jutting out from the side of a ridge, often between two draws. Contours: U or V shapes pointing away from high ground."),
    ("Cliff", "Minor", "A vertical or near-vertical slope. Contours run together or are drawn as one line with tick marks pointing toward low ground."),
]


# --------------------------------------------------------------------------
@dataclass
class MapOptions:
    title: str = "TRAINING AREA"
    sheet: str = "MM 001"
    scale: int = 25000
    paper: str = "Tabloid (17 x 11 in)"
    contour_interval_ft: float = 0          # 0 = automatic
    grid_zone: str = "5Q"
    square_id: str = "KV"
    easting_km: int = 12                    # first grid line numbers
    northing_km: int = 40
    gm_angle_deg: float = 10.0              # G-M angle, east (+) or west (-)
    vegetation: bool = True
    woods_cover: float = 0.40
    streams: bool = True
    hillshade: bool = False
    photo_underlay: float = 0.0             # 0..1 faint picture under the map
    lettered_points: bool = True
    course: bool = True
    num_checkpoints: int = 5
    dpi: int = 300


@dataclass
class Point:
    label: str           # "A", "CP1", "SP"
    feature: Feature


@dataclass
class MapModel:
    """Everything needed to draw any page (built once, drawn many times)."""
    z: np.ndarray
    zs: np.ndarray
    picture: Image.Image
    feats: TerrainFeatures
    topt: TerrainOptions
    mopt: MapOptions
    paper_w: float
    paper_h: float
    frame: tuple          # (left, bottom, width, height) in inches
    ground_w: float       # meters
    ground_h: float
    cell_m: float
    ci_ft: float
    e0: float             # easting (m) of the west edge, full number
    n0: float             # northing (m) of the south edge
    letters: list
    course: list          # [Point], first is SP
    woods: np.ndarray | None


# --------------------------------------------------------------------------
# Building the model
# --------------------------------------------------------------------------
def auto_interval(relief_ft: float, paper_h: float) -> float:
    target = 30 + 2.0 * paper_h            # bigger paper -> more contours
    want = relief_ft / target
    choices = [5, 10, 20, 25, 40, 50, 100, 200]
    return float(min(choices, key=lambda c: abs(math.log(c / max(want, 1e-6)))))


def layout(paper: str, aspect: float):
    """Pick landscape/portrait to fit the picture, and the map frame size in inches."""
    long, short = PAPERS.get(paper, PAPERS["Tabloid (17 x 11 in)"])
    W, H = (long, short) if aspect >= 1 else (short, long)
    k = min(W, H) / 11.0
    margin = 0.35 * k
    title_h = 0.55 * k
    marg_h = max(1.75, 2.05 * k)
    avail_w = W - 2 * margin - 0.5 * k       # room for grid numbers on the sides
    avail_h = H - margin - title_h - marg_h - 0.45 * k
    fw = avail_w
    fh = fw / aspect
    if fh > avail_h:
        fh = avail_h
        fw = fh * aspect
    left = (W - fw) / 2
    spare = avail_h - fh                      # leftover height: split above and below
    bottom = marg_h + 0.25 * k + spare / 2
    return W, H, (left, bottom, fw, fh)


def build_model(picture_path_or_img, topt: TerrainOptions, mopt: MapOptions) -> MapModel:
    img = load_picture(picture_path_or_img) if isinstance(picture_path_or_img, str) else picture_path_or_img
    z, small = make_elevation(img, topt)
    rows, cols = z.shape
    W, H, frame = layout(mopt.paper, cols / rows)
    ground_w = frame[2] * 0.0254 * mopt.scale
    cell_m = ground_w / cols
    ground_h = cell_m * rows
    ci = mopt.contour_interval_ft or auto_interval(topt.high_ft - topt.low_ft, H)
    feats = analyze(z, cell_m, ci)
    rng = random.Random(topt.seed)
    # Put the frame edges off the grid lines, like a real sheet.
    e0 = mopt.easting_km * 1000 - rng.randint(150, 850)
    n0 = mopt.northing_km * 1000 - rng.randint(150, 850)
    woods = vegetation_mask(z.shape, topt.seed, mopt.woods_cover) if mopt.vegetation else None

    model = MapModel(z=z, zs=gaussian_blur(z, 1.2), picture=small, feats=feats, topt=topt, mopt=mopt,
                     paper_w=W, paper_h=H, frame=frame, ground_w=ground_w, ground_h=ground_h,
                     cell_m=cell_m, ci_ft=ci, e0=e0, n0=n0, letters=[], course=[], woods=woods)
    model.letters = pick_letter_points(feats, rng, z.shape)
    model.course = pick_course(model, rng)
    return model


def pick_letter_points(f: TerrainFeatures, rng: random.Random, shape):
    rows, cols = shape

    def inside(p):      # keep letters off the map edge so they're easy to read
        return 0.05 * rows < p.r < 0.95 * rows and 0.05 * cols < p.c < 0.95 * cols

    picks = []
    plan = [("hilltops", 2), ("saddles", 2), ("depressions", 1), ("valleys", 2),
            ("ridges", 2), ("draws", 2), ("spurs", 2)]
    for name, k in plan:
        picks += [p for p in getattr(f, name) if inside(p)][:k]
    picks += [c[0] for c in f.cliffs if inside(c[0])][:1]
    picks = picks[:12]
    rng.shuffle(picks)
    return [Point(chr(ord("A") + i), p) for i, p in enumerate(picks)]


def pick_course(m: MapModel, rng: random.Random):
    if not m.mopt.course:
        return []
    rows, cols = m.z.shape
    used = {(p.feature.r, p.feature.c) for p in m.letters}
    pool = [p for p in m.feats.all_points() if (p.r, p.c) not in used]
    # add some extra hilltop-ish spots if the picture gave few features
    while len(pool) < m.mopt.num_checkpoints + 2:
        r, c = rng.uniform(0.1, 0.9) * rows, rng.uniform(0.1, 0.9) * cols
        pool.append(Feature("Point", r, c, float(m.z[int(r), int(c)])))
    # keep checkpoints off the map edges
    pool = [p for p in pool if 0.06 * rows < p.r < 0.94 * rows and 0.06 * cols < p.c < 0.94 * cols]
    rng.shuffle(pool)
    # Start point near the south edge
    sr, sc = rows * rng.uniform(0.86, 0.92), cols * rng.uniform(0.25, 0.75)
    sp = Feature("Start point", sr, sc, float(m.z[int(sr), int(sc)]))
    min_leg = 400 / m.cell_m          # meters -> cells
    max_leg = 1800 / m.cell_m

    def crosses(a, b, c, d):
        def ccw(p, q, r):
            return (r.c - p.c) * (q.r - p.r) - (q.c - p.c) * (r.r - p.r)
        return (ccw(a, b, c) * ccw(a, b, d) < 0) and (ccw(c, d, a) * ccw(c, d, b) < 0)

    # Walk the course: each next checkpoint is a sensible leg away (450-2,400 m),
    # as far as possible from everywhere already visited, without crossing an earlier leg.
    # extra plain points so a course can always be finished
    for _ in range(60):
        r, c = rng.uniform(0.08, 0.92) * rows, rng.uniform(0.08, 0.92) * cols
        pool.append(Feature("Point", r, c, float(m.z[int(r), int(c)])))

    route = [sp]
    for _ in range(m.mopt.num_checkpoints):
        cur = route[-1]
        best, best_s = None, -1e9
        for strict in (2, 1, 0):          # relax the rules only if nothing fits
            for p in pool:
                dl = math.hypot(p.r - cur.r, p.c - cur.c)
                if not (min_leg <= dl <= max_leg * (1.0 if strict else 1.4)):
                    continue
                if strict >= 1 and any(crosses(route[i - 1], route[i], cur, p) for i in range(1, len(route) - 1)):
                    continue
                spread = min(math.hypot(p.r - q.r, p.c - q.c) for q in route)
                if spread < min_leg * (1.0 if strict else 0.6):
                    continue
                sc = min(spread, 0.8 * max_leg) + rng.uniform(0, 0.25 * max_leg)
                if strict == 2 and p.kind == "Point":
                    sc -= 0.5 * max_leg        # real terrain features make better checkpoints
                if sc > best_s:
                    best, best_s = p, sc
            if best is not None:
                break
        if best is None:
            break
        pool.remove(best)
        route.append(best)
    return [Point("SP" if i == 0 else f"CP{i}", p) for i, p in enumerate(route)]


# --------------------------------------------------------------------------
# Coordinates
# --------------------------------------------------------------------------
def rc_to_xy(m: MapModel, r: float, c: float):
    """Grid cell -> meters from the SW corner of the map frame."""
    return (c + 0.5) * m.cell_m, m.ground_h - (r + 0.5) * m.cell_m


def grid_ref(m: MapModel, r: float, c: float, digits: int = 8) -> str:
    x, y = rc_to_xy(m, r, c)
    e = int((m.e0 + x) % 100000)
    n = int((m.n0 + y) % 100000)
    half = digits // 2
    div = 10 ** (5 - half)
    return f"{e // div:0{half}d} {n // div:0{half}d}"


def full_grid_ref(m: MapModel, r, c, digits=8):
    return f"{m.mopt.grid_zone} {m.mopt.square_id} {grid_ref(m, r, c, digits)}"


def leg(m: MapModel, a: Feature, b: Feature):
    xa, ya = rc_to_xy(m, a.r, a.c)
    xb, yb = rc_to_xy(m, b.r, b.c)
    dx, dy = xb - xa, yb - ya
    grid_az = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    mag_az = (grid_az - m.mopt.gm_angle_deg) % 360    # easterly G-M angle: subtract (grid -> magnetic)
    dist = math.hypot(dx, dy)
    return grid_az, mag_az, dist


def fmt_az(deg: float) -> str:
    return f"{deg:05.1f}° / {deg * MILS_PER_DEG:04.0f} mils"


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------
def _fs(m: MapModel, base: float) -> float:
    return base * min(m.paper_w, m.paper_h) / 11.0


def draw_map_page(m: MapModel, key: bool = False, dpi: int | None = None):
    W, H = m.paper_w, m.paper_h
    fig = plt.figure(figsize=(W, H), dpi=dpi or m.mopt.dpi)
    fig.patch.set_facecolor("white")
    L, B, FW, FH = m.frame
    ax = fig.add_axes([L / W, B / H, FW / W, FH / H])
    _draw_terrain(ax, m, key)
    _draw_grid_numbers(fig, ax, m)
    _draw_title(fig, m, key)
    _draw_margin(fig, m)
    return fig


def _draw_terrain(ax, m: MapModel, key: bool):
    rows, cols = m.z.shape
    ext = [0, m.ground_w, 0, m.ground_h]
    ax.set_xlim(0, m.ground_w)
    ax.set_ylim(0, m.ground_h)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_facecolor("white")
    lw = min(m.paper_w, m.paper_h) / 11.0

    if m.mopt.photo_underlay > 0:
        ax.imshow(np.asarray(m.picture), extent=ext, origin="upper", alpha=m.mopt.photo_underlay,
                  interpolation="bilinear", zorder=0)
    if m.woods is not None:
        ax.imshow(np.where(m.woods, 1.0, np.nan), extent=ext, origin="upper",
                  cmap=ListedColormap([GREEN]), alpha=0.95 if m.mopt.photo_underlay == 0 else 0.6,
                  interpolation="bilinear", zorder=1)
    if m.mopt.hillshade:
        ls = LightSource(azdeg=315, altdeg=45)
        shade = ls.hillshade(m.zs, vert_exag=0.05 / max(m.cell_m, 1e-6) * 30, dx=1, dy=1)
        ax.imshow(shade, extent=ext, origin="upper", cmap="gray", alpha=0.22, vmin=0, vmax=1, zorder=2)

    X = (np.arange(cols) + 0.5) * m.cell_m
    Y = m.ground_h - (np.arange(rows) + 0.5) * m.cell_m
    ci = m.ci_ft
    lo = math.ceil(m.zs.min() / ci) * ci
    hi = math.floor(m.zs.max() / ci) * ci
    levels = np.arange(lo, hi + ci / 2, ci)
    idx = [v for v in levels if round(v / ci) % 5 == 0]
    inter = [v for v in levels if round(v / ci) % 5 != 0]
    if inter:
        ax.contour(X, Y, m.zs, levels=inter, colors=BROWN, linewidths=0.35 * lw, zorder=4)
    if idx:
        cs = ax.contour(X, Y, m.zs, levels=idx, colors=BROWN_DARK, linewidths=0.85 * lw, zorder=4)
        ax.clabel(cs, fmt=lambda v: f"{v:,.0f}", fontsize=5.0 * lw, inline=True, inline_spacing=1.5)

    # depression tick marks
    for d in m.feats.depressions:
        level = math.ceil(m.zs[int(d.r), int(d.c)] / ci) * ci
        x0, y0 = rc_to_xy(m, d.r, d.c)
        cs = ax.contour(X, Y, m.zs, levels=[level], colors="none", linewidths=0)
        best = None
        for seg in cs.allsegs[0]:
            if len(seg) > 5 and Path(seg).contains_point((x0, y0)):
                if best is None or len(seg) < len(best):
                    best = seg
        if best is None:
            continue
        ticks = []
        L = np.cumsum(np.r_[0, np.hypot(*np.diff(best, axis=0).T)])
        tick_len = 0.0010 * m.mopt.scale * lw          # about 1 mm on paper
        spacing = tick_len * 3
        for s in np.arange(spacing / 2, L[-1], spacing):
            k = min(np.searchsorted(L, s), len(best) - 2)
            p, q = best[k], best[k + 1]
            t = (q - p) / (np.hypot(*(q - p)) + 1e-9)
            nrm = np.array([-t[1], t[0]])
            if np.dot(nrm, np.array([x0, y0]) - p) < 0:
                nrm = -nrm
            ticks.append([p, p + nrm * tick_len])
        ax.add_collection(LineCollection(ticks, colors=BROWN, linewidths=0.5 * lw, zorder=4))

    # cliffs
    for f, (r0, c0, r1, c1), (dr, dc) in m.feats.cliffs:
        p0 = np.array(rc_to_xy(m, r0, c0))
        p1 = np.array(rc_to_xy(m, r1, c1))
        ax.plot(*zip(p0, p1), color=BROWN_DARK, lw=1.6 * lw, solid_capstyle="round", zorder=5)
        down = np.array([dc, -dr])
        down /= np.hypot(*down) + 1e-9
        tl = 0.0012 * m.mopt.scale * lw
        segs = [[p0 + t * (p1 - p0), p0 + t * (p1 - p0) + down * tl] for t in np.linspace(0.05, 0.95, 9)]
        ax.add_collection(LineCollection(segs, colors=BROWN_DARK, linewidths=0.8 * lw, zorder=5))

    # water
    if m.mopt.streams:
        for (rr, cc, per) in m.feats.streams:
            xs = (cc + 0.5) * m.cell_m
            ys = m.ground_h - (rr + 0.5) * m.cell_m
            if per:
                ax.plot(xs, ys, color=BLUE, lw=0.9 * lw, solid_capstyle="round", zorder=6)
            else:
                ax.plot(xs, ys, color=BLUE, lw=0.6 * lw, dashes=(6, 2, 1, 2), zorder=6)

    # spot elevations on hilltops
    for f in m.feats.hilltops:
        x, y = rc_to_xy(m, f.r, f.c)
        ax.plot(x, y, "o", ms=1.6 * lw, color="black", zorder=7)
        ax.text(x + 0.0015 * m.mopt.scale, y, f"{f.elev_ft:,.0f}", fontsize=5.2 * lw, va="center",
                ha="left", zorder=7, color="black")

    # 1,000 m grid
    gx = [x for x in np.arange(math.ceil(m.e0 / 1000) * 1000, m.e0 + m.ground_w, 1000) - m.e0]
    gy = [y for y in np.arange(math.ceil(m.n0 / 1000) * 1000, m.n0 + m.ground_h, 1000) - m.n0]
    for x in gx:
        ax.axvline(x, color="black", lw=0.45 * lw, zorder=8)
    for y in gy:
        ax.axhline(y, color="black", lw=0.45 * lw, zorder=8)
    for s in ax.spines.values():
        s.set_linewidth(1.3 * lw)
        s.set_zorder(20)

    # lettered points (student) / labels (key)
    r_mark = 0.0011 * m.mopt.scale * lw
    if m.mopt.lettered_points or key:
        for p in m.letters:
            x, y = rc_to_xy(m, p.feature.r, p.feature.c)
            col = KEY_COLORS.get(p.feature.kind, RED) if key else PURPLE
            ax.add_patch(Circle((x, y), r_mark, fill=False, ec=col, lw=1.0 * lw, zorder=12))
            ax.plot(x, y, ".", ms=1.4 * lw, color=col, zorder=12)
            txt = f"{p.label}  {p.feature.kind.upper()}" if key else p.label
            left_side = p.feature.kind == "Hilltop"
            ax.text(x + (-1.25 if left_side else 1.25) * r_mark, y + r_mark * 1.25, txt,
                    fontsize=(6.5 if key else 8) * lw, ha="right" if left_side else "left",
                    fontweight="bold", color=col, zorder=13,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.75))

    # land navigation course
    if m.course:
        pts = []
        for p in m.course:
            x, y = rc_to_xy(m, p.feature.r, p.feature.c)
            pts.append((x, y))
            s = r_mark * 1.5
            tri = Polygon([(x, y + s), (x - s * 0.87, y - s * 0.5), (x + s * 0.87, y - s * 0.5)],
                          closed=True, fill=False, ec=PURPLE, lw=1.1 * lw, zorder=12)
            ax.add_patch(tri)
            ax.plot(x, y, ".", ms=1.4 * lw, color=PURPLE, zorder=12)
            ax.text(x - s * 1.1, y + s * 0.6, p.label, fontsize=7.5 * lw, fontweight="bold", color=PURPLE,
                    ha="right", zorder=13, bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.75))
        if key:
            for i in range(1, len(pts)):
                a, b = pts[i - 1], pts[i]
                ax.annotate("", xy=b, xytext=a, zorder=11,
                            arrowprops=dict(arrowstyle="-|>", color=PURPLE, lw=0.8 * lw, ls="--",
                                            shrinkA=8 * lw, shrinkB=8 * lw))
                gaz, maz, dist = leg(m, m.course[i - 1].feature, m.course[i].feature)
                vx, vy = b[0] - a[0], b[1] - a[1]
                nl = math.hypot(vx, vy) + 1e-9
                off = r_mark * 2.2
                mx = a[0] + 0.42 * vx + (-vy / nl) * off
                my = a[1] + 0.42 * vy + (vx / nl) * off
                ax.text(mx, my, f"{gaz:.0f}° GN\n{dist:,.0f} m", fontsize=5.5 * lw, color=PURPLE,
                        ha="center", va="center", zorder=13,
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=PURPLE, lw=0.4, alpha=0.9))

    # key: ridge lines
    if key:
        for (rr, cc) in m.feats.ridgelines:
            xs = (cc + 0.5) * m.cell_m
            ys = m.ground_h - (rr + 0.5) * m.cell_m
            ax.plot(xs, ys, color="#e07b00", lw=0.6 * lw, ls=":", zorder=9, alpha=0.8)


def _draw_grid_numbers(fig, ax, m: MapModel):
    W, H = m.paper_w, m.paper_h
    L, B, FW, FH = m.frame
    fs = _fs(m, 7.5)
    xs = np.arange(math.ceil(m.e0 / 1000) * 1000, m.e0 + m.ground_w, 1000)
    ys = np.arange(math.ceil(m.n0 / 1000) * 1000, m.n0 + m.ground_h, 1000)
    for i, e in enumerate(xs):
        fx = (L + (e - m.e0) / m.ground_w * FW) / W
        lab = f"{int(e // 1000) % 100:02d}"
        for fy, va in (((B - 0.04) / H, "top"), ((B + FH + 0.04) / H, "bottom")):
            fig.text(fx, fy, lab, ha="center", va=va, fontsize=fs, fontweight="bold")
        if i == 0:
            fig.text(fx + 0.012 * 11 / W, (B - 0.04) / H, "000m E.", ha="left", va="top", fontsize=fs * 0.55)
    for i, n in enumerate(ys):
        fy = (B + (n - m.n0) / m.ground_h * FH) / H
        lab = f"{int(n // 1000) % 100:02d}"
        fig.text((L - 0.05) / W, fy, lab, ha="right", va="center", fontsize=fs, fontweight="bold")
        fig.text((L + FW + 0.05) / W, fy, lab, ha="left", va="center", fontsize=fs, fontweight="bold")
        if i == 0:
            fig.text((L - 0.05) / W, fy - 0.13 * min(W, H) / 11 / H, "000m N.", ha="right", va="top",
                     fontsize=fs * 0.55)


def _draw_title(fig, m: MapModel, key: bool):
    W, H = m.paper_w, m.paper_h
    k = min(W, H) / 11.0
    L, B, FW, FH = m.frame
    top = min(1 - 0.3 * k / H, (B + FH + 0.85 * k) / H)
    fig.text(0.5, top, m.mopt.title.upper(), ha="center", va="top", fontsize=_fs(m, 17), fontweight="bold")
    fig.text(0.5, top - 0.32 * k / H, "MOORE MAPS TRAINING SERIES  •  FICTITIOUS TERRAIN  •  NOT FOR REAL-WORLD NAVIGATION",
             ha="center", va="top", fontsize=_fs(m, 7))
    fig.text(0.35 * k / W, top, f"1:{m.mopt.scale:,}", ha="left", va="top", fontsize=_fs(m, 11), fontweight="bold")
    fig.text(1 - 0.35 * k / W, top, f"SHEET {m.mopt.sheet}", ha="right", va="top", fontsize=_fs(m, 11),
             fontweight="bold")
    if key:
        fig.text(1 - 0.35 * k / W, top - 0.3 * k / H, "INSTRUCTOR ANSWER KEY", ha="right", va="top",
                 fontsize=_fs(m, 11), fontweight="bold", color=RED,
                 bbox=dict(boxstyle="square,pad=0.25", fc="white", ec=RED, lw=1.2))


def _bar_scale(fig, x0, y0, width_in, m: MapModel, unit_m: float, major: list, label: str, sub: int):
    """One bar scale. 'major' = tick values to the right of zero (in units); 'sub' = subdivisions left of 0."""
    W, H = m.paper_w, m.paper_h
    k = min(W, H) / 11.0
    in_per_unit = unit_m / m.mopt.scale / 0.0254
    first = major[1] - major[0] if len(major) > 1 else major[0]
    h = 0.06 * k
    ax = fig.add_axes([x0 / W, y0 / H, width_in / W, 0.30 * k / H])
    ax.set_xlim(-first * in_per_unit - 0.02, major[-1] * in_per_unit + 0.02)
    ax.set_ylim(0, 0.30 * k)
    ax.axis("off")
    fs = _fs(m, 5.5)
    # left extension (subdivided)
    for i in range(sub):
        a = -first + i * first / sub
        ax.add_patch(Rectangle((a * in_per_unit, 0.12 * k), first / sub * in_per_unit, h,
                               fc="black" if i % 2 == 0 else "white", ec="black", lw=0.5))
    for i in range(len(major) - 1):
        a, b = major[i], major[i + 1]
        ax.add_patch(Rectangle((a * in_per_unit, 0.12 * k), (b - a) * in_per_unit, h,
                               fc="white" if i % 2 == 0 else "black", ec="black", lw=0.5))
    ax.text(-first * in_per_unit, 0.21 * k, f"{first:g}", ha="center", fontsize=fs)
    for v in major:
        ax.text(v * in_per_unit, 0.21 * k, f"{v:,g}", ha="center", fontsize=fs)
    ax.text((major[-1] * in_per_unit) / 2, 0.0, label, ha="center", va="bottom", fontsize=fs * 1.05,
            fontweight="bold")


def _nice_bar(m: MapModel, unit_m: float, max_in: float):
    span_units = max_in * 0.0254 * m.mopt.scale / unit_m
    for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if span_units / step <= 5:
            n = int(span_units // step)
            return [i * step for i in range(max(n, 1) + 1)]
    return [0, span_units]


def _draw_margin(fig, m: MapModel):
    W, H = m.paper_w, m.paper_h
    k = min(W, H) / 11.0
    L, B, FW, FH = m.frame
    ytop = B - 0.38 * k                      # top of margin area (inches)
    fs = _fs(m, 6.2)

    # ---- legend (left) ----
    lx = 0.4 * k
    items = [
        ("idx", "Index contour (every 5th)"), ("int", "Intermediate contour"),
        ("dep", "Depression contour"), ("cliff", "Cliff"),
        ("per", "Perennial stream"), ("intm", "Intermittent stream"),
        ("woods", "Woods / vegetation"), ("spot", "Spot elevation (feet)"),
        ("grid", "1,000-meter grid line"), ("pt", "Lettered point / checkpoint"),
    ]
    lax = fig.add_axes([lx / W, (ytop - 1.55 * k) / H, 3.0 * k / W, 1.55 * k / H])
    lax.set_xlim(0, 3.0)
    lax.set_ylim(0, 1.55)
    lax.axis("off")
    lax.text(0, 1.5, "LEGEND", fontsize=fs * 1.15, fontweight="bold", va="top")
    for i, (kind, text) in enumerate(items):
        col, row = i // 5, i % 5
        x = col * 1.55
        y = 1.22 - row * 0.26
        if kind == "idx":
            lax.plot([x, x + 0.3], [y, y], color=BROWN_DARK, lw=0.85 * k)
        elif kind == "int":
            lax.plot([x, x + 0.3], [y, y], color=BROWN, lw=0.35 * k)
        elif kind == "dep":
            lax.plot([x, x + 0.3], [y, y], color=BROWN, lw=0.35 * k)
            for t in np.linspace(x + 0.03, x + 0.27, 5):
                lax.plot([t, t], [y, y - 0.05], color=BROWN, lw=0.5 * k)
        elif kind == "cliff":
            lax.plot([x, x + 0.3], [y, y], color=BROWN_DARK, lw=1.4 * k)
            for t in np.linspace(x + 0.03, x + 0.27, 5):
                lax.plot([t, t], [y, y - 0.06], color=BROWN_DARK, lw=0.7 * k)
        elif kind == "per":
            lax.plot([x, x + 0.3], [y, y], color=BLUE, lw=0.9 * k)
        elif kind == "intm":
            lax.plot([x, x + 0.3], [y, y], color=BLUE, lw=0.6 * k, dashes=(6, 2, 1, 2))
        elif kind == "woods":
            lax.add_patch(Rectangle((x, y - 0.07), 0.3, 0.14, fc=GREEN, ec="none"))
        elif kind == "spot":
            lax.plot(x + 0.06, y, "o", ms=1.6 * k, color="black")
            lax.text(x + 0.11, y, "1,240", fontsize=fs * 0.85, va="center")
        elif kind == "grid":
            lax.plot([x, x + 0.3], [y, y], color="black", lw=0.45 * k)
        elif kind == "pt":
            lax.add_patch(Circle((x + 0.08, y), 0.05, fill=False, ec=PURPLE, lw=0.9 * k))
            lax.add_patch(Polygon([(x + 0.24, y + 0.06), (x + 0.19, y - 0.04), (x + 0.29, y - 0.04)],
                                  fill=False, ec=PURPLE, lw=0.9 * k))
        lax.text(x + 0.36, y, text, fontsize=fs, va="center")

    # ---- scales (center) ----
    cx = W / 2
    bar_w = min(4.2 * k, W * 0.3)
    fig.text(cx / W, (ytop - 0.02 * k) / H, f"SCALE 1:{m.mopt.scale:,}", ha="center", va="top",
             fontsize=fs * 1.6, fontweight="bold")
    max_in = bar_w * 0.8
    _bar_scale(fig, cx - bar_w / 2, ytop - 0.62 * k, bar_w, m, 1.0, _nice_bar(m, 1.0, max_in), "METERS", 5)
    _bar_scale(fig, cx - bar_w / 2, ytop - 0.97 * k, bar_w, m, 1 / M_TO_YD, _nice_bar(m, 1 / M_TO_YD, max_in),
               "YARDS", 5)
    _bar_scale(fig, cx - bar_w / 2, ytop - 1.32 * k, bar_w, m, 1609.344, _nice_bar(m, 1609.344, max_in),
               "STATUTE MILES", 4)
    fig.text(cx / W, (ytop - 1.42 * k) / H, f"CONTOUR INTERVAL {m.ci_ft:g} FEET", ha="center", va="top",
             fontsize=fs * 1.25, fontweight="bold")
    fig.text(cx / W, (ytop - 1.62 * k) / H,
             f"Elevations in feet. Grid: 1,000-meter squares, zone {m.mopt.grid_zone}, 100,000-m square "
             f"{m.mopt.square_id}. Moore Maps v{__version__}.",
             ha="center", va="top", fontsize=fs * 0.85, color="#333")

    # ---- declination diagram + grid reference box (right) ----
    rx = W - 0.4 * k - 3.3 * k
    dax = fig.add_axes([rx / W, (ytop - 1.55 * k) / H, 1.0 * k / W, 1.5 * k / H])
    dax.set_xlim(-1, 1)
    dax.set_ylim(0, 3)
    dax.axis("off")
    gm = m.mopt.gm_angle_deg
    dax.plot([0, 0], [0.35, 2.6], color="black", lw=0.8 * k)
    dax.text(0, 2.65, "GN", ha="center", va="bottom", fontsize=fs, fontweight="bold")
    a = math.radians(gm * 2.2)                      # exaggerated so it's readable (as on real sheets)
    dax.plot([0, 2.1 * math.sin(a)], [0.35, 0.35 + 2.1 * math.cos(a)], color="black", lw=0.8 * k)
    dax.annotate("", xy=(2.25 * math.sin(a), 0.35 + 2.25 * math.cos(a)), xytext=(2.0 * math.sin(a), 0.35 + 2.0 * math.cos(a)),
                 arrowprops=dict(arrowstyle="-|>", lw=0.8 * k, color="black"))
    dax.text(2.3 * math.sin(a), 0.4 + 2.3 * math.cos(a), "MN", ha="center", va="bottom", fontsize=fs,
             fontweight="bold")
    dax.plot([0, -0.35], [0.35, 2.45], color="black", lw=0.8 * k)
    dax.plot(-0.37, 2.55, marker="*", ms=4 * k, color="black")
    dax.text(0, 0.05, f"{abs(gm):.1f}°\n{abs(gm) * MILS_PER_DEG:.0f} mils", ha="center", va="bottom",
             fontsize=fs * 0.85)

    tx = rx + 1.1 * k
    direction = "EAST" if gm >= 0 else "WEST"
    lines = [
        "DECLINATION DIAGRAM",
        f"G-M ANGLE {abs(gm) * MILS_PER_DEG:.0f} MILS ({abs(gm):.1f}°) {direction}.",
        "Grid azimuth to magnetic: " + ("SUBTRACT" if gm >= 0 else "ADD") + " the G-M angle.",
        "Magnetic azimuth to grid: " + ("ADD" if gm >= 0 else "SUBTRACT") + " the G-M angle.",
        "",
        "GRID REFERENCE",
        f"Grid zone designation: {m.mopt.grid_zone}",
        f"100,000-m square identification: {m.mopt.square_id}",
        "Read RIGHT, then UP. Sample 8-digit point:",
        f"   {m.mopt.grid_zone} {m.mopt.square_id} {grid_ref(m, m.z.shape[0] * 0.5, m.z.shape[1] * 0.5)}  (map center)",
    ]
    for i, t in enumerate(lines):
        bold = t in ("DECLINATION DIAGRAM", "GRID REFERENCE")
        fig.text(tx / W, (ytop - 0.05 * k - i * 0.155 * k) / H, t, ha="left", va="top",
                 fontsize=fs * (1.05 if bold else 0.92), fontweight="bold" if bold else "normal")


# --------------------------------------------------------------------------
# Text pages
# --------------------------------------------------------------------------
def _text_page(title: str, subtitle: str):
    fig = plt.figure(figsize=(8.5, 11), dpi=150)
    fig.text(0.5, 0.965, title, ha="center", va="top", fontsize=16, fontweight="bold")
    fig.text(0.5, 0.935, subtitle, ha="center", va="top", fontsize=9, color="#333")
    return fig


def _table(fig, top: float, headers, rows, widths, fs=8.5, row_h=0.024):
    x0 = 0.07
    y = top
    x = x0
    for h_, w_ in zip(headers, widths):
        fig.text(x, y, h_, fontsize=fs, fontweight="bold", va="top")
        x += w_
    y -= row_h * 0.9
    fig.add_artist(plt.Line2D([x0, x0 + sum(widths)], [y + row_h * 0.25] * 2, color="black", lw=0.8,
                              transform=fig.transFigure))
    for row in rows:
        x = x0
        for cell, w_ in zip(row, widths):
            fig.text(x, y, str(cell), fontsize=fs, va="top")
            x += w_
        fig.add_artist(plt.Line2D([x0, x0 + sum(widths)], [y - row_h * 0.72] * 2, color="#bbb", lw=0.4,
                                  transform=fig.transFigure))
        y -= row_h
    return y


def draw_exercise_page(m: MapModel):
    fig = _text_page(f"LAND NAVIGATION EXERCISE — {m.mopt.title.upper()}",
                     f"Sheet {m.mopt.sheet}  •  Scale 1:{m.mopt.scale:,}  •  Contour interval {m.ci_ft:g} ft  •  "
                     f"G-M angle {abs(m.mopt.gm_angle_deg):.1f}° {'E' if m.mopt.gm_angle_deg >= 0 else 'W'}")
    y = 0.90
    fig.text(0.07, y, "Name: ______________________________     Date: ____________     Score: ______",
             fontsize=9.5, va="top")
    y -= 0.04
    if m.letters:
        fig.text(0.07, y, "PART 1 — TERRAIN FEATURES", fontsize=11, fontweight="bold", va="top")
        y -= 0.022
        fig.text(0.07, y, "For each lettered point on the map, name the terrain feature and give its 8-digit grid "
                          "coordinate.\nMajor: hilltop, saddle, valley, ridge, depression.  Minor: draw, spur, cliff.",
                 fontsize=8.5, va="top")
        y -= 0.045
        rows = [[p.label, "______________________", f"{m.mopt.square_id} ________ ________", "________"]
                for p in m.letters]
        y = _table(fig, y, ["Point", "Terrain feature", "8-digit grid", "Elev (ft)"], rows,
                   [0.08, 0.34, 0.32, 0.12])
        y -= 0.02
    if len(m.course) > 1:
        fig.text(0.07, y, "PART 2 — LAND NAVIGATION COURSE", fontsize=11, fontweight="bold", va="top")
        y -= 0.022
        fig.text(0.07, y, "Plot each point from its grid. Then find the grid azimuth, magnetic azimuth and "
                          "distance for each leg.\nSP = start point. Use your protractor and the meter bar scale.",
                 fontsize=8.5, va="top")
        y -= 0.045
        rows = []
        for i, p in enumerate(m.course):
            g = full_grid_ref(m, p.feature.r, p.feature.c)
            if i == 0:
                rows.append([p.label, g, "—", "—", "—"])
            else:
                rows.append([f"{m.course[i - 1].label} → {p.label}", g, "_______", "_______", "_______ m"])
        y = _table(fig, y, ["Leg", "Go to grid", "Grid az", "Mag az", "Distance"], rows,
                   [0.15, 0.27, 0.15, 0.15, 0.16])
        y -= 0.02
    fig.text(0.07, y, "PART 3 — MAP READING", fontsize=11, fontweight="bold", va="top")
    y -= 0.025
    qs = []
    if m.feats.hilltops:
        h = max(m.feats.hilltops, key=lambda f: f.elev_ft)
        qs.append(f"What is the elevation of the highest hilltop, at grid {full_grid_ref(m, h.r, h.c, 6)}?  ________ ft")
    qs.append("What is the contour interval of this map?  ________ ft     How far apart are the grid lines?  ________ m")
    qs.append("Is the ground at CP1 higher or lower than at SP? By about how many feet?  ____________________")
    cp_feat = next((p for p in m.course[1:] if p.feature.kind not in ("Point", "Start point")), None)
    if cp_feat:
        qs.append(f"What terrain feature is {cp_feat.label} on?  ____________________")
    for i, q in enumerate(qs):
        fig.text(0.07, y, f"{i + 1}.  {q}", fontsize=8.8, va="top")
        y -= 0.03
    return fig


def draw_reference_page(m: MapModel):
    fig = _text_page("TERRAIN FEATURE REFERENCE CARD", "Five major, three minor (and two supplementary) terrain features")
    y = 0.905
    for name, kind, text in DEFINITIONS:
        fig.text(0.07, y, f"{name.upper()}", fontsize=12, fontweight="bold", va="top",
                 color=KEY_COLORS.get(name, RED))
        fig.text(0.07, y - 0.022, f"{kind} terrain feature", fontsize=8, va="top", color="#555")
        fig.text(0.30, y, textwrap.fill(text, 78), fontsize=9.0, va="top", linespacing=1.3)
        y -= 0.074
    fig.text(0.07, y, "SUPPLEMENTARY", fontsize=12, fontweight="bold", va="top")
    fig.text(0.30, y, textwrap.fill("CUT: a man-made cut through high ground (road or railroad bed). FILL: a man-made "
                                    "raise of low ground. Shown with tick marks along the road. "
                                    "(Not generated from pictures yet.)", 78), fontsize=9.0, va="top", linespacing=1.3)
    y -= 0.075
    fig.text(0.07, y, "FIST TRICK", fontsize=12, fontweight="bold", va="top")
    fig.text(0.30, y, textwrap.fill("Make a fist. Knuckles are hilltops, the spaces between knuckles are saddles, "
                                    "the fingers are ridges and spurs, the spaces between fingers are valleys and draws, "
                                    "and a cupped palm is a depression.", 78), fontsize=9.0, va="top", linespacing=1.3)
    y -= 0.075
    fig.text(0.07, y, "READING A GRID", fontsize=12, fontweight="bold", va="top")
    fig.text(0.30, y, textwrap.fill(f"Read RIGHT, then UP. On this sheet each grid square is 1,000 m. A 6-digit grid "
                                    f"locates a point within 100 m, an 8-digit grid within 10 m. Always give the grid "
                                    f"zone and 100,000-m square too: {m.mopt.grid_zone} {m.mopt.square_id} 1234 5678.",
                                    78), fontsize=9.2, va="top", linespacing=1.35)
    return fig


def draw_answer_page(m: MapModel):
    fig = _text_page(f"ANSWER SHEET — {m.mopt.title.upper()}", f"Sheet {m.mopt.sheet}  •  Instructor copy")
    y = 0.90
    if m.letters:
        fig.text(0.07, y, "PART 1 — TERRAIN FEATURES", fontsize=11, fontweight="bold", va="top")
        y -= 0.03
        rows = [[p.label, f"{p.feature.kind} ({'major' if p.feature.kind in MAJOR else 'minor'})",
                 full_grid_ref(m, p.feature.r, p.feature.c), f"{p.feature.elev_ft:,.0f}"] for p in m.letters]
        y = _table(fig, y, ["Point", "Terrain feature", "8-digit grid", "Elev (ft)"], rows,
                   [0.08, 0.30, 0.34, 0.12])
        fig.text(0.07, y - 0.003, f"Grids: accept within 10-20 m. Elevations: accept within half the contour "
                                  f"interval (±{m.ci_ft / 2:g} ft).", fontsize=7.8, va="top", color="#333")
        y -= 0.04
    if len(m.course) > 1:
        fig.text(0.07, y, "PART 2 — LAND NAVIGATION COURSE", fontsize=11, fontweight="bold", va="top")
        y -= 0.03
        rows = []
        total = 0.0
        for i, p in enumerate(m.course):
            g = full_grid_ref(m, p.feature.r, p.feature.c)
            if i == 0:
                rows.append([p.label, g, "—", "—", "—", f"{p.feature.elev_ft:,.0f}"])
                continue
            gaz, maz, dist = leg(m, m.course[i - 1].feature, p.feature)
            total += dist
            rows.append([f"{m.course[i - 1].label}→{p.label}", g, fmt_az(gaz), fmt_az(maz),
                         f"{dist:,.0f} m ({dist * M_TO_YD:,.0f} yd)", f"{p.feature.elev_ft:,.0f}"])
        y = _table(fig, y, ["Leg", "Grid", "Grid azimuth", "Magnetic azimuth", "Distance", "Elev ft"], rows,
                   [0.08, 0.155, 0.165, 0.165, 0.19, 0.07], fs=7.4)
        fig.text(0.07, y - 0.005, f"Total course distance: {total:,.0f} m ({total * M_TO_YD:,.0f} yd, "
                                  f"{total / 1609.344:.2f} mi).  Pace count check: at ~62 paces per 100 m, about "
                                  f"{total / 100 * 62:,.0f} paces.", fontsize=8, va="top")
        y -= 0.05
    fig.text(0.07, y, "PART 3 — MAP READING", fontsize=11, fontweight="bold", va="top")
    y -= 0.03
    ans = []
    if m.feats.hilltops:
        h = max(m.feats.hilltops, key=lambda f: f.elev_ft)
        ans.append(f"Highest hilltop: {h.elev_ft:,.0f} ft (the spot elevation printed next to it).")
    ans.append(f"Contour interval: {m.ci_ft:g} ft. Grid lines: 1,000 m apart.")
    if len(m.course) > 1:
        d = m.course[1].feature.elev_ft - m.course[0].feature.elev_ft
        ans.append(f"CP1 is {'higher' if d >= 0 else 'lower'} than SP by about {abs(d):,.0f} ft "
                   f"(SP {m.course[0].feature.elev_ft:,.0f} ft, CP1 {m.course[1].feature.elev_ft:,.0f} ft).")
    cp_feat = next((p for p in m.course[1:] if p.feature.kind not in ("Point", "Start point")), None)
    if cp_feat:
        ans.append(f"{cp_feat.label} is on a {cp_feat.feature.kind.lower()}.")
    for i, a in enumerate(ans):
        fig.text(0.07, y, f"{i + 1}.  {a}", fontsize=8.8, va="top")
        y -= 0.03
    y -= 0.02
    fig.text(0.07, y, textwrap.fill("Notes: grid azimuths are measured from grid north (up on the map). Magnetic "
                                    "azimuth = grid azimuth minus an easterly G-M angle (plus a westerly one). "
                                    "Distances are straight-line map distances; on the ground, add for hills and "
                                    "detours. Accept azimuths within ±3° (±50 mils).", 110),
             fontsize=7.8, va="top", color="#333")
    return fig


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def preview_image(m: MapModel, key: bool = False, max_px: int = 1400) -> Image.Image:
    dpi = max(40, int(max_px / max(m.paper_w, m.paper_h)))
    fig = draw_map_page(m, key=key, dpi=dpi)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def export_all(m: MapModel, out_dir: str, base: str) -> list:
    """Writes PNGs of both maps plus one PDF training packet. Returns the file paths."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    student = draw_map_page(m, key=False)
    p = os.path.join(out_dir, f"{base} - student map.png")
    student.savefig(p, dpi=m.mopt.dpi)
    paths.append(p)
    keyfig = draw_map_page(m, key=True)
    p = os.path.join(out_dir, f"{base} - answer key map.png")
    keyfig.savefig(p, dpi=m.mopt.dpi)
    paths.append(p)
    pdf_path = os.path.join(out_dir, f"{base} - training packet.pdf")
    ex = draw_exercise_page(m)
    ref = draw_reference_page(m)
    an = draw_answer_page(m)
    with PdfPages(pdf_path) as pdf:
        pdf.savefig(student)
        pdf.savefig(ex)
        pdf.savefig(ref)
        pdf.savefig(keyfig)
        pdf.savefig(an)
        d = pdf.infodict()
        d["Title"] = f"{m.mopt.title} - Moore Maps training packet"
        d["Author"] = "Moore Maps"
    for f in (student, keyfig, ex, ref, an):
        plt.close(f)
    paths.append(pdf_path)
    return paths


def options_to_dict(topt: TerrainOptions, mopt: MapOptions) -> dict:
    return {"terrain": asdict(topt), "map": asdict(mopt)}
