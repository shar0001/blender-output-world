#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_previews.py

保存済みの output/output_world.blend（または現在開いているシーン）に対して、
3カメラ（CAM_06 / CAM_07 / CAM_08）の静止画プレビューを output/v2_previews/ に
書き出す軽量スクリプト（暖かいアイボリー背景・960×540）。
build_output_world.py を再実行せずにプレビューだけを更新したいときに使う。

使い方（macOS ターミナル・ヘッドレス）::

    BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
    "$BLENDER" -b output/output_world.blend -P render_previews.py

Blender 内 Text Editor から実行した場合は、現在開いているシーンを使う。
"""

from __future__ import annotations

import os
import sys

try:
    import bpy  # noqa: F401  (存在確認のみ)
except ImportError as exc:
    raise SystemExit(
        "このスクリプトは Blender の Python から実行してください。\n"
        f"(import error: {exc})"
    )


def _this_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        import bpy as _bpy
        if _bpy.data.filepath:
            return os.path.dirname(_bpy.data.filepath)
        return os.getcwd()


def main() -> None:
    here = _this_dir()
    if here not in sys.path:
        sys.path.insert(0, here)

    # build_output_world のロジックを再利用（重複実装を避ける）
    import build_output_world as bow

    cfg = bow.load_config()
    dirs = bow.ensure_dirs(os.path.join(here, "output"))

    # シーンにフィールドが無い場合は警告（.blend を先に生成しておく）
    if bpy.data.collections.get(bow.COLLECTION_NAME) is None:
        bow.log.warning(
            "%s Collection が見つかりません。先に build_output_world.py で "
            "output_world.blend を生成してください。",
            bow.COLLECTION_NAME,
        )

    bow.setup_scene_base(cfg)
    saved = bow.render_v2_previews(cfg, dirs)
    bow.log.info("V2プレビュー %d 枚を保存しました:", len(saved))
    for p in saved:
        bow.log.info("  - %s", p)


if __name__ == "__main__":
    main()
