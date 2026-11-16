# Moore Maps: Development Log

**Developer:** John Moore
**Project:** Moore Maps, a Windows app that turns any picture into a military-style topographic training map (Python, NumPy, Matplotlib, Tkinter, PyInstaller)
**Goal:** High-interest learning material for teaching terrain features and land navigation. A picture students care about becomes the ground they learn to read.

Each entry records what was built, why, and the concepts behind it. The Git commit history on GitHub is the detailed, timestamped record of every change.

---

## 2026-11-14: v0.1.0, first version

**Idea:** Teaching terrain features from a standard map is dry. If the terrain comes from a picture the class recognizes, they pay attention, and the "reveal" at the end (fading the picture in under the contours) shows exactly how contour lines describe shape.

**Built**
- **Terrain engine** (`mooremaps/terrain.py`): picture -> brightness -> heavy blur (so it rolls like real ground) -> small random bumps -> elevation in feet between a chosen low and high.
- **Feature finder:** hilltops and depressions (closed contours that don't touch the edge, found with a flood fill), saddles (the curvature test: ground rises two ways and falls two ways), valleys/draws and ridges/spurs (D8 water-flow accumulation, run once on the ground and once on the upside-down ground), cliffs (steepest patches).
- **Map renderer** (`mooremaps/render.py`): contours, depression ticks, cliff symbols, streams, woods, 1,000-m grid with margin numbers, bar scales, declination diagram, legend; student map and instructor answer key.
- **Training packet:** exercise sheet, reference card and answer sheet, all generated from the same data so answers always match the map.
- **Desktop app** (`mooremaps/app.py`): live preview with Student / Answer key / Original tabs, all settings saved between sessions.
- **In-app updater** (`mooremaps/updater.py`): same design as Moore PC Mechanic. Checks GitHub Releases, downloads the new .exe, verifies it with a SHA-256 fingerprint, renames the running .exe out of the way (Windows allows renaming a running program but not overwriting it), moves the new one in and restarts.
- **Release pipeline** (`.github/workflows/release.yml`): raising the version number builds the .exe on GitHub's Windows server, tests it (command-line map + opening the real window), fingerprints it and publishes the Release.

**Concepts**
- Digital elevation models (DEMs) and contour interpolation; index vs. intermediate contours.
- Gaussian blur as a low-pass filter; separable convolution.
- Priority-flood depression filling and D8 flow accumulation (the same idea GIS programs use to draw streams).
- The Hessian matrix: its eigenvalues tell a hill (both negative), a pit (both positive) and a saddle (one of each) apart.
- Military grid reference: read right, then up; 6-digit = 100 m, 8-digit = 10 m. Grid vs. magnetic azimuth and the G-M angle; 6,400 mils in a circle.
- Packaging Python as a single Windows .exe; self-updating software; continuous integration.

**Tested (v0.1.0):** map generation and every page of the packet on a portrait photo and a synthetic picture; azimuth, mils and G-M math checked by hand; the updater's download, fingerprint check, swap, relaunch, cleanup and tampered-download rejection run against a local test server.

---

## 2026-11-15: v0.2.0, print up to 1200 dpi

**Asked for:** printing up to 1200 dpi.

**Problem:** a 1200 dpi tabloid map is 20,400 x 13,200 pixels (269 million). Drawing that in one piece needs over 1 GB for the drawing surface alone, and a 36 x 24 in poster at 1200 dpi would need about 5 GB, too much for a 16 GB PC with other programs open.

**Built**
- 600, 800 and 1200 dpi choices.
- **Tiled rendering** (`save_png` in `render.py`): the page is drawn in 4,096 x 4,096-pixel tiles, each cropped to exact pixel edges and pasted into the final picture. Only one tile's drawing surface exists at a time.
- **Memory check:** before saving, the app asks Windows how much memory is free (GlobalMemoryStatusEx) and, if the finished picture wouldn't fit comfortably, saves at the highest dpi that does and says so.
- **DPI written into the PNG** so it prints at true size.
- **Woods changed from a picture layer to vector shapes** (filled contours of the woods field), so edges are smooth at any resolution.
- **PDF kept vector:** maps, lines and text in the PDF are resolution-independent; only shading/photo layers are embedded at 300 dpi, which keeps the file small.

**Concepts:** raster vs. vector graphics; pixels = inches x dpi; memory cost of images (width x height x 3 bytes for RGB); tiling to bound memory; reading system memory through the Windows API with ctypes.
