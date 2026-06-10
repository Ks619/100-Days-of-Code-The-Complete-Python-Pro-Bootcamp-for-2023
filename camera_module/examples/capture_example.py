#!/usr/bin/env python3
"""Command-line tool: capture software-triggered images from the XCG-CG240C.

Examples (run from the repository root):

    # List the cameras the GenTL producer can see
    python camera_module/examples/capture_example.py --list

    # Grab one software-triggered image into ./captures/
    python camera_module/examples/capture_example.py

    # 10 images, one every 0.5 s, 20 ms exposure, into ./shots/
    python camera_module/examples/capture_example.py \
        --count 10 --interval 0.5 --exposure 20000 --output shots

    # Pick a specific camera and producer
    python camera_module/examples/capture_example.py \
        --cti /opt/mvIMPACT_Acquire/lib/x86_64/mvGenTLProducer.cti \
        --serial 3200130
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running the script directly from a repo checkout without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from camera_module import (  # noqa: E402
    CameraError,
    SonyXCG240Camera,
    find_cti_file,
    list_devices,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Software-triggered capture for the Sony XCG-CG240C",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--cti",
        default=None,
        help="Path to the GenTL producer (*.cti). Auto-detected from "
        "GENICAM_GENTL64_PATH when omitted.",
    )
    parser.add_argument(
        "--serial",
        default=None,
        help="Serial number of the camera to open (needed only with "
        "several cameras connected).",
    )
    parser.add_argument("--list", action="store_true", help="List cameras and exit.")
    parser.add_argument("--count", type=int, default=1, help="Number of images.")
    parser.add_argument(
        "--interval", type=float, default=0.0, help="Seconds between triggers."
    )
    parser.add_argument(
        "--output", default="captures", help="Output directory (or file for --count 1)."
    )
    parser.add_argument(
        "--exposure", type=float, default=None, help="Exposure time in microseconds."
    )
    parser.add_argument("--gain", type=float, default=None, help="Gain (dB).")
    parser.add_argument(
        "--pixel-format",
        default=None,
        help="GenICam pixel format, e.g. BayerRG8, RGB8, Mono8.",
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Frame fetch timeout in seconds."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.list:
        cti = args.cti or find_cti_file()
        if not cti:
            print("No GenTL producer (*.cti) found - install one, see README.md")
            return 1
        print(f"Using GenTL producer: {cti}")
        devices = list_devices(cti)
        if not devices:
            print("No GigE Vision cameras found.")
            return 1
        for index, device in enumerate(devices):
            print(f"[{index}] " + ", ".join(f"{k}={v}" for k, v in device.items() if v))
        return 0

    try:
        with SonyXCG240Camera(
            cti_file=args.cti,
            serial_number=args.serial,
            fetch_timeout=args.timeout,
        ) as camera:
            if args.pixel_format:
                camera.pixel_format = args.pixel_format
            if args.exposure is not None:
                camera.exposure_time = args.exposure
            if args.gain is not None:
                camera.gain = args.gain

            print(f"Connected: {camera.device_info}")
            for index in range(args.count):
                saved = camera.save_image(args.output)
                print(f"[{index + 1}/{args.count}] saved {saved}")
                if args.interval and index + 1 < args.count:
                    time.sleep(args.interval)
    except (CameraError, FileNotFoundError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
