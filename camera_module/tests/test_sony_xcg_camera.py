"""Unit tests for the Sony XCG-CG240C camera module.

The GenICam stack is replaced by lightweight fakes, so the tests run
without a camera, without a GenTL producer and without the harvesters
package installed.  numpy and OpenCV are required (they are runtime
dependencies of the module anyway).
"""

import numpy as np
import pytest

pytest.importorskip("cv2")

from camera_module import sony_xcg_camera
from camera_module.sony_xcg_camera import (
    CameraError,
    CameraNotConnectedError,
    CaptureTimeoutError,
    SonyXCG240Camera,
    _convert_to_bgr,
)

WIDTH, HEIGHT = 16, 8


# ---------------------------------------------------------------------------
# Fake GenICam / harvesters stack
# ---------------------------------------------------------------------------
class FakeNode:
    def __init__(self, value=None):
        self.value = value
        self.executed = 0

    def execute(self):
        self.executed += 1


class FakeNodeMap:
    def __init__(self):
        self.AcquisitionMode = FakeNode("SingleFrame")
        self.TriggerSelector = FakeNode("FrameStart")
        self.TriggerMode = FakeNode("Off")
        self.TriggerSource = FakeNode("Line1")
        self.TriggerSoftware = FakeNode()
        self.PixelFormat = FakeNode("BayerRG8")
        self.ExposureTime = FakeNode(10000.0)
        self.Gain = FakeNode(0.0)
        self.DeviceVendorName = FakeNode("Sony")
        self.DeviceModelName = FakeNode("XCG-CG240C")
        self.DeviceSerialNumber = FakeNode("3200130")


class FakeComponent:
    def __init__(self, data, width, height, data_format):
        self.data = data
        self.width = width
        self.height = height
        self.data_format = data_format


class FakePayload:
    def __init__(self, component):
        self.components = [component]


class FakeBuffer:
    def __init__(self, component):
        self.payload = FakePayload(component)
        self.requeued = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.requeued = True


class FakeRemoteDevice:
    def __init__(self, node_map):
        self.node_map = node_map


class FakeAcquirer:
    def __init__(self, node_map, frame_factory):
        self.remote_device = FakeRemoteDevice(node_map)
        self._frame_factory = frame_factory
        self.started = False
        self.destroyed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def fetch(self, timeout=None):
        return self._frame_factory()

    def destroy(self):
        self.destroyed = True


class FakeDeviceInfo:
    model = "XCG-CG240C"
    serial_number = "3200130"
    vendor = "Sony"


class FakeHarvester:
    """Stands in for harvesters.core.Harvester."""

    node_map = None
    frame_factory = None
    last_instance = None

    def __init__(self):
        self.device_info_list = [FakeDeviceInfo()]
        self.files = []
        self.was_reset = False
        self.acquirer = None
        FakeHarvester.last_instance = self

    def add_file(self, path):
        self.files.append(path)

    def update(self):
        pass

    def create(self, search_key):
        self.acquirer = FakeAcquirer(FakeHarvester.node_map, FakeHarvester.frame_factory)
        return self.acquirer

    def reset(self):
        self.was_reset = True


def make_bayer_rg8_frame():
    """A 2x2-tiled pure-red BayerRG frame: R G / G B with R=255."""
    raw = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    raw[0::2, 0::2] = 255  # red photosites
    component = FakeComponent(raw.reshape(-1), WIDTH, HEIGHT, "BayerRG8")
    return FakeBuffer(component)


@pytest.fixture
def camera(monkeypatch, tmp_path):
    """A connected camera wired to the fake GenICam stack."""
    node_map = FakeNodeMap()
    FakeHarvester.node_map = node_map
    FakeHarvester.frame_factory = make_bayer_rg8_frame
    monkeypatch.setattr(sony_xcg_camera, "Harvester", FakeHarvester)

    cti = tmp_path / "fake_producer.cti"
    cti.write_text("not a real producer")
    cam = SonyXCG240Camera(cti_file=cti, serial_number="3200130")
    cam.connect()
    yield cam
    cam.disconnect()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_connect_configures_software_trigger(camera):
    node_map = FakeHarvester.node_map
    assert node_map.AcquisitionMode.value == "Continuous"
    assert node_map.TriggerSelector.value == "FrameStart"
    assert node_map.TriggerMode.value == "On"
    assert node_map.TriggerSource.value == "Software"


