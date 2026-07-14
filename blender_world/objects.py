"""Scatter procedural objects across the OUTPUT field.

Objects are placed on a deterministic pseudo-random grid and rest on the
approximate terrain surface. A small palette of primitive shapes keeps the
render visually varied without external assets.
"""

from __future__ import annotations

import random
from typing import List

import bpy

from .config import ScatterConfig, TerrainConfig
from .terrain import surface_point

_PALETTE = [
    (0.85, 0.32, 0.22, 1.0),
    (0.24, 0.55, 0.85, 1.0),
    (0.95, 0.78, 0.28, 1.0),
    (0.55, 0.35, 0.75, 1.0),
]


def _make_object_material(index: int) -> "bpy.types.Material":
    color = _PALETTE[index % len(_PALETTE)]
    mat = bpy.data.materials.new(name=f"ScatterMat_{index}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.4
    return mat


def _add_primitive(kind: int) -> "bpy.types.Object":
    if kind == 0:
        bpy.ops.mesh.primitive_cube_add()
    elif kind == 1:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2)
    elif kind == 2:
        bpy.ops.mesh.primitive_cone_add()
    else:
        bpy.ops.mesh.primitive_cylinder_add()
    return bpy.context.active_object


def scatter_objects(
    scatter: ScatterConfig, terrain: TerrainConfig
) -> List["bpy.types.Object"]:
    """Place ``scatter.count`` primitives across the field surface."""

    rng = random.Random(scatter.seed)
    half = terrain.size / 2.0 - scatter.margin
    created: List["bpy.types.Object"] = []

    for i in range(scatter.count):
        x = rng.uniform(-half, half)
        y = rng.uniform(-half, half)
        point = surface_point(terrain, x, y)

        obj = _add_primitive(rng.randint(0, 3))
        scale = rng.uniform(scatter.min_scale, scatter.max_scale)
        obj.scale = (scale, scale, scale)
        # Rest the object on the surface (lift by its half-height).
        point.z += scale
        obj.location = point
        obj.rotation_euler = (0.0, 0.0, rng.uniform(0.0, 6.283))
        obj.name = f"Scatter_{i:03d}"
        obj.data.materials.append(_make_object_material(i))
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        created.append(obj)

    return created
