# Simple Implementation Overview

This is a short user-facing summary of how the program works.

## What The Program Does

The program detects car license plates in parking spaces. It can use either a saved image or live camera video.

## How It Runs

1. The user starts the program with `python main.py`.
2. The program reads options from `settings.json` and command-line arguments.
3. It chooses image mode, webcam mode, loop mode, or preview mode.
4. It processes each frame and produces JSON results.

## Camera Or Image Input

- In image mode, the program reads one image file.
- In webcam mode, it opens the selected camera number.
- In multi-camera mode, it opens and processes several camera streams.
- Camera resolution can be set in `settings.json`.

## Parking Spaces

- The program divides the image into parking sections.
- Sections can be split automatically into rows or columns.
- The user can also draw or configure custom scan areas.
- Each section has a simple name like `a`, `b`, or `c`.

## Plate Detection

- The program looks for license plate areas inside each parking section.
- It can use a YOLO model for trained object detection.
- It can also use a heuristic image-processing detector.
- If YOLO misses a plate, the heuristic detector can be used as fallback.

## OCR

- After a plate is detected, the plate image is cropped.
- The crop is cleaned and enhanced.
- OCR reads the plate text.
- The program checks whether the text looks like a valid Korean license plate.

## Results

The program outputs information such as:

- camera or image source
- parking section name
- whether a section is occupied
- detected plate text
- confidence score
- plate and section box positions

## Preview Mode

Preview mode shows live camera windows. The user can:

- see parking section boxes
- see detected plate boxes
- draw scan areas with the mouse
- rename scan areas with keyboard letters
- inspect crop/debug images

## Publishing

The program can publish results in several ways:

- print JSON
- send JSON to an HTTP server
- save cropped plate images locally
- upload plate images to Azure Blob Storage
- update Firebase Realtime Database

## Utility Scripts

Extra scripts help with maintenance:

- `check_db.py` checks Firebase data.
- `refresh_firebase_blob_sas.py` refreshes Azure image links.
- `resize_uploaded_plate_images.py` resizes uploaded plate images.
