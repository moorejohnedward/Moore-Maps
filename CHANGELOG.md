# Changelog - Moore Maps

## v0.2.0 - Nov 15, 2026 (Print up to 1200 dpi, shorter titles)
- **Shorter, generic titles.** The picture's file name no longer goes into the map title (it stays "TRAINING AREA" unless you type your own, and long titles are trimmed to 28 characters). The line under the title is now just "TRAINING MAP • NOT FOR NAVIGATION". Packet pages are titled "LAND NAV EXERCISE", "TERRAIN FEATURES" and "ANSWER SHEET", and exported files are named like "Training Area MM 001 - student map.png".
- **New print qualities: 600, 800 and 1200 dpi** (plus the existing 150-400). Pick them under Export > Print quality.
- **Big pictures without running out of memory.** High-dpi maps are drawn in tiles of at most 4,096 x 4,096 pixels and joined, so a 1200 dpi tabloid map (20,400 x 13,200 pixels) saves fine on a 16 GB PC. If a size still wouldn't fit in free memory (for example a 36 x 24 in poster at 1200 dpi), the PNGs drop to the highest dpi that fits and the app tells you.
- **The dpi is saved inside the PNG files,** so photo programs and printers print them at the right size (an 11 x 17 in map prints at 11 x 17 in).
- **Woods are now vector shapes,** so their edges stay smooth at any dpi instead of looking blocky up close.
- **The PDF training packet stays small and sharp:** its maps are vector (printers draw them at their full resolution, 1200 dpi or more), with only relief shading and the picture underlay saved at 300 dpi.
- Export shows its progress in the status bar (for example "Saving the student map at 1200 dpi… 45%").

## v0.1.0 - Nov 14, 2026 (First version)
- **Any picture becomes a topographic training map.** Bright = high ground, dark = low ground (or the reverse with Invert). Sliders for picture likeness, smoothness, natural bumps and peak steepness; a random seed reshuffles the details.
- **Military map look:** brown contours with every 5th one heavier and numbered, depression contours with tick marks, cliff symbols, blue perennial and intermittent streams, green woods, spot elevations on hilltops, a black 1,000-meter grid numbered in the margin.
- **Marginal information:** title and sheet number, scale, bar scales in meters, yards and statute miles, contour interval in feet, legend, declination diagram with the G-M angle in degrees and mils, and grid reference instructions.
- **Automatic terrain features:** hilltops, saddles, depressions, valleys, ridges, draws, spurs and cliffs are found and lettered A, B, C… on the student map.
- **Land-nav course:** a start point and up to 10 checkpoints on real terrain features, with legs of 400-1,800 m that never cross each other.
- **Training packet PDF:** student map, exercise sheet, terrain feature reference card, instructor answer-key map and answer sheet (8-digit grids, elevations, grid and magnetic azimuths in degrees and mils, distances in meters and yards, total distance and pace count).
- **Paper sizes** from Letter to 36 x 24 in poster, at 150-400 dpi. Scales 1:10,000, 1:24,000, 1:25,000 and 1:50,000.
- **In-app updates** from GitHub Releases with a SHA-256 safety check, "Skip this version" and a start-up check you can turn off.
