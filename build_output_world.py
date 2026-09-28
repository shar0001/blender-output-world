#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_output_world.py  (art pass v3)

ストーリーボード後半3カット
  06 OUTPUT EMERGENCE / 07 DIVE THROUGH OUTPUT / 08 HERO REVEAL
のための、再実行可能な Blender 自動構築システム。

1個の角丸Cube(OW_SourceCube)を Geometry Nodes でインスタンス化し、青いブロック
群からなる OUTPUT フィールドを構築する。個別オブジェクトは生成しない
（Realize Instances 不使用）。

v2 の主な改善:
  * マテリアルを OW_SourceCube へ割り当て（インスタンスが正しく継承）。
  * 鮮やかなコバルトブルー + 約1〜2% のシグナルレッド（INSTANCER属性、
    読めない場合でも既定でコバルト＝グレーにならない安全設計）。
  * 3つの非対称ピーク + 低/中周波ノイズ + 前中後の高さリズム。
  * 生成の波にオーバーシュートと時間差（8〜12F の余韻）。
  * DIVE 用にプロシージャルな低ブロックの「データチャネル」。
  * カメラをグリッド軸から約7°ずらし、黒い溝を目立たなくする。
  * 発光球を小型・スムーズ化し Principled+Emission で立体感。
  * プレビューは暖かいアイボリー背景（最終は透過、実行後に設定復元）。

v3（参考ストーリーボードのルックに寄せる）:
  * 色管理を Standard に固定（AgX による彩度低下を回避）。
  * 140×140=19,600 ブロックの高密度フィールド（個別オブジェクトは作らない）。
  * ブロックの縦グラデーション（根元の濃い青 → 電気的ブルー → 頂部ライラック）。
  * カメラ距離による空気遠近（霞）。距離はショットごとにキー（CONSTANT）。
  * 背景は見た目アイボリー1.0、照明としては弱い青寄り環境光（Light Path）。
  * 浮遊粒子・縦データライン+ドット・地面を GN 内で生成（インスタンス / 1メッシュ）。
  * DIVE 用データチャネルは 07 の間だけ開き、両脇にランダムな高さの壁を立てる。
  * コンポジタの Glare(Bloom) で発光部をにじませる。

Blender 5.1.2 対応:
  * EEVEE エンジン名を自動選択。
  * スロット化 Action(Layer/Strip/Channelbag) の F-Curve を辿って補間を設定。
  * ShaderNodeMix(RGBA) を型安全に使用（レガシー MixRGB 非依存）。

安全性:
  * OUTPUT_WORLD Collection と接頭辞 "OW_" のデータブロックのみ再生成。
  * 他 Collection / データには触れない。ファイル削除はしない（バックアップは copy）。
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import sys
import traceback
from datetime import datetime

try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError as exc:  # Blender 外で import された場合
    raise SystemExit(
        "このスクリプトは Blender の Python から実行してください。"
        "例: blender --background --python build_output_world.py\n"
        f"(import error: {exc})"
    )


# --------------------------------------------------------------------------- #
# 定数（この接頭辞と Collection 名のみを再生成対象とする）                       #
# --------------------------------------------------------------------------- #
PREFIX = "OW_"
COLLECTION_NAME = "OUTPUT_WORLD"
SCENE_NAME = PREFIX + "Scene"  # 専用シーン（起動時のデフォルト Cube 等が映り込まない）

GN_GROUP_NAME = PREFIX + "GeometryNodes"
CUBE_MESH_NAME = PREFIX + "SourceCube"
CUBE_OBJ_NAME = PREFIX + "SourceCube"     # インスタンス元（マテリアルはここへ割当）
FIELD_OBJ_NAME = PREFIX + "Field"
MAT_BLOCK_NAME = PREFIX + "Mat_Block"
MAT_ORB_NAME = PREFIX + "Mat_Orb"
MAT_LINE_NAME = PREFIX + "Mat_DataLine"

RED_ATTR_NAME = "block_red"  # INSTANCE ドメイン属性（Shader は INSTANCER で読む）
HEIGHT_ATTR_NAME = "block_h"  # 正規化した最終高さ 0..1（頂部の明るさに使う）
MAT_ACCENT_NAME = PREFIX + "Mat_Accent"

CAM_EMERGENCE = PREFIX + "CAM_06_EMERGENCE"
CAM_DIVE = PREFIX + "CAM_07_DIVE"
CAM_HERO = PREFIX + "CAM_08_HERO"

TARGET_06 = PREFIX + "TARGET_06"
TARGET_DIVE = PREFIX + "TARGET_DIVE"
TARGET_08 = PREFIX + "TARGET_08"
CAM_PRELUDE = PREFIX + "CAM_01_05_CORE"
CAM_FINISH = PREFIX + "CAM_09_FINISH"
TARGET_PRELUDE = PREFIX + "TARGET_CORE"
TARGET_FINISH = PREFIX + "TARGET_09"
MAT_CORE_NAME = PREFIX + "Mat_Core"
PRELUDE_CENTER = (0.0, 80.0, 40.0)
NET_WOBBLE = 0.22          # ネットワークの点のゆらぎ量（m）
PULSE_EDGE_RATIO = 0.45    # 光の粒が走る線の割合  # 01〜05 はフィールドから離れた上空で撮る

# フィールドをグリッド軸から少し回す（黒い溝を目立たなくする, 5〜9°）
FIELD_ROT_Z_DEG = 7.0

BLOCK_FILL = 0.92  # block幅 = spacing * BLOCK_FILL（0.90〜0.93）

HERO_ORB_COUNT = 3

# タイムライン
FRAME_START = 1
FRAME_END = 264
FPS = 24
# 01〜05: コア（ネットワーク→収束→静止→点火→解放）
SHOT_CONNECT = (1, 24)
SHOT_COLLAPSE = (25, 48)
SHOT_SYNC = (49, 72)
SHOT_IGNITION = (73, 96)
SHOT_RELEASE = (97, 120)
# 06〜08: OUTPUT フィールド
SHOT_EMERGENCE = (121, 152)
SHOT_DIVE = (153, 184)
SHOT_HERO = (185, 216)
# 09: フィニッシュ（正面・球体からデータラインが降りる）
SHOT_FINISH = (217, 264)

RES_X = 1920
RES_Y = 1080

# 色（sRGB hex → 後で linear 変換）
COBALT_HEX = "#163CFF"
SIGNAL_RED_HEX = "#FF3048"

# v3 ルック: ブロックの縦グラデーション（根元→中腹→頂部）
BLOCK_DEEP_HEX = "#1226E6"
BLOCK_ELECTRIC_HEX = "#3450FF"
BLOCK_TOP_HEX = "#AEB0FF"
# 空気遠近（遠景をアイボリー〜ライラックに溶かす）
BG_IVORY_HEX = "#F4EEE6"
HAZE_HEX = "#ECE6F4"
FOG_START = 16.0
FOG_END = 78.0
FOG_MAX = 0.92
ACCENT_HEX = "#C9C4FF"  # 粒子・縦ライン
FOG_NODE_NAME = "OW_Fog"
FOG_CLEAR_FRAMES = 12  # 05 の閃光 → 06 で霞が晴れるまでのフレーム数
CHANNEL_Y_END = 14.0  # データチャネル(DIVE)を置くローカル Y の上限
# ショットごとの霞の距離（カメラ距離が違うため）: (開始m, 終了m)
FOG_PER_SHOT = {"06": (14.0, 70.0), "07": (8.0, 48.0), "08": (26.0, 88.0), "09": (26.0, 95.0)}
WORLD_LIGHT_STRENGTH = 0.28  # 背景は見た目1.0、照明としては弱く
PARTICLE_COUNT = 380
RISE_RATIO = 0.035   # 09 で小キューブ列を立てる塔の割合（中央寄り）
RISE_STACK = 7      # 1列あたりの小キューブ数
LOOKDEV_PREVIEW = True
PREVIEW_SHOTS = set()  # 空=全ショット。CLI: -- --preview-shots 01,05,09  # プレビューでも DOF/モーションブラーを入れて見た目を確認
LINE_RATIO = 0.0018


# --------------------------------------------------------------------------- #
# ロギング                                                                     #
# --------------------------------------------------------------------------- #
log = logging.getLogger("output_world")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[OUTPUT_WORLD] %(levelname)s: %(message)s"))
    log.addHandler(_h)
log.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# 色ユーティリティ                                                              #
# --------------------------------------------------------------------------- #
def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear_rgba(hex_str: str, alpha: float = 1.0):
    """'#RRGGBB' を Blender の linear RGBA タプルへ変換。"""
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b), alpha)


# --------------------------------------------------------------------------- #
# 設定ロード                                                                   #
# --------------------------------------------------------------------------- #
def script_dir() -> str:
    """スクリプトのあるディレクトリ（Text Editor 実行にも対応）。"""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        if bpy.data.filepath:
            return os.path.dirname(bpy.data.filepath)
        return os.getcwd()


CONFIG_DEFAULTS = {
    "grid_x": 32,
    "grid_y": 32,
    "spacing": 1.0,
    "min_height": 0.4,
    "max_height": 9.0,
    "noise_scale": 2.2,
    "noise_strength": 1.0,
    "center_peak_strength": 1.0,
    "build_start_frame": 121,
    "build_end_frame": 152,
    "red_ratio": 0.015,
    "random_seed": 20260714,
    "preview_resolution_percentage": 50,
    "final_resolution_percentage": 100,
    "output_format": "PNG",
}


def load_config() -> dict:
    """config.json を読み、既定値とマージして返す。"""
    path = os.path.join(script_dir(), "config.json")
    cfg = dict(CONFIG_DEFAULTS)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                user = json.load(fp)
            if not isinstance(user, dict):
                raise ValueError("config.json はオブジェクト(辞書)である必要があります。")
            unknown = set(user) - set(CONFIG_DEFAULTS)
            if unknown:
                log.warning("config.json の未知キーを無視します: %s", ", ".join(sorted(unknown)))
            cfg.update({k: v for k, v in user.items() if k in CONFIG_DEFAULTS})
            log.info("config.json を読み込みました: %s", path)
        except Exception as exc:  # noqa: BLE001 - 原因を明示して既定値へ
            log.error("config.json の読み込みに失敗しました (%s)。既定値を使用します。", exc)
    else:
        log.warning("config.json が見つかりません (%s)。既定値を使用します。", path)

    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict) -> None:
    """値域を検証し、危険な値を早期に弾く。"""
    def _pos_int(key):
        v = int(cfg[key])
        if v < 2:
            raise ValueError(f"{key} は 2 以上にしてください (現在 {v})")
        cfg[key] = v

    _pos_int("grid_x")
    _pos_int("grid_y")
    cfg["spacing"] = float(cfg["spacing"])
    cfg["min_height"] = float(cfg["min_height"])
    cfg["max_height"] = float(cfg["max_height"])
    if cfg["max_height"] <= cfg["min_height"]:
        raise ValueError("max_height は min_height より大きくしてください。")
    cfg["red_ratio"] = min(max(float(cfg["red_ratio"]), 0.0), 1.0)
    cfg["random_seed"] = int(cfg["random_seed"])
    fmt = str(cfg["output_format"]).upper()
    if fmt in ("PNG",):
        cfg["output_format"] = "PNG"
    elif fmt in ("EXR", "OPEN_EXR", "OPENEXR"):
        cfg["output_format"] = "OPEN_EXR"
    else:
        log.warning("未対応の output_format '%s' -> PNG を使用します。", fmt)
        cfg["output_format"] = "PNG"

    total = cfg["grid_x"] * cfg["grid_y"]
    if total > 500000:
        log.warning("インスタンス数が非常に多いです (%d)。プレビューが重くなる可能性があります。", total)


# --------------------------------------------------------------------------- #
# バージョン差の吸収ヘルパー                                                     #
# --------------------------------------------------------------------------- #
def blender_version() -> tuple:
    return tuple(bpy.app.version)


def new_interface_socket(group, name, in_out, socket_type):
    """ノードグループの入出力ソケットを作る（4.0+ / 3.x 両対応）。"""
    if hasattr(group, "interface"):  # Blender 4.0+
        return group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    coll = group.inputs if in_out == "INPUT" else group.outputs
    return coll.new(socket_type, name)


def set_eevee_engine(scene) -> str:
    """Blender バージョンに応じた EEVEE エンジンを設定して名称を返す。

    * 4.2 系のみ 'BLENDER_EEVEE_NEXT'
    * 4.3+ / 5.x は 'BLENDER_EEVEE'（EEVEE Next が既定名に統合）
    """
    v = blender_version()
    if (4, 2, 0) <= v < (4, 3, 0):
        candidates = ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]
    else:
        candidates = ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]
    for name in candidates:
        try:
            scene.render.engine = name
            log.info("レンダーエンジン: %s (Blender %s)", name, bpy.app.version_string)
            return name
        except Exception:  # noqa: BLE001 - 無効なエンジン名は次候補へ
            continue
    log.warning("EEVEE を設定できませんでした。既定のエンジンを使用します。")
    return scene.render.engine


