# Sony XCG-CG240C Camera Module

Python module for capturing and saving images from the **Sony XCG-CG240C**
industrial camera using a **software trigger**: every call to
`capture()` / `save_image()` fires one exposure and returns/saves exactly one
frame — ideal for machine-vision inspection stations.

## The camera

| Property | Value |
|---|---|
| Model | Sony XCG-CG240C (colour) |
| Sensor | 1/1.2-type global-shutter CMOS, 2.35 MP |
| Resolution | 1920 × 1200 (up to ~41 fps free-run) |
| Interface | Gigabit Ethernet — **GigE Vision / GenICam** compliant |
| Power | PoE (IEEE 802.3af, 37–57 V) **or** 12 V DC (3.6 W) via the I/O connector |
| Lens mount | C-mount |

Because the camera is GigE Vision / GenICam compliant, no Sony-specific SDK
is needed: this module uses the standard GenICam stack.

## Architecture

```
your code ──► camera_module.SonyXCG240Camera
                 │  (GenICam features: TriggerSource=Software, TriggerSoftware, ...)
                 ▼
              harvesters (Python GenICam consumer)
                 ▼
              GenTL producer  (*.cti shared library — vendor neutral)
                 ▼
              GigE Vision ──► XCG-CG240C
```

## Installation

### 1. Python packages

```bash
pip install -r camera_module/requirements.txt
```

### 2. A GenTL producer (`*.cti`)

The producer is the driver layer that speaks GigE Vision. Install **one** of:

