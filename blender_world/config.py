"""Configuration for the Blender OUTPUT world generator.

All tunable parameters live here so the generation is deterministic and
easy to adjust without touching the generation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class TerrainConfig:
    """Parameters that control the ground field / terrain."""

    size: float = 40.0            # side length of the square field (meters)
    subdivisions: int = 128       # grid resolution used for displacement
    height: float = 4.0           # peak displacement height
    noise_scale: float = 6.0      # spatial frequency of the terrain noise
    seed: int = 20260714          # deterministic noise seed


@dataclass
class ScatterConfig:
    """Parameters that control the objects scattered on the field."""

    count: int = 60               # number of scattered objects
    min_scale: float = 0.4
    max_scale: float = 1.6
    margin: float = 2.0           # keep objects away from the field edges
    seed: int = 424242


@dataclass
class LightingConfig:
    """Sun light and world background."""

    sun_energy: float = 3.0
    sun_angle: Tuple[float, float, float] = (0.9, 0.0, 0.6)  # radians
    world_color: Tuple[float, float, float] = (0.05, 0.09, 0.16)
    world_strength: float = 1.0


@dataclass
class CameraConfig:
    location: Tuple[float, float, float] = (0.0, -38.0, 22.0)
    look_at: Tuple[float, float, float] = (0.0, 0.0, 2.0)
    lens: float = 35.0            # focal length in mm


@dataclass
class RenderConfig:
    engine: str = "BLENDER_EEVEE"
    resolution_x: int = 1920
    resolution_y: int = 1080
    samples: int = 64
    output_dir: str = "output"
    file_name: str = "output_world"
    file_format: str = "PNG"


@dataclass
class WorldConfig:
    """Top-level configuration aggregating every stage."""

    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    scatter: ScatterConfig = field(default_factory=ScatterConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    render: RenderConfig = field(default_factory=RenderConfig)


def default_config() -> WorldConfig:
    """Return the default world configuration."""

    return WorldConfig()
