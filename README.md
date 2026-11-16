# Moore Maps

Turn **any picture** into a **military-style topographic training map**: brown contour lines with numbered index contours, blue streams, green woods, a 1,000-meter grid, bar scales in meters, yards and miles, and a declination diagram. Built for teaching **terrain features** and **land navigation** with high-interest material.

Every map comes with a ready-to-teach **training packet** (PDF):

1. **Student map** with lettered points (A, B, C…) and a land-nav course (SP + checkpoints)
2. **Exercise sheet**: name the terrain feature at each letter, plot the course from 8-digit grids, find azimuths and distances, read elevations
3. **Terrain feature reference card**: the 5 major and 3 minor features, the fist trick, reading a grid
4. **Instructor answer-key map**: every point labeled, ridgelines marked, course legs drawn with azimuths and distances
5. **Answer sheet**: features with grids and elevations, grid and magnetic azimuths (degrees and mils), distances in meters and yards, total course length and a pace-count estimate

## Get it running

**Easiest:** download `MooreMaps.exe` from this project's **Releases** page and run it. No install needed.

**Build it yourself:** double-click `Build-Exe.bat`. It installs what it needs and builds one self-contained `MooreMaps.exe` into `Release (app to run and share)`. Needs Python 3.12 from python.org (tick "Add python.exe to PATH").

**From source:** `Run-From-Source.bat` (or `python MooreMaps.py`).

## Using it

1. **Open picture…** Bright areas become high ground, dark areas low ground. Tick **Invert** to flip that.
2. Slide **Picture likeness** and **Smoothness** until the hills and valleys look right. **Natural bumps** adds small knolls; **Peak steepness** makes high ground steeper. **New random** reshuffles the bumps, woods, lettered points and course without changing the picture's shape.
3. Set the **elevation range** (feet) and **contour interval** (Auto picks 10, 20 or 40 ft and so on).
4. Fill in the **map title**, **sheet number**, **scale** (1:25,000 is a good classroom scale) and **paper size** (Letter to 36 x 24 in poster).
5. Check the **Answer key** tab, then **Export training packet…** (PNG maps at print quality plus the PDF packet). Exports go to `Documents\Moore Maps` by default.

**Print quality:** 150 to 1200 dpi. 300 dpi is print-shop quality; 600-1200 dpi is for fine-line printers and large posters. High-dpi PNGs are drawn in tiles so they fit in memory, and carry their dpi so they print at the right size. The PDF's maps are vector, so the PDF prints sharp at any printer resolution.

**Show picture under map** fades the original picture in beneath the contours, so you can do the "reveal" at the end of a class.

## How the terrain features are found

- **Hilltop**: highest point inside a closed contour that doesn't touch the map edge.
- **Depression**: lowest point inside a closed contour, drawn with tick marks pointing in.
- **Saddle**: ground rises two ways and falls two ways (checked along the curvature directions).
- **Valley / Draw**: water-flow paths. Every spot drains to its steepest downhill neighbor; paths that collect water from a large area are valleys (and streams), small ones are draws. Only spots where the contours bend sharply on real slopes get a letter.
- **Ridge / Spur**: the same flow math run on upside-down ground. Long lines of high ground are ridges, short ones jutting off them are spurs.
- **Cliff**: the steepest ground on the map, drawn with the cliff symbol (tick marks toward low ground).

Feature detection is automatic, so **look over the answer key before class**. If a letter isn't a clean example, click **New random** or nudge Smoothness.

## Updates

After the first copy, you never need to rebuild for an upgrade. Click **Check for updates** (top right). The app also checks quietly when it starts and shows a green banner when a new version is out. It downloads the new version from this project's GitHub Releases, checks its SHA-256 fingerprint, swaps itself and restarts. **Skip this version** and the start-up check are under the banner and the Help menu.

**How a new version gets published:** add an entry at the top of `CHANGELOG.md` (`## v0.2.0 - date`), raise `__version__` in `mooremaps/__init__.py` to match, commit and push to `main`. GitHub Actions sees the new version number, builds `MooreMaps.exe` on Windows, tests it (makes a map from the command line and opens the real window), fingerprints it and posts the Release. The changelog entry becomes the "What's new" text in the app.

School/progress record: `DEVLOG.md` and the commit history.

## Command line

```
MooreMaps.exe picture.jpg                       open the app with a picture loaded
MooreMaps.exe --cli picture.jpg OUTFOLDER       make a training packet with no window
                [--seed N] [--dpi N] [--title "NAME"] [--invert]
```

## Built with

Python 3.12, NumPy, Pillow, Matplotlib, Tkinter with the Sun Valley theme (sv-ttk), packaged with PyInstaller.

## Roadmap

- AI depth mode: use a depth-estimation model so a photo's real 3D shape becomes the ground (faces and bodies become true hills, backgrounds become valleys)
- Roads and trails with cuts and fills (the two supplementary terrain features)
- Click-to-zoom preview and click-a-point grid readout
- Night-land-nav and terrain-association question sets
- Print tiling for big maps on letter paper
