from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from parking_processor import ParkingLotProcessor
from plate_publish import (
    AzureBlobImagePublisher,
    FirebasePlatePublisher,
    LocalImageWebPublisher,
    PlateUpdateDispatcher,
    normalize_firebase_database_url,
    resolve_project_id_from_service_account,
)
from parking_types import Box, ProcessedFrameAnalysis, ScanArea, normalize_section_name, section_name_from_index
from plate_detection import divide_into_sections, resolve_default_yolo_model
from plate_ocr import load_image
from preview_windows import CROP_WINDOW_NAME, WINDOW_NAME, ScanAreaSelector, draw_crop_debug_window, draw_preview_frame


DEFAULT_SETTINGS_PATH = Path("settings.json")
PREVIEW_WINDOW_INITIAL_SIZE = (1280, 720)
CROP_WINDOW_INITIAL_SIZE = (1280, 480)
PREFERRED_CAMERA_RESOLUTIONS = (
    (4000, 3000),
    (3840, 2160),
    (2560, 1440),
    (1920, 1080),
    (1600, 900),
    (1280, 720),
    (1024, 768),
    (800, 600),
    (640, 480),
)


def create_resizable_window(window_name: str, initial_size: tuple[int, int]) -> None:
    width, height = initial_size
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, width, height)


def request_camera_resolution(capture: cv2.VideoCapture, resolution: tuple[int, int]) -> None:
    if hasattr(cv2, "VideoWriter_fourcc") and hasattr(cv2, "CAP_PROP_FOURCC"):
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    width, height = resolution
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)


def request_highest_camera_resolution(capture: cv2.VideoCapture) -> None:
    if hasattr(cv2, "VideoWriter_fourcc") and hasattr(cv2, "CAP_PROP_FOURCC"):
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    best_resolution: tuple[int, int] | None = None
    best_area = 0
    for width, height in PREFERRED_CAMERA_RESOLUTIONS:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if actual_width <= 0 or actual_height <= 0:
            continue
        area = actual_width * actual_height
        if area > best_area:
            best_area = area
            best_resolution = (actual_width, actual_height)

    if best_resolution is not None:
        width, height = best_resolution
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)


def open_camera(camera_index: int, resolution: tuple[int, int] | None = None) -> cv2.VideoCapture:
    backends = []
    if os.name == "nt" and hasattr(cv2, "CAP_DSHOW"):
        backends.append(cv2.CAP_DSHOW)
    backends.append(cv2.CAP_ANY)

    capture = cv2.VideoCapture()
    for backend in backends:
        capture = cv2.VideoCapture(camera_index, backend)
        if capture.isOpened():
            break
        capture.release()
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open webcam index {camera_index}.")
    if resolution is None:
        request_highest_camera_resolution(capture)
    else:
        request_camera_resolution(capture, resolution)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def capture_webcam_frame(camera_index: int, resolution: tuple[int, int] | None = None) -> np.ndarray:
    capture = open_camera(camera_index, resolution)
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError("Unable to read a frame from the webcam.")
        return frame
    finally:
        capture.release()


def resolve_yolo_model_argument(detector_name: str, yolo_model_path: str | None) -> str | None:
    if detector_name != "yolo":
        return yolo_model_path
    if yolo_model_path:
        return yolo_model_path
    default_model = resolve_default_yolo_model()
    return str(default_model) if default_model is not None else None


