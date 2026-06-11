#!/usr/bin/env python3
from __future__ import annotations

import argparse

from rover.renderer import render_all_modes


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Cleo rover expression PNG previews")
    parser.add_argument("--out", default="renders/expressions")
    args = parser.parse_args()
    paths = render_all_modes(args.out)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
