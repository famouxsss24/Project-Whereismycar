# User-Facing Feature Implementation Overview

This document explains how each visible program feature is implemented from the user's point of view.

## Main Workflow

| User-facing feature | How it is implemented |
| --- | --- |
| Start the program | The user runs `python main.py` with either an image path or webcam options. The program loads settings, validates options, builds the detection/OCR pipeline, then chooses the correct run mode. |
| Use settings file | Runtime options are stored in `settings.json`. At startup, the program reads this file and uses those values as defaults unless the user overrides them with command-line options. |
| Process a still image | The program loads the image from disk, divides it into parking sections, detects possible plates in each section, reads plate text with OCR, and prints/publishes the result. |
| Process live camera input once | The program opens the selected camera, captures one frame, runs the same detection/OCR process, publishes the result, and releases the camera. |
| Run continuously | In loop mode, cameras stay open and the program repeats frame capture, detection, OCR, publishing, and waiting for the configured interval. |
| Preview live results | In preview mode, the user sees OpenCV windows with camera frames, parking section boxes, plate boxes, status text, and crop-debug panels. |

## Camera Features

| User-facing feature | How it is implemented |
| --- | --- |
| Select one camera | The user provides one camera index, for example `--camera 0`. The program opens that index through OpenCV and configures resolution and buffer size. |
| Select multiple cameras | The user repeats `--camera` or uses `--cameras 0,1`. The program opens each camera and processes each stream separately. |
| Configure camera resolution | The settings file can define per-camera width and height. If no resolution is configured, the program tries preferred high resolutions and keeps the best one OpenCV accepts. |
| Use camera-specific scan areas | Each camera can have its own saved parking section boxes in `camera_section_boxes`, so different camera angles can use different recognition areas. |

## Parking Area Features

| User-facing feature | How it is implemented |
| --- | --- |
| Automatic parking sections | If no custom boxes are provided, the program divides the image into equal columns or rows based on the configured section count and layout. |
| Custom recognition areas | The user can provide `--section-box x,y,width,height` values or save boxes in settings. These boxes replace automatic section splitting. |
| Named parking zones | Sections are named with lowercase labels such as `a`, `b`, `c`. These names are included in output as the parking zone and section name. |
| Avoid duplicate section names | When multiple cameras or saved boxes reuse the same names, the program renames later duplicates so published zones remain unique. |
| Save scan areas from preview | In preview mode, user-drawn boxes are saved back to `settings.json`, so the same areas are restored next time. |

## Plate Detection Features

| User-facing feature | How it is implemented |
| --- | --- |
| Choose detector type | The user selects `heuristic` or `yolo`. The program creates the matching detector before processing frames. |
| Heuristic plate detection | The program uses image-processing steps such as contrast operations, gradients, thresholding, and contour filtering to find plate-shaped regions. |
| YOLO plate detection | The program loads a trained YOLO model, runs object detection, ranks detected boxes by confidence, and extracts plate crops from the frame. |
| YOLO with fallback | If YOLO is selected and fallback is allowed, missed sections can still be checked by the heuristic detector. |
| Correct rotated plate crops | After detection, the program attempts to straighten plate crops so OCR receives a cleaner, more readable image. |
| Improve OCR input quality | Plate crops are enhanced with grayscale conversion, contrast improvement, upscaling, and padding before OCR is retried. |

## OCR Features

| User-facing feature | How it is implemented |
| --- | --- |
| Read Korean license plates | The OCR engine extracts text fragments from plate crops, then the program combines and filters those fragments into likely Korean plate strings. |
| Reject invalid plate text | OCR output is checked against the expected Korean plate pattern before being treated as a valid plate. |
| Pick the best OCR result | The program compares OCR from the original crop and enhanced crop, then keeps the valid result with better confidence. |
| Reduce repeated OCR work | OCR results are cached by image content so repeated identical crops do not need to be read again. |

## Output Features

| User-facing feature | How it is implemented |
| --- | --- |
| Print JSON result | The processed frame is converted into a JSON payload containing source, timestamp, detector, sections, occupancy, plate text, confidence, and boxes. |
| Show occupied/empty sections | Each section result records whether a plate candidate was detected and whether a valid plate was read. |
| Include plate image crops | When publishing plate updates, the program keeps section crops and rectified plate crops in memory for preview and image upload. |
| Suppress duplicate updates | The same plate is not repeatedly published until the configured cooldown period has passed. |

## Publishing Features

| User-facing feature | How it is implemented |
| --- | --- |
| Send results to an HTTP server | If a server URL is configured, valid plate updates are posted as JSON. |
| Save plate images locally | If local image publishing is enabled, cropped plate images are written to a local folder and exposed through a small built-in static server. |
| Upload plate images to Azure | If Azure Blob Storage is configured, plate images are encoded as JPEG, uploaded to the configured container, and returned as blob URLs. |
| Use temporary Azure image links | If SAS expiry is configured, uploaded Azure image URLs include a temporary read-only SAS token. |
| Update Firebase records | If Firebase is configured, the program writes each detected plate under the configured database path with zone, last four digits, image URL, and entry time. |
| Preserve first entry time | When Firebase already has an entry time for a plate, later updates keep the original entry time instead of overwriting it. |

## Preview Controls

| User-facing feature | How it is implemented |
| --- | --- |
| Draw scan areas | The user drags on the preview window. The program converts mouse positions into clamped pixel boxes. |
| Rename a selected area | Pressing a lowercase letter assigns that section name to the selected scan area. |
| Switch selected area | Pressing `Tab` cycles through available scan areas. |
| Reset scan areas | Pressing reset restores configured/default scan areas and updates the processor. |
| Clear scan areas | Pressing clear removes active scan areas and saves the changed configuration. |
| View crop debugging | A second window displays section crops and plate crops so the user can inspect why OCR succeeds or fails. |

## Maintenance Utilities

| User-facing feature | How it is implemented |
| --- | --- |
| Check Firebase data | `check_db.py` connects with the Firebase service account and prints stored database records. |
| Refresh Azure image links | `refresh_firebase_blob_sas.py` reads Firebase image URLs and replaces expired Azure SAS links with fresh read-only links. |
| Resize uploaded plate images | `resize_uploaded_plate_images.py` downloads plate image blobs, resizes/re-encodes them, overwrites the blob, and updates references. |
