"""Scene bootstrap helpers.

Everything here is idempotent: running the generator twice in the same
Blender session produces the same clean scene.
"""

from __future__ import annotations

import bpy


def reset_scene() -> None:
    """Remove every object and purge orphan datablocks.

    This gives generation a clean slate regardless of what the default
    startup file contains.
    """

    # Delete all objects.
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Purge orphaned data (meshes, materials, lights left behind).
    for collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.textures,
    ):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def ensure_object_mode() -> None:
    """Guarantee we are in OBJECT mode before mutating the scene."""

    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
