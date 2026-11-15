"""Draws the Moore Maps icon: a topo map tile (brown contours, blue stream, grid)
with a red compass needle. Writes assets/app.ico and assets/logo.png.

    python tools/make_icon.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                    # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Circle  # noqa: E402
import numpy as np                                 # noqa: E402
from PIL import Image                              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
os.makedirs(ASSETS, exist_ok=True)

fig = plt.figure(figsize=(10.24, 10.24), dpi=100)
fig.patch.set_alpha(0)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

outer = FancyBboxPatch((0.03, 0.03), 0.94, 0.94, boxstyle="round,pad=0,rounding_size=0.18",
                       fc="#4b5320", ec="none")
ax.add_patch(outer)
inner = FancyBboxPatch((0.075, 0.075), 0.85, 0.85, boxstyle="round,pad=0,rounding_size=0.145",
                       fc="#f4ecd6", ec="none")
ax.add_patch(inner)

# terrain: two hills and a saddle
x = np.linspace(0, 1, 400)
X, Y = np.meshgrid(x, x)
Z = (1.0 * np.exp(-((X - 0.36) ** 2 / 0.030 + (Y - 0.60) ** 2 / 0.050))
     + 0.8 * np.exp(-((X - 0.70) ** 2 / 0.020 + (Y - 0.40) ** 2 / 0.030))
     + 0.15 * np.sin(6 * X + 2 * Y))
woods = ax.contourf(X, Y, Z, levels=[0.55, 0.85], colors=["#cfe3b4"])
cs1 = ax.contour(X, Y, Z, levels=np.arange(-0.2, 1.2, 0.09), colors="#9a5b2c", linewidths=5)
cs2 = ax.contour(X, Y, Z, levels=[0.25, 0.70], colors="#6e3a15", linewidths=11)
stream, = ax.plot([0.08, 0.25, 0.42, 0.55, 0.62, 0.92], [0.12, 0.2, 0.26, 0.22, 0.12, 0.10],
                  color="#1c6dd0", lw=12, solid_capstyle="round")
grid = [ax.axvline(v, color="#222", lw=3) for v in (0.33, 0.66)] + \
       [ax.axhline(v, color="#222", lw=3) for v in (0.33, 0.66)]
for art in [woods, cs1, cs2, stream] + grid:
    art.set_clip_path(inner)

# compass needle
cx, cy, L, W = 0.74, 0.64, 0.15, 0.055
ax.add_patch(Polygon([(cx, cy + L), (cx - W, cy), (cx, cy - 0.02), (cx + W, cy)], fc="#d62a1e", ec="#222", lw=4))
ax.add_patch(Polygon([(cx, cy - L * 0.85), (cx - W, cy), (cx, cy - 0.02), (cx + W, cy)], fc="white", ec="#222", lw=4))
ax.add_patch(Circle((cx, cy), 0.022, fc="#222"))
ax.text(cx, cy + L + 0.02, "N", ha="center", va="bottom", fontsize=52, fontweight="bold", color="#222")

png = os.path.join(ASSETS, "logo.png")
fig.savefig(png, dpi=100, transparent=True)
img = Image.open(png).convert("RGBA")
img.save(os.path.join(ASSETS, "app.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", png, "and app.ico")
