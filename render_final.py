#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_final.py

保存済みの output/output_world.blend から、After Effects 用の本番連番を書き出す。

  * 1920×1080 / 24fps / 背景透過（RGBA）
  * 形式は config.json の output_format（PNG 16bit / OpenEXR）
  * ショットごとに output/render/<ショット名>/<ショット名>_####.png
    （フレーム番号は通しの番号。例: 06 は 0121〜0152）
  * .blend は保存しない（読み込んで描くだけ）

使い方（macOS ターミナル。リポジトリのフォルダで実行）::

    BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

    # まず1フレームだけ試して、1フレームあたりの時間を確認
    "$BLENDER" -b output/output_world.blend -P render_final.py -- --test 200

    # 全ショット（01〜09）を書き出す
    "$BLENDER" -b output/output_world.blend -P render_final.py -- all

    # 一部のショットだけ
    "$BLENDER" -b output/output_world.blend -P render_final.py -- 06 07
"""

from __future__ import annotations

import os
import sys
import time

try:
    import bpy
except ImportError as exc:
    raise SystemExit(
        "このスクリプトは Blender の Python から実行してください。\n"
        f"(import error: {exc})"
    )


def _this_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        if bpy.data.filepath:
            return os.path.dirname(os.path.dirname(bpy.data.filepath))
        return os.getcwd()


def _args() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def main() -> None:
    here = _this_dir()
    if here not in sys.path:
        sys.path.insert(0, here)
    import build_output_world as bow

    if bpy.data.collections.get(bow.COLLECTION_NAME) is None:
        raise SystemExit(
            f"{bow.COLLECTION_NAME} が見つかりません。output/output_world.blend を開いて実行するか、"
            "先に build_output_world.py で生成してください。"
        )
    scene = bpy.data.scenes.get(bow.SCENE_NAME) or bpy.context.scene
    if bpy.context.window is not None:
        bpy.context.window.scene = scene

    cfg = bow.load_config()
    dirs = bow.ensure_dirs(os.path.join(here, "output"))
    args = _args()

    if args[:1] == ["--test"]:
        frame = int(args[1]) if len(args) > 1 else bow.SHOT_HERO[1]
        bow.apply_final_settings(cfg)
        bow._apply_image_format(scene, cfg, transparent=True)
        scene.frame_set(frame)
        ext = "exr" if cfg["output_format"] == "OPEN_EXR" else "png"
        out = os.path.join(dirs["render"], "_test", f"test_{frame:04d}.{ext}")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        scene.render.filepath = out
        t = time.time()
        bpy.ops.render.render(write_still=True, scene=scene.name)
        sec = time.time() - t
        total = sec * (bow.FRAME_END - bow.FRAME_START + 1)
        bow.log.info("テスト描画: frame %d → %s", frame, out)
        bow.log.info("1フレーム %.1f 秒 → 全 %d フレームの目安 %.0f 分",
                     sec, bow.FRAME_END - bow.FRAME_START + 1, total / 60.0)
        return

    keys = list(bow.SHOT_TABLE) if (not args or args == ["all"]) else [a.zfill(2) for a in args]
    unknown = [k for k in keys if k not in bow.SHOT_TABLE]
    if unknown:
        raise SystemExit(f"未知のショット: {', '.join(unknown)}（01〜09 または all）")

    t_all = time.time()
    for key in keys:
        t = time.time()
        shot_dir = bow.render_shot(key, cfg, dirs)
        bow.log.info("ショット %s 完了: %.1f 分 → %s", key, (time.time() - t) / 60.0, shot_dir)
    bow.log.info("全 %d ショット完了: %.1f 分 / 出力先 %s",
                 len(keys), (time.time() - t_all) / 60.0, dirs["render"])


if __name__ == "__main__":
    main()
