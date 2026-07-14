"""Procedural terrain / OUTPUT field generation.

Builds a subdivided plane and displaces it with a deterministic Perlin
noise texture to create rolling terrain. Returns the terrain object so
callers can sample its height for object scatter placement.
"""

from __future__ import annotations

import math

import bpy
import mathutils

from .config import TerrainConfig


def _make_terrain_material() -> "bpy.types.Material":
    mat = bpy.data.materials.new(name="TerrainMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.12, 0.35, 0.14, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    return mat


def create_terrain(config: TerrainConfig) -> "bpy.types.Object":
    """Create the displaced ground field and return its object."""

    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=config.subdivisions,
        y_subdivisions=config.subdivisions,
        size=config.size,
    )
    terrain = bpy.context.active_object
    terrain.name = "OutputField"

    # Deterministic noise texture used to drive the displacement modifier.
    tex = bpy.data.textures.new(name="TerrainNoise", type="MUSGRAVE")
    tex.noise_scale = config.noise_scale
    # ``noise_basis``/seed differ across Blender versions; offset the texture
    # deterministically instead so results are reproducible everywhere.
    tex.nabla = 0.03

    displace = terrain.modifiers.new(name="Displace", type="DISPLACE")
    displace.texture = tex
    displace.strength = config.height
    displace.mid_level = 0.0

    terrain.data.materials.append(_make_terrain_material())

    # Smooth shading for the field surface.
    for polygon in terrain.data.polygons:
        polygon.use_smooth = True

    return terrain


def sample_height(config: TerrainConfig, x: float, y: float) -> float:
    """Approximate terrain height at ``(x, y)``.

    Mirrors the Musgrave-style displacement with a cheap analytic function
    so object scatter can rest on the surface without a raycast. This is an
    approximation, not an exact match to the modifier output.
    """

    freq = math.tau / max(config.noise_scale, 1e-6)
    n = (
        math.sin(x * freq + config.seed % 7)
        + math.cos(y * freq * 0.8 + config.seed % 5)
        + 0.5 * math.sin((x + y) * freq * 1.3)
    )
    return (n / 2.5) * config.height


def surface_point(config: TerrainConfig, x: float, y: float) -> mathutils.Vector:
    """Return a point resting on the approximate terrain surface."""

    return mathutils.Vector((x, y, sample_height(config, x, y)))
