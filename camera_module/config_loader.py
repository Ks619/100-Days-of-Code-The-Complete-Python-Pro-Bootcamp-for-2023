"""Load and validate the camera_module YAML configuration file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class CameraConfig:
    serial_number: Optional[str] = None
    ip: Optional[str] = None
    cti_file: Optional[str] = None
    fetch_timeout: float = 5.0


@dataclass
class CaptureConfig:
    delay: float = 0.0
    count: int = 1
    output_dir: str = "captures"
    exposure_time: Optional[float] = None
    gain: Optional[float] = None
    pixel_format: Optional[str] = None


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Config":
        """Load config from a YAML file. Falls back to defaults if file is missing."""
        if yaml is None:
            raise ImportError("PyYAML is required: pip install pyyaml")

        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()

        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        cam_raw = raw.get("camera", {}) or {}
        cap_raw = raw.get("capture", {}) or {}

        return cls(
            camera=CameraConfig(
                serial_number=cam_raw.get("serial_number"),
                ip=cam_raw.get("ip"),
                cti_file=cam_raw.get("cti_file"),
                fetch_timeout=float(cam_raw.get("fetch_timeout", 5.0)),
            ),
            capture=CaptureConfig(
                delay=float(cap_raw.get("delay", 0.0)),
                count=int(cap_raw.get("count", 1)),
                output_dir=str(cap_raw.get("output_dir", "captures")),
                exposure_time=_optional_float(cap_raw.get("exposure_time")),
                gain=_optional_float(cap_raw.get("gain")),
                pixel_format=cap_raw.get("pixel_format") or None,
            ),
        )


def _optional_float(value) -> Optional[float]:
    return float(value) if value is not None else None
