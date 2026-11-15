"""Command-line mode: picture in, training packet out (no window)."""

import argparse
import os

from .render import MapOptions, build_model, export_all
from .terrain import TerrainOptions


def main(argv):
    ap = argparse.ArgumentParser(prog="MooreMaps --cli")
    ap.add_argument("picture")
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--title", default="TRAINING AREA")
    ap.add_argument("--paper", default="Tabloid (17 x 11 in)")
    ap.add_argument("--invert", action="store_true")
    a = ap.parse_args(argv)
    model = build_model(a.picture, TerrainOptions(seed=a.seed, invert=a.invert),
                        MapOptions(title=a.title, dpi=a.dpi, paper=a.paper))
    paths = export_all(model, a.out_dir, os.path.splitext(os.path.basename(a.picture))[0])
    f = model.feats
    print(f"Contour interval {model.ci_ft:g} ft; hilltops {len(f.hilltops)}, saddles {len(f.saddles)}, "
          f"depressions {len(f.depressions)}, valleys {len(f.valleys)}, ridges {len(f.ridges)}, "
          f"draws {len(f.draws)}, spurs {len(f.spurs)}, cliffs {len(f.cliffs)}; "
          f"{len(model.letters)} lettered points, {len(model.course) - 1 if model.course else 0} checkpoints")
    for p in paths:
        print("wrote", p)
    return 0
