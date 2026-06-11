#!/usr/bin/env python3
"""Continuously capture software-triggered images from the Sony XCG-CG240C.

Reads settings from camera_module/config.yaml by default.
Any CLI argument overrides the corresponding config value.
Press Ctrl+C to stop.

Examples:

    # Use config.yaml defaults
    python camera_module/examples/capture_example.py

    # Override delay and output folder
    python camera_module/examples/capture_example.py --delay 1.0 --output D:/shots

    # Use a different config file
    python camera_module/examples/capture_example.py --config my_config.yaml

    # List detected cameras
    python camera_module/examples/capture_example.py --list
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from camera_module import CameraError, CaptureTimeoutError, SonyXCG240Camera, find_cti_file, list_devices
from camera_module.config_loader import Config

MAX_CONSECUTIVE_TIMEOUTS = 3
_LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous software-triggered capture for the Sony XCG-CG240C",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default=None, help="Path to a YAML config file.")
    parser.add_argument("--list", action="store_true", help="List cameras and exit.")

    # Camera overrides
    parser.add_argument("--serial", default=None, help="Camera serial number.")
    parser.add_argument("--ip", default=None, help="Camera IP address.")
    parser.add_argument("--cti", default=None, help="Path to the GenTL producer (*.cti).")
    parser.add_argument("--packet-size", type=int, default=None, dest="packet_size", help="GigE packet size (1500=safe, 8164=jumbo).")

    # Capture overrides
    parser.add_argument("--delay", type=float, default=None, help="Seconds between captures.")
    parser.add_argument("--output", default=None, help="Output directory (created if missing).")
    parser.add_argument("--integration-time", type=float, default=None, dest="integration_time", help="Integration (exposure) time in ms (e.g. 20 = 20 ms).")
    parser.add_argument("--gain", type=float, default=None, help="Gain (dB).")
    parser.add_argument("--pixel-format", default=None, help="e.g. BayerBG8, BayerBG10Packed.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    cfg = Config.load(args.config)
    if cfg.source:
        print(f"Loaded config: {cfg.source}")
    else:
        from camera_module.config_loader import default_config_path
        print(
            f"WARNING: no config.yaml found at {default_config_path()} — "
            "using built-in defaults.",
            file=sys.stderr,
        )

    serial      = args.serial or cfg.camera.serial_number
    ip          = args.ip     or cfg.camera.ip
    cti         = args.cti    or cfg.camera.cti_file
    packet_size = args.packet_size if args.packet_size is not None else cfg.camera.packet_size
    delay       = args.delay    if args.delay    is not None else cfg.capture.delay
    output      = args.output   or cfg.capture.output_dir
    integration_time = args.integration_time if args.integration_time is not None else cfg.capture.integration_time
    gain        = args.gain     if args.gain     is not None else cfg.capture.gain
    pixel_fmt   = args.pixel_format or cfg.capture.pixel_format

    search_key = serial or ip

    # Ensure output directory exists
    Path(output).mkdir(parents=True, exist_ok=True)

    if args.list:
        producer = cti or find_cti_file()
        if not producer:
            print("No GenTL producer (*.cti) found — install one, see README.md")
            return 1
        print(f"Using GenTL producer: {producer}")
        devices = list_devices(producer)
        if not devices:
            print("No GigE Vision cameras found.")
            return 1
        for index, device in enumerate(devices):
            print(f"[{index}] " + ", ".join(f"{k}={v}" for k, v in device.items() if v))
        return 0

    index = 0
    try:
        with SonyXCG240Camera(
            cti_file=cti, serial_number=search_key, auto_configure=False,
        ) as camera:
            # Set pixel format BEFORE trigger config (some cameras lock it after)
            if pixel_fmt:
                try:
                    camera.pixel_format = pixel_fmt
                except CameraError:
                    avail = camera.available_pixel_formats
                    print(
                        f"WARNING: Could not set pixel_format='{pixel_fmt}'. "
                        f"Available formats: {avail}. Using current: "
                        f"'{camera.pixel_format}'",
                        file=sys.stderr,
                    )

            # Set packet size BEFORE starting acquisition
            if packet_size is not None:
                try:
                    camera.set_feature("GevSCPSPacketSize", packet_size)
                    _LOGGER.info("Packet size set to %d bytes", packet_size)
                except CameraError:
                    _LOGGER.warning("Could not set GevSCPSPacketSize=%d", packet_size)

            camera.configure_software_trigger()
            if integration_time is not None:
                camera.integration_time = integration_time
            if gain is not None:
                camera.gain = gain

            print(f"Connected: {camera.device_info}")
            print(f"Pixel format: {camera.pixel_format}")
            print(f"Saving images to: {Path(output).resolve()}")
            print("Press Ctrl+C to stop.\n")

            consecutive_timeouts = 0
            while True:
                try:
                    index += 1
                    saved = camera.save_image(output)
                    print(f"[{index}] saved {saved}")
                    consecutive_timeouts = 0
                except CaptureTimeoutError:
                    consecutive_timeouts += 1
                    print(
                        f"[{index}] WARNING: frame timeout "
                        f"({consecutive_timeouts}/{MAX_CONSECUTIVE_TIMEOUTS})",
                        file=sys.stderr,
                    )
                    if consecutive_timeouts >= MAX_CONSECUTIVE_TIMEOUTS:
                        print(
                            "ERROR: Too many consecutive timeouts. "
                            "Enable jumbo frames (MTU 9000) on your NIC, "
                            "or lower packet_size in config.yaml.",
                            file=sys.stderr,
                        )
                        return 1
                if delay:
                    time.sleep(delay)

    except KeyboardInterrupt:
        print(f"\nStopped after {index} image(s).")
    except (CameraError, FileNotFoundError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