def parse_section_box_argument(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError(f"Invalid section box format: {value!r}. Expected x,y,w,h")
    try:
        x, y, width, height = (int(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"Section box contains non-integer values: {value!r}") from exc
    if x < 0 or y < 0:
        raise ValueError(f"Section box coordinates must be >= 0: {value!r}")
    if width <= 0 or height <= 0:
        raise ValueError(f"Section box width/height must be > 0: {value!r}")
    return (x, y, x + width, y + height)


def parse_section_boxes(raw_boxes: list[str] | None) -> list[tuple[int, int, int, int]]:
    if not raw_boxes:
        return []
    return [parse_section_box_argument(raw_value) for raw_value in raw_boxes]


def scan_areas_from_boxes(boxes: list[Box]) -> list[ScanArea]:
    return [ScanArea(section_name_from_index(index), box) for index, box in enumerate(boxes)]


def parse_camera_list_argument(value: str) -> list[int]:
    indexes: list[int] = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        try:
            index = int(stripped)
        except ValueError as exc:
            raise ValueError(f"Camera index must be an integer: {stripped!r}") from exc
        if index < 0:
            raise ValueError(f"Camera index must be >= 0: {index}")
        indexes.append(index)
    if not indexes:
        raise ValueError("At least one camera index is required.")
    return indexes


def dedupe_camera_indexes(indexes: list[int]) -> list[int]:
    deduped: list[int] = []
    for index in indexes:
        if index not in deduped:
            deduped.append(index)
    return deduped


def cli_has_option(argv: list[str], option_name: str) -> bool:
    return any(item == option_name or item.startswith(f"{option_name}=") for item in argv)


def resolve_settings_path(argv: list[str]) -> Path:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    known_args, _ = bootstrap.parse_known_args(argv)
    return Path(known_args.settings)


def _as_bool(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"Setting `{key}` must be a boolean.")


def _as_int(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Setting `{key}` must be an integer.")
    return value


def _as_int_list(value: object, key: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"Setting `{key}` must be a list of integers.")
    indexes = []
    for item in value:
        indexes.append(_as_int(item, key))
    if not indexes:
        raise ValueError(f"Setting `{key}` must include at least one camera index.")
    for index in indexes:
        if index < 0:
            raise ValueError(f"Setting `{key}` camera indexes must be >= 0.")
    return dedupe_camera_indexes(indexes)


def _as_camera_resolution_map(value: object, key: str = "camera_resolutions") -> dict[int, tuple[int, int]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Setting `{key}` must be an object keyed by camera index.")

    resolutions: dict[int, tuple[int, int]] = {}
    for raw_camera_index, raw_resolution in value.items():
        try:
            camera_index = int(raw_camera_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} key must be a camera index: {raw_camera_index!r}") from exc
        if camera_index < 0:
            raise ValueError(f"{key} keys must be >= 0.")
        if not isinstance(raw_resolution, dict):
            raise ValueError(f"{key}[{camera_index}] must be an object with width and height.")
        width = _as_int(raw_resolution.get("width"), f"{key}[{camera_index}].width")
        height = _as_int(raw_resolution.get("height"), f"{key}[{camera_index}].height")
        if width <= 0 or height <= 0:
            raise ValueError(f"{key}[{camera_index}] width and height must be > 0.")
        resolutions[camera_index] = (width, height)
    return resolutions


def _as_float(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Setting `{key}` must be a number.")
    return float(value)


def _as_optional_str(value: object, key: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise ValueError(f"Setting `{key}` must be a string or null.")


def _normalize_scan_area_settings(value: object, key: str = "section_boxes") -> list[ScanArea]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Setting `{key}` must be a list.")

    normalized: list[ScanArea] = []
    for index, item in enumerate(value):
        name = section_name_from_index(index)
        if isinstance(item, str):
            normalized.append(ScanArea(name, parse_section_box_argument(item)))
            continue
        if isinstance(item, dict):
            missing = [key for key in ("x", "y", "width", "height") if key not in item]
            if missing:
                raise ValueError(f"{key}[{index}] is missing keys: {', '.join(missing)}")
            if "name" in item:
                name = normalize_section_name(str(item["name"]), f"{key}[{index}].name")
            try:
                x = int(item["x"])
                y = int(item["y"])
                width = int(item["width"])
                height = int(item["height"])
            except Exception as exc:
                raise ValueError(f"{key}[{index}] contains non-integer values.") from exc
            normalized.append(ScanArea(name, parse_section_box_argument(f"{x},{y},{width},{height}")))
            continue
        if isinstance(item, (list, tuple)) and len(item) == 4:
            try:
                x = int(item[0])
                y = int(item[1])
                width = int(item[2])
                height = int(item[3])
            except Exception as exc:
                raise ValueError(f"{key}[{index}] contains non-integer values.") from exc
            normalized.append(ScanArea(name, parse_section_box_argument(f"{x},{y},{width},{height}")))
            continue
        raise ValueError(
            f"{key}[{index}] must be string, object(x,y,width,height), or [x,y,width,height]."
        )
    names = [area.name for area in normalized]
    if len(names) != len(set(names)):
        raise ValueError(f"Setting `{key}` contains duplicate scan area names.")
    return normalized


def _normalize_camera_scan_area_settings(value: object) -> dict[int, list[ScanArea]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Setting `camera_section_boxes` must be an object keyed by camera index.")

    normalized: dict[int, list[ScanArea]] = {}
    for raw_camera_index, raw_boxes in value.items():
        try:
            camera_index = int(raw_camera_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"camera_section_boxes key must be a camera index: {raw_camera_index!r}") from exc
        if camera_index < 0:
            raise ValueError("camera_section_boxes keys must be >= 0.")
        normalized[camera_index] = _normalize_scan_area_settings(
            raw_boxes,
            f"camera_section_boxes[{camera_index}]",
        )
    return normalized


def box_to_settings_entry(box: Box) -> dict[str, int]:
    x1, y1, x2, y2 = box
    return {
        "x": int(x1),
        "y": int(y1),
        "width": int(x2 - x1),
        "height": int(y2 - y1),
    }


def scan_area_to_settings_entry(area: ScanArea) -> dict[str, int | str]:
    entry = box_to_settings_entry(area.box)
    return {"name": area.name, **entry}


def load_settings_defaults(settings_path: Path, cli_argv: list[str]) -> dict[str, object]:
    if not settings_path.exists():
        return {}

    try:
        with settings_path.open("r", encoding="utf-8") as settings_file:
            raw_settings = json.load(settings_file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse settings file `{settings_path}`: {exc}") from exc

    if not isinstance(raw_settings, dict):
        raise ValueError(f"Settings file `{settings_path}` must contain a JSON object.")

    defaults: dict[str, object] = {}
    if "image_path" in raw_settings:
        defaults["image_path"] = _as_optional_str(raw_settings["image_path"], "image_path")
    if "webcam" in raw_settings:
        defaults["webcam"] = _as_bool(raw_settings["webcam"], "webcam")
    if not cli_has_option(cli_argv, "--camera") and not cli_has_option(cli_argv, "--cameras"):
        if "cameras" in raw_settings:
            defaults["camera"] = _as_int_list(raw_settings["cameras"], "cameras")
        elif "camera" in raw_settings:
            camera_index = _as_int(raw_settings["camera"], "camera")
            if camera_index < 0:
                raise ValueError("Setting `camera` must be >= 0.")
            defaults["camera"] = [camera_index]
    if "camera_resolutions" in raw_settings:
        defaults["camera_resolutions"] = _as_camera_resolution_map(raw_settings["camera_resolutions"])
    if "sections" in raw_settings:
        defaults["sections"] = _as_int(raw_settings["sections"], "sections")
    if "--section-box" not in cli_argv:
        if "section_boxes" in raw_settings:
            defaults["scan_area"] = _normalize_scan_area_settings(raw_settings["section_boxes"])
        if "camera_section_boxes" in raw_settings:
            defaults["camera_scan_areas"] = _normalize_camera_scan_area_settings(
                raw_settings["camera_section_boxes"]
            )
    if "detector" in raw_settings:
        detector = _as_optional_str(raw_settings["detector"], "detector")
        if detector not in ("heuristic", "yolo"):
            raise ValueError("Setting `detector` must be `heuristic` or `yolo`.")
        defaults["detector"] = detector
    if "yolo_only" in raw_settings:
        defaults["yolo_only"] = _as_bool(raw_settings["yolo_only"], "yolo_only")
    if "yolo_model" in raw_settings:
        defaults["yolo_model"] = _as_optional_str(raw_settings["yolo_model"], "yolo_model")
    if "yolo_conf" in raw_settings:
        defaults["yolo_conf"] = _as_float(raw_settings["yolo_conf"], "yolo_conf")
    if "yolo_imgsz" in raw_settings:
        defaults["yolo_imgsz"] = _as_int(raw_settings["yolo_imgsz"], "yolo_imgsz")
    if "layout" in raw_settings:
        layout = _as_optional_str(raw_settings["layout"], "layout")
        if layout not in ("columns", "rows"):
            raise ValueError("Setting `layout` must be `columns` or `rows`.")
        defaults["layout"] = layout
    if "server_url" in raw_settings:
        defaults["server_url"] = _as_optional_str(raw_settings["server_url"], "server_url")
    if "firebase_service_account" in raw_settings:
        defaults["firebase_service_account"] = _as_optional_str(
            raw_settings["firebase_service_account"], "firebase_service_account"
        )
    if "firebase_database_url" in raw_settings:
        defaults["firebase_database_url"] = _as_optional_str(raw_settings["firebase_database_url"], "firebase_database_url")
    if "firebase_root_path" in raw_settings:
        defaults["firebase_root_path"] = _as_optional_str(raw_settings["firebase_root_path"], "firebase_root_path")
    if "local_image_dir" in raw_settings:
        defaults["local_image_dir"] = _as_optional_str(raw_settings["local_image_dir"], "local_image_dir")
    if "local_image_base_url" in raw_settings:
        defaults["local_image_base_url"] = _as_optional_str(raw_settings["local_image_base_url"], "local_image_base_url")
    if "serve_local_images" in raw_settings:
        defaults["serve_local_images"] = _as_bool(raw_settings["serve_local_images"], "serve_local_images")
    if "local_image_server_host" in raw_settings:
        defaults["local_image_server_host"] = _as_optional_str(
            raw_settings["local_image_server_host"], "local_image_server_host"
        )
    if "local_image_server_port" in raw_settings:
        defaults["local_image_server_port"] = _as_int(raw_settings["local_image_server_port"], "local_image_server_port")
    if "azure_storage_connection_string" in raw_settings:
        defaults["azure_storage_connection_string"] = _as_optional_str(
            raw_settings["azure_storage_connection_string"], "azure_storage_connection_string"
        )
    if "azure_blob_container" in raw_settings:
        defaults["azure_blob_container"] = _as_optional_str(raw_settings["azure_blob_container"], "azure_blob_container")
    if "azure_blob_prefix" in raw_settings:
        defaults["azure_blob_prefix"] = _as_optional_str(raw_settings["azure_blob_prefix"], "azure_blob_prefix")
    if "azure_blob_sas_ttl_minutes" in raw_settings:
        defaults["azure_blob_sas_ttl_minutes"] = _as_int(raw_settings["azure_blob_sas_ttl_minutes"], "azure_blob_sas_ttl_minutes")
    if "azure_secrets_path" in raw_settings:
        defaults["azure_secrets_path"] = _as_optional_str(raw_settings["azure_secrets_path"], "azure_secrets_path")
    if "timeout" in raw_settings:
        defaults["timeout"] = _as_float(raw_settings["timeout"], "timeout")
    if "interval" in raw_settings:
        defaults["interval"] = _as_float(raw_settings["interval"], "interval")
    if "plate_cooldown" in raw_settings:
        defaults["plate_cooldown"] = _as_float(raw_settings["plate_cooldown"], "plate_cooldown")
    if "loop" in raw_settings:
        defaults["loop"] = _as_bool(raw_settings["loop"], "loop")
    if "preview" in raw_settings:
        defaults["preview"] = _as_bool(raw_settings["preview"], "preview")
    if "pretty" in raw_settings:
        defaults["pretty"] = _as_bool(raw_settings["pretty"], "pretty")

    return defaults


def process_webcam_frame(
    processor: ParkingLotProcessor,
    frame: np.ndarray,
    camera_index: int,
    dispatcher: PlateUpdateDispatcher,
    pretty: bool,
) -> ProcessedFrameAnalysis:
    analysis = processor.process_frame(frame, "webcam", str(camera_index))
    try:
        dispatcher.emit(analysis, pretty)
    except Exception as exc:  # pragma: no cover - live preview path
        print(f"Publish error: {exc}", file=sys.stderr)
    return analysis


def load_azure_secrets(path_value: str | None) -> dict[str, object]:
    if not path_value:
        return {}

    secrets_path = Path(path_value)
    if not secrets_path.exists():
        raise ValueError(f"Azure secrets file not found: {secrets_path}")

    try:
        with secrets_path.open("r", encoding="utf-8") as secrets_file:
            data = json.load(secrets_file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse Azure secrets file `{secrets_path}`: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Azure secrets file `{secrets_path}` must contain a JSON object.")
    return data


def build_parser(defaults: dict[str, object] | None = None) -> argparse.ArgumentParser:
    default_model = resolve_default_yolo_model()
    default_model_help = f" Auto-detected default: {default_model}." if default_model is not None else ""

    parser = argparse.ArgumentParser(
        description="Split a parking image into sections, detect and OCR license plates, and return JSON.",
    )
    parser.add_argument(
        "--settings",
        default=str(DEFAULT_SETTINGS_PATH),
        help=f"Path to a JSON settings file. Default: {DEFAULT_SETTINGS_PATH}.",
    )
    parser.add_argument("image_path", nargs="?", help="Path to an image to process.")
    parser.add_argument("--webcam", action="store_true", help="Capture frames from a webcam instead of an image.")
    parser.add_argument(
        "--camera",
        type=int,
        action="append",
        default=[],
        help="Webcam index. Repeat for multiple cameras. Default: 0.",
    )
    parser.add_argument(
        "--cameras",
        help="Comma-separated webcam indexes, for example 0,1. Overrides --camera.",
    )
    parser.add_argument("--sections", type=int, default=3, help="Number of parking sections. Default: 3.")
    parser.add_argument(
        "--section-box",
        action="append",
        metavar="X,Y,W,H",
        help=(
            "Custom recognition box in pixels (repeat per section). "
            "Format: x,y,width,height. When provided, overrides --sections and --layout."
        ),
    )
    parser.add_argument(
        "--detector",
        choices=("heuristic", "yolo"),
        default="heuristic",
        help="Plate detector backend. Default: heuristic.",
    )
    parser.add_argument(
        "--yolo-only",
        action="store_true",
        help="Use YOLO only (disable heuristic fallback when YOLO misses).",
    )
    parser.add_argument("--yolo-model", help=f"Path to YOLO weights for license-plate detection.{default_model_help}")
    parser.add_argument("--yolo-conf", type=float, default=0.25, help="YOLO confidence threshold. Default: 0.25.")
    parser.add_argument("--yolo-imgsz", type=int, default=640, help="YOLO inference image size. Default: 640.")
    parser.add_argument(
        "--layout",
        choices=("columns", "rows"),
        default="columns",
        help="How to divide the image. Default: columns.",
    )
    parser.add_argument("--server-url", help="Optional server URL to receive the JSON via POST.")
    parser.add_argument(
        "--firebase-service-account",
        help="Path to Firebase service account JSON. Enables Firebase Realtime DB updates.",
    )
    parser.add_argument(
        "--firebase-database-url",
        help="Firebase Realtime Database URL. If omitted, inferred from project_id.",
    )
    parser.add_argument(
        "--firebase-root-path",
        default="parking_lot",
        help="Realtime DB root path for plate records. Default: parking_lot.",
    )
    parser.add_argument(
        "--local-image-dir",
        default="plate_images",
        help="Directory to save cropped plate images for local hosting. Default: plate_images.",
    )
    parser.add_argument(
        "--local-image-base-url",
        help="External base URL for local images. If omitted, built-in static server URL is used.",
    )
    parser.add_argument(
        "--serve-local-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run built-in static server for local plate images. Default: enabled.",
    )
    parser.add_argument(
        "--local-image-server-host",
        default="127.0.0.1",
        help="Host for built-in local image server. Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--local-image-server-port",
        type=int,
        default=8787,
        help="Port for built-in local image server. Default: 8787.",
    )
    parser.add_argument(
        "--azure-storage-connection-string",
        help="Azure Storage connection string. When set with --azure-blob-container, plate JPGs are uploaded to Blob Storage.",
    )
    parser.add_argument(
        "--azure-blob-container",
        help="Azure Blob container name for plate JPG uploads.",
    )
    parser.add_argument(
        "--azure-blob-prefix",
        default="plate_images",
        help="Blob path prefix inside the container. Default: plate_images.",
    )
    parser.add_argument(
        "--azure-blob-sas-ttl-minutes",
        type=int,
        default=0,
        help="If >0, append a read-only SAS token valid for this many minutes to image URLs. Default: 0.",
    )
    parser.add_argument(
        "--azure-secrets-path",
        help=(
            "Path to Azure secrets JSON file. Supported keys: "
            "azure_storage_connection_string, azure_blob_container, azure_blob_prefix, azure_blob_sas_ttl_minutes."
        ),
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="POST timeout in seconds. Default: 10.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between webcam OCR runs. Default: 1.")
    parser.add_argument(
        "--plate-cooldown",
        type=float,
        default=30.0,
        help="Seconds to suppress duplicate updates for the same plate. Default: 30.",
    )
    parser.add_argument("--loop", action="store_true", help="Continuously process webcam frames.")
    parser.add_argument("--preview", action="store_true", help="Show live preview and crop debug windows.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    if defaults:
        parser.set_defaults(**defaults)
    return parser


def build_dispatcher(args: argparse.Namespace) -> PlateUpdateDispatcher:
    firebase_publisher: FirebasePlatePublisher | None = None
    if args.firebase_service_account:
        project_id = resolve_project_id_from_service_account(args.firebase_service_account)
        firebase_database_url = normalize_firebase_database_url(project_id, args.firebase_database_url)
        firebase_publisher = FirebasePlatePublisher(
            service_account_path=args.firebase_service_account,
            database_url=firebase_database_url,
            root_path=args.firebase_root_path or "parking_lot",
        )

    azure_secrets = load_azure_secrets(args.azure_secrets_path)
    azure_storage_connection_string = args.azure_storage_connection_string or _as_optional_str(
        azure_secrets.get("azure_storage_connection_string"), "azure_storage_connection_string"
    )
    azure_blob_container = args.azure_blob_container or _as_optional_str(
        azure_secrets.get("azure_blob_container"), "azure_blob_container"
    )
    azure_blob_prefix = args.azure_blob_prefix or _as_optional_str(
        azure_secrets.get("azure_blob_prefix"), "azure_blob_prefix"
    )
    azure_blob_sas_ttl_minutes = args.azure_blob_sas_ttl_minutes
    if azure_blob_sas_ttl_minutes == 0 and "azure_blob_sas_ttl_minutes" in azure_secrets:
        azure_blob_sas_ttl_minutes = _as_int(
            azure_secrets.get("azure_blob_sas_ttl_minutes"), "azure_blob_sas_ttl_minutes"
        )

    azure_image_publisher: AzureBlobImagePublisher | None = None
    if azure_storage_connection_string and azure_blob_container:
        azure_image_publisher = AzureBlobImagePublisher(
            connection_string=azure_storage_connection_string,
            container_name=azure_blob_container,
            blob_prefix=azure_blob_prefix or "plate_images",
            sas_ttl_minutes=azure_blob_sas_ttl_minutes,
        )

    local_image_publisher: LocalImageWebPublisher | None = None
    if azure_image_publisher is None:
        local_image_base_url = args.local_image_base_url or os.environ.get("LOCAL_IMAGE_BASE_URL")
        local_image_publisher = LocalImageWebPublisher(
            image_dir=args.local_image_dir or "plate_images",
            base_url=local_image_base_url,
            serve=args.serve_local_images,
            host=args.local_image_server_host or "127.0.0.1",
            port=args.local_image_server_port,
        )

    return PlateUpdateDispatcher(
        server_url=args.server_url,
        timeout=args.timeout,
        cooldown_seconds=args.plate_cooldown,
        firebase_publisher=firebase_publisher,
        local_image_publisher=local_image_publisher,
        azure_image_publisher=azure_image_publisher,
    )


def resolve_camera_indexes(args: argparse.Namespace) -> list[int]:
    if args.cameras:
        return dedupe_camera_indexes(parse_camera_list_argument(args.cameras))
    indexes = dedupe_camera_indexes(list(args.camera or []))
    if not indexes:
        indexes = [0]
    for index in indexes:
        if index < 0:
            raise ValueError("Camera indexes must be >= 0.")
    return indexes


def build_processor(
    args: argparse.Namespace,
    scan_areas: list[ScanArea] | None,
    resolved_yolo_model: str | None,
) -> ParkingLotProcessor:
    processor = ParkingLotProcessor(
        section_count=args.sections,
        layout=args.layout,
        section_boxes=None if scan_areas is None else [area.box for area in scan_areas],
        detector_name=args.detector,
        yolo_model_path=resolved_yolo_model,
        yolo_confidence=args.yolo_conf,
        yolo_image_size=args.yolo_imgsz,
        allow_yolo_fallback=not args.yolo_only,
    )
    if scan_areas is not None:
        processor.set_scan_areas(scan_areas)
    return processor


def build_processors(
    args: argparse.Namespace,
    scan_areas_by_camera: dict[int, list[ScanArea] | None],
    resolved_yolo_model: str | None,
    camera_indexes: list[int],
) -> dict[int, ParkingLotProcessor]:
    return {
        camera_index: build_processor(args, scan_areas_by_camera.get(camera_index), resolved_yolo_model)
        for camera_index in camera_indexes
    }


def camera_resolution_for(args: argparse.Namespace, camera_index: int) -> tuple[int, int] | None:
    resolutions = getattr(args, "camera_resolutions", None)
    return resolutions.get(camera_index) if isinstance(resolutions, dict) else None


def open_cameras(args: argparse.Namespace, camera_indexes: list[int]) -> dict[int, cv2.VideoCapture]:
    captures: dict[int, cv2.VideoCapture] = {}
    try:
        for camera_index in camera_indexes:
            captures[camera_index] = open_camera(camera_index, camera_resolution_for(args, camera_index))
        return captures
    except Exception:
        for capture in captures.values():
            capture.release()
        raise


def resolve_configured_scan_areas(
    args: argparse.Namespace,
    camera_indexes: list[int],
    cli_section_box_override: bool,
) -> dict[int, list[ScanArea] | None]:
    cli_scan_areas = scan_areas_from_boxes(parse_section_boxes(args.section_box))
    raw_settings_scan_areas = getattr(args, "scan_area", None)
    settings_scan_areas = raw_settings_scan_areas if isinstance(raw_settings_scan_areas, list) else None
    global_scan_areas = cli_scan_areas if cli_section_box_override else settings_scan_areas or cli_scan_areas
    raw_camera_scan_areas = getattr(args, "camera_scan_areas", None)
    camera_scan_areas = raw_camera_scan_areas if isinstance(raw_camera_scan_areas, dict) else {}

    configured: dict[int, list[ScanArea] | None] = {}
    for camera_index in camera_indexes:
        if args.webcam and not cli_section_box_override and camera_index in camera_scan_areas:
            configured[camera_index] = camera_scan_areas[camera_index]
            continue
        configured[camera_index] = global_scan_areas if global_scan_areas else None
    return configured


def save_camera_scan_areas(settings_path: Path, camera_index: int, scan_areas: list[ScanArea]) -> None:
    settings: dict[str, object] = {}
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as settings_file:
            raw_settings = json.load(settings_file)
        if isinstance(raw_settings, dict):
            settings = raw_settings

    raw_camera_boxes = settings.get("camera_section_boxes")
    camera_boxes = raw_camera_boxes if isinstance(raw_camera_boxes, dict) else {}
    camera_boxes[str(camera_index)] = [scan_area_to_settings_entry(area) for area in scan_areas]
    settings["camera_section_boxes"] = camera_boxes

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, ensure_ascii=False, indent=2)
        settings_file.write("\n")


def run_once(
    args: argparse.Namespace,
    processors: dict[int, ParkingLotProcessor],
    dispatcher: PlateUpdateDispatcher,
    camera_indexes: list[int],
) -> int:
    if args.webcam:
        for camera_index in camera_indexes:
            frame = capture_webcam_frame(camera_index, camera_resolution_for(args, camera_index))
            analysis = processors[camera_index].process_frame(frame, "webcam", str(camera_index))
            dispatcher.emit(analysis, args.pretty)
        return 0
    else:
        image_path = Path(args.image_path)
        if not image_path.exists():
            print(f"Image not found: {image_path}", file=sys.stderr)
            return 1
        processor = processors[camera_indexes[0]]
        analysis = processor.process_frame(load_image(image_path), "image", str(image_path))

    dispatcher.emit(analysis, args.pretty)
    return 0


def run_loop(
    args: argparse.Namespace,
    processors: dict[int, ParkingLotProcessor],
    dispatcher: PlateUpdateDispatcher,
    camera_indexes: list[int],
) -> int:
    captures = open_cameras(args, camera_indexes)
    try:
        while True:
            for camera_index, capture in captures.items():
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise RuntimeError(f"Unable to read a frame from webcam index {camera_index}.")
                analysis = processors[camera_index].process_frame(frame, "webcam", str(camera_index))
                dispatcher.emit(analysis, args.pretty)
            time.sleep(args.interval)
    finally:
        for capture in captures.values():
            capture.release()


@dataclass
class PreviewCameraState:
    processor: ParkingLotProcessor
    selector: ScanAreaSelector
    window_name: str
    crop_window_name: str
    latest_analysis: ProcessedFrameAnalysis | None = None
    latest_error: str | None = None
    last_completed_at: float | None = None
    last_submission_at: float = 0.0
    pending: concurrent.futures.Future[ProcessedFrameAnalysis] | None = None
    selector_initialized: bool = False


def preview_window_name(base_name: str, camera_index: int, multi_camera: bool) -> str:
    return f"{base_name} - Camera {camera_index}" if multi_camera else base_name


def initial_scan_areas(
    args: argparse.Namespace,
    configured_scan_areas: list[ScanArea] | None,
    frame_shape: tuple[int, ...],
) -> list[ScanArea]:
    if configured_scan_areas is not None:
        return list(configured_scan_areas)
    return [
        ScanArea(spec.display_name, spec.box)
        for spec in divide_into_sections(frame_shape, args.sections, args.layout)
    ]


def run_preview_loop(
    args: argparse.Namespace,
    processors: dict[int, ParkingLotProcessor],
    dispatcher: PlateUpdateDispatcher,
    camera_indexes: list[int],
    configured_scan_areas_by_camera: dict[int, list[ScanArea] | None],
    settings_path: Path,
) -> int:
    captures = open_cameras(args, camera_indexes)
    multi_camera = len(camera_indexes) > 1
    states: dict[int, PreviewCameraState] = {}

    for camera_index in camera_indexes:
        selector = ScanAreaSelector()
        window_name = preview_window_name(WINDOW_NAME, camera_index, multi_camera)
        crop_window_name = preview_window_name(CROP_WINDOW_NAME, camera_index, multi_camera)
        create_resizable_window(window_name, PREVIEW_WINDOW_INITIAL_SIZE)
        create_resizable_window(crop_window_name, CROP_WINDOW_INITIAL_SIZE)
        cv2.setMouseCallback(window_name, selector.mouse_callback)
        states[camera_index] = PreviewCameraState(
            processor=processors[camera_index],
            selector=selector,
            window_name=window_name,
            crop_window_name=crop_window_name,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(camera_indexes))) as executor:
        try:
            while True:
                now = time.monotonic()
                for camera_index, capture in captures.items():
                    state = states[camera_index]
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        raise RuntimeError(f"Unable to read a frame from webcam index {camera_index}.")

                    state.selector.set_frame_shape(frame.shape)
                    if not state.selector_initialized:
                        state.selector.set_initial_scan_areas(
                            initial_scan_areas(
                                args,
                                configured_scan_areas_by_camera.get(camera_index),
                                frame.shape,
                            )
                        )
                        state.selector_initialized = True

                    if state.selector.consume_changed():
                        state.processor.set_scan_areas(state.selector.scan_areas)
                        save_camera_scan_areas(settings_path, camera_index, state.selector.scan_areas)

                    if state.pending is not None and state.pending.done():
                        try:
                            state.latest_analysis = state.pending.result()
                            state.latest_error = None
                            state.last_completed_at = now
                        except Exception as exc:  # pragma: no cover - live preview path
                            state.latest_error = str(exc)
                        state.pending = None

                    if state.pending is None and now - state.last_submission_at >= args.interval:
                        state.pending = executor.submit(
                            process_webcam_frame,
                            state.processor,
                            frame.copy(),
                            camera_index,
                            dispatcher,
                            args.pretty,
                        )
                        state.last_submission_at = now

                    section_specs = state.processor.get_section_specs(frame.shape)
                    latest_analysis = state.latest_analysis
                    latest_payload = latest_analysis.payload if latest_analysis is not None else None
                    display = draw_preview_frame(
                        frame=frame,
                        section_specs=section_specs,
                        payload=latest_payload,
                        pending=state.pending is not None,
                        last_completed_at=None if state.last_completed_at is None else now - state.last_completed_at,
                        latest_error=state.latest_error,
                        draft_box=state.selector.draft_box,
                        selected_section_name=state.selector.selected_name,
                    )
                    crop_debug_display = draw_crop_debug_window(
                        processed_sections=latest_analysis.sections if latest_analysis is not None else [],
                        section_specs=section_specs,
                    )
                    cv2.imshow(state.window_name, display)
                    cv2.imshow(state.crop_window_name, crop_debug_display)

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    return 0
                elif key == ord("c"):
                    for camera_index, state in states.items():
                        state.selector.clear()
                        state.processor.set_scan_areas(state.selector.scan_areas)
                        save_camera_scan_areas(settings_path, camera_index, state.selector.scan_areas)
                elif key == ord("r"):
                    for camera_index, state in states.items():
                        state.selector.reset()
                        state.processor.set_scan_areas(state.selector.scan_areas)
                        save_camera_scan_areas(settings_path, camera_index, state.selector.scan_areas)
                elif key == 9:
                    for state in states.values():
                        state.selector.select_next()
                elif ord("a") <= key <= ord("z"):
                    name = chr(key)
                    for camera_index, state in states.items():
                        if state.selector.rename_selected(name):
                            state.processor.set_scan_areas(state.selector.scan_areas)
                            save_camera_scan_areas(settings_path, camera_index, state.selector.scan_areas)
        finally:
            for capture in captures.values():
                capture.release()
            cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    argv_list = list(argv) if argv is not None else sys.argv[1:]
    settings_path = resolve_settings_path(argv_list)
    try:
        defaults = load_settings_defaults(settings_path, argv_list)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser = build_parser(defaults=defaults)
    args = parser.parse_args(argv_list)
    try:
        camera_indexes = resolve_camera_indexes(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.webcam and args.image_path:
        parser.error("Choose an image path or --webcam, not both.")
    if not args.webcam and not args.image_path:
        parser.error("Provide an IMAGE_PATH or use --webcam.")
    if args.loop and not args.webcam:
        parser.error("--loop requires --webcam.")
    if args.preview and not args.webcam:
        parser.error("--preview requires --webcam.")
    if args.sections <= 0 and not args.section_box:
        parser.error("--sections must be greater than 0.")
    if args.yolo_conf <= 0 or args.yolo_conf > 1:
        parser.error("--yolo-conf must be in the range (0, 1].")
    if args.yolo_imgsz <= 0:
        parser.error("--yolo-imgsz must be greater than 0.")
    if args.yolo_only and args.detector != "yolo":
        parser.error("--yolo-only requires --detector yolo.")
    if args.interval <= 0:
        parser.error("--interval must be greater than 0.")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0.")
    if args.plate_cooldown < 0:
        parser.error("--plate-cooldown must be >= 0.")
    if args.firebase_service_account and not Path(args.firebase_service_account).exists():
        parser.error("--firebase-service-account path does not exist.")
    if args.local_image_server_port <= 0 or args.local_image_server_port > 65535:
        parser.error("--local-image-server-port must be in range 1..65535.")
    if args.azure_blob_sas_ttl_minutes < 0:
        parser.error("--azure-blob-sas-ttl-minutes must be >= 0.")
    azure_secrets_data: dict[str, object] = {}
    try:
        azure_secrets_data = load_azure_secrets(args.azure_secrets_path)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        effective_connection = args.azure_storage_connection_string or _as_optional_str(
            azure_secrets_data.get("azure_storage_connection_string"), "azure_storage_connection_string"
        )
        effective_container = args.azure_blob_container or _as_optional_str(
            azure_secrets_data.get("azure_blob_container"), "azure_blob_container"
        )
    except ValueError as exc:
        parser.error(str(exc))
    if bool(effective_connection) != bool(effective_container):
        parser.error(
            "Azure configuration requires both connection string and container "
            "(via CLI/settings and/or --azure-secrets-path file)."
        )

    try:
        configured_scan_areas_by_camera = resolve_configured_scan_areas(
            args,
            camera_indexes,
            cli_has_option(argv_list, "--section-box"),
        )
    except ValueError as exc:
        parser.error(str(exc))
    resolved_yolo_model = resolve_yolo_model_argument(args.detector, args.yolo_model)
    if args.detector == "yolo" and resolved_yolo_model is None:
        parser.error("--detector yolo requires --yolo-model or a supported default model in `models/`.")

    try:
        dispatcher = build_dispatcher(args)
        if args.preview:
            processors = build_processors(args, configured_scan_areas_by_camera, resolved_yolo_model, camera_indexes)
            return run_preview_loop(
                args,
                processors,
                dispatcher,
                camera_indexes,
                configured_scan_areas_by_camera,
                settings_path,
            )
        if args.loop:
            processors = build_processors(args, configured_scan_areas_by_camera, resolved_yolo_model, camera_indexes)
            return run_loop(args, processors, dispatcher, camera_indexes)
        run_once_camera_indexes = camera_indexes if args.webcam else [camera_indexes[0]]
        processors = build_processors(args, configured_scan_areas_by_camera, resolved_yolo_model, run_once_camera_indexes)
        return run_once(args, processors, dispatcher, run_once_camera_indexes)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
