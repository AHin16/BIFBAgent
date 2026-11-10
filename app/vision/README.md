# Built-in vision backend

These modules are vendored from the local YOLOTracker project on 2026-11-10.
Inference, custom BiFPN weight compatibility, image I/O and offline flow-warning algorithms are preserved.
Imports use this package, Ultralytics configuration writes to `data/ultralytics`, and the predictor's standalone example is omitted. No YOLOTracker source directory is read at runtime.
Model weights are selected separately in the application settings.

The SHA-256 values below identify the original source files before these integration changes.

| Built-in file | Original YOLOTracker file | Original SHA-256 |
| --- | --- | --- |
| `predictor.py` | `detector_head/yolo11/predictor_yolo11.py` | `7c47d6ea6e8a838fb9dec56cf4863add55b0371827e0e36095c97ffd8d0e253e` |
| `image_io.py` | `bubble_analyzer/image_io.py` | `f5ceb2361044d76478ea5cabfcaec379b9c708b7a5d84fb1913ace54e31e9795` |
| `gas_holdup.py` | `bubble_analyzer/gas_holdup.py` | `5ed0e98f12d7a79467e48c18531788958892dc3e5308396ba0d333bbc2f31c19` |
| `inference.py` | `bubble_analyzer/inference.py` | `979e31b92bb884627f6139ebd67fb7bb877363591628a53014f7c2b946788a74` |
| `flow_warning/__init__.py` | `flow_warning/__init__.py` | `bb54927901d1256f8368643b43bc2477a24ddcb0ff90549c975766af6f603bc3` |
| `flow_warning/workflow.py` | `flow_warning/workflow.py` | `c1add86adb39cdce3baeb15a0887611aaf27e1eb060794654d2fc479f7822324` |
| `flow_warning/measurements.py` | `flow_warning/measurements.py` | `3aee8c095967ee8c34ce9cbc996fdb71c5d294f92c801ce78f0aed4202a40816` |
| `flow_warning/rules.py` | `flow_warning/rules.py` | `6c6010022897cfc9c49734a98286d12307b0b497d1fdd205b6233fe6f00db674` |
