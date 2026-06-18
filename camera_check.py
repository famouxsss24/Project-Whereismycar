from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ConnectedCamera:
    index: int
    capture: cv2.VideoCapture
    width: int
    height: int
    backend_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List connected camera indexes and show a small live preview."
    )
    parser.add_argument(
        "--max-index",
        type=int,
        default=10,
        help="Highest camera index to test, inclusive. Default: 10",
    )
    parser.add_argument(
        "--probe-width",
        type=int,
        default=640,
        help="Requested camera width while probing. Default: 640",
    )
    parser.add_argument(
        "--probe-height",
        type=int,
        default=480,
        help="Requested camera height while probing. Default: 480",
    )
    parser.add_argument(
        "--preview-width",
        type=int,
        default=320,
        help="Width of each preview tile. Default: 320",
    )
    parser.add_argument(
        "--preview-height",
        type=int,
        default=180,
        help="Height of each preview tile. Default: 180",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "dshow", "msmf", "any"),
        default="auto",
        help="OpenCV camera backend. On Windows, auto uses DirectShow only. Default: auto",
    )
    return parser.parse_args()


def named_backend(name: str) -> tuple[str, int] | None:
    if name == "dshow" and hasattr(cv2, "CAP_DSHOW"):
        return ("DirectShow", cv2.CAP_DSHOW)
    if name == "msmf" and hasattr(cv2, "CAP_MSMF"):
        return ("MSMF", cv2.CAP_MSMF)
    if name == "any":
        return ("Any", cv2.CAP_ANY)
    return None


def camera_backends(backend_name: str) -> list[tuple[str, int]]:
    if backend_name != "auto":
        backend = named_backend(backend_name)
        return [backend] if backend is not None else []

    if os.name == "nt" and hasattr(cv2, "CAP_DSHOW"):
        return [("DirectShow", cv2.CAP_DSHOW)]
    return [("Any", cv2.CAP_ANY)]


def open_camera(
    index: int,
    width: int,
    height: int,
    backend_name: str,
) -> tuple[cv2.VideoCapture, str] | None:
    for display_name, backend in camera_backends(backend_name):
        capture = cv2.VideoCapture(index, backend)
        if not capture.isOpened():
            capture.release()
            continue

        if hasattr(cv2, "CAP_PROP_FOURCC") and hasattr(cv2, "VideoWriter_fourcc"):
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        for _ in range(5):
            ok, frame = capture.read()
            if ok and frame is not None:
                return capture, display_name

        capture.release()
    return None


def find_connected_cameras(
    max_index: int,
    width: int,
    height: int,
    backend_name: str,
) -> list[ConnectedCamera]:
    connected: list[ConnectedCamera] = []
    for index in range(max_index + 1):
        print(f"Checking camera {index}...", flush=True)
        opened = open_camera(index, width, height, backend_name)
        if opened is None:
            continue

        capture, opened_backend = opened
        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        connected.append(
            ConnectedCamera(index, capture, actual_width, actual_height, opened_backend)
        )
        print(
            f"  connected: camera {index} ({actual_width}x{actual_height}, {opened_backend})",
            flush=True,
        )
    return connected


def labeled_tile(
    frame: np.ndarray | None,
    camera: ConnectedCamera,
    preview_size: tuple[int, int],
) -> np.ndarray:
    preview_width, preview_height = preview_size
    if frame is None:
        tile = np.zeros((preview_height, preview_width, 3), dtype=np.uint8)
        label = f"Camera {camera.index}: no frame"
    else:
        tile = cv2.resize(frame, preview_size, interpolation=cv2.INTER_AREA)
        label = f"Camera {camera.index}  {camera.width}x{camera.height}  {camera.backend_name}"

    cv2.rectangle(tile, (0, 0), (preview_width, 30), (0, 0, 0), thickness=-1)
    cv2.putText(
        tile,
        label,
        (10, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return tile


def build_preview_grid(
    cameras: list[ConnectedCamera],
    preview_size: tuple[int, int],
) -> np.ndarray:
    preview_width, preview_height = preview_size
    cols = max(1, math.ceil(math.sqrt(len(cameras))))
    rows = math.ceil(len(cameras) / cols)
    blank_tile = np.zeros((preview_height, preview_width, 3), dtype=np.uint8)

    tiles: list[np.ndarray] = []
    for camera in cameras:
        ok, frame = camera.capture.read()
        tiles.append(labeled_tile(frame if ok else None, camera, preview_size))

    while len(tiles) < rows * cols:
        tiles.append(blank_tile.copy())

    row_images = []
    for row in range(rows):
        start = row * cols
        row_images.append(np.hstack(tiles[start : start + cols]))
    return np.vstack(row_images)


def show_live_preview(
    cameras: list[ConnectedCamera],
    preview_width: int,
    preview_height: int,
) -> None:
    if not cameras:
        print("No connected cameras found.")
        return

    camera_numbers = ", ".join(str(camera.index) for camera in cameras)
    print(f"Connected camera indexes: {camera_numbers}")
    print("Press q or Esc in the preview window to quit. Ctrl+C also exits cleanly.")

    window_name = "Camera Check"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        while True:
            grid = build_preview_grid(cameras, (preview_width, preview_height))
            cv2.imshow(window_name, grid)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    except KeyboardInterrupt:
        print("\nCamera check stopped.")
    finally:
        for camera in cameras:
            camera.capture.release()
        cv2.destroyAllWindows()


def main() -> None:
    args = parse_args()
    cameras = find_connected_cameras(
        args.max_index,
        args.probe_width,
        args.probe_height,
        args.backend,
    )
    show_live_preview(cameras, args.preview_width, args.preview_height)


if __name__ == "__main__":
    main()
