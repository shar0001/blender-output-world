"""Lighting and world background setup."""

from __future__ import annotations

import bpy

from .config import LightingConfig


def setup_lighting(config: LightingConfig) -> "bpy.types.Object":
    """Add a sun light and configure the world background."""

    sun_data = bpy.data.lights.new(name="Sun", type="SUN")
    sun_data.energy = config.sun_energy
    sun = bpy.data.objects.new(name="Sun", object_data=sun_data)
    sun.rotation_euler = config.sun_angle
    bpy.context.collection.objects.link(sun)

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        r, g, b = config.world_color
        bg.inputs["Color"].default_value = (r, g, b, 1.0)
        bg.inputs["Strength"].default_value = config.world_strength

    return sun
