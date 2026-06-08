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
from parking_types import Box, ProcessedFrameAnalysis, SectionSpec
from plate_detection import divide_into_sections, resolve_default_yolo_model
from plate_ocr import load_image
from preview_windows import WINDOW_NAME, ScanAreaSelector, draw_crop_debug_window, draw_preview_frame


DEFAULT_SETTINGS_PATH = Path("settings.json")


def open_camera(camera_index: int, width: int = 0, height: int = 0, fps: float = 0.0) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if os.name == "nt" and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
    capture = cv2.VideoCapture(camera_index, backend)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open webcam index {camera_index}.")
    if hasattr(cv2, "CAP_PROP_FOURCC"):
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    if width > 0:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height > 0:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps > 0:
        capture.set(cv2.CAP_PROP_FPS, fps)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def capture_webcam_frame(camera_index: int, width: int = 0, height: int = 0, fps: float = 0.0) -> np.ndarray:
    capture = open_camera(camera_index, width, height, fps)
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


def _as_str_list(value: object, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Setting `{key}` must be a list of strings.")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"Setting `{key}` item #{index + 1} must be a string.")
        items.append(item)
    return items


def _normalize_section_box_settings(value: object, key: str = "section_boxes") -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Setting `{key}` must be a list.")

    normalized: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            normalized.append(item)
            continue
        if isinstance(item, dict):
            missing = [key for key in ("x", "y", "width", "height") if key not in item]
            if missing:
                raise ValueError(f"{key}[{index}] is missing keys: {', '.join(missing)}")
            try:
                x = int(item["x"])
                y = int(item["y"])
                width = int(item["width"])
                height = int(item["height"])
            except Exception as exc:
                raise ValueError(f"{key}[{index}] contains non-integer values.") from exc
            normalized.append(f"{x},{y},{width},{height}")
            continue
        if isinstance(item, (list, tuple)) and len(item) == 4:
            try:
                x = int(item[0])
                y = int(item[1])
                width = int(item[2])
                height = int(item[3])
            except Exception as exc:
                raise ValueError(f"{key}[{index}] contains non-integer values.") from exc
            normalized.append(f"{x},{y},{width},{height}")
            continue
        raise ValueError(
            f"{key}[{index}] must be string, object(x,y,width,height), or [x,y,width,height]."
        )
    return normalized


def _normalize_camera_section_box_settings(value: object) -> dict[int, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Setting `camera_section_boxes` must be an object keyed by camera index.")

    normalized: dict[int, list[str]] = {}
    for raw_camera_index, raw_boxes in value.items():
        try:
            camera_index = int(raw_camera_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"camera_section_boxes key must be a camera index: {raw_camera_index!r}") from exc
        if camera_index < 0:
            raise ValueError("camera_section_boxes keys must be >= 0.")
        normalized[camera_index] = _normalize_section_box_settings(
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
    if "camera_width" in raw_settings:
        defaults["camera_width"] = _as_int(raw_settings["camera_width"], "camera_width")
    if "camera_height" in raw_settings:
        defaults["camera_height"] = _as_int(raw_settings["camera_height"], "camera_height")
    if "camera_fps" in raw_settings:
        defaults["camera_fps"] = _as_float(raw_settings["camera_fps"], "camera_fps")
    if "sections" in raw_settings:
        defaults["sections"] = _as_int(raw_settings["sections"], "sections")
    if "--section-box" not in cli_argv:
        if "section_boxes" in raw_settings:
            defaults["section_box"] = _normalize_section_box_settings(raw_settings["section_boxes"])
        if "camera_section_boxes" in raw_settings:
            defaults["camera_section_boxes"] = _normalize_camera_section_box_settings(
                raw_settings["camera_section_boxes"]
            )
    if "zone_offsets" in raw_settings:
        raw_offsets = raw_settings["zone_offsets"]
        if isinstance(raw_offsets, dict):
            defaults["zone_offsets"] = {str(k): int(v) for k, v in raw_offsets.items()}
    if "section_zones" in raw_settings:
        raw_section_zones = raw_settings["section_zones"]
        if isinstance(raw_section_zones, dict):
            defaults["section_zones"] = {
                str(camera_index): [str(zone).strip().upper() for zone in zones]
                for camera_index, zones in raw_section_zones.items()
                if isinstance(zones, list)
            }
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
    if "dwell_seconds" in raw_settings:
        defaults["dwell_seconds"] = _as_float(raw_settings["dwell_seconds"], "dwell_seconds")
    if "loop" in raw_settings:
        defaults["loop"] = _as_bool(raw_settings["loop"], "loop")
    if "preview" in raw_settings:
        defaults["preview"] = _as_bool(raw_settings["preview"], "preview")
    if "pretty" in raw_settings:
        defaults["pretty"] = _as_bool(raw_settings["pretty"], "pretty")
    if "known_plates" in raw_settings:
        defaults["known_plates"] = _as_str_list(raw_settings["known_plates"], "known_plates")

    return defaults


def process_webcam_frame(
    processor: ParkingLotProcessor,
    frame: np.ndarray,
    camera_index: int,
) -> ProcessedFrameAnalysis:
    return processor.process_frame(frame, "webcam", str(camera_index))


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
    parser.add_argument("--camera-width", type=int, default=0, help="Requested webcam width in pixels. Default: camera default.")
    parser.add_argument("--camera-height", type=int, default=0, help="Requested webcam height in pixels. Default: camera default.")
    parser.add_argument("--camera-fps", type=float, default=0.0, help="Requested webcam FPS. Default: camera default.")
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
    parser.add_argument(
        "--dwell-seconds",
        type=float,
        default=5.0,
        help="Seconds a plate must stay in the same zone before being written to Firebase. Default: 5.",
    )
    parser.add_argument("--loop", action="store_true", help="Continuously process webcam frames.")
    parser.add_argument("--preview", action="store_true", help="Show live preview and crop debug windows.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    parser.add_argument(
        "--known-plate",
        action="append",
        dest="known_plates",
        default=[],
        help="Known demo/test plate used to correct OCR when Hangul is missed. Repeatable.",
    )
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

    zone_offsets = getattr(args, "zone_offsets", None) or {}
    section_zones = getattr(args, "section_zones", None) or {}
    dwell_seconds = getattr(args, "dwell_seconds", 5.0)
    return PlateUpdateDispatcher(
        server_url=args.server_url,
        timeout=args.timeout,
        cooldown_seconds=args.plate_cooldown,
        firebase_publisher=firebase_publisher,
        local_image_publisher=local_image_publisher,
        azure_image_publisher=azure_image_publisher,
        zone_offsets=zone_offsets,
        section_zones=section_zones,
        dwell_seconds=dwell_seconds,
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
    section_boxes: list[Box] | None,
    resolved_yolo_model: str | None,
) -> ParkingLotProcessor:
    return ParkingLotProcessor(
        section_count=args.sections,
        layout=args.layout,
        section_boxes=section_boxes,
        detector_name=args.detector,
        yolo_model_path=resolved_yolo_model,
        yolo_confidence=args.yolo_conf,
        yolo_image_size=args.yolo_imgsz,
        allow_yolo_fallback=not args.yolo_only,
        known_plates=args.known_plates,
    )


def build_processors(
    args: argparse.Namespace,
    section_boxes_by_camera: dict[int, list[Box] | None],
    resolved_yolo_model: str | None,
    camera_indexes: list[int],
) -> dict[int, ParkingLotProcessor]:
    return {
        camera_index: build_processor(args, section_boxes_by_camera.get(camera_index), resolved_yolo_model)
        for camera_index in camera_indexes
    }


def open_cameras(
    camera_indexes: list[int],
    width: int = 0,
    height: int = 0,
    fps: float = 0.0,
) -> dict[int, cv2.VideoCapture]:
    captures: dict[int, cv2.VideoCapture] = {}
    try:
        for camera_index in camera_indexes:
            captures[camera_index] = open_camera(camera_index, width, height, fps)
        return captures
    except Exception:
        for capture in captures.values():
            capture.release()
        raise


def parse_camera_section_boxes(raw_boxes: dict[int, list[str]] | None) -> dict[int, list[Box]]:
    if not raw_boxes:
        return {}
    return {
        camera_index: parse_section_boxes(camera_boxes)
        for camera_index, camera_boxes in raw_boxes.items()
    }


def resolve_configured_section_boxes(
    args: argparse.Namespace,
    camera_indexes: list[int],
    cli_section_box_override: bool,
) -> dict[int, list[Box] | None]:
    global_section_boxes = parse_section_boxes(args.section_box)
    camera_section_boxes = parse_camera_section_boxes(getattr(args, "camera_section_boxes", None))

    configured: dict[int, list[Box] | None] = {}
    for camera_index in camera_indexes:
        if args.webcam and not cli_section_box_override and camera_index in camera_section_boxes:
            configured[camera_index] = camera_section_boxes[camera_index]
            continue
        configured[camera_index] = global_section_boxes if global_section_boxes else None
    return configured


def save_camera_section_boxes(settings_path: Path, camera_index: int, boxes: list[Box]) -> None:
    settings: dict[str, object] = {}
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as settings_file:
            raw_settings = json.load(settings_file)
        if isinstance(raw_settings, dict):
            settings = raw_settings

    raw_camera_boxes = settings.get("camera_section_boxes")
    camera_boxes = raw_camera_boxes if isinstance(raw_camera_boxes, dict) else {}
    camera_boxes[str(camera_index)] = [box_to_settings_entry(box) for box in boxes]
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
            frame = capture_webcam_frame(camera_index, args.camera_width, args.camera_height, args.camera_fps)
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
    captures = open_cameras(camera_indexes, args.camera_width, args.camera_height, args.camera_fps)
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
    latest_analysis: ProcessedFrameAnalysis | None = None
    latest_error: str | None = None
    last_completed_at: float | None = None
    last_submission_at: float = 0.0
    pending: concurrent.futures.Future[ProcessedFrameAnalysis] | None = None
    pending_revision: int | None = None
    scan_revision: int = 0
    selector_initialized: bool = False
    crop_debug_display: np.ndarray | None = None
    crop_debug_signature: tuple[int | None, tuple[tuple[str, Box], ...]] | None = None


@dataclass
class DashboardItem:
    camera_index: int
    preview: np.ndarray
    crop_debug: np.ndarray


@dataclass
class DashboardHitRegion:
    camera_index: int
    left: int
    top: int
    right: int
    bottom: int
    scale: float


def preview_window_name(base_name: str, camera_index: int, multi_camera: bool) -> str:
    return f"{base_name} - Camera {camera_index}" if multi_camera else base_name


def resize_with_scale(image: np.ndarray, max_width: int, max_height: int) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    if height == 0 or width == 0:
        return np.zeros((max_height, max_width, 3), dtype=np.uint8), 1.0

    scale = min(max_width / width, max_height / height, 1.0)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    if new_width == width and new_height == height:
        return image, 1.0
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(image, (new_width, new_height), interpolation=interpolation), scale


def paste_image(canvas: np.ndarray, image: np.ndarray, x: int, y: int) -> None:
    height, width = image.shape[:2]
    canvas[y:y + height, x:x + width] = image


def build_preview_dashboard(items: list[DashboardItem]) -> tuple[np.ndarray, dict[int, DashboardHitRegion]]:
    if not items:
        return np.zeros((360, 640, 3), dtype=np.uint8), {}

    max_preview_width = 640
    max_preview_height = 480
    max_crop_width = 640
    max_crop_height = 260
    padding = 8
    gap = 12
    title_height = 28
    columns = min(2, len(items))

    prepared = []
    for item in items:
        preview, preview_scale = resize_with_scale(item.preview, max_preview_width, max_preview_height)
        crop_debug, _ = resize_with_scale(item.crop_debug, max_crop_width, max_crop_height)
        tile_width = max(preview.shape[1], crop_debug.shape[1]) + padding * 2
        tile_height = title_height + preview.shape[0] + crop_debug.shape[0] + padding * 3
        prepared.append((item, preview, preview_scale, crop_debug, tile_width, tile_height))

    rows = [prepared[index:index + columns] for index in range(0, len(prepared), columns)]
    column_widths = [
        max(row[column][4] for row in rows if column < len(row))
        for column in range(columns)
    ]
    row_heights = [max(tile[5] for tile in row) for row in rows]

    canvas_width = sum(column_widths) + gap * (columns + 1)
    canvas_height = sum(row_heights) + gap * (len(rows) + 1)
    canvas = np.full((canvas_height, canvas_width, 3), 28, dtype=np.uint8)
    hit_regions: dict[int, DashboardHitRegion] = {}

    cursor_y = gap
    for row_index, row in enumerate(rows):
        cursor_x = gap
        for column_index, tile in enumerate(row):
            item, preview, preview_scale, crop_debug, tile_width, tile_height = tile
            tile_left = cursor_x
            tile_top = cursor_y
            tile_right = tile_left + column_widths[column_index]
            tile_bottom = tile_top + row_heights[row_index]
            cv2.rectangle(canvas, (tile_left, tile_top), (tile_right - 1, tile_bottom - 1), (55, 55, 55), 1)
            cv2.putText(
                canvas,
                f"Camera {item.camera_index}",
                (tile_left + padding, tile_top + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (230, 230, 230),
                2,
                cv2.LINE_AA,
            )

            preview_x = tile_left + padding
            preview_y = tile_top + title_height + padding
            crop_x = tile_left + padding
            crop_y = preview_y + preview.shape[0] + padding
            paste_image(canvas, preview, preview_x, preview_y)
            paste_image(canvas, crop_debug, crop_x, crop_y)
            hit_regions[item.camera_index] = DashboardHitRegion(
                camera_index=item.camera_index,
                left=preview_x,
                top=preview_y,
                right=preview_x + preview.shape[1],
                bottom=preview_y + preview.shape[0],
                scale=preview_scale,
            )

            cursor_x += column_widths[column_index] + gap
        cursor_y += row_heights[row_index] + gap

    return canvas, hit_regions


def section_specs_signature(
    latest_analysis: ProcessedFrameAnalysis | None,
    section_specs: list[SectionSpec],
) -> tuple[int | None, tuple[tuple[str, Box], ...]]:
    analysis_id = id(latest_analysis) if latest_analysis is not None else None
    specs_signature = tuple(
        (spec.section_id, spec.box)
        for spec in section_specs
    )
    return (analysis_id, specs_signature)


def zone_from_index(section_index: int) -> str:
    if 0 <= section_index < 26:
        return chr(ord("A") + section_index)
    return f"Z{section_index + 1}"


def section_zone_labels(args: argparse.Namespace, camera_index: int, section_specs: list[SectionSpec]) -> dict[str, str]:
    section_zones = getattr(args, "section_zones", None) or {}
    camera_section_zones = section_zones.get(str(camera_index))
    zone_offsets = getattr(args, "zone_offsets", None) or {}
    zone_offset = zone_offsets.get(str(camera_index), 0)
    labels: dict[str, str] = {}
    for spec in section_specs:
        label = zone_from_index(spec.index + zone_offset)
        if camera_section_zones is not None and spec.index < len(camera_section_zones):
            configured_label = str(camera_section_zones[spec.index]).strip().upper()
            if configured_label:
                label = configured_label
        labels[spec.section_id] = label
    return labels


def initial_scan_boxes(
    args: argparse.Namespace,
    configured_section_boxes: list[Box] | None,
    frame_shape: tuple[int, ...],
) -> list[Box]:
    if configured_section_boxes is not None:
        return list(configured_section_boxes)
    return [spec.box for spec in divide_into_sections(frame_shape, args.sections, args.layout)]


def run_preview_loop(
    args: argparse.Namespace,
    processors: dict[int, ParkingLotProcessor],
    dispatcher: PlateUpdateDispatcher,
    camera_indexes: list[int],
    configured_section_boxes_by_camera: dict[int, list[Box] | None],
    settings_path: Path,
) -> int:
    captures = open_cameras(camera_indexes, args.camera_width, args.camera_height, args.camera_fps)
    states: dict[int, PreviewCameraState] = {}
    hit_regions: dict[int, DashboardHitRegion] = {}
    active_drag_camera: list[int | None] = [None]

    def map_dashboard_point(region: DashboardHitRegion, x: int, y: int) -> tuple[int, int]:
        frame_x = int(round((x - region.left) / region.scale))
        frame_y = int(round((y - region.top) / region.scale))
        return (frame_x, frame_y)

    def dashboard_mouse_callback(event: int, x: int, y: int, flags: int, userdata: object | None = None) -> None:
        camera_index = active_drag_camera[0]
        region = hit_regions.get(camera_index) if camera_index is not None else None

        if event == cv2.EVENT_LBUTTONDOWN:
            camera_index = None
            region = None
            for candidate_index, candidate_region in hit_regions.items():
                if (
                    candidate_region.left <= x < candidate_region.right
                    and candidate_region.top <= y < candidate_region.bottom
                ):
                    camera_index = candidate_index
                    region = candidate_region
                    active_drag_camera[0] = candidate_index
                    break

        if camera_index is None or region is None:
            return

        state = states.get(camera_index)
        if state is None:
            return

        frame_x, frame_y = map_dashboard_point(region, x, y)
        state.selector.mouse_callback(event, frame_x, frame_y, flags, userdata)
        if event == cv2.EVENT_LBUTTONUP:
            active_drag_camera[0] = None

    for camera_index in camera_indexes:
        selector = ScanAreaSelector()
        selector.set_max_boxes(args.sections)
        states[camera_index] = PreviewCameraState(
            processor=processors[camera_index],
            selector=selector,
        )

    cv2.namedWindow(WINDOW_NAME)
    cv2.setMouseCallback(WINDOW_NAME, dashboard_mouse_callback)

    worker_count = max(1, len(camera_indexes))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        try:
            while True:
                now = time.monotonic()
                dashboard_items: list[DashboardItem] = []
                for camera_index, capture in captures.items():
                    state = states[camera_index]
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        raise RuntimeError(f"Unable to read a frame from webcam index {camera_index}.")

                    state.selector.set_frame_shape(frame.shape)
                    if not state.selector_initialized:
                        state.selector.set_initial_boxes(
                            initial_scan_boxes(
                                args,
                                configured_section_boxes_by_camera.get(camera_index),
                                frame.shape,
                            )
                        )
                        state.selector_initialized = True

                    if state.selector.consume_changed():
                        state.processor.set_section_boxes(state.selector.boxes)
                        save_camera_section_boxes(settings_path, camera_index, state.selector.boxes)
                        state.scan_revision += 1
                        state.latest_error = None
                        state.last_submission_at = 0.0
                        if state.pending is not None and not state.pending.done():
                            state.pending.cancel()
                        state.pending = None
                        state.pending_revision = None
                        state.crop_debug_display = None
                        state.crop_debug_signature = None

                    if state.pending is not None and state.pending.done():
                        try:
                            analysis = state.pending.result()
                            if state.pending_revision == state.scan_revision:
                                try:
                                    dispatcher.emit(analysis, args.pretty)
                                except Exception as exc:  # pragma: no cover - live preview path
                                    print(f"Publish error: {exc}", file=sys.stderr)
                                state.latest_analysis = analysis
                                state.latest_error = None
                                state.last_completed_at = now
                        except Exception as exc:  # pragma: no cover - live preview path
                            if state.pending_revision == state.scan_revision:
                                state.latest_error = str(exc)
                        state.pending = None
                        state.pending_revision = None

                    if (
                        state.pending is None
                        and not state.selector.is_dragging
                        and now - state.last_submission_at >= args.interval
                    ):
                        state.pending = executor.submit(
                            process_webcam_frame,
                            state.processor,
                            frame.copy(),
                            camera_index,
                        )
                        state.pending_revision = state.scan_revision
                        state.last_submission_at = now

                    section_specs = state.processor.get_section_specs(frame.shape)
                    section_labels = section_zone_labels(args, camera_index, section_specs)
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
                        section_labels=section_labels,
                    )
                    crop_debug_signature = section_specs_signature(latest_analysis, section_specs)
                    if state.crop_debug_signature != crop_debug_signature or state.crop_debug_display is None:
                        state.crop_debug_display = draw_crop_debug_window(
                            processed_sections=latest_analysis.sections if latest_analysis is not None else [],
                            section_specs=section_specs,
                            section_labels=section_labels,
                        )
                        state.crop_debug_signature = crop_debug_signature
                    dashboard_items.append(
                        DashboardItem(
                            camera_index=camera_index,
                            preview=display,
                            crop_debug=state.crop_debug_display,
                        )
                    )

                dashboard_display, next_hit_regions = build_preview_dashboard(dashboard_items)
                hit_regions.clear()
                hit_regions.update(next_hit_regions)
                cv2.imshow(WINDOW_NAME, dashboard_display)

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    return 0
                if key == ord("c"):
                    for camera_index, state in states.items():
                        state.selector.clear()
                        state.processor.set_section_boxes(state.selector.boxes)
                        save_camera_section_boxes(settings_path, camera_index, state.selector.boxes)
                if key == ord("r"):
                    for camera_index, state in states.items():
                        state.selector.reset()
                        state.processor.set_section_boxes(state.selector.boxes)
                        save_camera_section_boxes(settings_path, camera_index, state.selector.boxes)
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
        configured_section_boxes_by_camera = resolve_configured_section_boxes(
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
            processors = build_processors(args, configured_section_boxes_by_camera, resolved_yolo_model, camera_indexes)
            return run_preview_loop(
                args,
                processors,
                dispatcher,
                camera_indexes,
                configured_section_boxes_by_camera,
                settings_path,
            )
        if args.loop:
            processors = build_processors(args, configured_section_boxes_by_camera, resolved_yolo_model, camera_indexes)
            return run_loop(args, processors, dispatcher, camera_indexes)
        run_once_camera_indexes = camera_indexes if args.webcam else [camera_indexes[0]]
        processors = build_processors(args, configured_section_boxes_by_camera, resolved_yolo_model, run_once_camera_indexes)
        return run_once(args, processors, dispatcher, run_once_camera_indexes)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
