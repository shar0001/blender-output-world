"""Camera setup pointed at the OUTPUT field."""

from __future__ import annotations

import bpy
import mathutils

from .config import CameraConfig


def setup_camera(config: CameraConfig) -> "bpy.types.Object":
    """Create a camera and aim it at ``config.look_at``."""

    cam_data = bpy.data.cameras.new(name="Camera")
    cam_data.lens = config.lens
    cam = bpy.data.objects.new(name="Camera", object_data=cam_data)
    cam.location = config.location
    bpy.context.collection.objects.link(cam)

    # Point the camera at the target: -Z is the camera's forward axis.
    direction = mathutils.Vector(config.look_at) - mathutils.Vector(config.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    bpy.context.scene.camera = cam
    return cam
