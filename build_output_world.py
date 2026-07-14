#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_output_world.py

ストーリーボード後半3カット
  06 OUTPUT EMERGENCE / 07 DIVE THROUGH OUTPUT / 08 HERO REVEAL
のための、再実行可能な Blender 自動構築システム。

1個の角丸Cubeを Geometry Nodes でインスタンス化し、青いブロック群からなる
巨大な OUTPUT フィールドを構築する。個別オブジェクトは生成しない。

実行例（macOS ターミナル）::

    /Applications/Blender.app/Contents/MacOS/Blender --background --python build_output_world.py

または Blender 内 Text Editor から「スクリプト実行」。

安全性:
  * OUTPUT_WORLD Collection と接頭辞 "OW_" のデータブロックのみを再生成する。
  * ユーザーの他 Collection / データには一切触れない。
  * ファイル削除は行わない（バックアップは copy のみ）。
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
CUBE_MESH_NAME = PREFIX + "BaseCube"
CUBE_OBJ_NAME = PREFIX + "BaseCube"
FIELD_OBJ_NAME = PREFIX + "Field"
MAT_BLOCK_NAME = PREFIX + "Mat_Block"
MAT_ORB_NAME = PREFIX + "Mat_Orb"

RED_ATTR_NAME = "block_red"  # POINT ドメインの属性名（Shader は INSTANCER で読む）

CAM_EMERGENCE = PREFIX + "CAM_06_EMERGENCE"
CAM_DIVE = PREFIX + "CAM_07_DIVE"
CAM_HERO = PREFIX + "CAM_08_HERO"

TARGET_STATIC = PREFIX + "TARGET_STATIC"
TARGET_DIVE = PREFIX + "TARGET_DIVE"

HERO_ORB_COUNT = 3  # 発光球（数個のみ。ブロック群は GN インスタンスで生成）

# タイムライン
FRAME_START = 1
FRAME_END = 96
FPS = 24
SHOT_EMERGENCE = (1, 32)
SHOT_DIVE = (33, 64)
SHOT_HERO = (65, 96)

RES_X = 1920
RES_Y = 1080


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
# 設定ロード                                                                   #
# --------------------------------------------------------------------------- #
def script_dir() -> str:
    """スクリプトのあるディレクトリ（Text Editor 実行にも対応）。"""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # Text Editor 実行時など __file__ が無い場合
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
    # Blender 3.x
    coll = group.inputs if in_out == "INPUT" else group.outputs
    return coll.new(socket_type, name)


def set_eevee_engine(scene) -> str:
    """Blender バージョンに応じた EEVEE エンジンを設定して名称を返す。"""
    candidates = []
    if blender_version() >= (4, 2, 0):
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
        "render": os.path.join(base_out, "render"),
        "backups": os.path.join(base_out, "backups"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


def backup_existing_blend(dirs: dict) -> None:
    """既存の output_world.blend があれば安全にコピーしてバックアップ。

    ファイル削除は一切行わない（copy のみ）。
    """
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
    """OUTPUT_WORLD Collection と OW_ データブロックのみを削除する。

    他 Collection / 他データには触れない。ファイルは削除しない。
    """
    # 1) OUTPUT_WORLD 内のオブジェクトを削除
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

    # 2) OW_ 接頭辞のデータブロックを掃除（.001 重複を防ぐ）
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

    # 3) 我々が作ったマーカーだけ削除（camera が OW_ のもの）
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
# 角丸 Cube（1個だけ）                                                          #
# --------------------------------------------------------------------------- #
def create_rounded_cube(coll) -> "bpy.types.Object":
    """底面 z=0、上面 z=1 の単位角丸Cubeを1個だけ作成し、ソースとして隠す。

    bpy.ops を使わず bmesh で生成する。ベベルは最小限。
    """
    mesh = bpy.data.meshes.new(CUBE_MESH_NAME)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)  # -0.5..0.5

    # 最小限のベベル（角丸）
    try:
        bmesh.ops.bevel(
            bm,
            geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            offset=0.04,
            segments=1,
            profile=0.7,
            affect="EDGES",
        )
    except (TypeError, ValueError) as exc:
        log.warning("ベベルをスキップしました（バージョン差の可能性）: %s", exc)

    # 底面を z=0 に（原点を底面へ）
    bmesh.ops.translate(bm, verts=list(bm.verts), vec=(0.0, 0.0, 0.5))
    for f in bm.faces:
        f.smooth = False
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(CUBE_OBJ_NAME, mesh)
    obj.location = (0.0, 0.0, 0.0)
    # ソースとして描画から除外（インスタンスには影響しない）
    obj.hide_render = True
    obj.hide_viewport = True
    link_to_world(coll, obj)
    return obj


