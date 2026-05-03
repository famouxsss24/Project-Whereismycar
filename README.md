# Project WhereIsMyCar Vision

Parking-lot license plate detection and OCR pipeline for Korean plates.

## Environment

- Python 3.12 recommended
- Windows, Linux, or macOS
- Webcam required for live mode (`--webcam`)

## Settings File

All runtime options can be set in [`settings.json`](C:/Users/Sangjee/PycharmProjects/MobileRobotTemi/settings.json).
The app reads this file automatically by default.

Use a different file:

```bash
python main.py --settings my_settings.json
```

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Model

Place YOLO plate detector weights under `models/`, for example:

- `models/license-plate-finetune-v1m.pt`

When `--detector yolo` is selected, the app auto-detects supported model names in `models/`.

## Run (Image)

```bash
python main.py test1.jpg --detector heuristic --pretty
```

Run using only settings file values:

```bash
python main.py --settings settings.json
```

YOLO mode:

```bash
python main.py test1.jpg --detector yolo --yolo-model models/license-plate-finetune-v1m.pt --pretty
```

Custom recognition boxes (quantity/size/location):

```bash
python main.py test1.jpg --detector yolo \
  --section-box 40,120,280,180 \
  --section-box 360,120,280,180 \
  --section-box 680,120,280,180 \
  --pretty
```

Each `--section-box` is `x,y,width,height` in pixels.  
The number of `--section-box` options defines section quantity.

## Run (Webcam)

Single capture:

```bash
python main.py --webcam --camera 0 --detector yolo --preview --pretty
```

Continuous loop:

```bash
python main.py --webcam --loop --interval 1.0 --detector yolo
```

## Optional HTTP Output

Send JSON payload to a server:

```bash
python main.py test1.jpg --server-url http://localhost:8000/plates --timeout 10
```

## Notes

- `--yolo-only` disables heuristic fallback when YOLO misses.
- `--layout columns|rows` controls section split direction.
- `--section-box x,y,w,h` overrides automatic section splitting.
- Press `q` or `Esc` to exit preview mode.
