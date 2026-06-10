#!/usr/bin/env python3
"""Command-line tool: capture software-triggered images from the XCG-CG240C.

Configuration is loaded from camera_module/config.yaml by default.
Any CLI argument overrides the corresponding config file value.

Examples:

    # Use config.yaml defaults
    python camera_module/examples/capture_example.py

    # Override specific values
    python camera_module/examples/capture_example.py --count 10 --delay 0.5

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

from camera_module import CameraError, SonyXCG240Camera, find_cti_file, list_devices
from camera_module.config_loader import Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Software-triggered capture for the Sony XCG-CG240C",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a YAML config file (default: camera_module/config.yaml).",
    )
    parser.add_argument("--list", action="store_true", help="List cameras and exit.")

    # Camera overrides
    parser.add_argument("--serial", default=None, help="Camera serial number.")
    parser.add_argument("--ip", default=None, help="Camera IP address.")
    parser.add_argument("--cti", default=None, help="Path to the GenTL producer (*.cti).")
    parser.add_argument("--timeout", type=float, default=None, help="Fetch timeout (seconds).")

    # Capture overrides
    parser.add_argument("--count", type=int, default=None, help="Number of images.")
    parser.add_argument("--delay", type=float, default=None, help="Seconds between captures.")
    parser.add_argument("--output", default=None, help="Output directory.")
    parser.add_argument("--exposure", type=float, default=None, help="Exposure time (µs).")
    parser.add_argument("--gain", type=float, default=None, help="Gain (dB).")
    parser.add_argument("--pixel-format", default=None, help="e.g. BayerRG8, Mono8.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # Load config file, then let CLI args override
    cfg = Config.load(args.config)

    serial      = args.serial   or cfg.camera.serial_number
    ip          = args.ip       or cfg.camera.ip
    cti         = args.cti      or cfg.camera.cti_file
    timeout     = args.timeout  if args.timeout  is not None else cfg.camera.fetch_timeout
    count       = args.count    if args.count    is not None else cfg.capture.count
    delay       = args.delay    if args.delay    is not None else cfg.capture.delay
    output      = args.output   or cfg.capture.output_dir
    exposure    = args.exposure if args.exposure is not None else cfg.capture.exposure_time
    gain        = args.gain     if args.gain     is not None else cfg.capture.gain
    pixel_fmt   = args.pixel_format or cfg.capture.pixel_format

    # Serial takes priority; fall back to IP as the search key
    search_key = serial or ip

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

    try:
        with SonyXCG240Camera(
            cti_file=cti,
            serial_number=search_key,
            fetch_timeout=timeout,
        ) as camera:
            if pixel_fmt:
                camera.pixel_format = pixel_fmt
            if exposure is not None:
                camera.exposure_time = exposure
            if gain is not None:
                camera.gain = gain

            print(f"Connected: {camera.device_info}")
            for index in range(count):
                saved = camera.save_image(output)
                print(f"[{index + 1}/{count}] saved {saved}")
                if delay and index + 1 < count:
                    time.sleep(delay)
    except (CameraError, FileNotFoundError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