| Producer | Notes |
|---|---|
| [STEMMER CVB CameraSuite](https://www.stemmer-imaging.com/en/products/software/cvb-camerasuite/) | **Free, no expiry, vendor-neutral.** Installs `GEVTL.cti`. Recommended. |
| [Baumer GAPI SDK](https://www.baumer.com/us/en/service-support/download-center/) | **Free**, vendor-neutral, installs `bgapi2_gige.cti` |
| [Pleora eBUS SDK ≤ v5](https://www.pleora.com/products/ebus-sdk/) | `ebTLProducer.cti` — v5 was free; **v6+ requires a paid licence** |
| [Balluff / MATRIX VISION ImpactAcquire](https://www.balluff.com/en-de/digital-solutions-and-services/machine-vision-software) | `mvGenTLProducer.cti` — **only free with Balluff cameras**. With third-party cameras (like the XCG) it runs as a time-limited evaluation, then watermarks every frame |

The installer normally sets the `GENICAM_GENTL64_PATH` environment variable;
the module auto-discovers the `.cti` from there, or you can pass the path
explicitly via `cti_file=`.

### 3. Camera connection (hardware)

* **Power**: plug the camera into a PoE (802.3af) switch/injector, **or**
  feed 12 V DC through the circular I/O connector.
* **Network**: put the NIC on the same subnet as the camera (the camera
  defaults to DHCP, falling back to link-local 169.254.x.x).
* **Performance**: enable jumbo frames (MTU 9000) on the NIC and set the
  receive buffer high; otherwise frames may be dropped.

## Usage

### Quick start — software trigger + save

```python
from camera_module import SonyXCG240Camera

with SonyXCG240Camera() as cam:                  # .cti auto-discovered
    path = cam.save_image("captures/")           # trigger → capture → save
    print(f"image written to {path}")
```

`connect()` (called by the context manager) automatically programs the
GenICam software-trigger sequence:

```
AcquisitionMode = Continuous
TriggerSelector = FrameStart
TriggerMode     = On
TriggerSource   = Software
```

and each `capture()`/`save_image()` executes the `TriggerSoftware` command,
so the camera exposes exactly one frame per call.

### Full control

```python
from camera_module import SonyXCG240Camera, list_devices

print(list_devices())                            # discover cameras / serials

cam = SonyXCG240Camera(
    cti_file="/opt/mvIMPACT_Acquire/lib/x86_64/mvGenTLProducer.cti",
    serial_number="3200130",                     # printed on the label
    fetch_timeout=5.0,
)
cam.connect()

cam.pixel_format = "BayerRG8"                    # colour, demosaiced on the PC
cam.exposure_time = 20000                        # µs
cam.gain = 6.0                                   # dB

frame = cam.capture()                            # numpy BGR array (OpenCV order)
cam.save_image("captures/part_001.png", image=frame)

cam.set_feature("GevSCPSPacketSize", 8164)       # any GenICam feature by name

cam.disconnect()
```

### Command line

```bash
python camera_module/examples/capture_example.py --list           # find cameras
python camera_module/examples/capture_example.py                  # 1 shot → ./captures
python camera_module/examples/capture_example.py \
    --count 10 --interval 0.5 --exposure 20000 --output shots/
```

## Building a standalone .exe (no Python required to run)

From the repository root, on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File camera_module\build_exe.ps1
```

This produces:

```
dist\
├── camera_capture.exe   ← double-click or run from a terminal
└── config.yaml          ← edit settings any time; read on every start
```

The exe looks for `config.yaml` **in its own folder**, so you can move the
two files together anywhere (USB stick, another PC — the GenTL producer
must still be installed on that PC). All CLI flags keep working, e.g.
`camera_capture.exe --list`.

## API summary

| Member | Description |
|---|---|
| `SonyXCG240Camera(cti_file, serial_number, fetch_timeout, auto_configure)` | Driver class; context-manager aware |
| `connect()` / `disconnect()` | Open/close the camera (auto-configures software trigger) |
| `configure_software_trigger()` / `configure_free_run()` | Switch trigger modes |
| `trigger()` | Fire one `TriggerSoftware` command |
| `capture(trigger=True)` | Trigger + fetch one frame as a numpy array (BGR / mono) |
| `save_image(path=None, image=None, trigger=True)` | Trigger + write PNG/JPG/TIFF; timestamped name when `path` is a directory/None |
| `exposure_time`, `gain`, `pixel_format` | Read/write camera settings |
| `get_feature(name)` / `set_feature(name, value)` | Raw access to any GenICam feature |
| `list_devices(cti_file=None)` | Enumerate reachable cameras |
| `find_cti_file()` | Locate an installed GenTL producer |

Errors: `CameraError` (base), `CameraNotConnectedError`, `CaptureTimeoutError`.

## Pixel formats

`Mono8/10/12`, `BayerRG/GR/GB/BG 8/10/12` (demosaiced to BGR with OpenCV)
and `RGB8`/`BGR8` are supported. 10/12-bit data is scaled to the full
16-bit range before saving. Note the deliberate GenICam→OpenCV Bayer name
swap in the code (OpenCV names patterns from the second pixel row).

## Running the tests

The unit tests fake the GenICam layer, so **no camera or GenTL producer is
needed** (only `numpy`, `opencv-python`, `pytest`):

```bash
pip install pytest
pytest camera_module/tests -v
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No GenTL producer (*.cti) found` | Install a producer (see above) or pass `cti_file=` |
| `No GigE Vision camera found` | Check PoE power/link LED; same subnet; disable firewall on the camera NIC; some producers need admin rights for "IP force" |
| `CaptureTimeoutError` | Increase `fetch_timeout`; enable jumbo frames (MTU 9000); lower `GevSCPSPacketSize`; ensure `TriggerMode=On` wasn't reset by another tool |
| Balluff banner in every image: *"unsupported third party device … free evaluation period has ended"* | Balluff's producer is only free with Balluff cameras. Install a vendor-neutral producer (CVB CameraSuite, rc_genicam_api, or eBUS — see table above) and point `cti_file` in config.yaml at the new `.cti` |
| Image looks green/checkered | Wrong Bayer order — set `cam.pixel_format = "BayerRG8"` |
| Colours swapped (red↔blue) | You're displaying the BGR array as RGB — use `cv2.cvtColor(img, cv2.COLOR_BGR2RGB)` |