# --------------------------------------------------------------------------- #
# マテリアル                                                                    #
# --------------------------------------------------------------------------- #
def _principled(mat):
    return mat.node_tree.nodes.get("Principled BSDF")


def create_block_material(cfg) -> "bpy.types.Material":
    """コバルト青半光沢 + 赤（block_red 属性で分岐）マテリアル。"""
    mat = bpy.data.materials.new(MAT_BLOCK_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links

    bsdf = _principled(mat)
    out = nodes.get("Material Output")

    # 属性（INSTANCER）: 生成元ポイントの block_red を読む
    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_type = "INSTANCER"
    attr.attribute_name = RED_ATTR_NAME
    attr.location = (-800, 200)

    cobalt = (0.02, 0.09, 0.85, 1.0)
    signal_red = (0.85, 0.03, 0.05, 1.0)

    mix_base = nodes.new("ShaderNodeMixRGB")
    mix_base.blend_type = "MIX"
    mix_base.inputs["Color1"].default_value = cobalt
    mix_base.inputs["Color2"].default_value = signal_red
    mix_base.location = (-500, 300)
    links.new(attr.outputs["Fac"], mix_base.inputs["Fac"])

    # 赤ノードはわずかに発光
    emis = nodes.new("ShaderNodeMixRGB")
    emis.blend_type = "MIX"
    emis.inputs["Color1"].default_value = (0.0, 0.0, 0.0, 1.0)
    emis.inputs["Color2"].default_value = (0.9, 0.05, 0.08, 1.0)
    emis.location = (-500, 0)
    links.new(attr.outputs["Fac"], emis.inputs["Fac"])

    if bsdf is not None:
        links.new(mix_base.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.35
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.15
        # Emission 入力名はバージョンで異なる
        for ename in ("Emission Color", "Emission"):
            if ename in bsdf.inputs:
                links.new(emis.outputs["Color"], bsdf.inputs[ename])
                break
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 2.0
        if out is not None:
            links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def create_orb_material() -> "bpy.types.Material":
    """白〜淡いライラックの発光球マテリアル。"""
    mat = bpy.data.materials.new(MAT_ORB_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (200, 0)
    emis = nodes.new("ShaderNodeEmission")
    emis.inputs["Color"].default_value = (0.92, 0.90, 1.0, 1.0)  # 白〜ライラック
    emis.inputs["Strength"].default_value = 12.0
    emis.location = (0, 0)
    links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


# --------------------------------------------------------------------------- #
# Geometry Nodes                                                               #
# --------------------------------------------------------------------------- #
def _rv_float_sockets(node):
    """FunctionNodeRandomValue を FLOAT にして (min,max,seed,id,out) を返す。"""
    node.data_type = "FLOAT"
    mins = [s for s in node.inputs if s.name == "Min" and s.type == "VALUE"]
    maxs = [s for s in node.inputs if s.name == "Max" and s.type == "VALUE"]
    seed = [s for s in node.inputs if s.name == "Seed"]
    ids = [s for s in node.inputs if s.name == "ID"]
    out = [s for s in node.outputs if s.name == "Value" and s.type == "VALUE"]
    return mins[0], maxs[0], seed[0], ids[0], out[0]


def _map_range(nt, loc, from_min, from_max, to_min, to_max, interp="LINEAR", clamp=True):
    n = nt.nodes.new("ShaderNodeMapRange")
    n.data_type = "FLOAT"
    n.interpolation_type = interp
    n.clamp = clamp
    n.location = loc
    n.inputs["From Min"].default_value = from_min
    n.inputs["From Max"].default_value = from_max
    n.inputs["To Min"].default_value = to_min
    n.inputs["To Max"].default_value = to_max
    return n


def _math(nt, op, loc, val1=None, val2=None):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.location = loc
    if val1 is not None:
        n.inputs[0].default_value = val1
    if val2 is not None:
        n.inputs[1].default_value = val2
    return n


def build_geometry_nodes(cfg) -> "bpy.types.NodeTree":
    """Grid → Mesh to Points → Instance on Points の GN グループを構築。

    * Realize Instances は使わない（軽量）。
    * 高さ = 中央バイアス × Noise × strength + Random（中心に複数の山）。
    * Scene Time + Smooth Step で中心から外へビルドの波を広げる。
    """
    ng = bpy.data.node_groups.new(GN_GROUP_NAME, "GeometryNodeTree")
    new_interface_socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    new_interface_socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-1400, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (1400, 0)

    # 幾何定数
    gx, gy = cfg["grid_x"], cfg["grid_y"]
    spacing = cfg["spacing"]
    size_x = (gx - 1) * spacing
    size_y = (gy - 1) * spacing
    max_radius = 0.5 * math.hypot(size_x, size_y)
    block_w = spacing * 0.82
    band = max(spacing * 5.0, 1e-3)

    # --- Grid ---
    grid = nodes.new("GeometryNodeMeshGrid")
    grid.location = (-1150, 200)
    grid.inputs["Size X"].default_value = size_x
    grid.inputs["Size Y"].default_value = size_y
    grid.inputs["Vertices X"].default_value = gx
    grid.inputs["Vertices Y"].default_value = gy

    m2p = nodes.new("GeometryNodeMeshToPoints")
    m2p.location = (-950, 200)
    links.new(grid.outputs["Mesh"], m2p.inputs["Mesh"])

    # --- 位置・距離・index ---
    pos = nodes.new("GeometryNodeInputPosition")
    pos.location = (-1150, -250)
    sep = nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-950, -250)
    links.new(pos.outputs["Position"], sep.inputs["Vector"])
    comb_xy = nodes.new("ShaderNodeCombineXYZ")
    comb_xy.location = (-780, -250)
    links.new(sep.outputs["X"], comb_xy.inputs["X"])
    links.new(sep.outputs["Y"], comb_xy.inputs["Y"])
    dist = nodes.new("ShaderNodeVectorMath")
    dist.operation = "LENGTH"
    dist.location = (-600, -250)
    links.new(comb_xy.outputs["Vector"], dist.inputs[0])

    idx = nodes.new("GeometryNodeInputIndex")
    idx.location = (-1150, -520)

    # --- Noise（複数の山を作る） ---
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-780, 0)
    if "Scale" in noise.inputs:
        noise.inputs["Scale"].default_value = cfg["noise_scale"]
    if "Detail" in noise.inputs:
        noise.inputs["Detail"].default_value = 2.0
    links.new(pos.outputs["Position"], noise.inputs["Vector"])

    # --- 中央バイアス（中心=1, 端=0, Smooth Step） ---
    center_bias = _map_range(nt=ng, loc=(-600, 120), from_min=0.0, from_max=max_radius,
                             to_min=1.0, to_max=0.0, interp="SMOOTHSTEP", clamp=True)
    links.new(dist.outputs["Value"], center_bias.inputs["Value"])

    # --- Random（高さ変化 + 赤選択） ---
    rnd_h = nodes.new("FunctionNodeRandomValue")
    rnd_h.location = (-600, -60)
    r_min, r_max, r_seed, r_id, r_out = _rv_float_sockets(rnd_h)
    r_min.default_value = 0.0
    r_max.default_value = 1.0
    r_seed.default_value = cfg["random_seed"] + 3
    links.new(idx.outputs["Index"], r_id)

    rnd_red = nodes.new("FunctionNodeRandomValue")
    rnd_red.location = (-600, -420)
    rr_min, rr_max, rr_seed, rr_id, rr_out = _rv_float_sockets(rnd_red)
    rr_min.default_value = 0.0
    rr_max.default_value = 1.0
    rr_seed.default_value = cfg["random_seed"] + 7  # 赤位置は固定
    links.new(idx.outputs["Index"], rr_id)

    # --- 高さ合成: (center_bias * cps) * (noise * ns) + rand*0.12 → clamp01 ---
    cps = nodes.new("ShaderNodeMath"); cps.operation = "MULTIPLY"; cps.location = (-380, 120)
    cps.inputs[1].default_value = cfg["center_peak_strength"]
    links.new(center_bias.outputs["Result"], cps.inputs[0])

    ns = nodes.new("ShaderNodeMath"); ns.operation = "MULTIPLY"; ns.location = (-380, 0)
    ns.inputs[1].default_value = cfg["noise_strength"]
    links.new(noise.outputs["Fac"], ns.inputs[0])

    core = nodes.new("ShaderNodeMath"); core.operation = "MULTIPLY"; core.location = (-200, 60)
    links.new(cps.outputs["Value"], core.inputs[0])
    links.new(ns.outputs["Value"], core.inputs[1])

    rnd_scaled = nodes.new("ShaderNodeMath"); rnd_scaled.operation = "MULTIPLY"
    rnd_scaled.location = (-200, -80); rnd_scaled.inputs[1].default_value = 0.12
    links.new(r_out, rnd_scaled.inputs[0])

    h_sum = nodes.new("ShaderNodeMath"); h_sum.operation = "ADD"; h_sum.location = (-20, 0)
    links.new(core.outputs["Value"], h_sum.inputs[0])
    links.new(rnd_scaled.outputs["Value"], h_sum.inputs[1])

    h01 = nodes.new("ShaderNodeClamp"); h01.location = (160, 0)
    h01.inputs["Min"].default_value = 0.0
    h01.inputs["Max"].default_value = 1.0
    links.new(h_sum.outputs["Value"], h01.inputs["Value"])

    # height = min_height + range * h01
    h_scaled = nodes.new("ShaderNodeMath"); h_scaled.operation = "MULTIPLY"
    h_scaled.location = (340, 0)
    h_scaled.inputs[1].default_value = cfg["max_height"] - cfg["min_height"]
    links.new(h01.outputs["Result"], h_scaled.inputs[0])
    height = nodes.new("ShaderNodeMath"); height.operation = "ADD"; height.location = (520, 0)
    height.inputs[1].default_value = cfg["min_height"]
    links.new(h_scaled.outputs["Value"], height.inputs[0])

    # --- ビルドの波（Scene Time → build_radius → Smooth Step factor） ---
    stime = nodes.new("GeometryNodeInputSceneTime")
    stime.location = (-380, -300)
    build_prog = _map_range(nt=ng, loc=(-200, -300),
                            from_min=cfg["build_start_frame"], from_max=cfg["build_end_frame"],
                            to_min=0.0, to_max=1.0, interp="SMOOTHSTEP", clamp=True)
    links.new(stime.outputs["Frame"], build_prog.inputs["Value"])

    build_radius = nodes.new("ShaderNodeMath"); build_radius.operation = "MULTIPLY"
    build_radius.location = (-20, -300)
    build_radius.inputs[1].default_value = max_radius + band
    links.new(build_prog.outputs["Result"], build_radius.inputs[0])

    t = nodes.new("ShaderNodeMath"); t.operation = "SUBTRACT"; t.location = (160, -300)
    links.new(build_radius.outputs["Value"], t.inputs[0])
    links.new(dist.outputs["Value"], t.inputs[1])

    factor = _map_range(nt=ng, loc=(340, -300), from_min=0.0, from_max=band,
                        to_min=0.0, to_max=1.0, interp="SMOOTHSTEP", clamp=True)
    links.new(t.outputs["Value"], factor.inputs["Value"])

    # z_scale = height * factor
    z_scale = nodes.new("ShaderNodeMath"); z_scale.operation = "MULTIPLY"
    z_scale.location = (700, -150)
    links.new(height.outputs["Value"], z_scale.inputs[0])
    links.new(factor.outputs["Result"], z_scale.inputs[1])

    scale_vec = nodes.new("ShaderNodeCombineXYZ"); scale_vec.location = (880, -150)
    scale_vec.inputs["X"].default_value = block_w
    scale_vec.inputs["Y"].default_value = block_w
    links.new(z_scale.outputs["Value"], scale_vec.inputs["Z"])

    # --- 赤選択を POINT 属性として保存（Shader は INSTANCER で読む） ---
    red_test = nodes.new("ShaderNodeMath"); red_test.operation = "LESS_THAN"
    red_test.location = (-380, -420)
    red_test.inputs[1].default_value = cfg["red_ratio"]
    links.new(rr_out, red_test.inputs[0])

    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.location = (-750, 200)
    store.data_type = "FLOAT"
    store.domain = "POINT"
    store.inputs["Name"].default_value = RED_ATTR_NAME
    store_val = [s for s in store.inputs if s.name == "Value" and s.type == "VALUE"][0]
    links.new(m2p.outputs["Points"], store.inputs["Geometry"])
    links.new(red_test.outputs["Value"], store_val)

    # --- Object Info（ソースCube） ---
    obj_info = nodes.new("GeometryNodeObjectInfo")
    obj_info.location = (700, 350)
    obj_info.inputs["As Instance"].default_value = True
    base = bpy.data.objects.get(CUBE_OBJ_NAME)
    if base is not None:
        obj_info.inputs["Object"].default_value = base

    # --- Instance on Points ---
    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (1050, 200)
    links.new(store.outputs["Geometry"], iop.inputs["Points"])
    links.new(obj_info.outputs["Geometry"], iop.inputs["Instance"])
    links.new(scale_vec.outputs["Vector"], iop.inputs["Scale"])

    links.new(iop.outputs["Instances"], n_out.inputs[0])

    log.info(
        "GN 構築: grid=%dx%d (=%d instances), max_radius=%.2f, band=%.2f",
        gx, gy, gx * gy, max_radius, band,
    )
    return ng


def create_field_object(coll, cfg) -> "bpy.types.Object":
    """空メッシュ + Geometry Nodes modifier のフィールドオブジェクト。"""
    mesh = bpy.data.meshes.new(PREFIX + "FieldMesh")
    obj = bpy.data.objects.new(FIELD_OBJ_NAME, mesh)
    obj.location = (0.0, 0.0, 0.0)
    link_to_world(coll, obj)

    ng = build_geometry_nodes(cfg)
    mod = obj.modifiers.new(name="OW_GeometryNodes", type="NODES")
    mod.node_group = ng

    # マテリアルを割当（インスタンスへ継承される）
    block_mat = create_block_material(cfg)
    obj.data.materials.append(block_mat)
    return obj


# --------------------------------------------------------------------------- #
# 発光球（数個のみ）                                                            #
# --------------------------------------------------------------------------- #
def create_hero_orbs(coll, cfg) -> list:
    orb_mat = create_orb_material()
    orbs = []
    gx, gy, spacing = cfg["grid_x"], cfg["grid_y"], cfg["spacing"]
    positions = [
        (0.0, 0.0, cfg["max_height"] * 0.9),
        (-spacing * gx * 0.18, spacing * gy * 0.12, cfg["max_height"] * 0.7),
        (spacing * gx * 0.2, -spacing * gy * 0.15, cfg["max_height"] * 0.6),
    ]
    for i in range(min(HERO_ORB_COUNT, len(positions))):
        mesh = bpy.data.meshes.new(PREFIX + f"OrbMesh_{i}")
        bm = bmesh.new()
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.9)
        except TypeError:
            bmesh.ops.create_icosphere(bm, subdivisions=2, diameter=1.8)
        for f in bm.faces:
            f.smooth = True
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(PREFIX + f"Orb_{i}", mesh)
        obj.location = positions[i]
        obj.data.materials.append(orb_mat)
        link_to_world(coll, obj)
        orbs.append(obj)
    return orbs


