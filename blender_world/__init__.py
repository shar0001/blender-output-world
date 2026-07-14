"""Blender OUTPUT World generator package.

Procedurally builds a 3D "OUTPUT field" world in Blender — displaced
terrain, scattered objects, lighting, and a camera — and renders it to an
image. Designed to run headless via::

    blender --background --python generate_world.py

See :func:`build_world` for the full pipeline.
"""

from __future__ import annotations

from .config import WorldConfig, default_config

__all__ = ["WorldConfig", "default_config", "build_world"]


def build_world(config: "WorldConfig | None" = None) -> str:
    """Run the full generation pipeline and render the OUTPUT world.

    Imports of the Blender-dependent modules are deferred so that this
    package can be imported (for example, to read :mod:`config`) outside of
    Blender without triggering an ``import bpy`` failure.

    Returns the absolute path of the rendered image.
    """

    from . import camera, lighting, objects, render, scene, terrain

    if config is None:
        config = default_config()

    scene.reset_scene()
    terrain_obj = terrain.create_terrain(config.terrain)
    objects.scatter_objects(config.scatter, config.terrain)
    lighting.setup_lighting(config.lighting)
    camera.setup_camera(config.camera)

    out_path = render.render_still(config.render)
    print(f"[blender_world] OUTPUT world rendered to: {out_path}")
    print(f"[blender_world] terrain object: {terrain_obj.name}")
    return out_path
