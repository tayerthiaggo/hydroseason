"""``python -m hydroseason`` -- the same entry point as the installed script.

One parser, one execution path: a source tree or a controlled environment
without the console script installed reaches exactly the same code.
"""
from hydroseason.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