# --------------------------------------------------------------------------- #
# ライティング                                                                  #
# --------------------------------------------------------------------------- #
def create_lights(coll, cfg) -> list:
    made = []
    # キーライト（大面積・柔らかい）
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

    # フィルライト（弱い）
    fill_data = bpy.data.lights.new(PREFIX + "Fill", "AREA")
    fill_data.shape = "RECTANGLE"
    fill_data.size = 30.0
    fill_data.size_y = 20.0
    fill_data.energy = 1200.0
    fill = bpy.data.objects.new(PREFIX + "Fill", fill_data)
    fill.location = (24.0, -10.0, 18.0)
    fill.rotation_euler = (math.radians(68), 0.0, math.radians(48))
    link_to_world(coll, fill)
    made.append(fill)

    # World（淡いアイボリー・反射控えめ）: 専用の OW_World を使い、他データに触れない
    world = bpy.data.worlds.get(PREFIX + "World") or bpy.data.worlds.new(PREFIX + "World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.95, 0.93, 0.88, 1.0)
        bg.inputs["Strength"].default_value = 0.35
    return made


# --------------------------------------------------------------------------- #
# カメラ                                                                        #
# --------------------------------------------------------------------------- #
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


def _smooth_fcurves(obj):
    ad = obj.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.handle_left_type = "AUTO_CLAMPED"
                kp.handle_right_type = "AUTO_CLAMPED"


def create_cameras(coll, cfg) -> dict:
    target_static = _add_empty(coll, TARGET_STATIC, (0.0, 0.0, 3.5))
    target_dive = _add_empty(coll, TARGET_DIVE, (0.0, 0.0, 4.0))

    # CAM_06 EMERGENCE : 40mm, 低め中距離, わずかにドリーイン
    cam06 = _add_camera(coll, CAM_EMERGENCE, 40.0)
    _track_to(cam06, target_static)
    _key_loc(cam06, SHOT_EMERGENCE[0], (6.0, -30.0, 7.0))
    _key_loc(cam06, SHOT_EMERGENCE[1], (2.0, -24.0, 6.5))
    _smooth_fcurves(cam06)

    # CAM_07 DIVE : 24mm, 内部を高速移動, 非衝突, 強いパララックス
    cam07 = _add_camera(coll, CAM_DIVE, 24.0)
    _track_to(cam07, target_dive)
    # ブロック最大高(=max_height)より上を維持して衝突回避
    fly_z = cfg["max_height"] + 1.0
    _key_loc(cam07, SHOT_DIVE[0], (-11.0, -19.0, fly_z))
    _key_loc(cam07, (SHOT_DIVE[0] + SHOT_DIVE[1]) // 2, (0.0, 0.0, fly_z + 1.0))
    _key_loc(cam07, SHOT_DIVE[1], (11.0, 19.0, fly_z))
    _smooth_fcurves(cam07)
    # 注視点は進行方向へ先行
    _key_loc(target_dive, SHOT_DIVE[0], (-5.0, -8.0, 4.0))
    _key_loc(target_dive, SHOT_DIVE[1], (15.0, 28.0, 3.0))
    _smooth_fcurves(target_dive)

    # CAM_08 HERO : 50mm, 上昇しながら後退, 全景ヒーロー構図
    cam08 = _add_camera(coll, CAM_HERO, 50.0)
    _track_to(cam08, target_static)
    _key_loc(cam08, SHOT_HERO[0], (3.0, -22.0, 11.0))
    _key_loc(cam08, SHOT_HERO[1], (0.0, -44.0, 22.0))
    _smooth_fcurves(cam08)
    # HERO のみ DOF（最終レンダー時に有効化）
    cam08.data.dof.focus_object = target_static
    cam08.data.dof.aperture_fstop = 4.0

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
# レンダー設定（プレビュー / 最終）                                              #
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
    """960×540 相当・低サンプル・モーションブラー/DOF OFF。"""
    scene = bpy.context.scene
    scene.render.resolution_percentage = int(cfg["preview_resolution_percentage"])
    ee = getattr(scene, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        ee.taa_render_samples = 16
    _set_motion_blur(scene, False)
    _set_dof_all(False)


def apply_final_settings(cfg) -> None:
    """1920×1080・高サンプル・モーションブラー ON・DOF(CAM_08)のみ ON。"""
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


# --------------------------------------------------------------------------- #
# プレビュー / ショットレンダー                                                  #
# --------------------------------------------------------------------------- #
SHOT_TABLE = {
    "06": {"cam": CAM_EMERGENCE, "range": SHOT_EMERGENCE, "preview_frame": SHOT_EMERGENCE[1]},
    "07": {"cam": CAM_DIVE, "range": SHOT_DIVE, "preview_frame": (SHOT_DIVE[0] + SHOT_DIVE[1]) // 2},
    "08": {"cam": CAM_HERO, "range": SHOT_HERO, "preview_frame": SHOT_HERO[1]},
}


def render_previews(cfg, dirs: dict) -> list:
    """3カメラの静止画プレビューを output/previews/ に保存する。"""
    scene = bpy.context.scene
    apply_preview_settings(cfg)
    saved = []
    for key, info in SHOT_TABLE.items():
        cam = bpy.data.objects.get(info["cam"])
        if cam is None:
            log.warning("プレビュー: カメラが見つかりません %s", info["cam"])
            continue
        scene.camera = cam
        scene.frame_set(info["preview_frame"])
        out_path = os.path.join(dirs["previews"], f"{info['cam']}.png")
        scene.render.filepath = out_path
        log.info("プレビュー描画: %s (frame %d)", info["cam"], info["preview_frame"])
        try:
            bpy.ops.render.render(write_still=True)
            saved.append(out_path)
        except RuntimeError as exc:
            log.error("プレビュー描画に失敗: %s (%s)", info["cam"], exc)
    return saved


def render_shot(shot_key: str, cfg, dirs: dict) -> str:
    """指定ショット('06'/'07'/'08')を連番でレンダリング（最終設定）。"""
    if shot_key not in SHOT_TABLE:
        raise ValueError(f"未知のショット: {shot_key} (06/07/08)")
    info = SHOT_TABLE[shot_key]
    scene = bpy.context.scene
    apply_final_settings(cfg)
    cam = bpy.data.objects.get(info["cam"])
    scene.camera = cam
    scene.frame_start, scene.frame_end = info["range"]
    shot_dir = os.path.join(dirs["render"], info["cam"])
    os.makedirs(shot_dir, exist_ok=True)
    scene.render.filepath = os.path.join(shot_dir, info["cam"] + "_")
    log.info("最終描画(連番): %s frames %s -> %s", info["cam"], info["range"], shot_dir)
    bpy.ops.render.render(animation=True)
    return shot_dir


# --------------------------------------------------------------------------- #
# サマリーログ                                                                  #
# --------------------------------------------------------------------------- #
def log_summary(cfg, dirs, cams, engine, instance_count) -> None:
    coll = bpy.data.collections.get(COLLECTION_NAME)
    obj_count = len(coll.objects) if coll else 0
    log.info("================ OUTPUT_WORLD 完了サマリー ================")
    log.info("Blender          : %s", bpy.app.version_string)
    log.info("Collection       : %s (オブジェクト数 %d)", COLLECTION_NAME, obj_count)
    log.info("インスタンス数   : %d (%dx%d, 個別オブジェクトではない)",
             instance_count, cfg["grid_x"], cfg["grid_y"])
    log.info("カメラ           : %s", ", ".join(sorted(c.name for c in cams.values())))
    log.info("レンダーエンジン : %s / %dx%d / %dfps", engine, RES_X, RES_Y, FPS)
    log.info("背景透過         : True / 出力形式 %s", cfg["output_format"])
    log.info("尺               : %d-%d frames (96F)", FRAME_START, FRAME_END)
    log.info(".blend 保存先    : %s", os.path.join(dirs["out"], "output_world.blend"))
    log.info("プレビュー保存先 : %s", dirs["previews"])
    log.info("連番出力先       : %s", dirs["render"])
    log.info("==========================================================")


# --------------------------------------------------------------------------- #
# メイン                                                                        #
# --------------------------------------------------------------------------- #
def save_blend(dirs) -> str:
    path = os.path.join(dirs["out"], "output_world.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    log.info(".blend を保存しました: %s", path)
    return path


def build(do_previews: bool = True) -> None:
    cfg = load_config()
    base_out = os.path.join(script_dir(), "output")
    dirs = ensure_dirs(base_out)

    log.info("Blender %s / OUTPUT_WORLD 構築を開始します。", bpy.app.version_string)

    backup_existing_blend(dirs)
    purge_previous()

    coll = get_world_collection()
    create_rounded_cube(coll)          # 角丸Cube 1個
    field = create_field_object(coll, cfg)  # GN でインスタンス化
    create_hero_orbs(coll, cfg)
    create_lights(coll, cfg)
    cams = create_cameras(coll, cfg)
    setup_markers(cams)

    engine = setup_scene_base(cfg)
    bpy.context.scene.camera = cams["emergence"]
    bpy.context.scene.frame_set(FRAME_START)

    save_blend(dirs)

    if do_previews:
        render_previews(cfg, dirs)
        # プレビュー後、最終描画に備えて設定を戻す
        apply_final_settings(cfg)
        save_blend(dirs)

    instance_count = cfg["grid_x"] * cfg["grid_y"]
    log_summary(cfg, dirs, cams, engine, instance_count)


def _parse_cli_args() -> dict:
    """`--` 以降の引数を読む（--no-previews / --shot 06 等）。"""
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
        build(do_previews=opts["previews"])
        if opts["shot"]:
            cfg = load_config()
            dirs = ensure_dirs(os.path.join(script_dir(), "output"))
            render_shot(opts["shot"], cfg, dirs)
    except Exception:  # noqa: BLE001 - 原因を明示してから再送出
        log.error("処理中にエラーが発生しました。以下を確認してください:")
        log.error("  * Blender のバージョン（4.x 推奨、3.4+ で概ね動作）")
        log.error("  * config.json の値域")
        log.error("  * 実行が Blender の Python 上であること")
        log.error("----- traceback -----\n%s", traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
