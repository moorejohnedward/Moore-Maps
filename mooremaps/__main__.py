"""Start Moore Maps.

  MooreMaps.exe                      open the app
  MooreMaps.exe picture.jpg          open the app with a picture loaded
  MooreMaps.exe --cli picture.jpg OUTFOLDER [--seed N] [--dpi N]
                                     make a training packet without the window (used by the build check)
"""

import sys


def run():
    args = sys.argv[1:]
    if args and args[0] == "--cli":
        from .cli import main as cli_main
        sys.exit(cli_main(args[1:]))
    from .app import main
    main(args)


if __name__ == "__main__":
    run()