# --------------------------------------------------------------------------- #
# バックアップ / 掃除（安全な再生成）                                            #
# --------------------------------------------------------------------------- #
def ensure_dirs(base_out: str) -> dict:
    dirs = {
        "out": base_out,
        "previews": os.path.join(base_out, "previews"),
        "v2_previews": os.path.join(base_out, "v2_previews"),
        "render": os.path.join(base_out, "render"),
        "backups": os.path.join(base_out, "backups"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


def backup_existing_blend(dirs: dict) -> None:
    """既存 output_world.blend を安全にコピー（削除は一切しない）。"""
    target = os.path.join(dirs["out"], "output_world.blend")
    if os.path.isfile(target):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(dirs["backups"], f"output_world_{stamp}.blend")
        try:
            shutil.copy2(target, dst)
            log.info("バックアップを作成しました: %s", dst)
        except OSError as exc:
            log.error("バックアップ作成に失敗しました (%s)。処理は続行します。", exc)
    else:
        log.info("既存 .blend が無いためバックアップはスキップします。")


def purge_previous() -> None:
    """OUTPUT_WORLD Collection と OW_ データブロックのみを削除。

    他 Collection / 他データには触れない。ファイルは削除しない。
    """
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is not None:
        for obj in list(coll.objects):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except (RuntimeError, ReferenceError) as exc:
                log.warning("オブジェクト削除に失敗: %s (%s)", getattr(obj, "name", "?"), exc)
        try:
            bpy.data.collections.remove(coll)
        except (RuntimeError, ReferenceError) as exc:
            log.warning("Collection 削除に失敗: %s (%s)", COLLECTION_NAME, exc)

    for coll_data in (
        bpy.data.objects,
        bpy.data.node_groups,
        bpy.data.materials,
        bpy.data.meshes,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.worlds,
        bpy.data.curves,
    ):
        for block in list(coll_data):
            if block.name.startswith(PREFIX):
                try:
                    coll_data.remove(block)
                except (RuntimeError, ReferenceError):
                    pass

    scene = bpy.context.scene
    for marker in list(scene.timeline_markers):
        cam = marker.camera
        if marker.name.startswith(PREFIX) or (cam is not None and cam.name.startswith(PREFIX)):
            scene.timeline_markers.remove(marker)

    log.info("前回生成物(OUTPUT_WORLD / %s*)を掃除しました。", PREFIX)


def use_output_scene() -> "bpy.types.Scene":
    """専用シーン OW_Scene を作って（または再利用して）アクティブにする。

    元のシーン（起動時のデフォルト Cube / Light や、ユーザーのオブジェクト）には
    一切触れず、それらがレンダーに映り込むこともない。
    """
    scene = bpy.data.scenes.get(SCENE_NAME) or bpy.data.scenes.new(SCENE_NAME)
    win = bpy.context.window
    if win is None and bpy.context.window_manager.windows:
        win = bpy.context.window_manager.windows[0]
    if win is not None:
        win.scene = scene
    if bpy.context.scene != scene:
        raise RuntimeError(f"専用シーン {SCENE_NAME} をアクティブにできませんでした。")
    others = [o.name for o in scene.objects if not o.name.startswith(PREFIX)]
    if others:
        log.warning("%s に OW_ 以外のオブジェクトがあります（触れません）: %s",
                    SCENE_NAME, ", ".join(others[:10]))
    log.info("専用シーン: %s（元のシーンには触れません）", SCENE_NAME)
    return scene


def get_world_collection() -> "bpy.types.Collection":
    coll = bpy.data.collections.new(COLLECTION_NAME)
    bpy.context.scene.collection.children.link(coll)
    return coll


def link_to_world(coll, obj) -> None:
    coll.objects.link(obj)


# --------------------------------------------------------------------------- #
# 角丸 Cube（1個だけ・マテリアル継承元）                                          #
# --------------------------------------------------------------------------- #
def create_source_cube(coll) -> "bpy.types.Object":
    """底面 z=0 / 上面 z=1 の単位角丸Cubeを1個だけ作成（隠しソース）。"""
    mesh = bpy.data.meshes.new(CUBE_MESH_NAME)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    try:
        bmesh.ops.bevel(
            bm,
            geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            offset=0.035,
            segments=2,
            profile=0.7,
            affect="EDGES",
        )
    except (TypeError, ValueError) as exc:
        log.warning("ベベルをスキップしました（バージョン差の可能性）: %s", exc)

    bmesh.ops.translate(bm, verts=list(bm.verts), vec=(0.0, 0.0, 0.5))  # 底面 z=0
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(CUBE_OBJ_NAME, mesh)
    obj.location = (0.0, 0.0, 0.0)
    obj.hide_render = True
    obj.hide_viewport = True
    link_to_world(coll, obj)
    return obj


# --------------------------------------------------------------------------- #
# マテリアル                                                                    #
# --------------------------------------------------------------------------- #
def _ensure_material_nodes(mat):
    """Principled BSDF と Material Output を確実に用意して返す。

    Blender のバージョンによって、新規マテリアルに既定ノードが入っていない/
    名前が違う場合がある（5.1 で確認）。無ければ作ってつなぐ。
    """
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (0, 0)
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    bsdf.name = "Principled BSDF"
    out.name = "Material Output"
    if not out.inputs["Surface"].is_linked:
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf, out


def _principled(mat):
    return _ensure_material_nodes(mat)[0]


def _mix_rgba(nt, loc, fac_socket, color1, color2):
    """ShaderNodeMix(RGBA) を型安全に作る（レガシー MixRGB 非依存）。

    Blender 3.4+ / 4.x / 5.x で利用可能。戻り値は結果カラー出力ソケット。
    """
    n = nt.nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.location = loc
    fac_in = next(s for s in n.inputs if s.name == "Factor" and s.type == "VALUE")
    a_in = next(s for s in n.inputs if s.name == "A" and s.type == "RGBA")
    b_in = next(s for s in n.inputs if s.name == "B" and s.type == "RGBA")
    out = next(s for s in n.outputs if s.name == "Result" and s.type == "RGBA")
    a_in.default_value = color1
    b_in.default_value = color2
    nt.links.new(fac_socket, fac_in)
    return out


def create_block_material(cfg) -> "bpy.types.Material":
    """v3 ルック: 根元の濃い青 → 電気的ブルー → 頂部ライラックの縦グラデーション。

    * 縦方向: インスタンス元Cubeのローカル座標 z(0..1) = ブロック内の高さ。
    * 高い塔ほど頂部が明るい（INSTANCER 属性 block_h）。
    * 赤ノード: INSTANCER 属性 block_red。読めない場合は青のまま（グレーにならない）。
    * 空気遠近: カメラ距離でアイボリー〜ライラックの霞へ溶かす。
    """
    deep = hex_to_linear_rgba(BLOCK_DEEP_HEX)
    electric = hex_to_linear_rgba(BLOCK_ELECTRIC_HEX)
    top = hex_to_linear_rgba(BLOCK_TOP_HEX)
    signal_red = hex_to_linear_rgba(SIGNAL_RED_HEX)
    haze = hex_to_linear_rgba(HAZE_HEX)

    mat = bpy.data.materials.new(MAT_BLOCK_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf, out = _ensure_material_nodes(mat)

    # --- 入力 ---
    tex = nodes.new("ShaderNodeTexCoord"); tex.location = (-1500, 300)
    sep = nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1320, 300)
    links.new(tex.outputs["Object"], sep.inputs["Vector"])
    local_z = sep.outputs["Z"]  # 0=根元, 1=頂部

    a_h = nodes.new("ShaderNodeAttribute"); a_h.location = (-1500, 60)
    a_h.attribute_type = "INSTANCER"
    a_h.attribute_name = HEIGHT_ATTR_NAME
    a_red = nodes.new("ShaderNodeAttribute"); a_red.location = (-1500, -160)
    a_red.attribute_type = "INSTANCER"
    a_red.attribute_name = RED_ATTR_NAME

    geo = nodes.new("ShaderNodeNewGeometry"); geo.location = (-1500, -380)
    sep_n = nodes.new("ShaderNodeSeparateXYZ"); sep_n.location = (-1320, -380)
    links.new(geo.outputs["Normal"], sep_n.inputs["Vector"])

    # --- グラデーション係数 g = z * (0.3 + 0.7*h) + 上面ブースト ---
    def m(op, loc, a, b=None):
        n = nodes.new("ShaderNodeMath"); n.operation = op; n.location = loc
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                links.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    h_w = m("MULTIPLY_ADD", (-1120, 60), a_h.outputs["Fac"], 0.8)
    h_w.node.inputs[2].default_value = 0.2
    z2 = m("POWER", (-1120, 240), local_z, 2.8)
    g = m("MULTIPLY", (-940, 200), z2, h_w)
    top_face = nodes.new("ShaderNodeMapRange"); top_face.location = (-1120, -380)
    top_face.inputs["From Min"].default_value = 0.5
    top_face.inputs["From Max"].default_value = 0.95
    top_face.inputs["To Min"].default_value = 0.0
    top_face.inputs["To Max"].default_value = 0.30
    links.new(sep_n.outputs["Z"], top_face.inputs["Value"])
    g2 = m("ADD", (-760, 120), g, top_face.outputs["Result"])

    ramp = nodes.new("ShaderNodeValToRGB"); ramp.location = (-580, 160)
    els = ramp.color_ramp.elements
    els[0].position = 0.0; els[0].color = deep
    els[1].position = 1.0; els[1].color = top
    mid = els.new(0.40); mid.color = electric
    links.new(g2, ramp.inputs["Fac"])

    col = _mix_rgba(nt, (-300, 200), a_red.outputs["Fac"], (0, 0, 0, 1), signal_red)
    # A 側を ramp にするため Mix を作り直す
    mix_node = col.node
    a_in = next(s for s in mix_node.inputs if s.name == "A" and s.type == "RGBA")
    links.new(ramp.outputs["Color"], a_in)

    emit_strength = m("MULTIPLY_ADD", (-300, -80), a_red.outputs["Fac"], 2.6)
    emit_strength.node.inputs[2].default_value = 0.34  # 青=0.34, 赤=2.94

    if bsdf is not None:
        links.new(col, bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.42
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.05
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.35
        for ename in ("Emission Color", "Emission"):
            if ename in bsdf.inputs:
                links.new(col, bsdf.inputs[ename])
                break
        if "Emission Strength" in bsdf.inputs:
            links.new(emit_strength, bsdf.inputs["Emission Strength"])

    # --- 空気遠近: カメラ距離 → 霞(Emission)へミックス ---
    cam = nodes.new("ShaderNodeCameraData"); cam.location = (-300, -300)
    fog = nodes.new("ShaderNodeMapRange"); fog.location = (-120, -300)
    fog.name = FOG_NODE_NAME
    fog.interpolation_type = "SMOOTHSTEP"
    fog.inputs["From Min"].default_value = FOG_START
    fog.inputs["From Max"].default_value = FOG_END
    fog.inputs["To Min"].default_value = 0.0
    fog.inputs["To Max"].default_value = FOG_MAX
    links.new(cam.outputs["View Distance"], fog.inputs["Value"])
    haze_em = nodes.new("ShaderNodeEmission"); haze_em.location = (60, -200)
    haze_em.inputs["Color"].default_value = haze
    haze_em.inputs["Strength"].default_value = 1.0
    mix_sh = nodes.new("ShaderNodeMixShader"); mix_sh.location = (260, 0)
    links.new(fog.outputs["Result"], mix_sh.inputs["Fac"])
    if bsdf is not None:
        links.new(bsdf.outputs["BSDF"], mix_sh.inputs[1])
    links.new(haze_em.outputs["Emission"], mix_sh.inputs[2])
    if out is not None:
        out.location = (460, 0)
        links.new(mix_sh.outputs["Shader"], out.inputs["Surface"])

    log.info("ブロックマテリアル生成(v3): %s 縦グラデ %s→%s→%s, Red=%s, 霞 %.0f〜%.0fm",
             MAT_BLOCK_NAME, BLOCK_DEEP_HEX, BLOCK_ELECTRIC_HEX, BLOCK_TOP_HEX,
             SIGNAL_RED_HEX, FOG_START, FOG_END)
    return mat


def create_accent_material() -> "bpy.types.Material":
    """浮遊粒子・縦ライン・ドット用の淡いライラック発光（GN の Set Material で使う）。"""
    mat = bpy.data.materials.new(MAT_ACCENT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (200, 0)
    emis = nt.nodes.new("ShaderNodeEmission"); emis.location = (0, 0)
    emis.inputs["Color"].default_value = hex_to_linear_rgba(ACCENT_HEX)
    emis.inputs["Strength"].default_value = 2.2
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


def create_orb_material(name: str, emit_strength: float) -> "bpy.types.Material":
    """白〜淡いライラック。Principled + Emission を併用して立体感を作る。"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial"); out.location = (300, 0)
    mix = nodes.new("ShaderNodeMixShader"); mix.location = (120, 0)
    mix.inputs["Fac"].default_value = 0.62  # Emission 寄り（少しだけ陰影を残す）

    bsdf = nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (-120, 140)
    bsdf.inputs["Base Color"].default_value = (0.90, 0.88, 1.0, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.30

    emis = nodes.new("ShaderNodeEmission"); emis.location = (-120, -140)
    emis.inputs["Color"].default_value = (0.86, 0.83, 1.0, 1.0)  # 淡いライラック
    emis.inputs["Strength"].default_value = emit_strength

    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(emis.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def create_line_material() -> "bpy.types.Material":
    """細いデータラインの淡い発光マテリアル。"""
    mat = bpy.data.materials.new(MAT_LINE_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (200, 0)
    emis = nt.nodes.new("ShaderNodeEmission"); emis.location = (0, 0)
    emis.inputs["Color"].default_value = (0.80, 0.86, 1.0, 1.0)
    emis.inputs["Strength"].default_value = 3.0
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


# --------------------------------------------------------------------------- #
# Geometry Nodes 用 小ヘルパー                                                  #
# --------------------------------------------------------------------------- #
def _link_or_set(nt, socket, val):
    if isinstance(val, bpy.types.NodeSocket):
        nt.links.new(val, socket)
    elif val is not None:
        socket.default_value = val


def _M(nt, op, loc, a=None, b=None):
    """ShaderNodeMath。a/b はソケットまたは数値。出力ソケットを返す。"""
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    _link_or_set(nt, n.inputs[0], a)
    _link_or_set(nt, n.inputs[1], b)
    return n.outputs[0]


def _clamp01(nt, loc, val):
    n = nt.nodes.new("ShaderNodeClamp")
    n.location = loc
    n.inputs["Min"].default_value = 0.0
    n.inputs["Max"].default_value = 1.0
    _link_or_set(nt, n.inputs["Value"], val)
    return n.outputs["Result"]


def _map_range(nt, loc, value, from_min, from_max, to_min, to_max,
               interp="LINEAR", clamp=True):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.data_type = "FLOAT"
    n.interpolation_type = interp
    n.clamp = clamp
    n.location = loc
    n.inputs["From Min"].default_value = from_min
    n.inputs["From Max"].default_value = from_max
    n.inputs["To Min"].default_value = to_min
    n.inputs["To Max"].default_value = to_max
    _link_or_set(nt, n.inputs["Value"], value)
    return n.outputs["Result"]


def _combine(nt, loc, x=0.0, y=0.0, z=0.0):
    n = nt.nodes.new("ShaderNodeCombineXYZ")
    n.location = loc
    _link_or_set(nt, n.inputs["X"], x)
    _link_or_set(nt, n.inputs["Y"], y)
    _link_or_set(nt, n.inputs["Z"], z)
    return n


def _random_float(nt, loc, seed, id_socket, vmin=0.0, vmax=1.0):
    n = nt.nodes.new("FunctionNodeRandomValue")
    n.data_type = "FLOAT"
    n.location = loc
    mn = next(s for s in n.inputs if s.name == "Min" and s.type == "VALUE")
    mx = next(s for s in n.inputs if s.name == "Max" and s.type == "VALUE")
    sd = next(s for s in n.inputs if s.name == "Seed")
    ids = next(s for s in n.inputs if s.name == "ID")
    out = next(s for s in n.outputs if s.name == "Value" and s.type == "VALUE")
    mn.default_value = vmin
    mx.default_value = vmax
    sd.default_value = seed
    if id_socket is not None:
        nt.links.new(id_socket, ids)
    return out


# --------------------------------------------------------------------------- #
# Geometry Nodes 本体                                                          #
# --------------------------------------------------------------------------- #
def _store_attr(nt, loc, geo_socket, name, value_socket, domain):
    n = nt.nodes.new("GeometryNodeStoreNamedAttribute")
    n.location = loc
    n.data_type = "FLOAT"
    n.domain = domain
    n.inputs["Name"].default_value = name
    val = next(s for s in n.inputs if s.name == "Value" and s.type == "VALUE")
    nt.links.new(geo_socket, n.inputs["Geometry"])
    nt.links.new(value_socket, val)
    return n.outputs["Geometry"]


def build_geometry_nodes(cfg, accent_mat=None, block_mat=None):
    """Grid → Mesh to Points → Instance on Points（Realize 不使用）。

    v3:
      * 高さ = 3つの非対称ピーク × 低/中周波ノイズ + 細い尖塔 × 前中後リズム
        × データチャネル（両脇は壁として高くする）。
      * 立ち上がり: 中心から外への波 + easeOutBack + 時間差。
      * 属性: block_red / block_h（INSTANCE ドメイン, Shader は INSTANCER で読む）。
      * 装飾: 浮遊粒子と縦データライン+ドット（どれもインスタンス, 個別オブジェクト無し）。
    """
    ng = bpy.data.node_groups.new(GN_GROUP_NAME, "GeometryNodeTree")
    new_interface_socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    new_interface_socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput"); n_in.location = (-1700, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (2600, 0)

    gx, gy = cfg["grid_x"], cfg["grid_y"]
    spacing = cfg["spacing"]
    size_x = (gx - 1) * spacing
    size_y = (gy - 1) * spacing
    hx, hy = size_x * 0.5, size_y * 0.5
    max_radius = 0.5 * math.hypot(size_x, size_y)
    block_w = spacing * BLOCK_FILL
    band = max(max_radius * 0.18, spacing * 5.0)
    ns = cfg["noise_strength"]
    cps = cfg["center_peak_strength"]
    seed = cfg["random_seed"]
    mh = cfg["max_height"]

    # データチャネル（DIVE 用）: メートル単位
    channel_x = -hx + round((0.20 * size_x + hx) / spacing) * spacing  # ブロック列の中心に合わせる
    channel_inner = 0.9
    channel_outer = 2.0
    channel_low = 0.16
    wall_height = mh * 0.38   # 通路の両脇に立つ壁（パララックス用）
    wall_reach = 4.5

    # 3つの非対称ピーク（半サイズに対する比率, 半径は max_radius 比）
    peaks = [
        (-0.06 * hx, 0.05 * hy, 0.40 * max_radius, 1.00),   # 主ピーク(中景)
        (-0.46 * hx, -0.42 * hy, 0.26 * max_radius, 0.80),  # 前景の大ブロック
        (-0.30 * hx, 0.62 * hy, 0.34 * max_radius, 0.70),   # 遠景の尾根
    ]

    # --- Grid → Points ---
    grid = nodes.new("GeometryNodeMeshGrid"); grid.location = (-1500, 260)
    grid.inputs["Size X"].default_value = size_x
    grid.inputs["Size Y"].default_value = size_y
    grid.inputs["Vertices X"].default_value = gx
    grid.inputs["Vertices Y"].default_value = gy
    m2p = nodes.new("GeometryNodeMeshToPoints"); m2p.location = (-1300, 260)
    links.new(grid.outputs["Mesh"], m2p.inputs["Mesh"])

    # --- 位置・XY・中心距離・index ---
    pos = nodes.new("GeometryNodeInputPosition"); pos.location = (-1500, -300)
    sep = nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1320, -300)
    links.new(pos.outputs["Position"], sep.inputs["Vector"])
    xsock, ysock = sep.outputs["X"], sep.outputs["Y"]
    pos_xy = _combine(nt=ng, loc=(-1140, -300), x=xsock, y=ysock, z=0.0)
    dist_c = nodes.new("ShaderNodeVectorMath"); dist_c.operation = "LENGTH"
    dist_c.location = (-960, -360)
    links.new(pos_xy.outputs["Vector"], dist_c.inputs[0])
    dist_center = dist_c.outputs["Value"]
    idx = nodes.new("GeometryNodeInputIndex"); idx.location = (-1500, -560)
    stime = nodes.new("GeometryNodeInputSceneTime"); stime.location = (-780, -460)
    # データチャネルは DIVE ショット中だけ開く（06/08 では通路の縞が見えない）
    ch_on_a = _M(ng, "GREATER_THAN", (-600, -760), stime.outputs["Frame"], SHOT_DIVE[0] - 0.5)
    ch_on_b = _M(ng, "LESS_THAN", (-600, -840), stime.outputs["Frame"], SHOT_DIVE[1] + 0.5)
    ch_on = _M(ng, "MULTIPLY", (-440, -800), ch_on_a, ch_on_b)

    # --- 低周波 / 中周波ノイズ ---
    noise_lo = nodes.new("ShaderNodeTexNoise"); noise_lo.location = (-1140, 120)
    noise_lo.inputs["Scale"].default_value = cfg["noise_scale"] * 0.5
    noise_lo.inputs["Detail"].default_value = 2.0
    links.new(pos.outputs["Position"], noise_lo.inputs["Vector"])
    noise_mid = nodes.new("ShaderNodeTexNoise"); noise_mid.location = (-1140, -60)
    noise_mid.inputs["Scale"].default_value = cfg["noise_scale"] * 2.2
    noise_mid.inputs["Detail"].default_value = 3.0
    links.new(pos.outputs["Position"], noise_mid.inputs["Vector"])

    # --- 3ピーク（max） ---
    peak_outs = []
    for i, (px, py, pr, ph) in enumerate(peaks):
        pk_pos = _combine(nt=ng, loc=(-960, 400 - i * 120), x=px, y=py, z=0.0)
        pd = nodes.new("ShaderNodeVectorMath"); pd.operation = "DISTANCE"
        pd.location = (-780, 400 - i * 120)
        links.new(pos_xy.outputs["Vector"], pd.inputs[0])
        links.new(pk_pos.outputs["Vector"], pd.inputs[1])
        peak_outs.append(_map_range(ng, (-600, 400 - i * 120), pd.outputs["Value"],
                                    0.0, pr, ph, 0.0, interp="SMOOTHSTEP", clamp=True))
    peaks_max = _M(ng, "MAXIMUM", (-400, 420), peak_outs[0], peak_outs[1])
    peaks_max = _M(ng, "MAXIMUM", (-260, 420), peaks_max, peak_outs[2])

    # --- 高さ合成 ---
    nl = _M(ng, "MULTIPLY", (-780, 120), noise_lo.outputs["Fac"], 0.22 * ns)
    nm_half = _M(ng, "MULTIPLY", (-780, -20), noise_mid.outputs["Fac"], 0.6 * ns)
    nm_text = _M(ng, "ADD", (-600, -20), nm_half, 0.4)
    mount = _M(ng, "MULTIPLY", (-120, 300), peaks_max, nm_text)
    mount2 = _M(ng, "MULTIPLY", (40, 300), mount, cps)
    rnd_h = _random_float(ng, (-780, -220), seed + 3, idx.outputs["Index"])
    rnd_term = _M(ng, "MULTIPLY", (-600, -220), rnd_h, 0.10)
    # 細い尖塔（ピーク域の約5%を持ち上げる）
    rnd_sp = _random_float(ng, (-780, -330), seed + 19, idx.outputs["Index"])
    is_sp = _M(ng, "LESS_THAN", (-600, -330), rnd_sp, 0.05)
    sp_amt = _M(ng, "MULTIPLY", (-440, -330), is_sp, peaks_max)
    sp_term = _M(ng, "MULTIPLY", (-280, -330), sp_amt, 0.55)
    hsum = _M(ng, "ADD", (200, 200), nl, mount2)
    hsum2 = _M(ng, "ADD", (360, 200), hsum, rnd_term)
    hsum3 = _M(ng, "ADD", (440, 120), hsum2, sp_term)
    h01 = _clamp01(ng, (520, 200), hsum3)
    h_scaled = _M(ng, "MULTIPLY", (680, 200), h01, mh - cfg["min_height"])
    height = _M(ng, "ADD", (840, 200), h_scaled, cfg["min_height"])

    # --- 前中後の高さリズム ---
    ymul = _M(ng, "MULTIPLY", (200, -40), ysock, 6.0 / max(size_y, 1e-3))
    ysin = _M(ng, "SINE", (360, -40), ymul, None)
    ysc = _M(ng, "MULTIPLY", (520, -40), ysin, 0.15)
    depth_mod = _M(ng, "ADD", (680, -40), ysc, 0.85)
    h_a = _M(ng, "MULTIPLY", (1000, 160), height, depth_mod)

    # --- データチャネル + 両脇の壁 ---
    dxc = _M(ng, "SUBTRACT", (200, -200), xsock, channel_x)
    absdxc = _M(ng, "ABSOLUTE", (360, -200), dxc, None)
    wall_add = _map_range(ng, (520, -120), absdxc, channel_outer, channel_outer + wall_reach,
                          wall_height, 0.0, interp="SMOOTHSTEP", clamp=True)
    rnd_wall = _random_float(ng, (700, -120), seed + 41, idx.outputs["Index"], 0.25, 1.35)
    wall_var0 = _M(ng, "MULTIPLY", (860, -120), wall_add, rnd_wall)
    ymask_w0 = _map_range(ng, (700, -40), ysock, CHANNEL_Y_END, CHANNEL_Y_END + 8.0,
                          1.0, 0.0, interp="SMOOTHSTEP", clamp=True)
    ymask_w = _M(ng, "MULTIPLY", (820, -40), ymask_w0, ch_on)
    wall_var = _M(ng, "MULTIPLY", (940, -120), wall_var0, ymask_w)
    h_w = _M(ng, "ADD", (1080, 60), h_a, wall_var)
    channel_factor = _map_range(ng, (520, -200), absdxc, channel_inner, channel_outer,
                                channel_low, 1.0, interp="SMOOTHSTEP", clamp=True)
    ymask0 = _map_range(ng, (700, -300), ysock, CHANNEL_Y_END, CHANNEL_Y_END + 8.0,
                        1.0, 0.0, interp="SMOOTHSTEP", clamp=True)
    ymask = _M(ng, "MULTIPLY", (780, -360), ymask0, ch_on)
    cf_inv = _M(ng, "SUBTRACT", (860, -300), 1.0, channel_factor)
    cf_m = _M(ng, "MULTIPLY", (1000, -300), cf_inv, ymask)
    channel_eff = _M(ng, "SUBTRACT", (1140, -300), 1.0, cf_m)
    h_b = _M(ng, "MULTIPLY", (1160, 120), h_w, channel_eff)

    # --- 生成の波 ---
    build_prog = _map_range(ng, (-600, -460), stime.outputs["Frame"],
                            cfg["build_start_frame"], cfg["build_end_frame"], 0.0, 1.0,
                            interp="SMOOTHSTEP", clamp=True)
    build_radius = _M(ng, "MULTIPLY", (-420, -460), build_prog, max_radius + band)
    t_wave = _M(ng, "SUBTRACT", (-260, -460), build_radius, dist_center)
    local_t = _M(ng, "DIVIDE", (-100, -460), t_wave, band)
    rnd_stag = _random_float(ng, (-260, -600), seed + 11, idx.outputs["Index"])
    jitter = _M(ng, "MULTIPLY", (-100, -600), rnd_stag, 0.35)
    t_jit = _M(ng, "SUBTRACT", (60, -520), local_t, jitter)
    p = _clamp01(ng, (220, -520), t_jit)
    u = _M(ng, "SUBTRACT", (380, -520), p, 1.0)
    u2 = _M(ng, "MULTIPLY", (540, -560), u, u)
    u3 = _M(ng, "MULTIPLY", (540, -640), u2, u)
    c1t = _M(ng, "MULTIPLY", (700, -560), u2, 1.70158)
    c3t = _M(ng, "MULTIPLY", (700, -640), u3, 2.70158)
    s1 = _M(ng, "ADD", (860, -580), c1t, c3t)
    f_over = _M(ng, "ADD", (1020, -580), s1, 1.0)

    z_scale = _M(ng, "MULTIPLY", (1340, 40), h_b, f_over)
    # 未成長のブロックは幅も0にして消す（数は一定のまま＝モーションブラーが破綻しない）
    grow_w = _map_range(ng, (1340, 120), z_scale, 0.0, 0.03, 0.0, block_w, clamp=True)
    scale_vec = _combine(nt=ng, loc=(1500, 40), x=grow_w, y=grow_w, z=z_scale)

    # 高さを点に保存（縦ライン用に後で読む）
    pts = _store_attr(ng, (1340, 480), m2p.outputs["Points"], "ow_z", z_scale, "POINT")

    # --- ブロック本体 ---
    obj_info = nodes.new("GeometryNodeObjectInfo"); obj_info.location = (1340, 320)
    obj_info.inputs["As Instance"].default_value = True
    base = bpy.data.objects.get(CUBE_OBJ_NAME)
    if base is not None:
        obj_info.inputs["Object"].default_value = base
    iop = nodes.new("GeometryNodeInstanceOnPoints"); iop.location = (1600, 260)
    links.new(pts, iop.inputs["Points"])
    links.new(obj_info.outputs["Geometry"], iop.inputs["Instance"])
    links.new(scale_vec.outputs["Vector"], iop.inputs["Scale"])

    idx2 = nodes.new("GeometryNodeInputIndex"); idx2.location = (1600, -220)
    rnd_red = _random_float(ng, (1600, -360), seed + 7, idx2.outputs["Index"])
    red_test = _M(ng, "LESS_THAN", (1760, -300), rnd_red, cfg["red_ratio"])
    blocks = _store_attr(ng, (1760, 260), iop.outputs["Instances"], RED_ATTR_NAME,
                         red_test, "INSTANCE")
    blocks = _store_attr(ng, (1920, 260), blocks, HEIGHT_ATTR_NAME, h01, "INSTANCE")

    join = nodes.new("GeometryNodeJoinGeometry"); join.location = (2400, 0)
    links.new(blocks, join.inputs[0])

    # 地面: ブロック間のすき間から背景が透けて「溝」に見えるのを防ぐ
    ground0 = nodes.new("GeometryNodeMeshGrid"); ground0.location = (1760, 520)
    ground0.inputs["Size X"].default_value = size_x + spacing * 2.0
    ground0.inputs["Size Y"].default_value = size_y + spacing * 2.0
    ground0.inputs["Vertices X"].default_value = 2
    ground0.inputs["Vertices Y"].default_value = 2
    # 01〜05（フィールド生成前）は地面ごと消す
    before = _M(ng, "LESS_THAN", (1760, 640), stime.outputs["Frame"], cfg["build_start_frame"])
    ground = nodes.new("GeometryNodeDeleteGeometry"); ground.location = (1920, 520)
    ground.domain = "FACE"
    links.new(ground0.outputs["Mesh"], ground.inputs["Geometry"])
    links.new(before, ground.inputs["Selection"])
    if block_mat is not None:
        g_m = nodes.new("GeometryNodeSetMaterial"); g_m.location = (2100, 520)
        g_m.inputs["Material"].default_value = block_mat
        links.new(ground.outputs["Geometry"], g_m.inputs["Geometry"])
        links.new(g_m.outputs["Geometry"], join.inputs[0])
    else:
        links.new(ground.outputs["Geometry"], join.inputs[0])

    if accent_mat is not None:
        # --- 浮遊粒子（06 の上空に漂うデータ） ---
        cloud = nodes.new("GeometryNodePoints"); cloud.location = (1340, -900)
        cloud.inputs["Count"].default_value = PARTICLE_COUNT
        idx3 = nodes.new("GeometryNodeInputIndex"); idx3.location = (1000, -1000)
        rv = nodes.new("FunctionNodeRandomValue"); rv.location = (1160, -1000)
        rv.data_type = "FLOAT_VECTOR"
        vmin = next(s for s in rv.inputs if s.name == "Min" and s.type == "VECTOR")
        vmax = next(s for s in rv.inputs if s.name == "Max" and s.type == "VECTOR")
        vseed = next(s for s in rv.inputs if s.name == "Seed")
        vid = next(s for s in rv.inputs if s.name == "ID")
        vout = next(s for s in rv.outputs if s.name == "Value" and s.type == "VECTOR")
        vmin.default_value = (-0.28 * hx, -0.05 * hy, mh * 0.60)
        vmax.default_value = (0.22 * hx, 0.50 * hy, mh * 1.9)
        vseed.default_value = seed + 31
        links.new(idx3.outputs["Index"], vid)
        f_rel = _M(ng, "SUBTRACT", (1000, -1150), stime.outputs["Frame"], cfg["build_start_frame"])
        f_rel = _M(ng, "MAXIMUM", (1080, -1150), f_rel, 0.0)
        drift = _M(ng, "MULTIPLY", (1160, -1150), f_rel, 0.02)
        drift_v = _combine(nt=ng, loc=(1300, -1150), x=0.0, y=0.0, z=drift)
        vsum = nodes.new("ShaderNodeVectorMath"); vsum.operation = "ADD"
        vsum.location = (1300, -1020)
        links.new(vout, vsum.inputs[0])
        links.new(drift_v.outputs["Vector"], vsum.inputs[1])
        links.new(vsum.outputs["Vector"], cloud.inputs["Position"])
        # 粒子はビルドと一緒に現れる
        pre_fin_p = _M(ng, "LESS_THAN", (1340, -1250), stime.outputs["Frame"], SHOT_FINISH[0] - 0.5)
        dot_scale = _M(ng, "MULTIPLY", (1500, -1150), build_prog, pre_fin_p)  # 09 では出さない

        ico = nodes.new("GeometryNodeMeshIcoSphere"); ico.location = (1500, -860)
        ico.inputs["Radius"].default_value = 0.045
        ico.inputs["Subdivisions"].default_value = 1
        ico_m = nodes.new("GeometryNodeSetMaterial"); ico_m.location = (1660, -860)
        ico_m.inputs["Material"].default_value = accent_mat
        links.new(ico.outputs["Mesh"], ico_m.inputs["Geometry"])
        iop_p = nodes.new("GeometryNodeInstanceOnPoints"); iop_p.location = (1820, -900)
        links.new(cloud.outputs["Points"], iop_p.inputs["Points"])
        links.new(ico_m.outputs["Geometry"], iop_p.inputs["Instance"])
        rnd_ps = _random_float(ng, (1660, -1040), seed + 37, idx3.outputs["Index"], 0.4, 1.6)
        ps = _M(ng, "MULTIPLY", (1820, -1100), rnd_ps, dot_scale)
        links.new(ps, iop_p.inputs["Scale"])
        links.new(iop_p.outputs["Instances"], join.inputs[0])

        # --- 縦データライン + 頂部ドット（08 のシステム感） ---
        idx4 = nodes.new("GeometryNodeInputIndex"); idx4.location = (1000, -1400)
        rnd_l = _random_float(ng, (1160, -1400), seed + 23, idx4.outputs["Index"])
        is_line0 = _M(ng, "LESS_THAN", (1320, -1400), rnd_l, LINE_RATIO)
        off_ch = _M(ng, "GREATER_THAN", (1320, -1480), absdxc, channel_outer + 1.0)
        is_line = _M(ng, "MULTIPLY", (1440, -1440), is_line0, off_ch)  # 通路内には立てない
        sel = nodes.new("GeometryNodeSeparateGeometry"); sel.location = (1500, -1300)
        sel.domain = "POINT"
        links.new(pts, sel.inputs["Geometry"])
        links.new(is_line, sel.inputs["Selection"])
        sub = sel.outputs["Selection"]

        named = nodes.new("GeometryNodeInputNamedAttribute"); named.location = (1500, -1500)
        named.data_type = "FLOAT"
        named.inputs["Name"].default_value = "ow_z"
        z_attr = next(s for s in named.outputs if s.name == "Attribute")
        idx5 = nodes.new("GeometryNodeInputIndex"); idx5.location = (1500, -1620)
        extra = _random_float(ng, (1660, -1620), seed + 29, idx5.outputs["Index"],
                              mh * 0.3, mh * 1.0)
        line_prog = _map_range(ng, (1660, -1760), stime.outputs["Frame"],
                               cfg["build_end_frame"], cfg["build_end_frame"] + 30, 0.0, 1.0,
                               interp="SMOOTHSTEP", clamp=True)
        extra_b = _M(ng, "MULTIPLY", (1820, -1620), extra, line_prog)
        line_len = _M(ng, "ADD", (1980, -1560), z_attr, extra_b)

        cyl = nodes.new("GeometryNodeMeshCylinder"); cyl.location = (1660, -1250)
        cyl.inputs["Vertices"].default_value = 6
        cyl.inputs["Radius"].default_value = 0.012
        cyl.inputs["Depth"].default_value = 1.0
        xf = nodes.new("GeometryNodeTransform"); xf.location = (1820, -1250)
        xf.inputs["Translation"].default_value = (0.0, 0.0, 0.5)  # 底面を z=0 へ
        links.new(cyl.outputs["Mesh"], xf.inputs["Geometry"])
        cyl_m = nodes.new("GeometryNodeSetMaterial"); cyl_m.location = (1980, -1250)
        cyl_m.inputs["Material"].default_value = accent_mat
        links.new(xf.outputs["Geometry"], cyl_m.inputs["Geometry"])
        l_scale = _combine(nt=ng, loc=(2140, -1500), x=1.0, y=1.0, z=line_len)
        iop_l = nodes.new("GeometryNodeInstanceOnPoints"); iop_l.location = (2140, -1300)
        links.new(sub, iop_l.inputs["Points"])
        pre_fin = _M(ng, "LESS_THAN", (1980, -1480), stime.outputs["Frame"], SHOT_FINISH[0] - 0.5)
        # 伸びる前のラインはブロック内に隠れているので選別不要。数の変化はカットの瞬間(09)だけ
        line_vis = pre_fin  # 09 では出さない
        links.new(line_vis, iop_l.inputs["Selection"])
        links.new(cyl_m.outputs["Geometry"], iop_l.inputs["Instance"])
        links.new(l_scale.outputs["Vector"], iop_l.inputs["Scale"])
        links.new(iop_l.outputs["Instances"], join.inputs[0])

        top_off = _combine(nt=ng, loc=(2140, -1700), x=0.0, y=0.0, z=line_len)
        setp = nodes.new("GeometryNodeSetPosition"); setp.location = (2300, -1650)
        links.new(sub, setp.inputs["Geometry"])
        links.new(top_off.outputs["Vector"], setp.inputs["Offset"])
        ico2 = nodes.new("GeometryNodeMeshIcoSphere"); ico2.location = (2140, -1850)
        ico2.inputs["Radius"].default_value = 0.09
        ico2.inputs["Subdivisions"].default_value = 2
        ico2_m = nodes.new("GeometryNodeSetMaterial"); ico2_m.location = (2300, -1850)
        ico2_m.inputs["Material"].default_value = accent_mat
        links.new(ico2.outputs["Mesh"], ico2_m.inputs["Geometry"])
        iop_d = nodes.new("GeometryNodeInstanceOnPoints"); iop_d.location = (2460, -1700)
        links.new(setp.outputs["Geometry"], iop_d.inputs["Points"])
        links.new(line_prog, iop_d.inputs["Scale"])  # ラインが伸びるまでドットは大きさ0
        links.new(line_vis, iop_d.inputs["Selection"])
        links.new(ico2_m.outputs["Geometry"], iop_d.inputs["Instance"])
        links.new(iop_d.outputs["Instances"], join.inputs[0])

    # --- 09 FINISH: 塔の上に小キューブの列が立ち昇る（データの上昇） ---
    fin_prog = _map_range(ng, (1000, -2100), stime.outputs["Frame"],
                          SHOT_FINISH[0], SHOT_FINISH[0] + 24, 0.0, 1.0,
                          interp="SMOOTHSTEP", clamp=True)
    idx6 = nodes.new("GeometryNodeInputIndex"); idx6.location = (1000, -2250)
    rnd_c = _random_float(ng, (1160, -2250), seed + 53, idx6.outputs["Index"])
    is_col0 = _M(ng, "LESS_THAN", (1320, -2250), rnd_c, RISE_RATIO)
    in_band = _map_range(ng, (1160, -2380), dist_center, 0.0, 0.55 * max_radius,
                         1.0, 0.0, interp="LINEAR", clamp=True)
    is_col1 = _M(ng, "MULTIPLY", (1320, -2380), is_col0, _M(ng, "GREATER_THAN", (1240, -2440), in_band, 0.05))
    on_fin = _M(ng, "GREATER_THAN", (1320, -2500), stime.outputs["Frame"], SHOT_FINISH[0] - 0.5)
    is_col = _M(ng, "MULTIPLY", (1480, -2320), is_col1, on_fin)
    colsel = nodes.new("GeometryNodeSeparateGeometry"); colsel.location = (1640, -2200)
    colsel.domain = "POINT"
    links.new(pts, colsel.inputs["Geometry"])
    links.new(is_col, colsel.inputs["Selection"])
    dup = nodes.new("GeometryNodeDuplicateElements"); dup.location = (1800, -2200)
    dup.domain = "POINT"
    dup.inputs["Amount"].default_value = RISE_STACK
    links.new(colsel.outputs["Selection"], dup.inputs["Geometry"])
    named2 = nodes.new("GeometryNodeInputNamedAttribute"); named2.location = (1640, -2400)
    named2.data_type = "FLOAT"
    named2.inputs["Name"].default_value = "ow_z"
    z_top = next(o for o in named2.outputs if o.name == "Attribute")
    k1 = _M(ng, "ADD", (1960, -2400), dup.outputs["Duplicate Index"], 1.0)
    idx7 = nodes.new("GeometryNodeInputIndex"); idx7.location = (1800, -2520)
    gap = _random_float(ng, (1960, -2520), seed + 59, idx7.outputs["Index"], 0.22, 0.55)
    stack = _M(ng, "MULTIPLY", (2120, -2400), k1, gap)
    rise = _M(ng, "MULTIPLY", (2120, -2520), fin_prog, mh * 0.35)
    rise_k = _M(ng, "MULTIPLY", (2280, -2460), rise, _M(ng, "DIVIDE", (2200, -2560), k1, float(RISE_STACK)))
    zc = _M(ng, "ADD", (2280, -2360), z_top, stack)
    zc = _M(ng, "ADD", (2440, -2360), zc, rise_k)
    zc_v = _combine(nt=ng, loc=(2600, -2360), x=0.0, y=0.0, z=zc)
    cpos = nodes.new("GeometryNodeSetPosition"); cpos.location = (2600, -2200)
    links.new(dup.outputs["Geometry"], cpos.inputs["Geometry"])
    links.new(zc_v.outputs["Vector"], cpos.inputs["Offset"])
    csz = _random_float(ng, (2440, -2560), seed + 61, idx7.outputs["Index"], 0.05, 0.13)
    shrink = _M(ng, "SUBTRACT", (2440, -2660), 1.15, _M(ng, "DIVIDE", (2280, -2660), k1, float(RISE_STACK) + 1.0))
    csz = _M(ng, "MULTIPLY", (2600, -2560), csz, shrink)   # 上ほど小さく
    csz = _M(ng, "MULTIPLY", (2760, -2560), csz, fin_prog)
    iop_c = nodes.new("GeometryNodeInstanceOnPoints"); iop_c.location = (2760, -2200)
    links.new(cpos.outputs["Geometry"], iop_c.inputs["Points"])
    links.new(obj_info.outputs["Geometry"], iop_c.inputs["Instance"])
    links.new(csz, iop_c.inputs["Scale"])
    links.new(iop_c.outputs["Instances"], join.inputs[0])

    links.new(join.outputs["Geometry"], n_out.inputs[0])

    approx_red = int(round(gx * gy * cfg["red_ratio"]))
    log.info("GN構築(v3): grid=%dx%d (=%d blocks), 粒子=%d, 縦ライン≈%d, 赤≈%d (%.1f%%), "
             "field=%.1fx%.1fm",
             gx, gy, gx * gy, PARTICLE_COUNT, int(gx * gy * LINE_RATIO), approx_red,
             cfg["red_ratio"] * 100.0, size_x, size_y)
    return ng, {"channel_x": channel_x, "field_rot": math.radians(FIELD_ROT_Z_DEG),
                "size_x": size_x, "size_y": size_y, "max_radius": max_radius,
                "wall_height": wall_height}


def create_field_object(coll, cfg, accent_mat=None, block_mat=None):
    """空メッシュ + GN modifier のフィールド。マテリアルはソースCubeへ割当済み。"""
    mesh = bpy.data.meshes.new(PREFIX + "FieldMesh")
    obj = bpy.data.objects.new(FIELD_OBJ_NAME, mesh)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, math.radians(FIELD_ROT_Z_DEG))
    link_to_world(coll, obj)

    ng, meta = build_geometry_nodes(cfg, accent_mat, block_mat)
    mod = obj.modifiers.new(name="OW_GeometryNodes", type="NODES")
    mod.node_group = ng
    return obj, meta


def assign_block_material_to_source(source_obj, block_mat) -> None:
    """ブロックマテリアルを OW_SourceCube のメッシュへ確実に割り当てる（本修正）。"""
    mesh = source_obj.data
    mesh.materials.clear()
    mesh.materials.append(block_mat)
    log.info("マテリアル割当: '%s' → %s (mesh:'%s', slots=%d)",
             block_mat.name, source_obj.name, mesh.name, len(mesh.materials))


# --------------------------------------------------------------------------- #
# 発光球 + データライン                                                         #
# --------------------------------------------------------------------------- #
def _rot2d(x, y, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (x * c - y * s, x * s + y * c)


def _make_icosphere(name, radius, subdiv=4):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    except TypeError:
        bmesh.ops.create_icosphere(bm, subdivisions=subdiv, diameter=radius * 2.0)
    for face in bm.faces:
        face.smooth = True  # Shade Smooth
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def create_hero_orbs(coll, cfg, meta) -> list:
    """主球体1個 + 遠景の小球体1〜2個。フィールド回転に合わせて配置。"""
    ang = meta["field_rot"]
    mat_main = create_orb_material(MAT_ORB_NAME, emit_strength=2.2)
    mat_far = create_orb_material(MAT_ORB_NAME + "_Far", emit_strength=1.4)
    mh = cfg["max_height"]

    # (localX, localY, z, radius, material, subdiv)
    specs = [
        (-3.0, 9.0, mh * 1.05, 0.55, mat_main, 4),     # 主球体（中景, 小さめ）
        (9.0, 16.0, mh * 0.80, 0.30, mat_far, 3),      # 遠景 小
        (-12.0, 20.0, mh * 0.70, 0.26, mat_far, 3),    # 遠景 小
    ]
    orbs = []
    for i, (lx, ly, z, r, mat, sub) in enumerate(specs[:HERO_ORB_COUNT]):
        wx, wy = _rot2d(lx, ly, ang)
        mesh = _make_icosphere(PREFIX + f"OrbMesh_{i}", r, sub)
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(PREFIX + f"Orb_{i}", mesh)
        obj.location = (wx, wy, z)
        link_to_world(coll, obj)
        orbs.append(obj)
    return orbs


def create_data_lines(coll, cfg, meta, main_orb) -> list:
    """主球体からフィールドへ伸びる細いデータラインを数本（示唆的に）。"""
    mat = create_line_material()
    ang = meta["field_rot"]
    made = []
    # 主球体近傍から、フィールド上の2点（ローカル）へ
    targets_local = [(-3.0, 9.0, 0.0)]  # 主球体の真下へ1本（縦ラインのモチーフに揃える）
    start = Vector(main_orb.location)
    for i, (lx, ly, lz) in enumerate(targets_local):
        wx, wy = _rot2d(lx, ly, ang)
        end = Vector((wx, wy, lz))
        vec = end - start
        length = vec.length
        if length < 1e-4:
            continue
        mesh = bpy.data.meshes.new(PREFIX + f"LineMesh_{i}")
        bm = bmesh.new()
        try:
            bmesh.ops.create_cone(bm, cap_ends=True, segments=6,
                                  radius1=0.02, radius2=0.02, depth=length)
        except TypeError:  # 旧 API（diameter 引数）
            bmesh.ops.create_cone(bm, cap_ends=True, segments=6,
                                  diameter1=0.04, diameter2=0.04, depth=length)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mat)
        obj = bpy.data.objects.new(PREFIX + f"DataLine_{i}", mesh)
        obj.location = (start + end) * 0.5
        obj.rotation_euler = vec.to_track_quat("Z", "Y").to_euler()
        link_to_world(coll, obj)
        made.append(obj)
    return made


# --------------------------------------------------------------------------- #
# 01〜05: コア（ネットワーク → 収束 → 静止 → 点火 → 解放）                       #
# --------------------------------------------------------------------------- #
def _emission_material(name, hex_color, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (200, 0)
    emis = nt.nodes.new("ShaderNodeEmission"); emis.location = (0, 0)
    emis.inputs["Color"].default_value = hex_to_linear_rgba(hex_color)
    emis.inputs["Strength"].default_value = strength
    nt.links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


def _key_visible(obj, first, last):
    """first〜last の間だけレンダー/ビューポートに出す（CONSTANT キー）。"""
    for attr in ("hide_render", "hide_viewport"):
        if first > FRAME_START:
            setattr(obj, attr, True)
            obj.keyframe_insert(data_path=attr, frame=FRAME_START)
        setattr(obj, attr, False)
        obj.keyframe_insert(data_path=attr, frame=first)
        if last < FRAME_END:
            setattr(obj, attr, True)
            obj.keyframe_insert(data_path=attr, frame=last + 1)
    for fc in _iter_action_fcurves(obj):
        if fc.data_path.startswith("hide_"):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"
    setattr(obj, "hide_render", False)
    setattr(obj, "hide_viewport", False)


def _key_mod(obj, mod, ident, frame, value):
    mod[ident] = float(value)
    obj.keyframe_insert(data_path=f'modifiers["{mod.name}"]["{ident}"]', frame=frame)


def _build_radial_gn(name, line_mat, dot_mat=None, pulse_mat=None, animated=False):
    """位置を中心から Scale 倍し、辺を細いチューブ、頂点をドットにする GN。

    animated=True（ネットワーク用）では点ごとの動きを加える:
      * 時間差のある収縮/爆発（点ごとに Scale の効き方を変える）
      * ノイズによるゆらぎ（線も一緒に伸び縮みする）
      * ドットのまたたき
      * 線の上を外→中心へ走る光の粒（Pulse 入力で表示量を制御）
    点の数は常に一定（表示/非表示は大きさで行う）。

    戻り値: (node_group, {"Scale": id, "DotScale": id, "LineRadius": id, ...})
    """
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    new_interface_socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    ids = {}
    socks = [("Scale", 1.0), ("DotScale", 1.0), ("LineRadius", 0.006)]
    if animated:
        socks += [("Wobble", NET_WOBBLE), ("Pulse", 0.0)]
    for sock_name, default in socks:
        item = new_interface_socket(ng, sock_name, "INPUT", "NodeSocketFloat")
        if hasattr(item, "default_value"):
            item.default_value = default
        ids[sock_name] = item.identifier
    new_interface_socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    n_in = nodes.new("NodeGroupInput"); n_in.location = (-900, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (900, 0)

    pos = nodes.new("GeometryNodeInputPosition"); pos.location = (-700, -200)
    scl = nodes.new("ShaderNodeVectorMath"); scl.operation = "SCALE"; scl.location = (-520, -200)
    links.new(pos.outputs["Position"], scl.inputs[0])
    setp = nodes.new("GeometryNodeSetPosition"); setp.location = (-340, 0)
    links.new(n_in.outputs["Geometry"], setp.inputs["Geometry"])
    links.new(scl.outputs["Vector"], setp.inputs["Position"])
    stime = nodes.new("GeometryNodeInputSceneTime"); stime.location = (-900, -700)
    frame = stime.outputs["Frame"]
    vidx = nodes.new("GeometryNodeInputIndex"); vidx.location = (-900, -560)
    if animated:
        # 時間差: 点ごとに Scale^e（e が大きい点ほど早く中心へ吸い込まれ、爆発では遠くへ飛ぶ）
        expo = _random_float(ng, (-700, -420), 17, vidx.outputs["Index"], 0.7, 1.5)
        ps = _M(ng, "POWER", (-520, -380), n_in.outputs["Scale"], expo)
        links.new(ps, scl.inputs["Scale"])
        # ゆらぎ: 4D ノイズ（時間で変化）。収縮しきった後は揺れない（振幅 × min(Scale,1)）
        wn = nodes.new("ShaderNodeTexNoise"); wn.location = (-700, -860)
        wn.noise_dimensions = "4D"
        wn.inputs["Scale"].default_value = 0.35
        wn.inputs["Detail"].default_value = 1.0
        links.new(pos.outputs["Position"], wn.inputs["Vector"])
        links.new(_M(ng, "MULTIPLY", (-860, -900), frame, 0.035), wn.inputs["W"])
        ctr = nodes.new("ShaderNodeVectorMath"); ctr.operation = "SUBTRACT"; ctr.location = (-520, -860)
        ctr.inputs[1].default_value = (0.5, 0.5, 0.5)
        links.new(wn.outputs["Color"], ctr.inputs[0])
        amp = _M(ng, "MULTIPLY", (-520, -1000), n_in.outputs["Wobble"],
                 _M(ng, "MINIMUM", (-700, -1040), n_in.outputs["Scale"], 1.0))
        off = nodes.new("ShaderNodeVectorMath"); off.operation = "SCALE"; off.location = (-340, -860)
        links.new(ctr.outputs["Vector"], off.inputs[0])
        links.new(amp, off.inputs["Scale"])
        links.new(off.outputs["Vector"], setp.inputs["Offset"])
    else:
        links.new(n_in.outputs["Scale"], scl.inputs["Scale"])

    join = nodes.new("GeometryNodeJoinGeometry"); join.location = (700, 0)

    # 辺 → 細いチューブ
    m2c = nodes.new("GeometryNodeMeshToCurve"); m2c.location = (-120, 120)
    links.new(setp.outputs["Geometry"], m2c.inputs["Mesh"])
    circ = nodes.new("GeometryNodeCurvePrimitiveCircle"); circ.location = (-120, 280)
    circ.inputs["Resolution"].default_value = 4
    links.new(n_in.outputs["LineRadius"], circ.inputs["Radius"])
    c2m = nodes.new("GeometryNodeCurveToMesh"); c2m.location = (100, 160)
    links.new(m2c.outputs["Curve"], c2m.inputs["Curve"])
    links.new(circ.outputs["Curve"], c2m.inputs["Profile Curve"])
    lm = nodes.new("GeometryNodeSetMaterial"); lm.location = (300, 160)
    lm.inputs["Material"].default_value = line_mat
    links.new(c2m.outputs["Mesh"], lm.inputs["Geometry"])
    links.new(lm.outputs["Geometry"], join.inputs[0])

    if dot_mat is not None:
        m2p = nodes.new("GeometryNodeMeshToPoints"); m2p.location = (-120, -160)
        links.new(setp.outputs["Geometry"], m2p.inputs["Mesh"])
        ico = nodes.new("GeometryNodeMeshIcoSphere"); ico.location = (-120, -340)
        ico.inputs["Radius"].default_value = 0.026
        ico.inputs["Subdivisions"].default_value = 2
        dm = nodes.new("GeometryNodeSetMaterial"); dm.location = (60, -340)
        dm.inputs["Material"].default_value = dot_mat
        links.new(ico.outputs["Mesh"], dm.inputs["Geometry"])
        idx = nodes.new("GeometryNodeInputIndex"); idx.location = (-120, -500)
        rnd = _random_float(ng, (60, -500), 7, idx.outputs["Index"], 0.5, 1.6)
        hub_r = _random_float(ng, (60, -620), 13, idx.outputs["Index"])
        is_hub = _M(ng, "LESS_THAN", (220, -620), hub_r, 0.07)
        hub_mul = _M(ng, "MULTIPLY_ADD", (380, -620), is_hub, 2.2)
        hub_mul.node.inputs[2].default_value = 1.0
        sz = _M(ng, "MULTIPLY", (380, -500), rnd, hub_mul)
        sz = _M(ng, "MULTIPLY", (540, -500), sz, n_in.outputs["DotScale"])
        if animated:  # またたき: 点ごとに位相の違う脈動
            ph = _random_float(ng, (220, -760), 29, idx.outputs["Index"], 0.0, 6.283)
            wave = _M(ng, "SINE", (540, -760), _M(ng, "MULTIPLY_ADD", (380, -760), frame, 0.32), None)
            wave.node.inputs[0].links[0].from_node.inputs[2].default_value = 0.0
            links.new(ph, wave.node.inputs[0].links[0].from_node.inputs[2])
            tw = _M(ng, "MULTIPLY_ADD", (700, -760), wave, 0.32)
            tw.node.inputs[2].default_value = 0.85
            sz = _M(ng, "MULTIPLY", (700, -500), sz, tw)
        iop = nodes.new("GeometryNodeInstanceOnPoints"); iop.location = (540, -200)
        links.new(m2p.outputs["Points"], iop.inputs["Points"])
        links.new(dm.outputs["Geometry"], iop.inputs["Instance"])
        links.new(sz, iop.inputs["Scale"])
        links.new(iop.outputs["Instances"], join.inputs[0])

    if animated and pulse_mat is not None:
        _add_edge_pulses(ng, setp.outputs["Geometry"], join, frame, n_in.outputs["Pulse"], pulse_mat)

    links.new(join.outputs["Geometry"], n_out.inputs[0])
    return ng, ids


def _add_edge_pulses(ng, geo, join, frame, pulse_amt, pulse_mat):
    """線（辺）の一部に、外側の端から中心側の端へ走る光の粒を載せる。"""
    nodes, links = ng.nodes, ng.links
    ev = nodes.new("GeometryNodeInputMeshEdgeVertices"); ev.location = (-120, -1200)
    g1 = nodes.new("GeometryNodeStoreNamedAttribute"); g1.location = (60, -1100)
    g1.data_type = "FLOAT_VECTOR"; g1.domain = "EDGE"
    g1.inputs["Name"].default_value = "ow_p1"
    links.new(geo, g1.inputs["Geometry"])
    links.new(ev.outputs["Position 1"], next(i for i in g1.inputs if i.name == "Value" and i.type == "VECTOR"))
    g2 = nodes.new("GeometryNodeStoreNamedAttribute"); g2.location = (220, -1100)
    g2.data_type = "FLOAT_VECTOR"; g2.domain = "EDGE"
    g2.inputs["Name"].default_value = "ow_p2"
    links.new(g1.outputs["Geometry"], g2.inputs["Geometry"])
    links.new(ev.outputs["Position 2"], next(i for i in g2.inputs if i.name == "Value" and i.type == "VECTOR"))
    ep = nodes.new("GeometryNodeMeshToPoints"); ep.location = (380, -1100)
    ep.mode = "EDGES"
    links.new(g2.outputs["Geometry"], ep.inputs["Mesh"])

    def named(nm, loc):
        n = nodes.new("GeometryNodeInputNamedAttribute"); n.location = loc
        n.data_type = "FLOAT_VECTOR"
        n.inputs["Name"].default_value = nm
        return next(o for o in n.outputs if o.name == "Attribute")
    p1, p2 = named("ow_p1", (220, -1300)), named("ow_p2", (220, -1420))

    def length(v, loc):
        n = nodes.new("ShaderNodeVectorMath"); n.operation = "LENGTH"; n.location = loc
        links.new(v, n.inputs[0])
        return n.outputs["Value"]
    p1_far = _M(ng, "GREATER_THAN", (540, -1360), length(p1, (380, -1300)), length(p2, (380, -1420)))

    def vmix(fac, a, b, loc):
        n = nodes.new("ShaderNodeMix"); n.data_type = "VECTOR"; n.location = loc
        links.new(fac, next(i for i in n.inputs if i.name == "Factor" and i.type == "VALUE"))
        links.new(a, next(i for i in n.inputs if i.name == "A" and i.type == "VECTOR"))
        links.new(b, next(i for i in n.inputs if i.name == "B" and i.type == "VECTOR"))
        return next(o for o in n.outputs if o.name == "Result" and o.type == "VECTOR")
    start = vmix(p1_far, p2, p1, (700, -1300))   # 外側の端
    end = vmix(p1_far, p1, p2, (700, -1420))     # 中心側の端

    eidx = nodes.new("GeometryNodeInputIndex"); eidx.location = (380, -1560)
    speed = _random_float(ng, (540, -1560), 41, eidx.outputs["Index"], 0.03, 0.07)
    offs = _random_float(ng, (540, -1680), 43, eidx.outputs["Index"])
    t = _M(ng, "FRACT", (860, -1600), _M(ng, "MULTIPLY_ADD", (700, -1600), frame, speed), None)
    t.node.inputs[0].links[0].from_node.inputs[2].default_value = 0.0
    links.new(offs, t.node.inputs[0].links[0].from_node.inputs[2])
    pos_t = vmix(t, start, end, (1020, -1360))
    sp = nodes.new("GeometryNodeSetPosition"); sp.location = (1180, -1100)
    links.new(ep.outputs["Points"], sp.inputs["Geometry"])
    links.new(pos_t, sp.inputs["Position"])

    carry = _M(ng, "LESS_THAN", (860, -1760), _random_float(ng, (700, -1760), 47, eidx.outputs["Index"]),
               PULSE_EDGE_RATIO)
    fade = _M(ng, "SINE", (1020, -1720), _M(ng, "MULTIPLY", (860, -1840), t, math.pi), None)
    size = _M(ng, "MULTIPLY", (1180, -1760), _M(ng, "MULTIPLY", (1020, -1840), carry, fade), pulse_amt)
    ico = nodes.new("GeometryNodeMeshIcoSphere"); ico.location = (1180, -1300)
    ico.inputs["Radius"].default_value = 0.032
    ico.inputs["Subdivisions"].default_value = 1
    pm = nodes.new("GeometryNodeSetMaterial"); pm.location = (1340, -1300)
    pm.inputs["Material"].default_value = pulse_mat
    links.new(ico.outputs["Mesh"], pm.inputs["Geometry"])
    ip = nodes.new("GeometryNodeInstanceOnPoints"); ip.location = (1500, -1100)
    links.new(sp.outputs["Geometry"], ip.inputs["Points"])
    links.new(pm.outputs["Geometry"], ip.inputs["Instance"])
    links.new(size, ip.inputs["Scale"])
    links.new(ip.outputs["Instances"], join.inputs[0])


def _network_mesh(name, seed, count, radius):
    """球状に分布した点と、近傍を結ぶ辺のメッシュ（ネットワーク）。"""
    import random
    rng = random.Random(seed)
    pts = []
    for _ in range(count):
        v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
        if v.length < 1e-6:
            continue
        v.normalize()
        pts.append(v * radius * (rng.random() ** 0.45))
    edges = set()
    link_d = radius * 0.36
    for i, a in enumerate(pts):
        near = sorted(((b - a).length, j) for j, b in enumerate(pts) if j != i)
        for d, j in near[:rng.choice((1, 2, 2, 3))]:
            if d < link_d:
                edges.add((min(i, j), max(i, j)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(p) for p in pts], sorted(edges), [])
    mesh.update()
    return mesh, len(pts), len(edges)


def _streak_mesh(name, seed, count, r_min, r_max):
    """中心から放射方向の短い線分（収束/爆発の光線）。"""
    import random
    rng = random.Random(seed)
    verts, edges = [], []
    for _ in range(count):
        v = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
        if v.length < 1e-6:
            continue
        v.normalize()
        r0 = rng.uniform(r_min, r_max)
        ln = rng.uniform(0.25, 2.4)
        verts += [tuple(v * r0), tuple(v * (r0 + ln))]
        edges.append((len(verts) - 2, len(verts) - 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    return mesh


def create_core_material() -> "bpy.types.Material":
    """コア球: ライラックの光沢 + 発光（キー） + 点火時の光のひび（Voronoi, キー）。"""
    mat = bpy.data.materials.new(MAT_CORE_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf, out = _ensure_material_nodes(mat)
    bsdf.inputs["Base Color"].default_value = hex_to_linear_rgba("#DCD9FF")
    bsdf.inputs["Roughness"].default_value = 0.28
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.5
    for ename in ("Emission Color", "Emission"):
        if ename in bsdf.inputs:
            bsdf.inputs[ename].default_value = hex_to_linear_rgba("#C9C4FF")
            break
    bsdf.inputs["Emission Strength"].default_value = 0.5

    tex = nodes.new("ShaderNodeTexCoord"); tex.location = (-900, -300)
    vor = nodes.new("ShaderNodeTexVoronoi"); vor.location = (-700, -300)
    vor.voronoi_dimensions = "4D"
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 2.2
    vor.name = "OW_CoreVeins"
    links.new(tex.outputs["Object"], vor.inputs["Vector"])
    edge = nodes.new("ShaderNodeMapRange"); edge.location = (-500, -300)
    edge.inputs["From Min"].default_value = 0.0
    edge.inputs["From Max"].default_value = 0.035
    edge.inputs["To Min"].default_value = 1.0
    edge.inputs["To Max"].default_value = 0.0
    links.new(vor.outputs["Distance"], edge.inputs["Value"])
    amt = nodes.new("ShaderNodeValue"); amt.location = (-500, -480)
    amt.name = "OW_VeinAmount"
    amt.outputs[0].default_value = 0.0
    vein = nodes.new("ShaderNodeMath"); vein.operation = "MULTIPLY"; vein.location = (-300, -360)
    links.new(edge.outputs["Result"], vein.inputs[0])
    links.new(amt.outputs[0], vein.inputs[1])
    vem = nodes.new("ShaderNodeEmission"); vem.location = (-100, -360)
    vem.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(vein.outputs["Value"], vem.inputs["Strength"])
    add = nodes.new("ShaderNodeAddShader"); add.location = (200, 0)
    links.new(bsdf.outputs["BSDF"], add.inputs[0])
    links.new(vem.outputs["Emission"], add.inputs[1])
    links.new(add.outputs["Shader"], out.inputs["Surface"])
    return mat


def create_prelude(coll, cfg) -> dict:
    """01〜05 を作る。カメラ1台 + ネットワーク/光線/コアの3オブジェクト。"""
    seed = cfg["random_seed"]
    c = Vector(PRELUDE_CENTER)
    dot_mat = _emission_material(PREFIX + "Mat_NetDot", "#4450EE", 1.0)
    line_mat = _emission_material(PREFIX + "Mat_NetLine", "#B4B0EE", 1.0)
    streak_mat = _emission_material(PREFIX + "Mat_Streak", "#D8D3F8", 1.4)

    # ネットワーク（01 収縮 → 02 収束 → 05 爆発で外へ）
    net_mesh, n_pts, n_edges = _network_mesh(PREFIX + "NetworkMesh", seed + 71, 720, 3.8)
    net = bpy.data.objects.new(PREFIX + "Network", net_mesh)
    net.location = c
    link_to_world(coll, net)
    pulse_mat = _emission_material(PREFIX + "Mat_NetPulse", "#7F88FF", 1.8)
    ng_net, nid = _build_radial_gn(PREFIX + "GN_Network", line_mat, dot_mat, pulse_mat, animated=True)
    mn = net.modifiers.new(name="OW_Radial", type="NODES"); mn.node_group = ng_net
    for f, s_, d_, l_ in ((1, 1.0, 1.0, 0.006), (24, 0.80, 1.0, 0.006), (30, 0.70, 1.0, 0.005),
                          (46, 0.05, 0.25, 0.0012), (48, 0.03, 0.0, 0.0),
                          (97, 0.03, 0.0, 0.0), (99, 0.2, 0.9, 0.0), (116, 6.5, 0.7, 0.0),
                          (120, 7.5, 0.0, 0.0)):
        _key_mod(net, mn, nid["Scale"], f, s_)
        _key_mod(net, mn, nid["DotScale"], f, d_)
        _key_mod(net, mn, nid["LineRadius"], f, l_)
    # 光の粒: 01 で流れ始め、02 の収束とともに消える
    for f, v in ((1, 0.0), (6, 1.0), (36, 1.0), (44, 0.0)):
        _key_mod(net, mn, nid["Pulse"], f, v)
    _smooth_fcurves(net)
    _key_visible(net, SHOT_CONNECT[0], SHOT_RELEASE[1])

    # 光線（02 で中心へ流れ込み / 05 で外へ爆発）
    st = bpy.data.objects.new(PREFIX + "Streaks", _streak_mesh(PREFIX + "StreakMesh", seed + 73, 460, 1.3, 5.5))
    st.location = c
    link_to_world(coll, st)
    ng_st, sid = _build_radial_gn(PREFIX + "GN_Streaks", streak_mat, None)
    ms = st.modifiers.new(name="OW_Radial", type="NODES"); ms.node_group = ng_st
    for f, s_, l_ in ((1, 1.9, 0.0), (24, 1.9, 0.0), (27, 1.7, 0.006), (46, 0.15, 0.004),
                      (49, 0.1, 0.0), (96, 0.2, 0.0), (98, 0.35, 0.011), (114, 7.0, 0.011),
                      (120, 8.0, 0.0)):
        _key_mod(st, ms, sid["Scale"], f, s_)
        _key_mod(st, ms, sid["LineRadius"], f, l_)
    _smooth_fcurves(st)
    _key_visible(st, SHOT_CONNECT[0], SHOT_RELEASE[1])

    # コア球（03 静止 / 04 点火 / 05 閃光で画面を白に）
    core_mat = create_core_material()
    core_mesh = _make_icosphere(PREFIX + "CoreMesh", 1.0, 5)
    core_mesh.materials.append(core_mat)
    core = bpy.data.objects.new(PREFIX + "Core", core_mesh)
    core.location = c
    link_to_world(coll, core)
    import random
    rng = random.Random(seed + 79)
    scale_keys = [(1, 0.32), (24, 0.30), (34, 0.34), (48, 1.0), (60, 1.025), (72, 1.0)]
    for f in range(75, 96, 3):  # 点火: 不安定に震える
        scale_keys.append((f, rng.uniform(0.98, 1.08)))
    scale_keys += [(97, 1.02), (101, 0.55), (107, 3.0), (112, 16.0), (116, 60.0)]
    for f, s_ in scale_keys:
        core.scale = (s_, s_, s_)
        core.keyframe_insert(data_path="scale", frame=f)
    _smooth_fcurves(core)
    _key_visible(core, SHOT_CONNECT[0], SHOT_RELEASE[1])
    bsdf = _principled(core_mat)
    es = bsdf.inputs["Emission Strength"]
    for f, v in ((1, 0.35), (48, 0.55), (72, 0.6), (88, 0.7), (96, 1.0), (100, 4.0), (106, 18.0),
                 (111, 60.0)):
        es.default_value = v
        es.keyframe_insert("default_value", frame=f)
    amt = core_mat.node_tree.nodes["OW_VeinAmount"].outputs[0]
    for f, v in ((1, 0.0), (72, 0.0), (80, 3.0), (94, 7.0), (99, 0.0)):
        amt.default_value = v
        amt.keyframe_insert("default_value", frame=f)
    w = core_mat.node_tree.nodes["OW_CoreVeins"].inputs["W"]
    for f, v in ((1, 0.0), (73, 0.0), (100, 2.5)):
        w.default_value = v
        w.keyframe_insert("default_value", frame=f)
    _smooth_fcurves(core_mat.node_tree)

    # カメラ（01〜05 共通, 50mm, ゆっくり寄る）
    tgt = _add_empty(coll, TARGET_PRELUDE, tuple(c))
    # コア球に立体感を出すやわらかいキーライト（01〜05 のみ）
    kd = bpy.data.lights.new(PREFIX + "CoreKey", "AREA")
    kd.shape = "DISK"
    kd.size = 7.0
    kd.energy = 900.0
    kd.color = (0.93, 0.92, 1.0)
    kl = bpy.data.objects.new(PREFIX + "CoreKey", kd)
    kl.location = tuple(c + Vector((-6.0, -9.0, 7.0)))
    link_to_world(coll, kl)
    _track_to(kl, tgt)
    _key_visible(kl, SHOT_CONNECT[0], SHOT_RELEASE[1])
    cam = _add_camera(coll, CAM_PRELUDE, 50.0)
    _track_to(cam, tgt)
    _key_loc(cam, SHOT_CONNECT[0], tuple(c + Vector((0.6, -19.0, 0.8))))
    _key_loc(cam, SHOT_IGNITION[1], tuple(c + Vector((0.0, -15.5, 0.3))))
    _key_loc(cam, SHOT_RELEASE[1], tuple(c + Vector((0.0, -14.5, 0.2))))
    _smooth_fcurves(cam)

    log.info("01-05 コア: ネットワーク点=%d 辺=%d / 光線=460 / コア球(点火・閃光キー) / カメラ=%s",
             n_pts, n_edges, CAM_PRELUDE)
    return {"camera": cam, "objects": [net, st, core]}


# --------------------------------------------------------------------------- #
# 09: フィニッシュ（正面・球体からデータラインが扇状に降りる）                      #
# --------------------------------------------------------------------------- #
def create_finish(coll, cfg, meta) -> dict:
    ang = meta["field_rot"]
    mh = cfg["max_height"]

    def W(lx, ly, z):
        return Vector((*_rot2d(lx, ly, ang), z))

    orb_mat = bpy.data.materials.get(MAT_ORB_NAME) or create_orb_material(MAT_ORB_NAME, 2.2)
    orb_pos = W(0.0, 6.0, mh * 2.2)
    orb_mesh = _make_icosphere(PREFIX + "FinishOrbMesh", 0.85, 4)
    orb_mesh.materials.append(orb_mat)
    orb = bpy.data.objects.new(PREFIX + "FinishOrb", orb_mesh)
    orb.location = orb_pos
    link_to_world(coll, orb)
    _key_visible(orb, SHOT_FINISH[0], SHOT_FINISH[1])

    # データライン（1つのカーブに多数のスプライン）
    import random
    rng = random.Random(cfg["random_seed"] + 83)
    cu = bpy.data.curves.new(PREFIX + "DataFanCurve", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.0065
    cu.bevel_resolution = 0
    cu.bevel_factor_mapping_end = "SPLINE"
    p0 = orb_pos - Vector((0.0, 0.0, 0.75))
    n_lines = 56
    for i in range(n_lines):
        t = i / (n_lines - 1)
        lx = (t - 0.5) * 36.0 + rng.uniform(-0.6, 0.6)
        ly = rng.uniform(1.0, 13.0)
        lz = rng.uniform(1.6, 4.2)
        p2 = W(lx, ly, lz)
        ctrl = Vector((p0.x + (p2.x - p0.x) * 0.72,
                       p0.y + (p2.y - p0.y) * 0.72,
                       p0.z - (p0.z - p2.z) * 0.22))
        sp = cu.splines.new("POLY")
        n = 28
        sp.points.add(n - 1)
        for k in range(n):
            u = k / (n - 1)
            q = (1 - u) ** 2 * p0 + 2 * (1 - u) * u * ctrl + u ** 2 * p2
            sp.points[k].co = (q.x, q.y, q.z, 1.0)
    sp = cu.splines.new("POLY")  # 真下への1本
    sp.points.add(1)
    down = W(0.0, 6.0, mh * 0.6)
    sp.points[0].co = (p0.x, p0.y, p0.z, 1.0)
    sp.points[1].co = (down.x, down.y, down.z, 1.0)
    cu.materials.append(_emission_material(PREFIX + "Mat_FanLine", "#B9B3F4", 1.15))
    fan = bpy.data.objects.new(PREFIX + "DataFan", cu)
    link_to_world(coll, fan)
    for f, v in ((SHOT_FINISH[0], 0.0), (SHOT_FINISH[0] + 26, 1.0)):
        cu.bevel_factor_end = v
        cu.keyframe_insert(data_path="bevel_factor_end", frame=f)
    _smooth_fcurves(cu)
    _key_visible(fan, SHOT_FINISH[0], SHOT_FINISH[1])

    # カメラ（正面・やや低め・前景ボケ）
    tgt = _add_empty(coll, TARGET_FINISH, tuple(W(0.0, 2.0, mh * 1.15)))
    cam = _add_camera(coll, CAM_FINISH, 42.0)
    _track_to(cam, tgt)
    _key_loc(cam, SHOT_FINISH[0], tuple(W(0.0, -28.0, mh * 0.80)))
    _key_loc(cam, SHOT_FINISH[1], tuple(W(0.0, -25.5, mh * 0.76)))
    _smooth_fcurves(cam)
    cam.data.dof.focus_object = tgt
    cam.data.dof.aperture_fstop = 1.8

    log.info("09 フィニッシュ: 球体 + データライン %d 本 + 小キューブ上昇 / カメラ=%s",
             n_lines + 1, CAM_FINISH)
    return {"camera": cam, "objects": [orb, fan]}


# --------------------------------------------------------------------------- #
# ライティング                                                                  #
# --------------------------------------------------------------------------- #
def create_lights(coll, cfg) -> list:
    made = []
    key_data = bpy.data.lights.new(PREFIX + "Key", "AREA")
    key_data.shape = "RECTANGLE"
    key_data.size = 40.0
    key_data.size_y = 24.0
    key_data.energy = 3800.0
    key_data.color = (0.86, 0.86, 1.0)
    key = bpy.data.objects.new(PREFIX + "Key", key_data)
    key.location = (-18.0, -22.0, 34.0)
    key.rotation_euler = (math.radians(52), 0.0, math.radians(-32))
    link_to_world(coll, key)
    made.append(key)

    fill_data = bpy.data.lights.new(PREFIX + "Fill", "AREA")
    fill_data.shape = "RECTANGLE"
    fill_data.size = 30.0
    fill_data.size_y = 20.0
    fill_data.energy = 700.0
    fill = bpy.data.objects.new(PREFIX + "Fill", fill_data)
    fill.location = (24.0, -10.0, 18.0)
    fill.rotation_euler = (math.radians(68), 0.0, math.radians(48))
    link_to_world(coll, fill)
    made.append(fill)

    world = bpy.data.worlds.get(PREFIX + "World") or bpy.data.worlds.new(PREFIX + "World")
    bpy.context.scene.world = world
    try:
        world.use_nodes = True
    except (AttributeError, TypeError):
        pass
    wn, wl = world.node_tree.nodes, world.node_tree.links
    # バージョンにより既定ノードが無い/名前が違うことがあるので、種類で探して無ければ作る
    bg = next((n for n in wn if n.type == "BACKGROUND" and n.name != "OW_BG_Light"), None)
    wout = next((n for n in wn if n.type == "OUTPUT_WORLD"), None)
    if bg is None:
        bg = wn.new("ShaderNodeBackground")
    if wout is None:
        wout = wn.new("ShaderNodeOutputWorld")
    bg.name = "Background"  # プレビュー用の背景切替はこの名前で探す
    ivory = hex_to_linear_rgba(BG_IVORY_HEX)
    if bg is not None and wout is not None:
        bg.inputs["Color"].default_value = ivory       # カメラに見える背景
        bg.inputs["Strength"].default_value = 1.0
        light_bg = wn.new("ShaderNodeBackground"); light_bg.name = "OW_BG_Light"
        light_bg.inputs["Color"].default_value = (0.72, 0.74, 1.0, 1.0)  # 照明: 青寄りの環境光
        light_bg.inputs["Strength"].default_value = WORLD_LIGHT_STRENGTH
        lp = wn.new("ShaderNodeLightPath")
        mix = wn.new("ShaderNodeMixShader")
        wl.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
        wl.new(light_bg.outputs["Background"], mix.inputs[1])
        wl.new(bg.outputs["Background"], mix.inputs[2])
        wl.new(mix.outputs["Shader"], wout.inputs["Surface"])
    return made


# --------------------------------------------------------------------------- #
# カメラ + Blender 5 Action(F-Curve) 対応                                       #
# --------------------------------------------------------------------------- #
def _iter_action_fcurves(obj):
    """スロット化 Action(4.4+/5.x) と レガシー Action 両対応で F-Curve を列挙。"""
    ad = obj.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    fcurves = []
    layers = getattr(act, "layers", None)
    if layers:
        slot = getattr(ad, "action_slot", None)
        for layer in layers:
            for strip in getattr(layer, "strips", []):
                cb = None
                if slot is not None and hasattr(strip, "channelbag"):
                    try:
                        cb = strip.channelbag(slot)
                    except Exception:  # noqa: BLE001
                        cb = None
                if cb is not None:
                    fcurves.extend(cb.fcurves)
                else:
                    for cb2 in getattr(strip, "channelbags", []):
                        fcurves.extend(cb2.fcurves)
    if not fcurves:  # レガシー Action フォールバック
        try:
            fcurves = list(act.fcurves)
        except Exception:  # noqa: BLE001
            fcurves = []
    return fcurves


def _smooth_fcurves(obj):
    """キーフレーム補間を Bezier(Auto Clamped) にして滑らかにする。"""
    n = 0
    for fc in _iter_action_fcurves(obj):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
            n += 1
    return n


def _add_empty(coll, name, location):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.location = location
    link_to_world(coll, e)
    return e


def _add_camera(coll, name, lens):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam = bpy.data.objects.new(name, cam_data)
    link_to_world(coll, cam)
    return cam


def _track_to(cam, target):
    c = cam.constraints.new("TRACK_TO")
    c.target = target
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"


def _key_loc(obj, frame, loc):
    obj.location = loc
    obj.keyframe_insert(data_path="location", frame=frame)


def create_cameras(coll, cfg, meta) -> dict:
    """カメラはフィールドのローカル座標で設計し、フィールド回転(7°)を掛けて配置。"""
    ang = meta["field_rot"]
    cx = meta["channel_x"]
    mh = cfg["max_height"]
    total_smoothed = 0

    def W(lx, ly, z):
        return (*_rot2d(lx, ly, ang), z)

    # ---- CAM_06 EMERGENCE : 32mm, 地表近くから中央の立ち上がりを見る ----
    tgt06 = _add_empty(coll, TARGET_06, W(0.0, 2.0, mh * 0.40))
    cam06 = _add_camera(coll, CAM_EMERGENCE, 32.0)
    _track_to(cam06, tgt06)
    _key_loc(cam06, SHOT_EMERGENCE[0], W(4.0, -31.0, mh * 0.50))
    _key_loc(cam06, SHOT_EMERGENCE[1], W(3.0, -27.5, mh * 0.45))  # わずかにドリーイン
    total_smoothed += _smooth_fcurves(cam06)
    cam06.data.dof.focus_object = tgt06
    cam06.data.dof.aperture_fstop = 1.2

    # ---- CAM_07 DIVE : 22mm, 壁に挟まれたデータチャネルを低く高速に抜ける ----
    fly_z = mh * 0.24
    cam07 = _add_camera(coll, CAM_DIVE, 22.0)
    tgt_dive = _add_empty(coll, TARGET_DIVE, W(cx, -16.0, fly_z * 0.85))
    _track_to(cam07, tgt_dive)
    for fr, ly in ((SHOT_DIVE[0], -30.0),
                   ((SHOT_DIVE[0] + SHOT_DIVE[1]) // 2, -14.0),
                   (SHOT_DIVE[1], 6.0)):
        _key_loc(cam07, fr, W(cx, ly, fly_z))
    total_smoothed += _smooth_fcurves(cam07)
    _key_loc(tgt_dive, SHOT_DIVE[0], W(cx, -16.0, fly_z * 0.85))  # 注視点は常に前方
    _key_loc(tgt_dive, SHOT_DIVE[1], W(cx, 24.0, fly_z * 0.80))
    total_smoothed += _smooth_fcurves(tgt_dive)

    # ---- CAM_08 HERO : 40mm, 上昇しながら後退し全景へ ----
    tgt08 = _add_empty(coll, TARGET_08, W(-2.0, 8.0, mh * 0.15))
    cam08 = _add_camera(coll, CAM_HERO, 40.0)
    _track_to(cam08, tgt08)
    _key_loc(cam08, SHOT_HERO[0], W(8.0, -30.0, mh * 1.6))
    _key_loc(cam08, SHOT_HERO[1], W(10.0, -44.0, mh * 2.9))
    total_smoothed += _smooth_fcurves(cam08)
    cam08.data.dof.focus_object = tgt08
    cam08.data.dof.aperture_fstop = 5.6

    log.info("カメラ生成(v3): 06(32mm) 07(22mm/dive z=%.2f) 08(40mm/hero), "
             "フィールド回転=%.1f°, F-Curve補間設定=%d本",
             fly_z, FIELD_ROT_Z_DEG, total_smoothed)
    return {"emergence": cam06, "dive": cam07, "hero": cam08}


def key_fog_per_shot(block_mat) -> None:
    """霞の距離をショット境界でキー（CONSTANT）。1本のアニメ描画でも各カメラに合う。"""
    fog = block_mat.node_tree.nodes.get(FOG_NODE_NAME)
    if fog is None:
        log.warning("霞ノードが見つからないためショット別の霞をスキップします。")
        return
    def key(frame, near, far, amount):
        fog.inputs["From Min"].default_value = near
        fog.inputs["From Max"].default_value = far
        fog.inputs["To Max"].default_value = amount
        for name in ("From Min", "From Max", "To Max"):
            fog.inputs[name].keyframe_insert("default_value", frame=frame)

    # 06 の頭: 閃光の直後は全体が霞(アイボリー)に包まれ、FOG_CLEAR_FRAMES かけて晴れる
    clear_to = SHOT_EMERGENCE[0] + FOG_CLEAR_FRAMES
    key(SHOT_EMERGENCE[0], 0.2, 2.5, 1.0)
    key(clear_to, *FOG_PER_SHOT["06"], FOG_MAX)
    for k, (start, _end) in (("07", SHOT_DIVE), ("08", SHOT_HERO), ("09", SHOT_FINISH)):
        key(start, *FOG_PER_SHOT[k], FOG_MAX)
    n = 0
    for fc in _iter_action_fcurves(block_mat.node_tree):
        if 'OW_Fog' not in fc.data_path:
            continue
        for kp in fc.keyframe_points:
            # 晴れていく区間だけ補間、それ以外はショット境界で切り替え
            kp.interpolation = "BEZIER" if int(round(kp.co[0])) == SHOT_EMERGENCE[0] else "CONSTANT"
            n += 1
    log.info("霞(ショット別): %s / キー %d 個(CONSTANT)", FOG_PER_SHOT, n)


def setup_markers(cams: dict) -> None:
    scene = bpy.context.scene
    plan = [
        (PREFIX + "M_01", SHOT_CONNECT[0], cams["prelude"]),
        (PREFIX + "M_06", SHOT_EMERGENCE[0], cams["emergence"]),
        (PREFIX + "M_07", SHOT_DIVE[0], cams["dive"]),
        (PREFIX + "M_08", SHOT_HERO[0], cams["hero"]),
        (PREFIX + "M_09", SHOT_FINISH[0], cams["finish"]),
    ]
    for name, frame, cam in plan:
        mk = scene.timeline_markers.new(name, frame=frame)
        mk.camera = cam


# --------------------------------------------------------------------------- #
# レンダー設定（プレビュー / 最終 / アイボリー背景）                              #
# --------------------------------------------------------------------------- #
def _apply_image_format(scene, cfg, transparent=True):
    r = scene.render
    r.film_transparent = bool(transparent)
    img = r.image_settings
    if cfg["output_format"] == "OPEN_EXR":
        img.file_format = "OPEN_EXR"
        img.color_mode = "RGBA"
        if hasattr(img, "exr_codec"):
            img.exr_codec = "ZIP"
    else:
        img.file_format = "PNG"
        img.color_mode = "RGBA"
        img.color_depth = "16"


def setup_scene_base(cfg) -> str:
    scene = bpy.context.scene
    engine = set_eevee_engine(scene)
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END
    scene.render.fps = FPS
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    _apply_image_format(scene, cfg, transparent=True)
    setup_color_management(scene)
    setup_bloom(scene)
    return engine


def setup_color_management(scene) -> None:
    """AgX は彩度が落ちるため Standard に固定（電気的ブルーを保つ）。"""
    vs = scene.view_settings
    for attr, val in (("view_transform", "Standard"), ("look", "None")):
        try:
            setattr(vs, attr, val)
        except (TypeError, ValueError) as exc:
            log.warning("色管理 %s=%s を設定できません: %s", attr, val, exc)
    vs.exposure = 0.0
    vs.gamma = 1.0
    log.info("色管理: view_transform=%s look=%s", vs.view_transform, vs.look)


def setup_bloom(scene) -> None:
    """発光部のにじみ（Glare/Bloom）。Blender 5 のコンポジタ(ノードグループ)方式。

    設定できない版では警告のみでスキップ（レンダー自体は続行）。
    """
    if not hasattr(scene, "compositing_node_group"):
        log.warning("このBlenderでは compositing_node_group が無いためブルームを省略します。")
        return
    name = PREFIX + "Compositor"
    ng = bpy.data.node_groups.get(name) or bpy.data.node_groups.new(name, "CompositorNodeTree")
    ng.nodes.clear()
    if not any(getattr(i, "in_out", "") == "OUTPUT" for i in ng.interface.items_tree):
        ng.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers"); rl.location = (-300, 0)
    gl = ng.nodes.new("CompositorNodeGlare"); gl.location = (0, 0)
    out = ng.nodes.new("NodeGroupOutput"); out.location = (300, 0)
    try:
        gl.inputs["Type"].default_value = "Bloom"
    except (TypeError, ValueError):
        pass
    for key, val in (("Threshold", 1.1), ("Strength", 0.35), ("Size", 0.5),
                     ("Saturation", 1.0)):
        if key in gl.inputs:
            gl.inputs[key].default_value = val
    ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
    ng.links.new(gl.outputs["Image"], out.inputs[0])
    scene.compositing_node_group = ng
    if hasattr(scene.render, "use_compositing"):
        scene.render.use_compositing = True
    log.info("ブルーム: %s (Glare/%s)", name, gl.inputs["Type"].default_value)


def apply_preview_settings(cfg) -> None:
    scene = bpy.context.scene
    scene.render.resolution_percentage = int(cfg["preview_resolution_percentage"])
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = 32 if LOOKDEV_PREVIEW else 16
    _set_motion_blur(scene, LOOKDEV_PREVIEW)
    _set_dof_all(False)
    if LOOKDEV_PREVIEW:  # 見た目確認用: 被写界深度も最終と同じにする
        for name in (CAM_EMERGENCE, CAM_HERO, CAM_FINISH):
            cam = bpy.data.objects.get(name)
            if cam is not None:
                cam.data.dof.use_dof = True


def apply_final_settings(cfg) -> None:
    scene = bpy.context.scene
    scene.render.resolution_percentage = int(cfg["final_resolution_percentage"])
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = 128
    _set_motion_blur(scene, True)
    _set_dof_all(False)
    for name in (CAM_EMERGENCE, CAM_HERO, CAM_FINISH):
        cam = bpy.data.objects.get(name)
        if cam is not None:
            cam.data.dof.use_dof = True


def _set_motion_blur(scene, on: bool) -> None:
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = on
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "use_motion_blur"):
        ee.use_motion_blur = on
    if on and hasattr(scene.render, "motion_blur_shutter"):
        scene.render.motion_blur_shutter = 0.5


def _set_dof_all(on: bool) -> None:
    for name in (CAM_PRELUDE, CAM_EMERGENCE, CAM_DIVE, CAM_HERO, CAM_FINISH):
        cam = bpy.data.objects.get(name)
        if cam is not None:
            cam.data.dof.use_dof = on


def _snapshot_bg():
    """film_transparent と World 背景色/強度を退避。"""
    scene = bpy.context.scene
    world = scene.world
    snap = {"transparent": scene.render.film_transparent, "color": None, "strength": None}
    if world and world.node_tree is not None:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            snap["color"] = tuple(bg.inputs["Color"].default_value)
            snap["strength"] = bg.inputs["Strength"].default_value
    return snap


def _set_preview_ivory_bg():
    """プレビュー用に暖かいアイボリー背景を表示（film_transparent=False）。"""
    scene = bpy.context.scene
    scene.render.film_transparent = False
    world = scene.world
    if world and world.node_tree is not None:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = hex_to_linear_rgba(BG_IVORY_HEX)  # 暖かいアイボリー
            bg.inputs["Strength"].default_value = 1.0


def _restore_bg(snap):
    scene = bpy.context.scene
    scene.render.film_transparent = snap["transparent"]
    world = scene.world
    if world and world.node_tree is not None and snap["color"] is not None:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = snap["color"]
            bg.inputs["Strength"].default_value = snap["strength"]


# --------------------------------------------------------------------------- #
# プレビュー / ショットレンダー                                                  #
# --------------------------------------------------------------------------- #
SHOT_TABLE = {
    "01": {"cam": CAM_PRELUDE, "range": SHOT_CONNECT, "preview_frame": 14, "label": "01_CONNECT"},
    "02": {"cam": CAM_PRELUDE, "range": SHOT_COLLAPSE, "preview_frame": 38, "label": "02_COLLAPSE"},
    "03": {"cam": CAM_PRELUDE, "range": SHOT_SYNC, "preview_frame": 62, "label": "03_SYNC"},
    "04": {"cam": CAM_PRELUDE, "range": SHOT_IGNITION, "preview_frame": 92, "label": "04_IGNITION"},
    "05": {"cam": CAM_PRELUDE, "range": SHOT_RELEASE, "preview_frame": 102, "label": "05_RELEASE"},
    "06": {"cam": CAM_EMERGENCE, "range": SHOT_EMERGENCE, "preview_frame": 144, "label": "06_EMERGENCE"},
    "07": {"cam": CAM_DIVE, "range": SHOT_DIVE, "preview_frame": 168, "label": "07_DIVE"},
    "08": {"cam": CAM_HERO, "range": SHOT_HERO, "preview_frame": 216, "label": "08_HERO"},
    "09": {"cam": CAM_FINISH, "range": SHOT_FINISH, "preview_frame": 264, "label": "09_FINISH"},
}


def _material_state_str() -> str:
    src = bpy.data.objects.get(CUBE_OBJ_NAME)
    if src is None:
        return "SourceCube 無し"
    slots = [m.name for m in src.data.materials if m is not None]
    return f"{CUBE_OBJ_NAME}.materials={slots or '空(グレー表示になります)'}"


def _render_preview_set(cfg, out_dir, label) -> list:
    """3カメラのプレビューを out_dir に描画（アイボリー背景・実行後に復元）。"""
    scene = bpy.context.scene
    snap = _snapshot_bg()
    apply_preview_settings(cfg)
    _set_preview_ivory_bg()
    mat_state = _material_state_str()
    saved = []
    try:
        for key, info in SHOT_TABLE.items():
            if PREVIEW_SHOTS and key not in PREVIEW_SHOTS:
                continue
            cam = bpy.data.objects.get(info["cam"])
            if cam is None:
                log.warning("プレビュー(%s): カメラが見つかりません %s", label, info["cam"])
                continue
            scene.camera = cam
            scene.frame_set(info["preview_frame"])
            out_path = os.path.join(out_dir, f"{info['label']}.png")
            scene.render.filepath = out_path
            log.info("[%s] 描画: shot=%s cam=%s frame=%d 背景=アイボリー 材質=%s",
                     label, key, info["cam"], info["preview_frame"], mat_state)
            try:
                bpy.ops.render.render(write_still=True)
                saved.append(out_path)
            except RuntimeError as exc:
                log.error("プレビュー描画に失敗: %s (%s)", info["cam"], exc)
    finally:
        _restore_bg(snap)  # プレビュー後は必ず設定を元に戻す
    return saved


def render_previews(cfg, dirs: dict) -> list:
    return _render_preview_set(cfg, dirs["previews"], "preview")


def render_v2_previews(cfg, dirs: dict) -> list:
    return _render_preview_set(cfg, dirs["v2_previews"], "v2_preview")


def render_shot(shot_key: str, cfg, dirs: dict) -> str:
    """指定ショット('06'/'07'/'08')を連番でレンダリング（最終・透過）。"""
    if shot_key not in SHOT_TABLE:
        raise ValueError(f"未知のショット: {shot_key} (01〜09)")
    info = SHOT_TABLE[shot_key]
    scene = bpy.context.scene
    apply_final_settings(cfg)
    _apply_image_format(scene, cfg, transparent=True)  # 最終は背景透過
    cam = bpy.data.objects.get(info["cam"])
    scene.camera = cam
    scene.frame_start, scene.frame_end = info["range"]
    shot_dir = os.path.join(dirs["render"], info["label"])
    os.makedirs(shot_dir, exist_ok=True)
    scene.render.filepath = os.path.join(shot_dir, info["label"] + "_")
    log.info("最終描画(連番/透過): %s frames %s -> %s", info["cam"], info["range"], shot_dir)
    bpy.ops.render.render(animation=True)
    return shot_dir


# --------------------------------------------------------------------------- #
# サマリーログ                                                                  #
# --------------------------------------------------------------------------- #
def log_summary(cfg, dirs, cams, engine, instance_count) -> None:
    coll = bpy.data.collections.get(COLLECTION_NAME)
    obj_count = len(coll.objects) if coll else 0
    approx_red = int(round(instance_count * cfg["red_ratio"]))
    log.info("================ OUTPUT_WORLD 完了サマリー (v4) ================")
    log.info("Blender          : %s", bpy.app.version_string)
    log.info("Collection       : %s (オブジェクト数 %d)", COLLECTION_NAME, obj_count)
    log.info("インスタンス数   : %d (%dx%d, 個別オブジェクトではない)",
             instance_count, cfg["grid_x"], cfg["grid_y"])
    log.info("マテリアル       : %s → %s", MAT_BLOCK_NAME, _material_state_str())
    log.info("色               : Cobalt=%s / Red=%s / 赤概算=%d (%.1f%%)",
             COBALT_HEX, SIGNAL_RED_HEX, approx_red, cfg["red_ratio"] * 100.0)
    log.info("カメラ           : %s", ", ".join(sorted(c.name for c in cams.values())))
    log.info("レンダーエンジン : %s / %dx%d / %dfps", engine, RES_X, RES_Y, FPS)
    log.info("背景             : 最終=透過 / プレビュー=アイボリー")
    log.info("尺               : %d-%d frames (%dF / %.1f秒)", FRAME_START, FRAME_END, FRAME_END - FRAME_START + 1, (FRAME_END - FRAME_START + 1) / FPS)
    log.info(".blend 保存先    : %s", os.path.join(dirs["out"], "output_world.blend"))
    log.info("プレビュー保存先 : %s", dirs["previews"])
    log.info("V2プレビュー     : %s", dirs["v2_previews"])
    log.info("連番出力先       : %s", dirs["render"])
    log.info("===============================================================")


# --------------------------------------------------------------------------- #
# メイン                                                                        #
# --------------------------------------------------------------------------- #
def save_blend(dirs) -> str:
    path = os.path.join(dirs["out"], "output_world.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    log.info(".blend を保存しました: %s", path)
    return path


def build(do_previews: bool = True, v2: bool = True) -> None:
    cfg = load_config()
    base_out = os.path.join(script_dir(), "output")
    dirs = ensure_dirs(base_out)

    log.info("Blender %s / OUTPUT_WORLD 構築(v4: 01〜09)を開始します。", bpy.app.version_string)

    backup_existing_blend(dirs)
    use_output_scene()
    purge_previous()

    coll = get_world_collection()
    source = create_source_cube(coll)                 # 角丸Cube 1個（隠しソース）
    block_mat = create_block_material(cfg)
    assign_block_material_to_source(source, block_mat)  # ★ マテリアル継承の修正
    accent_mat = create_accent_material()
    field, meta = create_field_object(coll, cfg, accent_mat, block_mat)  # GN でインスタンス化
    orbs = create_hero_orbs(coll, cfg, meta)
    lines = create_data_lines(coll, cfg, meta, orbs[0]) if orbs else []
    for o in orbs + lines:  # 06〜08 の球体は 01〜05 と 09 では出さない
        _key_visible(o, SHOT_EMERGENCE[0], SHOT_HERO[1])
    create_lights(coll, cfg)
    cams = create_cameras(coll, cfg, meta)
    cams["prelude"] = create_prelude(coll, cfg)["camera"]
    cams["finish"] = create_finish(coll, cfg, meta)["camera"]
    setup_markers(cams)
    key_fog_per_shot(block_mat)

    engine = setup_scene_base(cfg)
    bpy.context.scene.camera = cams["prelude"]
    bpy.context.scene.frame_set(FRAME_START)

    save_blend(dirs)

    if do_previews:
        render_v2_previews(cfg, dirs) if v2 else render_previews(cfg, dirs)
        apply_final_settings(cfg)         # 最終描画に備える
        _apply_image_format(bpy.context.scene, cfg, transparent=True)
        save_blend(dirs)

    log_summary(cfg, dirs, cams, engine, cfg["grid_x"] * cfg["grid_y"])


def _parse_cli_args() -> dict:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    opts = {"previews": True, "shot": None}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--no-previews":
            opts["previews"] = False
        elif a == "--shot" and i + 1 < len(args):
            opts["shot"] = args[i + 1]
            i += 1
        elif a == "--preview-shots" and i + 1 < len(args):
            PREVIEW_SHOTS.update(x.strip().zfill(2) for x in args[i + 1].split(",") if x.strip())
            i += 1
        i += 1
    return opts


def main() -> None:
    try:
        opts = _parse_cli_args()
        build(do_previews=opts["previews"], v2=True)
        if opts["shot"]:
            cfg = load_config()
            dirs = ensure_dirs(os.path.join(script_dir(), "output"))
            render_shot(opts["shot"], cfg, dirs)
    except Exception:  # noqa: BLE001 - 原因を明示してから再送出
        log.error("処理中にエラーが発生しました。以下を確認してください:")
        log.error("  * Blender のバージョン（5.1.2 で検証, 4.x でも概ね動作）")
        log.error("  * config.json の値域")
        log.error("  * 実行が Blender の Python 上であること")
        log.error("----- traceback -----\n%s", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
