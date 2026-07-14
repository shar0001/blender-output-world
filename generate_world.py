#!/usr/bin/env python3
"""Entry point for the Blender OUTPUT World generator.

Run headless with Blender::

    blender --background --python generate_world.py

Optional overrides can be passed after ``--``::

    blender --background --python generate_world.py -- --samples 128 --out output

The script adds its own directory to ``sys.path`` so the ``blender_world``
package resolves regardless of Blender's working directory.
"""

from __future__ import annotations

import argparse
import os
import sys

# Ensure the package next to this file is importable inside Blender.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Blender OUTPUT world.")
    parser.add_argument("--samples", type=int, default=None, help="Render samples.")
    parser.add_argument("--out", type=str, default=None, help="Output directory.")
    parser.add_argument("--name", type=str, default=None, help="Output file name.")
    parser.add_argument(
        "--scatter", type=int, default=None, help="Number of scattered objects."
    )
    return parser.parse_args(argv)


def _argv_after_double_dash() -> list[str]:
    """Return the CLI args Blender forwards after the ``--`` separator."""

    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def main() -> None:
    args = _parse_args(_argv_after_double_dash())

    from blender_world import build_world, default_config

    config = default_config()
    if args.samples is not None:
        config.render.samples = args.samples
    if args.out is not None:
        config.render.output_dir = args.out
    if args.name is not None:
        config.render.file_name = args.name
    if args.scatter is not None:
        config.scatter.count = args.scatter

    build_world(config)


if __name__ == "__main__":
    main()
