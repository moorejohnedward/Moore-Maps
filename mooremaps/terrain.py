"""Terrain engine: picture -> elevation grid -> terrain features.

Everything here is plain NumPy + Pillow so the finished .exe stays small.

How a picture becomes ground
----------------------------
A photo has no real height data, so brightness stands in for height:
bright = high ground, dark = low ground (or the reverse with "invert").
The brightness is blurred heavily so it rolls like real ground, a little
natural-looking "noise" is added so slopes aren't perfectly smooth, and the
result is stretched between the lowest and highest elevations you choose.

How features are found (the same 5 major / 3 minor features taught in FM 3-25.26)
---------------------------------------------------------------------------
* Hilltop     - highest point inside a closed contour that doesn't touch the map edge.
* Depression  - lowest point inside a closed contour (drawn with tick marks).
* Saddle      - a low point between two higher areas: ground rises two ways and
                falls two ways (a "pass").
* Valley/Draw - water-flow paths. Every cell drains to its steepest downhill
                neighbor; cells that collect water from a large area are valleys
                (main drainage, streams); smaller, shorter ones are draws.
* Ridge/Spur  - the same flow math run on upside-down ground: long lines of high
                ground are ridges, short ones that jut off them are spurs.
* Cliff       - the steepest ground on the map, where contours crowd together.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageOps

FT_TO_M = 0.3048


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------
@dataclass
class TerrainOptions:
    work_size: int = 640        # long side of the elevation grid, in cells
    smoothing: float = 2.5      # how rounded the ground is (blur, % of the short side)
    detail: float = 0.45        # 0 = only big shapes, 1 = keep more of the picture's shapes
    invert: bool = False        # True = dark is high ground
    gamma: float = 1.0          # >1 makes high ground steeper, <1 flatter
    roughness: float = 0.06     # natural-looking bumps
    seed: int = 7               # changes the bumps, vegetation and course
    low_ft: float = 400.0       # lowest elevation on the map
    high_ft: float = 1400.0     # highest elevation on the map


# --------------------------------------------------------------------------
# Small image-processing helpers (no SciPy needed)
# --------------------------------------------------------------------------
def _conv1d(a: np.ndarray, k: np.ndarray, axis: int) -> np.ndarray:
    r = len(k) // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="symmetric")
    out = np.zeros_like(a, dtype=np.float64)
    n = a.shape[axis]
    for i, w in enumerate(k):
        if axis == 0:
            out += w * p[i:i + n, :]
        else:
            out += w * p[:, i:i + n]
    return out


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur with mirrored edges."""
    if sigma < 0.3:
        return a.astype(np.float64).copy()
    # A very wide blur is done on a shrunken copy (same look, far faster).
    if sigma > 12:
        f = sigma / 6.0
        h, w = a.shape
        sh, sw = max(4, int(round(h / f))), max(4, int(round(w / f)))
        small = np.asarray(Image.fromarray(a.astype(np.float32)).resize((sw, sh), Image.BILINEAR), dtype=np.float64)
        small = gaussian_blur(small, sigma / f)
        return np.asarray(Image.fromarray(small.astype(np.float32)).resize((w, h), Image.BICUBIC), dtype=np.float64)
    r = max(1, int(3 * sigma + 0.5))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-(x * x) / (2 * sigma * sigma))
    k /= k.sum()
    return _conv1d(_conv1d(a, k, 0), k, 1)


def _filter(a: np.ndarray, r: int, fn) -> np.ndarray:
    size = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    t = fn(sliding_window_view(p, size, axis=0), axis=-1)
    return fn(sliding_window_view(t, size, axis=1), axis=-1)


def max_filter(a, r):
    return _filter(a, r, np.max)


def min_filter(a, r):
    return _filter(a, r, np.min)


