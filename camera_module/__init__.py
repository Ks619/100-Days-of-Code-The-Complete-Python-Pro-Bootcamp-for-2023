"""Camera module for the Sony XCG-CG240C GigE Vision industrial camera.

Provides software-triggered image capture and saving through the standard
GenICam stack (harvesters + any GenTL producer).
"""

from camera_module.sony_xcg_camera import (
    CameraError,
    CameraNotConnectedError,
    CaptureTimeoutError,
    SonyXCG240Camera,
    find_cti_file,
    list_devices,
)

__all__ = [
    "SonyXCG240Camera",
    "CameraError",
    "CameraNotConnectedError",
    "CaptureTimeoutError",
    "find_cti_file",
    "list_devices",
]

__version__ = "1.0.0"
