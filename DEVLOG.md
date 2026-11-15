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

**Tested:** map generation and every page of the packet on a portrait photo and a synthetic picture; azimuth, mils and G-M math checked by hand; the updater's download, fingerprint check, swap, relaunch, cleanup and tampered-download rejection run against a local test server.
