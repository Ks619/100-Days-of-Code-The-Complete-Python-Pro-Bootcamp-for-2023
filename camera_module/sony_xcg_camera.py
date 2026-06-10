"""Software-trigger image capture for the Sony XCG-CG240C GigE Vision camera.

Overview
--------
The Sony XCG-CG240C is a 2.35 MP (1920 x 1200) colour industrial camera
built around a 1/1.2-type global-shutter CMOS sensor.  It complies with the
GigE Vision / GenICam standards and is powered either over Ethernet
(PoE, IEEE 802.3af) or from a 12 V DC supply.

Because the camera implements the standard GenICam feature naming
convention (SFNC), this module drives it through the vendor-neutral
GenICam Python consumer `harvesters <https://github.com/genicam/harvesters>`_
and any GigE Vision GenTL producer (a ``*.cti`` shared library), e.g.:

* Balluff / MATRIX VISION ``mvGenTLProducer.cti`` (free with mvIMPACT Acquire)
* Pleora eBUS SDK ``ebTLProducer.cti``
* STEMMER IMAGING Common Vision Blox ``GEVTL.cti``

Quick start
-----------
>>> from camera_module import SonyXCG240Camera
>>> with SonyXCG240Camera(cti_file="/opt/mvIMPACT_Acquire/lib/x86_64/mvGenTLProducer.cti") as cam:
...     saved_path = cam.save_image("captures/inspection.png")   # software trigger + save
...     frame = cam.capture()                                    # software trigger -> numpy array

The software-trigger sequence programmed into the camera is the standard
GenICam one::

    AcquisitionMode  = Continuous
    TriggerSelector  = FrameStart
    TriggerMode      = On
    TriggerSource    = Software
    TriggerSoftware.execute()      # fires one exposure -> one frame
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

try:  # OpenCV is used for Bayer demosaicing and for writing image files.
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:  # harvesters is the GenICam consumer used to talk to the camera.
    from harvesters.core import Harvester
except ImportError:  # pragma: no cover
    Harvester = None

try:  # Raised by the GenTL producer when no frame arrives in time.
    from genicam.gentl import TimeoutException
except ImportError:  # pragma: no cover
    class TimeoutException(Exception):
        """Fallback used when the genicam runtime is not installed."""

_LOGGER = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT_S = 10.0
CONNECTION_ATTEMPTS = 2
CONNECTION_TIMEOUT_S = 600.0   # 10 minutes per attempt
CONNECTION_SCAN_INTERVAL_S = 5.0

_MONO_PATTERN = re.compile(r"Mono(8|10|12|16)")
_BAYER_PATTERN = re.compile(r"Bayer(RG|GR|GB|BG)(8|10|12|16)")

# OpenCV names Bayer patterns by the 2x2 tile that starts at the *second*
# row/column of the image, so the GenICam name and the OpenCV constant are
# deliberately "diagonally swapped" (GenICam BayerRG == OpenCV BayerBG).
_GENICAM_TO_CV2_BAYER = {"RG": "BG", "GR": "GB", "GB": "GR", "BG": "RG"}

PathLike = Union[str, os.PathLike]


class CameraError(RuntimeError):
    """Base class for every error raised by this module."""


class CameraNotConnectedError(CameraError):
    """An operation that needs an open camera was called while disconnected."""


class CaptureTimeoutError(CameraError):
    """The camera did not deliver a frame within the fetch timeout."""


def find_cti_file(extra_dirs: Sequence[PathLike] = ()) -> Optional[str]:
    """Return the first GenTL producer (``*.cti``) found on this machine.

    Looks through the directories listed in the standard environment
    variables ``GENICAM_GENTL64_PATH`` / ``GENICAM_GENTL32_PATH`` (set by
    every GenTL producer installer) and then through ``extra_dirs``.
    """
    candidates: List[str] = []
    for env_var in ("GENICAM_GENTL64_PATH", "GENICAM_GENTL32_PATH"):
        candidates.extend(os.environ.get(env_var, "").split(os.pathsep))
    candidates.extend(str(d) for d in extra_dirs)

    for directory in filter(None, candidates):
        for cti in sorted(Path(directory).glob("*.cti")):
            return str(cti)
    return None


def list_devices(cti_file: Optional[PathLike] = None) -> List[Dict[str, str]]:
    """Enumerate the GenICam cameras reachable through ``cti_file``.

    Returns one dict per camera with the fields the producer exposes
    (model, serial_number, vendor, ...).  Useful to discover the serial
    number to pass to :class:`SonyXCG240Camera` in multi-camera setups.
    """
    if Harvester is None:
        raise ImportError(
            "The 'harvesters' package is required: pip install harvesters"
        )
    cti = str(cti_file) if cti_file else find_cti_file()
    if not cti:
        raise CameraError(
            "No GenTL producer (*.cti) found. Install one (e.g. Balluff "
            "mvGenTLProducer) or pass cti_file explicitly."
        )

    harvester = Harvester()
    try:
        harvester.add_file(cti)
        harvester.update()
        devices = []
        for info in harvester.device_info_list:
            devices.append(
                {
                    field: str(getattr(info, field, "") or "")
                    for field in (
                        "model",
                        "serial_number",
                        "vendor",
                        "id_",
                        "version",
                        "user_defined_name",
                    )
                }
            )
        return devices
    finally:
        harvester.reset()


def _convert_to_bgr(
    data: np.ndarray, width: int, height: int, pixel_format: str
) -> np.ndarray:
    """Convert a raw transport buffer into a mono or BGR numpy image.

    10/12-bit data is left-shifted to use the full 16-bit range so that the
    saved PNG/TIFF files have a sensible brightness.
    """
    mono = _MONO_PATTERN.fullmatch(pixel_format)
    if mono:
        bits = int(mono.group(1))
        image = data.reshape(height, width)
        if bits > 8:
            image = np.left_shift(image.astype(np.uint16), 16 - bits)
        return image

    bayer = _BAYER_PATTERN.fullmatch(pixel_format)
    if bayer:
        pattern, bits_str = bayer.groups()
        bits = int(bits_str)
        raw = data.reshape(height, width)
        if bits > 8:
            raw = np.left_shift(raw.astype(np.uint16), 16 - bits)
        code = getattr(cv2, f"COLOR_Bayer{_GENICAM_TO_CV2_BAYER[pattern]}2BGR")
        return cv2.cvtColor(raw, code)

    if pixel_format in ("RGB8", "RGB8Packed"):
        return cv2.cvtColor(data.reshape(height, width, 3), cv2.COLOR_RGB2BGR)
    if pixel_format in ("BGR8", "BGR8Packed"):
        return data.reshape(height, width, 3)

    raise CameraError(
        f"Pixel format '{pixel_format}' is not supported by this module. "
        "Set the camera to one of: Mono8/10/12, BayerRG8/10/12 (any Bayer "
        "order), RGB8 or BGR8, e.g. cam.pixel_format = 'BayerRG8'."
    )


class SonyXCG240Camera:
    """High-level, software-trigger oriented driver for the XCG-CG240C.

    The class also works with any other GenICam/SFNC compliant GigE Vision
    camera, but defaults and documentation target the Sony XCG-CG240C.

    Parameters
    ----------
    cti_file:
        Path to the GenTL producer (``*.cti``).  When ``None`` the standard
        ``GENICAM_GENTL64_PATH``/``GENICAM_GENTL32_PATH`` directories are
        searched and the first producer found is used.
    serial_number:
        Serial number of the camera to open (printed on the label, e.g.
        ``"3200130"``).  May be ``None`` when only one camera is connected.
    fetch_timeout:
        Seconds :meth:`capture` waits for a frame after a software trigger.
    auto_configure:
        When ``True`` (default) :meth:`connect` immediately programs the
        camera for software-triggered acquisition.

    The class is a context manager: entering connects, leaving disconnects.
    """

    MODEL_NAME = "XCG-CG240C"
    SENSOR_RESOLUTION = (1920, 1200)  # (width, height) at full frame

    _EXPOSURE_NODES = ("ExposureTime", "ExposureTimeAbs", "ExposureTimeRaw")
    _GAIN_NODES = ("Gain", "GainRaw")

    def __init__(
        self,
        cti_file: Optional[PathLike] = None,
        serial_number: Optional[str] = None,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT_S,
        auto_configure: bool = True,
    ) -> None:
        if Harvester is None:
            raise ImportError(
                "The 'harvesters' package is required: pip install harvesters"
            )
        if cv2 is None:
            raise ImportError(
                "The 'opencv-python' package is required: pip install opencv-python"
            )

        cti = str(cti_file) if cti_file else find_cti_file()
        if not cti:
            raise CameraError(
                "No GenTL producer (*.cti) found. Install one (see README) "
                "or pass cti_file explicitly."
            )
        if not Path(cti).is_file():
            raise FileNotFoundError(f"GenTL producer not found: {cti}")

        self._cti_file = cti
        self._serial_number = serial_number
        self._fetch_timeout = float(fetch_timeout)
        self._auto_configure = auto_configure
        self._harvester: Optional[Any] = None
        self._acquirer: Optional[Any] = None
        self._acquiring = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._acquirer is not None

    def connect(self) -> "SonyXCG240Camera":
        """Open the camera, retrying up to 2 times with a 10-minute timeout each."""
        if self.is_connected:
            return self

        _LOGGER.info("Using GenTL producer: %s", self._cti_file)
        last_error: Optional[Exception] = None
        for attempt in range(1, CONNECTION_ATTEMPTS + 1):
            _LOGGER.info(
                "Connection attempt %d/%d (timeout %.0fs) ...",
                attempt, CONNECTION_ATTEMPTS, CONNECTION_TIMEOUT_S,
            )
            harvester = Harvester()
            try:
                harvester.add_file(self._cti_file)
                deadline = time.monotonic() + CONNECTION_TIMEOUT_S
                while True:
                    harvester.update()
                    if harvester.device_info_list:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CameraError(
                            f"No GigE Vision camera found after "
                            f"{CONNECTION_TIMEOUT_S:.0f}s on attempt {attempt}. "
                            "Check cabling, PoE power (802.3af) and subnet."
                        )
                    wait = min(CONNECTION_SCAN_INTERVAL_S, remaining)
                    _LOGGER.info(
                        "No camera yet — retrying in %.0fs (%.0fs remaining) ...",
                        wait, remaining,
                    )
                    time.sleep(wait)

                search_key: Any = (
                    {"serial_number": self._serial_number}
                    if self._serial_number
                    else 0
                )
                self._acquirer = harvester.create(search_key)
                self._harvester = harvester
                break  # connected successfully
            except CameraError as exc:
                harvester.reset()
                last_error = exc
                if attempt < CONNECTION_ATTEMPTS:
                    _LOGGER.warning("Attempt %d failed: %s — retrying ...", attempt, exc)
                else:
                    raise CameraError(
                        f"Could not connect after {CONNECTION_ATTEMPTS} attempts. "
                        f"Last error: {exc}"
                    ) from exc
            except Exception as exc:
                harvester.reset()
                raise CameraError(
                    f"Could not open camera (serial={self._serial_number!r}): {exc}"
                ) from exc

        info = self.device_info
        _LOGGER.info(
            "Connected to %s (serial %s)",
            info.get("model", "unknown model"),
            info.get("serial_number", "?"),
        )
        if self.MODEL_NAME not in info.get("model", ""):
            _LOGGER.info(
                "Note: connected camera reports model '%s' (driver is tuned "
                "for the %s but speaks generic GenICam).",
                info.get("model"),
                self.MODEL_NAME,
            )
        if self._auto_configure:
            self.configure_software_trigger()
        return self

    def disconnect(self) -> None:
        """Stop acquisition and release the camera and the GenTL producer."""
        with self._lock:
            if self._acquirer is not None:
                try:
                    if self._acquiring:
                        self._call_first(self._acquirer, ("stop", "stop_acquisition"))
                except Exception:  # noqa: BLE001 - best effort during teardown
                    _LOGGER.debug("Ignoring error while stopping acquisition")
                try:
                    self._acquirer.destroy()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Ignoring error while destroying acquirer")
                self._acquirer = None
                self._acquiring = False
            if self._harvester is not None:
                try:
                    self._harvester.reset()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Ignoring error while resetting harvester")
                self._harvester = None

    def __enter__(self) -> "SonyXCG240Camera":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "connected" if self.is_connected else "disconnected"
        return (
            f"<SonyXCG240Camera serial={self._serial_number!r} "
            f"cti={self._cti_file!r} {state}>"
        )

    # ------------------------------------------------------------------
    # Camera configuration
    # ------------------------------------------------------------------
    def configure_software_trigger(self) -> None:
        """Program the GenICam software-trigger sequence (one trigger = one frame)."""
        self._set_enum_if_available("AcquisitionMode", "Continuous")
        self._set_enum_if_available("TriggerSelector", "FrameStart")
        self._set_enum("TriggerMode", "On")
        self._set_enum("TriggerSource", "Software")
        _LOGGER.debug("Camera configured for software trigger")

    def configure_free_run(self) -> None:
        """Disable triggering: the camera streams frames continuously."""
        self._set_enum_if_available("TriggerSelector", "FrameStart")
        self._set_enum("TriggerMode", "Off")
        self._set_enum_if_available("AcquisitionMode", "Continuous")
        _LOGGER.debug("Camera configured for free run")

    @property
    def device_info(self) -> Dict[str, str]:
        """Identity reported by the camera (model, serial, vendor, ...)."""
        node_map = self._require_node_map()
        info = {}
        for key, node in (
            ("vendor", "DeviceVendorName"),
            ("model", "DeviceModelName"),
            ("serial_number", "DeviceSerialNumber"),
            ("version", "DeviceVersion"),
            ("user_id", "DeviceUserID"),
        ):
            try:
                info[key] = str(getattr(node_map, node).value)
            except Exception:  # noqa: BLE001 - node not exposed by this device
                continue
        return info

    @property
    def integration_time(self) -> float:
        """Integration (exposure) time in milliseconds."""
        return float(self._get_first_feature(self._EXPOSURE_NODES)) / 1000.0

    @integration_time.setter
    def integration_time(self, milliseconds: float) -> None:
        self._set_first_feature(self._EXPOSURE_NODES, milliseconds * 1000.0)

    @property
    def gain(self) -> float:
        """Analog gain (dB on SFNC cameras, raw steps on older firmware)."""
        return float(self._get_first_feature(self._GAIN_NODES))

    @gain.setter
    def gain(self, value: float) -> None:
        self._set_first_feature(self._GAIN_NODES, value)

    @property
    def pixel_format(self) -> str:
        return str(self._require_node_map().PixelFormat.value)

    @pixel_format.setter
    def pixel_format(self, value: str) -> None:
        self._set_enum("PixelFormat", value)

    def get_feature(self, name: str) -> Any:
        """Read any GenICam feature by name (escape hatch for power users)."""
        node_map = self._require_node_map()
        try:
            return getattr(node_map, name).value
        except AttributeError as exc:
            raise CameraError(f"Camera has no feature named '{name}'") from exc

    def set_feature(self, name: str, value: Any) -> None:
        """Write any GenICam feature by name (e.g. ``GevSCPSPacketSize``)."""
        node_map = self._require_node_map()
        try:
            getattr(node_map, name).value = value
        except AttributeError as exc:
            raise CameraError(f"Camera has no feature named '{name}'") from exc

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the acquisition engine (called automatically by capture)."""
        acquirer = self._require_acquirer()
        if not self._acquiring:
            self._call_first(acquirer, ("start", "start_acquisition"))
            self._acquiring = True

    def stop(self) -> None:
        """Stop the acquisition engine."""
        acquirer = self._require_acquirer()
        if self._acquiring:
            self._call_first(acquirer, ("stop", "stop_acquisition"))
            self._acquiring = False

    def trigger(self) -> None:
        """Fire one software trigger (TriggerSoftware GenICam command)."""
        node_map = self._require_node_map()
        try:
            node_map.TriggerSoftware.execute()
        except AttributeError as exc:
            raise CameraError(
                "Camera does not expose the TriggerSoftware command; call "
                "configure_software_trigger() first."
            ) from exc

    def capture(self, *, trigger: bool = True) -> np.ndarray:
        """Software-trigger the camera and return the frame as a numpy array.

        The returned image is BGR (OpenCV convention) for colour pixel
        formats and single-channel for Mono formats, so it can be passed
        straight to ``cv2.imwrite``/``cv2.imshow``.

        Set ``trigger=False`` to only fetch the next frame (e.g. when the
        camera is in free-run mode).
        """
        with self._lock:
            acquirer = self._require_acquirer()
            if not self._acquiring:
                self.start()
            if trigger:
                self.trigger()
            try:
                buffer = self._call_first(
                    acquirer, ("fetch", "fetch_buffer"), timeout=self._fetch_timeout
                )
            except TimeoutException as exc:
                raise CaptureTimeoutError(
                    f"No frame received within {self._fetch_timeout:.1f}s. "
                    "If frames are dropped on GigE, enable jumbo frames "
                    "(MTU 9000) or lower GevSCPSPacketSize."
                ) from exc

            with buffer:
                component = buffer.payload.components[0]
                image = _convert_to_bgr(
                    np.asarray(component.data),
                    int(component.width),
                    int(component.height),
                    str(component.data_format),
                )
                # The buffer memory is requeued to the driver when the
                # 'with' block exits, so hand back an independent copy.
                return image.copy()

    def save_image(
        self,
        path: Optional[PathLike] = None,
        *,
        image: Optional[np.ndarray] = None,
        trigger: bool = True,
    ) -> Path:
        """Software-trigger the camera and write the frame to disk.

        Parameters
        ----------
        path:
            Target file (extension picks the format: .png/.jpg/.tiff/.bmp).
            If ``path`` is a directory or ``None``, a timestamped name like
            ``captures/XCG-CG240C_20260610-153012_345678.png`` is generated.
        image:
            Save this pre-captured array instead of triggering a new frame.
        trigger:
            Forwarded to :meth:`capture` when a new frame is acquired.

        Returns the path of the written file.
        """
        if image is None:
            image = self.capture(trigger=trigger)

        target = Path(path) if path is not None else Path("captures")
        if path is None or target.suffix == "":
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S_%f")
            target = target / f"{self.MODEL_NAME}_{timestamp}.png"
        target.parent.mkdir(parents=True, exist_ok=True)

        if not cv2.imwrite(str(target), image):
            raise CameraError(f"OpenCV could not write the image to '{target}'")
        _LOGGER.info("Saved %sx%s image to %s", image.shape[1], image.shape[0], target)
        return target

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _require_acquirer(self) -> Any:
        if self._acquirer is None:
            raise CameraNotConnectedError(
                "Camera is not connected. Call connect() or use the class "
                "as a context manager."
            )
        return self._acquirer

    def _require_node_map(self) -> Any:
        return self._require_acquirer().remote_device.node_map

    @staticmethod
    def _call_first(obj: Any, method_names: Sequence[str], **kwargs: Any) -> Any:
        """Call the first method that exists on obj (harvesters API changed names)."""
        for name in method_names:
            method = getattr(obj, name, None)
            if callable(method):
                return method(**kwargs)
        raise AttributeError(
            f"{obj!r} has none of the expected methods {method_names}"
        )

    def _set_enum(self, node_name: str, value: str) -> None:
        node_map = self._require_node_map()
        try:
            getattr(node_map, node_name).value = value
        except Exception as exc:  # noqa: BLE001
            raise CameraError(
                f"Could not set {node_name} = '{value}': {exc}"
            ) from exc

    def _set_enum_if_available(self, node_name: str, value: str) -> None:
        try:
            self._set_enum(node_name, value)
        except CameraError:
            _LOGGER.debug("Feature %s not available; skipping", node_name)

    def _get_first_feature(self, node_names: Sequence[str]) -> Any:
        node_map = self._require_node_map()
        for name in node_names:
            node = getattr(node_map, name, None)
            if node is not None:
                return node.value
        raise CameraError(f"Camera exposes none of the features {node_names}")

    def _set_first_feature(self, node_names: Sequence[str], value: Any) -> None:
        node_map = self._require_node_map()
        for name in node_names:
            node = getattr(node_map, name, None)
            if node is not None:
                node.value = value
                return
        raise CameraError(f"Camera exposes none of the features {node_names}")
