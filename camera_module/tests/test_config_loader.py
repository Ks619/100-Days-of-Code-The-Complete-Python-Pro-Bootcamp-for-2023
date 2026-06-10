"""Tests for the YAML config loader."""

import pytest
pytest.importorskip("yaml")

from camera_module.config_loader import Config


def _write_yaml(tmp_path, content: str):
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return p


def test_load_full_config(tmp_path):
    p = _write_yaml(tmp_path, """
camera:
  serial_number: "3200130"
  ip: "192.168.1.100"
  cti_file: "/path/to/producer.cti"
capture:
  delay: 1.5
  output_dir: "C:/shots"
  exposure_time: 20000
  gain: 6.0
  pixel_format: "BayerRG8"
""")
    cfg = Config.load(p)
    assert cfg.camera.serial_number == "3200130"
    assert cfg.camera.ip == "192.168.1.100"
    assert cfg.camera.cti_file == "/path/to/producer.cti"
    assert cfg.capture.delay == 1.5
    assert cfg.capture.output_dir == "C:/shots"
    assert cfg.capture.exposure_time == 20000.0
    assert cfg.capture.gain == 6.0
    assert cfg.capture.pixel_format == "BayerRG8"


def test_null_values_become_none(tmp_path):
    p = _write_yaml(tmp_path, """
camera:
  serial_number: null
  ip: null
capture:
  exposure_time: null
  gain: null
  pixel_format: null
""")
    cfg = Config.load(p)
    assert cfg.camera.serial_number is None
    assert cfg.camera.ip is None
    assert cfg.capture.exposure_time is None
    assert cfg.capture.gain is None
    assert cfg.capture.pixel_format is None


def test_missing_file_returns_defaults():
    cfg = Config.load("/nonexistent/config.yaml")
    assert cfg.capture.delay == 0.0
    assert cfg.capture.output_dir == "captures"


def test_partial_config_fills_defaults(tmp_path):
    p = _write_yaml(tmp_path, """
capture:
  delay: 2.0
""")
    cfg = Config.load(p)
    assert cfg.capture.delay == 2.0
    assert cfg.capture.output_dir == "captures"   # default
    assert cfg.camera.serial_number is None        # default
