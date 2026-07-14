#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_output_world.py  (art pass v2)

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

GN_GROUP_NAME = PREFIX + "GeometryNodes"
CUBE_MESH_NAME = PREFIX + "SourceCube"
CUBE_OBJ_NAME = PREFIX + "SourceCube"     # インスタンス元（マテリアルはここへ割当）
FIELD_OBJ_NAME = PREFIX + "Field"
MAT_BLOCK_NAME = PREFIX + "Mat_Block"
MAT_ORB_NAME = PREFIX + "Mat_Orb"
MAT_LINE_NAME = PREFIX + "Mat_DataLine"

RED_ATTR_NAME = "block_red"  # INSTANCE ドメイン属性（Shader は INSTANCER で読む）

CAM_EMERGENCE = PREFIX + "CAM_06_EMERGENCE"
CAM_DIVE = PREFIX + "CAM_07_DIVE"
CAM_HERO = PREFIX + "CAM_08_HERO"

TARGET_06 = PREFIX + "TARGET_06"
TARGET_DIVE = PREFIX + "TARGET_DIVE"
TARGET_08 = PREFIX + "TARGET_08"

# フィールドをグリッド軸から少し回す（黒い溝を目立たなくする, 5〜9°）
FIELD_ROT_Z_DEG = 7.0

BLOCK_FILL = 0.92  # block幅 = spacing * BLOCK_FILL（0.90〜0.93）

HERO_ORB_COUNT = 3

# タイムライン
FRAME_START = 1
FRAME_END = 96
FPS = 24
SHOT_EMERGENCE = (1, 32)
SHOT_DIVE = (33, 64)
SHOT_HERO = (65, 96)

RES_X = 1920
RES_Y = 1080

