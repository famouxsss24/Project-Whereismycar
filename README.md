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

Multiple cameras:

```bash
python main.py --webcam --preview --camera 0 --camera 1 --detector yolo --pretty
```

Or with a comma-separated list:

```bash
python main.py --webcam --preview --cameras 0,1 --detector yolo --pretty
```

Continuous loop:

```bash
python main.py --webcam --loop --interval 1.0 --detector yolo
```

Settings can use either the existing single-camera form:

```json
{
  "camera": 0
}
```

Or multiple cameras:

```json
{
  "cameras": [0, 1]
}
```

## Live Scan Area Selection

In preview mode, OCR runs only inside the active scan rectangles shown on the camera frame.

- Drag with the mouse in a preview window to select a scan area.
- The first drag replaces the configured/default areas for that camera.
- Additional drags add more scan areas for that camera.
- Scan areas are saved automatically to `camera_section_boxes` in `settings.json`.
- Press `c` to clear scan areas.
- Press `r` to restore the configured/default areas.
- Press `q` or `Esc` to exit.

Saved multi-camera scan areas look like this:

```json
{
  "camera_section_boxes": {
    "0": [{"x": 20, "y": 120, "width": 180, "height": 180}],
    "1": [{"x": 30, "y": 100, "width": 220, "height": 160}]
  }
}
```

## Optional HTTP Output

Send JSON payload to a server:

```bash
python main.py test1.jpg --server-url http://localhost:8000/plates --timeout 10
```

## Firebase Integration (Filtered Updates)

Only valid YOLO plate detections are sent to server/Firebase.  
Duplicate plate updates are suppressed for `plate_cooldown` seconds (default `30`).

Set these in `settings.json`:

- `firebase_service_account`: path to service account JSON file
- `firebase_database_url`: optional, auto-inferred from `project_id` if null
- `firebase_root_path`: DB root path (default `parking_lot`)
- `plate_cooldown`: duplicate suppression time in seconds
- `local_image_dir`: local folder for cropped plate images
- `serve_local_images`: run built-in static file server for image URLs
- `local_image_server_host`: static server host
- `local_image_server_port`: static server port
- `local_image_base_url`: optional override if you already host that folder elsewhere
- `azure_storage_connection_string`: Azure Storage connection string for Blob uploads
- `azure_blob_container`: Blob container name for plate JPG uploads
- `azure_blob_prefix`: optional blob path prefix (default `plate_images`)
- `azure_blob_sas_ttl_minutes`: optional read-only SAS URL TTL in minutes (0 = plain blob URL)
- `azure_secrets_path`: optional path to Azure secrets JSON file (recommended)

Example:

```bash
python main.py --webcam --preview --detector yolo \
  --firebase-service-account secrets/firebase-service-account.json \
  --serve-local-images \
  --local-image-server-port 8787 \
  --plate-cooldown 30
```

## Azure Blob Storage for Plate JPGs

When both `azure_storage_connection_string` and `azure_blob_container` are resolved, cropped plate JPG files are uploaded to Azure Blob Storage and published as `image_url`.

Recommended secret file (`secrets/azure-blob.json`):

```json
{
  "azure_storage_connection_string": "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net",
  "azure_blob_container": "plate-images",
  "azure_blob_prefix": "parking_lot",
  "azure_blob_sas_ttl_minutes": 60
}
```

Example:

```bash
python main.py --webcam --preview --detector yolo \
  --firebase-service-account secrets/firebase-service-account.json \
  --azure-secrets-path secrets/azure-blob.json
```

Notes:

- If `azure_blob_sas_ttl_minutes` is `0`, the app stores and returns the plain blob URL.
- If `azure_blob_sas_ttl_minutes` is `> 0`, the app appends a read-only SAS token to `image_url`.
- If Azure settings are not provided, the app uses existing local image hosting behavior.

Check current DB data:

```bash
python check_db.py --service-account secrets/firebase-service-account.json --pretty
```

Read one plate key:

```bash
python check_db.py --service-account secrets/firebase-service-account.json --plate 123가4568 --pretty
```

Refresh all Azure Blob SAS URLs in Firebase (dry run):

```bash
python refresh_firebase_blob_sas.py \
  --service-account secrets/firebase-service-account.json \
  --database-url https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app \
  --azure-secrets-path secrets/azure-blob.json \
  --ttl-hours 168 \
  --dry-run
```

Apply updates:

```bash
python refresh_firebase_blob_sas.py \
  --service-account secrets/firebase-service-account.json \
  --database-url https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app \
  --azure-secrets-path secrets/azure-blob.json \
  --ttl-hours 168
```

## Public Image URL via Cloudflare Quick Tunnel

1. Install cloudflared (Windows):

```bash
winget install --id Cloudflare.cloudflared
```

2. Start your app (local image server on `127.0.0.1:8787`):

```bash
python main.py
```

3. In another terminal, expose the local image server:

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

Cloudflared prints a public URL like `https://xxxx-xxxx.trycloudflare.com`.

4. Set the URL for this shell session and restart app:

```bash
$env:LOCAL_IMAGE_BASE_URL="https://xxxx-xxxx.trycloudflare.com"
python main.py
```

Firebase `image_url` values will then use the public tunnel URL.

## Notes

- `--yolo-only` disables heuristic fallback when YOLO misses.
- `--layout columns|rows` controls section split direction.
- `--section-box x,y,w,h` overrides automatic section splitting.
- Press `q` or `Esc` to exit preview mode.