def test_capture_fires_software_trigger_and_demosaics(camera):
    image = camera.capture()
    assert FakeHarvester.node_map.TriggerSoftware.executed == 1
    # Bayer input must come back demosaiced to 3-channel BGR.
    assert image.shape == (HEIGHT, WIDTH, 3)
    assert image.dtype == np.uint8
    # The frame is pure red: blue/green stay low, red is dominant.
    b, g, r = image[..., 0], image[..., 1], image[..., 2]
    assert r.max() == 255
    assert r.mean() > b.mean()
    assert r.mean() > g.mean()


def test_save_image_writes_timestamped_png(camera, tmp_path):
    out_dir = tmp_path / "captures"
    saved = camera.save_image(out_dir)
    assert saved.exists()
    assert saved.parent == out_dir
    assert saved.suffix == ".png"
    assert saved.name.startswith("XCG-CG240C_")


def test_save_image_explicit_path(camera, tmp_path):
    target = tmp_path / "sub" / "shot.png"
    saved = camera.save_image(target)
    assert saved == target
    assert target.exists()


def test_capture_timeout_raises_dedicated_error(camera):
    def timeout_factory():
        raise sony_xcg_camera.TimeoutException("no frame")

    camera._acquirer._frame_factory = timeout_factory
    with pytest.raises(CaptureTimeoutError):
        camera.capture()


def test_operations_require_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(sony_xcg_camera, "Harvester", FakeHarvester)
    FakeHarvester.node_map = FakeNodeMap()
    cti = tmp_path / "fake_producer.cti"
    cti.write_text("x")
    cam = SonyXCG240Camera(cti_file=cti)
    with pytest.raises(CameraNotConnectedError):
        cam.capture()


def test_disconnect_releases_resources(monkeypatch, tmp_path):
    node_map = FakeNodeMap()
    FakeHarvester.node_map = node_map
    FakeHarvester.frame_factory = make_bayer_rg8_frame
    monkeypatch.setattr(sony_xcg_camera, "Harvester", FakeHarvester)
    cti = tmp_path / "fake_producer.cti"
    cti.write_text("x")

    with SonyXCG240Camera(cti_file=cti) as cam:
        acquirer = cam._acquirer
        harvester = FakeHarvester.last_instance
        cam.capture()
    assert acquirer.destroyed
    assert harvester.was_reset
    assert not cam.is_connected


def test_integration_time_and_gain_properties(camera):
    camera.integration_time = 20.0   # 20 ms -> 20000 µs on the camera
    camera.gain = 6.0
    assert camera.integration_time == 20.0
    assert camera.gain == 6.0
    assert FakeHarvester.node_map.ExposureTime.value == 20000.0  # stored as µs


def test_unsupported_pixel_format_raises():
    data = np.zeros(WIDTH * HEIGHT * 2, dtype=np.uint8)
    with pytest.raises(CameraError, match="not supported"):
        _convert_to_bgr(data, WIDTH, HEIGHT, "YUV422_8")


@pytest.mark.parametrize(
    "pixel_format,bits", [("Mono8", 8), ("Mono10", 10), ("Mono12", 12)]
)
def test_mono_conversion_scales_to_full_range(pixel_format, bits):
    dtype = np.uint8 if bits == 8 else np.uint16
    max_value = (1 << bits) - 1
    data = np.full(WIDTH * HEIGHT, max_value, dtype=dtype)
    image = _convert_to_bgr(data, WIDTH, HEIGHT, pixel_format)
    assert image.shape == (HEIGHT, WIDTH)
    expected = 255 if bits == 8 else ((1 << bits) - 1) << (16 - bits)
    assert int(image.max()) == expected


def test_rgb8_is_converted_to_bgr_order():
    rgb = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    rgb[..., 0] = 200  # red channel in RGB order
    image = _convert_to_bgr(rgb.reshape(-1), WIDTH, HEIGHT, "RGB8")
    assert image[..., 2].max() == 200  # red ends up in BGR channel 2
    assert image[..., 0].max() == 0
