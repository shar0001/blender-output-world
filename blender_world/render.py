"""Render configuration and OUTPUT image writing."""

from __future__ import annotations

import os

import bpy

from .config import RenderConfig


def _configure_engine(scene: "bpy.types.Scene", config: RenderConfig) -> None:
    """Select the render engine, tolerating Blender version differences.

    Newer Blender releases renamed ``BLENDER_EEVEE`` to
    ``BLENDER_EEVEE_NEXT``; fall back gracefully so the script runs across
    versions.
    """

    engine = config.engine
    try:
        scene.render.engine = engine
    except TypeError:
        fallback = "BLENDER_EEVEE_NEXT" if engine == "BLENDER_EEVEE" else "BLENDER_EEVEE"
        scene.render.engine = fallback

    eevee = getattr(scene, "eevee", None)
    if eevee is not None and hasattr(eevee, "taa_render_samples"):
        eevee.taa_render_samples = config.samples
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = config.samples


def configure_render(config: RenderConfig) -> str:
    """Apply render settings and return the absolute output file path."""

    scene = bpy.context.scene
    _configure_engine(scene, config)

    scene.render.resolution_x = config.resolution_x
    scene.render.resolution_y = config.resolution_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = config.file_format

    os.makedirs(config.output_dir, exist_ok=True)
    ext = config.file_format.lower()
    out_path = os.path.abspath(
        os.path.join(config.output_dir, f"{config.file_name}.{ext}")
    )
    scene.render.filepath = out_path
    return out_path


def render_still(config: RenderConfig) -> str:
    """Render a single frame to disk and return the written path."""

    out_path = configure_render(config)
    bpy.ops.render.render(write_still=True)
    return out_path