# 色（sRGB hex → 後で linear 変換）
COBALT_HEX = "#163CFF"
SIGNAL_RED_HEX = "#FF3048"


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
    "build_start_frame": 1,
    "build_end_frame": 32,
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
def _principled(mat):
    return mat.node_tree.nodes.get("Principled BSDF")


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
    """鮮やかなコバルトブルー(既定) + シグナルレッド(block_red=1)。

    block_red は INSTANCER 属性。読めない場合でも Fac=0 でコバルトになり、
    グレーにはならない（安全なフォールバック）。
    """
    cobalt = hex_to_linear_rgba(COBALT_HEX)
    signal_red = hex_to_linear_rgba(SIGNAL_RED_HEX)
    # ごく弱い青 Emission（影でも青が残る） / 赤はやや強い赤 Emission
    blue_emit = (cobalt[0] * 0.6, cobalt[1] * 0.6, cobalt[2] * 0.6, 1.0)
    red_emit = (signal_red[0], signal_red[1] * 0.4, signal_red[2] * 0.4, 1.0)

    mat = bpy.data.materials.new(MAT_BLOCK_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = _principled(mat)
    out = nodes.get("Material Output")

    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "INSTANCER"
    attr.attribute_name = RED_ATTR_NAME
    attr.location = (-900, 100)
    fac = attr.outputs["Fac"]

    base_col = _mix_rgba(nt, (-600, 300), fac, cobalt, signal_red)
    emit_col = _mix_rgba(nt, (-600, -100), fac, blue_emit, red_emit)

    if bsdf is not None:
        links.new(base_col, bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.32
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.10
        for ename in ("Emission Color", "Emission"):
            if ename in bsdf.inputs:
                links.new(emit_col, bsdf.inputs[ename])
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 0.6
        if out is not None:
            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    log.info("ブロックマテリアル生成: %s (Cobalt=%s, Red=%s, INSTANCER属性=%s)",
             MAT_BLOCK_NAME, COBALT_HEX, SIGNAL_RED_HEX, RED_ATTR_NAME)
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
def build_geometry_nodes(cfg) -> "bpy.types.NodeTree":
    """Grid → Mesh to Points → Instance on Points（Realize 不使用）。

    高さ = 3つの非対称ピーク × (低/中周波ノイズ) × 前中後リズム × データチャネル。
    立ち上がりは中心から外へ広がる波 + easeOutBack オーバーシュート + 時間差。
    """
    ng = bpy.data.node_groups.new(GN_GROUP_NAME, "GeometryNodeTree")
    new_interface_socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    new_interface_socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput"); n_in.location = (-1700, 0)
    n_out = nodes.new("NodeGroupOutput"); n_out.location = (1900, 0)

    gx, gy = cfg["grid_x"], cfg["grid_y"]
    spacing = cfg["spacing"]
    size_x = (gx - 1) * spacing
    size_y = (gy - 1) * spacing
    max_radius = 0.5 * math.hypot(size_x, size_y)
    block_w = spacing * BLOCK_FILL
    band = max(spacing * 5.0, 1e-3)
    ns = cfg["noise_strength"]
    cps = cfg["center_peak_strength"]
    seed = cfg["random_seed"]

    # データチャネル（DIVE 用の低ブロック帯）: フィールド右寄りのローカル X
    channel_x = 0.20 * size_x
    channel_inner = spacing * 1.6
    channel_outer = spacing * 3.2
    channel_low = 0.22  # チャネル内の高さ係数（0=空洞ではなく低ブロックを残す）

    # 3つの非対称ピーク（ローカル座標, 半径, 高さ係数）
    peaks = [
        (-1.0 * spacing, 0.5 * spacing, 0.42 * max_radius, 1.00),   # 主ピーク(中景)
        (-7.0 * spacing, -7.0 * spacing, 0.30 * max_radius, 0.85),  # 前景の大ブロック
        (-5.0 * spacing, 10.0 * spacing, 0.34 * max_radius, 0.62),  # 遠景の低い構造
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

    # --- 低周波 / 中周波ノイズ ---
    noise_lo = nodes.new("ShaderNodeTexNoise"); noise_lo.location = (-1140, 120)
    if "Scale" in noise_lo.inputs:
        noise_lo.inputs["Scale"].default_value = cfg["noise_scale"] * 0.5
    if "Detail" in noise_lo.inputs:
        noise_lo.inputs["Detail"].default_value = 2.0
    links.new(pos.outputs["Position"], noise_lo.inputs["Vector"])

    noise_mid = nodes.new("ShaderNodeTexNoise"); noise_mid.location = (-1140, -60)
    if "Scale" in noise_mid.inputs:
        noise_mid.inputs["Scale"].default_value = cfg["noise_scale"] * 1.7
    if "Detail" in noise_mid.inputs:
        noise_mid.inputs["Detail"].default_value = 3.0
    links.new(pos.outputs["Position"], noise_mid.inputs["Vector"])

    # --- 3ピークの合成（max） ---
    peak_outs = []
    for i, (px, py, pr, ph) in enumerate(peaks):
        pk_pos = _combine(nt=ng, loc=(-960, 400 - i * 120), x=px, y=py, z=0.0)
        pd = nodes.new("ShaderNodeVectorMath"); pd.operation = "DISTANCE"
        pd.location = (-780, 400 - i * 120)
        links.new(pos_xy.outputs["Vector"], pd.inputs[0])
        links.new(pk_pos.outputs["Vector"], pd.inputs[1])
        fall = _map_range(ng, (-600, 400 - i * 120), pd.outputs["Value"],
                          0.0, pr, ph, 0.0, interp="SMOOTHSTEP", clamp=True)
        peak_outs.append(fall)
    peaks_max = _M(ng, "MAXIMUM", (-400, 420), peak_outs[0], peak_outs[1])
    peaks_max = _M(ng, "MAXIMUM", (-260, 420), peaks_max, peak_outs[2])

    # --- 高さ合成 ---
    nl = _M(ng, "MULTIPLY", (-780, 120), noise_lo.outputs["Fac"], 0.25 * ns)
    nm_half = _M(ng, "MULTIPLY", (-780, -20), noise_mid.outputs["Fac"], 0.5 * ns)
    nm_text = _M(ng, "ADD", (-600, -20), nm_half, 0.5)
    mount = _M(ng, "MULTIPLY", (-120, 300), peaks_max, nm_text)
    mount2 = _M(ng, "MULTIPLY", (40, 300), mount, cps)
    rnd_h = _random_float(ng, (-780, -220), seed + 3, idx.outputs["Index"])
    rnd_term = _M(ng, "MULTIPLY", (-600, -220), rnd_h, 0.08)
    hsum = _M(ng, "ADD", (200, 200), nl, mount2)
    hsum2 = _M(ng, "ADD", (360, 200), hsum, rnd_term)
    h01 = _clamp01(ng, (520, 200), hsum2)
    h_scaled = _M(ng, "MULTIPLY", (680, 200), h01, cfg["max_height"] - cfg["min_height"])
    height = _M(ng, "ADD", (840, 200), h_scaled, cfg["min_height"])

    # --- 前中後の高さリズム（Y でうねり） ---
    ymul = _M(ng, "MULTIPLY", (200, -40), ysock, 0.35)
    ysin = _M(ng, "SINE", (360, -40), ymul, None)
    ysc = _M(ng, "MULTIPLY", (520, -40), ysin, 0.15)
    depth_mod = _M(ng, "ADD", (680, -40), ysc, 0.85)
    h_a = _M(ng, "MULTIPLY", (1000, 160), height, depth_mod)

    # --- データチャネル（|x - channel_x| が小さいほど低く） ---
    dxc = _M(ng, "SUBTRACT", (200, -200), xsock, channel_x)
    absdxc = _M(ng, "ABSOLUTE", (360, -200), dxc, None)
    channel_factor = _map_range(ng, (520, -200), absdxc,
                                channel_inner, channel_outer, channel_low, 1.0,
                                interp="SMOOTHSTEP", clamp=True)
    h_b = _M(ng, "MULTIPLY", (1160, 120), h_a, channel_factor)

    # --- 生成の波（Scene Time → build_radius → local_t） ---
    stime = nodes.new("GeometryNodeInputSceneTime"); stime.location = (-780, -420)
    build_prog = _map_range(ng, (-600, -420), stime.outputs["Frame"],
                            cfg["build_start_frame"], cfg["build_end_frame"], 0.0, 1.0,
                            interp="SMOOTHSTEP", clamp=True)
    build_radius = _M(ng, "MULTIPLY", (-420, -420), build_prog, max_radius + band)
    t_wave = _M(ng, "SUBTRACT", (-260, -420), build_radius, dist_center)
    local_t = _M(ng, "DIVIDE", (-100, -420), t_wave, band)
    rnd_stag = _random_float(ng, (-260, -560), seed + 11, idx.outputs["Index"])
    jitter = _M(ng, "MULTIPLY", (-100, -560), rnd_stag, 0.15)  # 時間差(余韻)
    t_jit = _M(ng, "ADD", (60, -480), local_t, jitter)
    p = _clamp01(ng, (220, -480), t_jit)

    # easeOutBack: f = 1 + c1*u^2 + c3*u^3 ,  u = p - 1（軽いオーバーシュート）
    u = _M(ng, "SUBTRACT", (380, -480), p, 1.0)
    u2 = _M(ng, "MULTIPLY", (540, -520), u, u)
    u3 = _M(ng, "MULTIPLY", (540, -600), u2, u)
    c1t = _M(ng, "MULTIPLY", (700, -520), u2, 1.70158)
    c3t = _M(ng, "MULTIPLY", (700, -600), u3, 2.70158)
    s1 = _M(ng, "ADD", (860, -540), c1t, c3t)
    f_over = _M(ng, "ADD", (1020, -540), s1, 1.0)

    z_scale = _M(ng, "MULTIPLY", (1340, 40), h_b, f_over)
    scale_vec = _combine(nt=ng, loc=(1500, 40), x=block_w, y=block_w, z=z_scale)

    # --- Object Info（ソースCube） ---
    obj_info = nodes.new("GeometryNodeObjectInfo"); obj_info.location = (1340, 320)
    obj_info.inputs["As Instance"].default_value = True
    base = bpy.data.objects.get(CUBE_OBJ_NAME)
    if base is not None:
        obj_info.inputs["Object"].default_value = base

    # --- Instance on Points ---
    iop = nodes.new("GeometryNodeInstanceOnPoints"); iop.location = (1600, 260)
    links.new(m2p.outputs["Points"], iop.inputs["Points"])
    links.new(obj_info.outputs["Geometry"], iop.inputs["Instance"])
    links.new(scale_vec.outputs["Vector"], iop.inputs["Scale"])

    # --- 赤選択を INSTANCE ドメインへ保存（Shader は INSTANCER で読む） ---
    idx2 = nodes.new("GeometryNodeInputIndex"); idx2.location = (1600, -220)
    rnd_red = _random_float(ng, (1600, -360), seed + 7, idx2.outputs["Index"])
    red_test = _M(ng, "LESS_THAN", (1760, -300), rnd_red, cfg["red_ratio"])
    store = nodes.new("GeometryNodeStoreNamedAttribute"); store.location = (1760, 260)
    store.data_type = "FLOAT"
    store.domain = "INSTANCE"
    store.inputs["Name"].default_value = RED_ATTR_NAME
    store_val = next(s for s in store.inputs if s.name == "Value" and s.type == "VALUE")
    links.new(iop.outputs["Instances"], store.inputs["Geometry"])
    links.new(red_test, store_val)
    links.new(store.outputs["Geometry"], n_out.inputs[0])

    approx_red = int(round(gx * gy * cfg["red_ratio"]))
    log.info("GN構築: grid=%dx%d (=%d instances), peaks=3, channel_x=%.1f, "
             "赤ノード概算=%d (%.1f%%)",
             gx, gy, gx * gy, channel_x, approx_red, cfg["red_ratio"] * 100.0)
    return ng, {"channel_x": channel_x, "field_rot": math.radians(FIELD_ROT_Z_DEG),
                "size_x": size_x, "size_y": size_y, "max_radius": max_radius}


def create_field_object(coll, cfg):
    """空メッシュ + GN modifier のフィールド。マテリアルはソースCubeへ割当済み。"""
    mesh = bpy.data.meshes.new(PREFIX + "FieldMesh")
    obj = bpy.data.objects.new(FIELD_OBJ_NAME, mesh)
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, math.radians(FIELD_ROT_Z_DEG))  # グリッド軸をずらす
    link_to_world(coll, obj)

    ng, meta = build_geometry_nodes(cfg)
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
    mat_main = create_orb_material(MAT_ORB_NAME, emit_strength=6.0)
    mat_far = create_orb_material(MAT_ORB_NAME + "_Far", emit_strength=2.4)
    mh = cfg["max_height"]

    # (localX, localY, z, radius, material, subdiv)
    specs = [
        (-1.0, 1.0, mh * 0.92, 0.62, mat_main, 4),     # 主球体（中景, 小さめ）
        (7.0, -8.0, mh * 0.70, 0.30, mat_far, 3),      # 遠景 小
        (-8.0, 11.0, mh * 0.60, 0.24, mat_far, 3),     # 遠景 小
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
    targets_local = [(-1.0, -3.0, cfg["max_height"] * 0.35),
                     (3.0, 3.0, cfg["max_height"] * 0.30)]
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
# ライティング                                                                  #
# --------------------------------------------------------------------------- #
def create_lights(coll, cfg) -> list:
    made = []
    key_data = bpy.data.lights.new(PREFIX + "Key", "AREA")
    key_data.shape = "RECTANGLE"
    key_data.size = 40.0
    key_data.size_y = 24.0
    key_data.energy = 5000.0
    key = bpy.data.objects.new(PREFIX + "Key", key_data)
    key.location = (-18.0, -22.0, 34.0)
    key.rotation_euler = (math.radians(52), 0.0, math.radians(-32))
    link_to_world(coll, key)
    made.append(key)

    fill_data = bpy.data.lights.new(PREFIX + "Fill", "AREA")
    fill_data.shape = "RECTANGLE"
    fill_data.size = 30.0
    fill_data.size_y = 20.0
    fill_data.energy = 1100.0
    fill = bpy.data.objects.new(PREFIX + "Fill", fill_data)
    fill.location = (24.0, -10.0, 18.0)
    fill.rotation_euler = (math.radians(68), 0.0, math.radians(48))
    link_to_world(coll, fill)
    made.append(fill)

    world = bpy.data.worlds.get(PREFIX + "World") or bpy.data.worlds.new(PREFIX + "World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.95, 0.93, 0.88, 1.0)
        bg.inputs["Strength"].default_value = 0.35
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
    ang = meta["field_rot"]
    channel_x = meta["channel_x"]
    total_smoothed = 0

    # ---- CAM_06 EMERGENCE : 38mm, 後退・高め・右奥へ非対称 ----
    tgt06 = _add_empty(coll, TARGET_06, (*_rot2d(4.0, 4.0, ang), 3.5))
    cam06 = _add_camera(coll, CAM_EMERGENCE, 38.0)
    _track_to(cam06, tgt06)
    _key_loc(cam06, SHOT_EMERGENCE[0], (4.0, -37.0, 10.0))   # 開始: 余白を残す
    _key_loc(cam06, SHOT_EMERGENCE[1], (1.0, -31.0, 11.0))   # わずかにドリーイン
    total_smoothed += _smooth_fcurves(cam06)

    # ---- CAM_07 DIVE : 24mm, データチャネル内部を通過 ----
    cam07 = _add_camera(coll, CAM_DIVE, 24.0)
    tgt_dive = _add_empty(coll, TARGET_DIVE, (*_rot2d(channel_x, -6.0, ang), 3.2))
    _track_to(cam07, tgt_dive)
    fly_z = 3.6  # ブロック内部（2.5〜5.0）
    for fr, ly in ((SHOT_DIVE[0], -18.0),
                   ((SHOT_DIVE[0] + SHOT_DIVE[1]) // 2, 0.0),
                   (SHOT_DIVE[1], 18.0)):
        wx, wy = _rot2d(channel_x, ly, ang)
        _key_loc(cam07, fr, (wx, wy, fly_z))
    total_smoothed += _smooth_fcurves(cam07)  # Bezier=中盤加速/前後減速
    # 注視点は常に前方へ先行
    _key_loc(tgt_dive, SHOT_DIVE[0], (*_rot2d(channel_x, -6.0, ang), 3.2))
    _key_loc(tgt_dive, SHOT_DIVE[1], (*_rot2d(channel_x, 30.0, ang), 2.8))
    total_smoothed += _smooth_fcurves(tgt_dive)

    # ---- CAM_08 HERO : 42mm, 右から左奥を見る・右に余白 ----
    tgt08 = _add_empty(coll, TARGET_08, (*_rot2d(-2.0, 2.0, ang), 4.0))
    cam08 = _add_camera(coll, CAM_HERO, 42.0)
    _track_to(cam08, tgt08)
    _key_loc(cam08, SHOT_HERO[0], (13.0, -19.0, 11.0))
    _key_loc(cam08, SHOT_HERO[1], (18.0, -44.0, 22.0))   # 上昇+後退
    total_smoothed += _smooth_fcurves(cam08)
    cam08.data.dof.focus_object = tgt08
    cam08.data.dof.aperture_fstop = 4.0

    log.info("カメラ生成: 06(38mm) 07(24mm/dive) 08(42mm/hero), "
             "フィールド回転=%.1f°, F-Curve補間設定=%d本", FIELD_ROT_Z_DEG, total_smoothed)
    return {"emergence": cam06, "dive": cam07, "hero": cam08}


def setup_markers(cams: dict) -> None:
    scene = bpy.context.scene
    plan = [
        (PREFIX + "M_06", SHOT_EMERGENCE[0], cams["emergence"]),
        (PREFIX + "M_07", SHOT_DIVE[0], cams["dive"]),
        (PREFIX + "M_08", SHOT_HERO[0], cams["hero"]),
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
    return engine


def apply_preview_settings(cfg) -> None:
    scene = bpy.context.scene
    scene.render.resolution_percentage = int(cfg["preview_resolution_percentage"])
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = 16
    _set_motion_blur(scene, False)
    _set_dof_all(False)


def apply_final_settings(cfg) -> None:
    scene = bpy.context.scene
    scene.render.resolution_percentage = int(cfg["final_resolution_percentage"])
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = 128
    _set_motion_blur(scene, True)
    _set_dof_all(False)
    hero = bpy.data.objects.get(CAM_HERO)
    if hero is not None:
        hero.data.dof.use_dof = True


def _set_motion_blur(scene, on: bool) -> None:
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = on
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "use_motion_blur"):
        ee.use_motion_blur = on
    if on and hasattr(scene.render, "motion_blur_shutter"):
        scene.render.motion_blur_shutter = 0.5


def _set_dof_all(on: bool) -> None:
    for name in (CAM_EMERGENCE, CAM_DIVE, CAM_HERO):
        cam = bpy.data.objects.get(name)
        if cam is not None:
            cam.data.dof.use_dof = on


def _snapshot_bg():
    """film_transparent と World 背景色/強度を退避。"""
    scene = bpy.context.scene
    world = scene.world
    snap = {"transparent": scene.render.film_transparent, "color": None, "strength": None}
    if world and world.use_nodes:
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
    if world and world.use_nodes:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = (0.96, 0.93, 0.86, 1.0)  # 暖かいアイボリー
            bg.inputs["Strength"].default_value = 1.0


def _restore_bg(snap):
    scene = bpy.context.scene
    scene.render.film_transparent = snap["transparent"]
    world = scene.world
    if world and world.use_nodes and snap["color"] is not None:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = snap["color"]
            bg.inputs["Strength"].default_value = snap["strength"]


# --------------------------------------------------------------------------- #
# プレビュー / ショットレンダー                                                  #
# --------------------------------------------------------------------------- #
SHOT_TABLE = {
    "06": {"cam": CAM_EMERGENCE, "range": SHOT_EMERGENCE, "preview_frame": 26},
    "07": {"cam": CAM_DIVE, "range": SHOT_DIVE, "preview_frame": 48},
    "08": {"cam": CAM_HERO, "range": SHOT_HERO, "preview_frame": 96},
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
            cam = bpy.data.objects.get(info["cam"])
            if cam is None:
                log.warning("プレビュー(%s): カメラが見つかりません %s", label, info["cam"])
                continue
            scene.camera = cam
            scene.frame_set(info["preview_frame"])
            out_path = os.path.join(out_dir, f"{info['cam']}.png")
            scene.render.filepath = out_path
            log.info("[%s] 描画: cam=%s frame=%d 背景=アイボリー 材質=%s",
                     label, info["cam"], info["preview_frame"], mat_state)
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
        raise ValueError(f"未知のショット: {shot_key} (06/07/08)")
    info = SHOT_TABLE[shot_key]
    scene = bpy.context.scene
    apply_final_settings(cfg)
    _apply_image_format(scene, cfg, transparent=True)  # 最終は背景透過
    cam = bpy.data.objects.get(info["cam"])
    scene.camera = cam
    scene.frame_start, scene.frame_end = info["range"]
    shot_dir = os.path.join(dirs["render"], info["cam"])
    os.makedirs(shot_dir, exist_ok=True)
    scene.render.filepath = os.path.join(shot_dir, info["cam"] + "_")
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
    log.info("================ OUTPUT_WORLD 完了サマリー (v2) ================")
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
    log.info("尺               : %d-%d frames (96F)", FRAME_START, FRAME_END)
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

    log.info("Blender %s / OUTPUT_WORLD 構築(v2)を開始します。", bpy.app.version_string)

    backup_existing_blend(dirs)
    purge_previous()

    coll = get_world_collection()
    source = create_source_cube(coll)                 # 角丸Cube 1個（隠しソース）
    block_mat = create_block_material(cfg)
    assign_block_material_to_source(source, block_mat)  # ★ マテリアル継承の修正
    field, meta = create_field_object(coll, cfg)      # GN でインスタンス化
    orbs = create_hero_orbs(coll, cfg, meta)
    if orbs:
        create_data_lines(coll, cfg, meta, orbs[0])
    create_lights(coll, cfg)
    cams = create_cameras(coll, cfg, meta)
    setup_markers(cams)

    engine = setup_scene_base(cfg)
    bpy.context.scene.camera = cams["emergence"]
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