def fractal_noise(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for sigma in (40, 20, 10, 5, 2.5):
        layer = gaussian_blur(rng.standard_normal((h, w)), sigma * min(h, w) / 480)
        layer /= layer.std() + 1e-9
        out += amp * layer
        total += amp
        amp *= 0.55
    out /= total
    return out / (out.std() + 1e-9)


def bilinear(z: np.ndarray, r: float, c: float) -> float:
    h, w = z.shape
    r = min(max(r, 0), h - 1.001)
    c = min(max(c, 0), w - 1.001)
    r0, c0 = int(r), int(c)
    fr, fc = r - r0, c - c0
    return float(z[r0, c0] * (1 - fr) * (1 - fc) + z[r0 + 1, c0] * fr * (1 - fc)
                 + z[r0, c0 + 1] * (1 - fr) * fc + z[r0 + 1, c0 + 1] * fr * fc)


# --------------------------------------------------------------------------
# Picture -> elevation
# --------------------------------------------------------------------------
def load_picture(path: str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)   # phone photos come in sideways otherwise
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    return img.convert("RGB")


def make_elevation(img: Image.Image, opt: TerrainOptions):
    """Returns (elevation in feet [rows x cols], the picture resized to the same grid)."""
    w0, h0 = img.size
    s = opt.work_size / max(w0, h0)
    w, h = max(32, int(round(w0 * s))), max(32, int(round(h0 * s)))
    small = img.resize((w, h), Image.LANCZOS)
    a = np.asarray(small.convert("L"), dtype=np.float64) / 255.0

    lo, hi = np.percentile(a, [1, 99])
    a = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
    if opt.invert:
        a = 1.0 - a
    a = a ** max(opt.gamma, 0.05)

    sig = max(opt.smoothing, 0.2) / 100.0 * min(h, w)
    base = gaussian_blur(a, sig)
    fine = gaussian_blur(a, sig * 0.4)
    z = (1 - opt.detail) * base + opt.detail * fine
    z = (z - z.min()) / max(z.max() - z.min(), 1e-9)
    if opt.roughness > 0:
        z = z + opt.roughness * 0.18 * fractal_noise(h, w, opt.seed)
    z = gaussian_blur(z, 1.0)
    z = (z - z.min()) / max(z.max() - z.min(), 1e-9)
    z_ft = opt.low_ft + z * (opt.high_ft - opt.low_ft)
    return z_ft, small


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------
@dataclass
class Feature:
    kind: str            # Hilltop, Saddle, Depression, Valley, Draw, Ridge, Spur, Cliff
    r: float             # row (0 = north edge)
    c: float             # column (0 = west edge)
    elev_ft: float


@dataclass
class Drainage:
    lines: list = field(default_factory=list)     # [(rows, cols, accum_cells), ...]


@dataclass
class TerrainFeatures:
    hilltops: list
    depressions: list            # Feature
    saddles: list
    valleys: list
    draws: list
    ridges: list
    spurs: list
    cliffs: list                 # (Feature, (r0,c0,r1,c1), downhill unit (dr,dc))
    streams: list                # [(rows, cols, perennial: bool)]
    ridgelines: list             # [(rows, cols)] for the answer key
    acc: np.ndarray
    acc_inv: np.ndarray

    def all_points(self):
        out = []
        for name in ("hilltops", "saddles", "depressions", "valleys", "draws", "ridges", "spurs"):
            out += getattr(self, name)
        out += [cf[0] for cf in self.cliffs]
        return out


def _region(mask: np.ndarray, r: int, c: int, limit: int = 400000):
    """Flood-fill the True region containing (r, c). Returns (touches_edge, size)."""
    h, w = mask.shape
    if not mask[r, c]:
        return True, 0
    seen = np.zeros_like(mask, dtype=bool)
    q = deque([(r, c)])
    seen[r, c] = True
    edge, n = False, 0
    while q:
        y, x = q.popleft()
        n += 1
        if y == 0 or x == 0 or y == h - 1 or x == w - 1:
            edge = True
        if n > limit:
            return True, n
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                seen[yy, xx] = True
                q.append((yy, xx))
    return edge, n


def _spaced(cands, min_dist, limit, taken=()):
    """Greedy pick: keep candidates (in order) that are far enough from each other and from 'taken'."""
    out = []
    for f in cands:
        ok = all((f.r - g.r) ** 2 + (f.c - g.c) ** 2 >= min_dist ** 2 for g in list(taken) + out)
        if ok:
            out.append(f)
            if len(out) >= limit:
                break
    return out


def fill_depressions(z: np.ndarray) -> np.ndarray:
    """Priority-flood: raise every pit to its spill level (plus a tiny slope) so water
    can always run off the map. Used only for routing drainage."""
    import heapq
    h, w = z.shape
    zf = z.ravel().tolist()
    filled = list(zf)
    closed = [False] * (h * w)
    heap = []
    eps = 1e-6 * (max(zf) - min(zf) + 1)
    for i in range(h * w):
        r, c = divmod(i, w)
        if r == 0 or c == 0 or r == h - 1 or c == w - 1:
            heap.append((zf[i], i))
            closed[i] = True
    heapq.heapify(heap)
    nbs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    while heap:
        e, i = heapq.heappop(heap)
        r, c = divmod(i, w)
        for dy, dx in nbs:
            rr, cc = r + dy, c + dx
            if 0 <= rr < h and 0 <= cc < w:
                j = rr * w + cc
                if not closed[j]:
                    closed[j] = True
                    v = zf[j] if zf[j] > e + eps else e + eps
                    filled[j] = v
                    heapq.heappush(heap, (v, j))
    return np.array(filled).reshape(h, w)


def flow_accumulation(z: np.ndarray):
    """D8 flow: each cell drains to its steepest downhill neighbor.
    Returns (accumulation in cells, receiver index or -1)."""
    h, w = z.shape
    n = h * w
    zf = z.ravel()
    best_drop = np.zeros(n)
    recv = np.full(n, -1, dtype=np.int64)
    rr, cc = np.divmod(np.arange(n), w)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            yy, xx = rr + dy, cc + dx
            ok = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            nb = np.where(ok, yy * w + xx, 0)
            drop = np.where(ok, (zf - zf[nb]) / math.hypot(dy, dx), -np.inf)
            better = drop > best_drop
            best_drop = np.where(better, drop, best_drop)
            recv = np.where(better, nb, recv)
    edge = (rr == 0) | (rr == h - 1) | (cc == 0) | (cc == w - 1)
    recv[edge] = -1                      # water at the map edge leaves the map
    acc = np.ones(n)
    order = np.argsort(-zf, kind="stable")
    recv_l = recv.tolist()
    acc_l = acc.tolist()
    for i in order.tolist():
        j = recv_l[i]
        if j >= 0:
            acc_l[j] += acc_l[i]
    return np.array(acc_l).reshape(h, w), recv


def _trace_channels(acc: np.ndarray, recv: np.ndarray, thresh: float):
    """Turn the drainage network into polylines (each with per-vertex accumulation)."""
    h, w = acc.shape
    accf = acc.ravel()
    chan = accf >= thresh
    has_up = np.zeros(h * w, dtype=bool)
    src = np.nonzero(chan & (recv >= 0))[0]
    has_up[recv[src]] = True
    heads = np.nonzero(chan & ~has_up)[0]
    heads = heads[np.argsort(-accf[heads])]
    visited = np.zeros(h * w, dtype=bool)
    lines = []
    for hd in heads.tolist():
        pts = []
        i = hd
        while i >= 0 and chan[i]:
            pts.append(i)
            if visited[i]:
                break
            visited[i] = True
            i = int(recv[i])
        if len(pts) >= 3:
            arr = np.array(pts)
            r, c = np.divmod(arr, w)
            lines.append((r.astype(float), c.astype(float), accf[arr]))
    # longest lines first so main valleys get drawn/labelled first
    lines.sort(key=lambda L: -L[2].max())
    return lines


def _smooth_line(r, c, k=3):
    if len(r) < 2 * k + 1:
        return r, c
    ker = np.ones(2 * k + 1) / (2 * k + 1)
    rp = np.pad(r, k, mode="edge")
    cp = np.pad(c, k, mode="edge")
    rs = np.convolve(rp, ker, mode="valid")
    cs = np.convolve(cp, ker, mode="valid")
    rs[0], cs[0], rs[-1], cs[-1] = r[0], c[0], r[-1], c[-1]
    return rs, cs


def analyze(z: np.ndarray, cell_m: float, ci_ft: float) -> TerrainFeatures:
    h, w = z.shape
    n = h * w
    md = min(h, w)
    zs = gaussian_blur(z, 1.5)

    # ---- hilltops ----
    rpk = max(4, int(0.035 * md))
    is_max = (zs >= max_filter(zs, rpk)) & (zs - min_filter(zs, 2 * rpk) > 2 * ci_ft)
    is_max[:3, :] = is_max[-3:, :] = False
    is_max[:, :3] = is_max[:, -3:] = False
    cand = sorted(zip(*np.nonzero(is_max)), key=lambda p: -zs[p])
    hilltops = []
    for (r, c) in cand:
        top = zs[r, c]
        level = math.floor(top / ci_ft) * ci_ft
        if top - level < 1e-6:
            level -= ci_ft
        edge, size = _region(zs >= level, int(r), int(c))
        if edge or size < 4:
            continue
        hilltops.append(Feature("Hilltop", float(r), float(c), float(z[r, c])))
    hilltops = _spaced(hilltops, 0.08 * md, 8)

    # ---- depressions ----
    is_min = (zs <= min_filter(zs, rpk)) & (max_filter(zs, 2 * rpk) - zs > 1.5 * ci_ft)
    is_min[:4, :] = is_min[-4:, :] = False
    is_min[:, :4] = is_min[:, -4:] = False
    cand = sorted(zip(*np.nonzero(is_min)), key=lambda p: zs[p])
    depressions = []
    for (r, c) in cand:
        bottom = zs[r, c]
        level = math.ceil(bottom / ci_ft) * ci_ft
        if level - bottom < 1e-6:
            level += ci_ft
        edge, size = _region(zs <= level, int(r), int(c))
        if edge or size < 6:
            continue
        depressions.append(Feature("Depression", float(r), float(c), float(z[r, c])))
    depressions = _spaced(depressions, 0.08 * md, 4)

    # ---- saddles ----
    gy, gx = np.gradient(zs)
    gyy, gyx = np.gradient(gy)
    gxy, gxx = np.gradient(gx)
    det = gxx * gyy - gxy * gyx
    gm = np.hypot(gx, gy)
    cand_mask = (gm <= min_filter(gm, 3)) & (det < 0)
    cand_mask[:6, :] = cand_mask[-6:, :] = False
    cand_mask[:, :6] = cand_mask[:, -6:] = False
    cands = sorted(zip(*np.nonzero(cand_mask)), key=lambda p: gm[p])
    d = max(6, int(0.045 * md))
    saddles = []
    for (r, c) in cands[:4000]:
        H = np.array([[gyy[r, c], gyx[r, c]], [gxy[r, c], gxx[r, c]]])
        H = (H + H.T) / 2
        vals, vecs = np.linalg.eigh(H)
        if not (vals[0] < 0 < vals[1]):
            continue
        z0 = zs[r, c]
        up, down = vecs[:, 1], vecs[:, 0]
        ups = [bilinear(zs, r + s * d * up[0], c + s * d * up[1]) for s in (-1, 1)]
        downs = [bilinear(zs, r + s * d * down[0], c + s * d * down[1]) for s in (-1, 1)]
        if min(ups) > z0 + 0.75 * ci_ft and max(downs) < z0 - 0.75 * ci_ft:
            saddles.append(Feature("Saddle", float(r), float(c), float(z[r, c])))
    saddles = _spaced(saddles, 0.08 * md, 5, taken=hilltops + depressions)

    # ---- drainage: streams, valleys, draws ----
    # Routed on a half-size grid with pits filled so water can always find a way out.
    f = 2 if md >= 200 else 1
    zc = zs[::f, ::f]
    nc = zc.size
    mdc = min(zc.shape)
    lap = gxx + gyy

    def lap_at(r, c):
        return lap[min(h - 1, int(r * f)), min(w - 1, int(c * f))]

    def feat(kind, r, c):
        R, C = min(h - 1, r * f), min(w - 1, c * f)
        return Feature(kind, float(R), float(C), float(z[int(R), int(C)]))

    zfill = fill_depressions(zc)
    in_pit = (zfill - zc) > 0.25 * ci_ft          # inside a depression: no stream drawn there
    acc, recv = flow_accumulation(zfill)
    raw = _trace_channels(acc, recv, max(20, 0.010 * nc))
    t_perennial = max(100, 0.05 * nc)
    streams = []
    for (rr, cc, aa) in raw:
        dry = in_pit[rr.astype(int), cc.astype(int)]
        rs, cs = _smooth_line(rr * f, cc * f)
        cls = np.where(dry, 0, np.where(aa >= t_perennial, 2, 1))   # 0 none, 1 intermittent, 2 perennial
        start = 0
        for k in range(1, len(cls) + 1):
            if k == len(cls) or cls[k] != cls[start]:
                end = min(k + 1, len(cls))
                if cls[start] > 0 and end - start >= 2:
                    streams.append((rs[start:end], cs[start:end], bool(cls[start] == 2)))
                start = k

    pts_taken = hilltops + depressions + saddles
    spacing = 0.11 * md
    # Only label textbook examples: clearly curved contours on real slopes.
    lap_hi = float(np.percentile(lap, 82))     # strongly concave (valley/draw)
    lap_lo = float(np.percentile(lap, 18))     # strongly convex (ridge/spur)
    lap_draw = float(np.percentile(lap, 68))   # draws/spurs are smaller, so a softer bend counts
    lap_spur = float(np.percentile(lap, 32))
    g_min = float(np.percentile(gm, 45))

    g_steep = float(np.percentile(gm, 60))     # draws and spurs must be on a real slope

    def best_on_line(rr, cc, sign, lo_frac, hi_frac, gmin=None):
        """Point on a line where the contours bend hardest (sign +1 concave, -1 convex)."""
        gmin = g_min if gmin is None else gmin
        L = len(rr)
        best, best_v = None, None
        for k in range(int(lo_frac * (L - 1)), max(int(hi_frac * (L - 1)), int(lo_frac * (L - 1)) + 1)):
            R, C = min(h - 1, int(rr[k] * f)), min(w - 1, int(cc[k] * f))
            if gm[R, C] < gmin or in_pit[int(rr[k]), int(cc[k])]:
                continue
            v = sign * lap[R, C]
            if best_v is None or v > best_v:
                best, best_v = k, v
        return best, best_v

    val_c, draw_c = [], []
    for (rr, cc, aa) in raw:
        if aa.max() >= 0.03 * nc:
            k, v = best_on_line(rr, cc, +1, 0.2, 0.8)
            if k is not None and v >= lap_hi:
                val_c.append((v, feat("Valley", rr[k], cc[k])))
    # draws: the small channels near the top of the drainage (traced at a lower threshold)
    for (rr, cc, aa) in _trace_channels(acc, recv, max(8, 0.0025 * nc)):
        if aa.max() < 0.02 * nc and len(rr) >= 0.03 * mdc:
            k, v = best_on_line(rr, cc, +1, 0.2, 0.7, g_steep)
            if k is not None and v >= lap_draw:
                draw_c.append((v, feat("Draw", rr[k], cc[k])))
    valleys = _spaced([x[1] for x in sorted(val_c, key=lambda t: -t[0])], spacing, 3, taken=pts_taken)
    draws = _spaced([x[1] for x in sorted(draw_c, key=lambda t: -t[0])], spacing, 4, taken=pts_taken + valleys)

    # ---- ridges and spurs: the same flow math on upside-down ground ----
    zinv = fill_depressions(-zc)
    acc_inv, recv_inv = flow_accumulation(zinv)
    raw_r = _trace_channels(acc_inv, recv_inv, max(20, 0.010 * nc))
    ridgelines, ridge_c, spur_c = [], [], []
    for (rr, cc, aa) in raw_r:
        rs, cs = _smooth_line(rr * f, cc * f)
        ridgelines.append((rs, cs))
        if aa.max() >= 0.03 * nc:
            k, v = best_on_line(rr, cc, -1, 0.2, 0.8)
            if k is not None and v >= -lap_lo:
                ridge_c.append((v, feat("Ridge", rr[k], cc[k])))
    # spurs: short lines of high ground jutting off the ridges
    for (rr, cc, aa) in _trace_channels(acc_inv, recv_inv, max(8, 0.0025 * nc)):
        if aa.max() < 0.02 * nc and len(rr) >= 0.03 * mdc:
            k, v = best_on_line(rr, cc, -1, 0.3, 0.8, g_steep)
            if k is not None and v >= -lap_spur:
                spur_c.append((v, feat("Spur", rr[k], cc[k])))
    taken = pts_taken + valleys + draws
    ridges = _spaced([x[1] for x in sorted(ridge_c, key=lambda t: -t[0])], spacing, 3, taken=taken)
    spurs = _spaced([x[1] for x in sorted(spur_c, key=lambda t: -t[0])], spacing, 4, taken=taken + ridges)

    # ---- cliffs: steepest ground ----
    slope_deg = np.degrees(np.arctan(gm * FT_TO_M / cell_m))
    thr = max(35.0, float(np.percentile(slope_deg, 99.5)))
    steep = slope_deg >= thr
    steep[:4, :] = steep[-4:, :] = False
    steep[:, :4] = steep[:, -4:] = False
    cliffs = []
    seen = np.zeros_like(steep)
    order = sorted(zip(*np.nonzero(steep)), key=lambda p: -slope_deg[p])
    for (r, c) in order:
        if seen[r, c]:
            continue
        # collect this steep patch
        q = deque([(r, c)])
        seen[r, c] = True
        pts = []
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and steep[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
        if len(pts) < max(8, int(0.00008 * n)):
            continue
        P = np.array(pts, dtype=float)
        cy, cx = float(r), float(c)                 # steepest spot of this patch = the cliff face
        P = P[np.hypot(P[:, 0] - cy, P[:, 1] - cx) <= 0.05 * md]
        ci, cj = int(r), int(c)
        gdir = np.array([gy[ci, cj], gx[ci, cj]])
        gdir /= np.linalg.norm(gdir) + 1e-9
        downhill = -gdir                          # points toward lower ground
        along = np.array([-gdir[1], gdir[0]])     # along the cliff face
        proj = (P - [cy, cx]) @ along
        half = max(4.0, min(0.06 * md, (proj.max() - proj.min()) / 2))
        f = Feature("Cliff", float(cy), float(cx), float(z[ci, cj]))
        seg = (cy - half * along[0], cx - half * along[1], cy + half * along[0], cx + half * along[1])
        if all((f.r - g.r) ** 2 + (f.c - g.c) ** 2 >= (0.035 * md) ** 2 for g in pts_taken + [x[0] for x in cliffs]):
            cliffs.append((f, seg, (float(downhill[0]), float(downhill[1]))))
        if len(cliffs) >= 2:
            break

    return TerrainFeatures(hilltops, depressions, saddles, valleys, draws, ridges, spurs,
                           cliffs, streams, ridgelines, acc, acc_inv)


def vegetation_field(shape, seed: int, cover: float = 0.45):
    """Green woods areas (for looks and map-reading practice).
    Returns (smooth field, threshold): woods are wherever field >= threshold. Keeping the smooth
    field lets the map draw the woods as vector outlines that stay crisp at any print dpi."""
    h, w = shape
    nz = fractal_noise(h, w, seed + 101)
    nz = gaussian_blur(nz, 0.012 * min(h, w))
    t = float(np.percentile(nz, 100 * (1 - cover)))
    return nz, t


def vegetation_mask(shape, seed: int, cover: float = 0.45) -> np.ndarray:
    nz, t = vegetation_field(shape, seed, cover)
    return nz >= t
