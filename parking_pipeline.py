from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from parking_processor import ParkingLotProcessor
from parking_types import ProcessedFrameResult
from plate_detection import resolve_default_yolo_model
from plate_ocr import load_image
from preview_windows import CROP_WINDOW_NAME, WINDOW_NAME, draw_crop_debug_window, draw_preview_frame
from transport import emit_payload


def open_camera(camera_index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if os.name == "nt" and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
    capture = cv2.VideoCapture(camera_index, backend)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open webcam index {camera_index}.")
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def capture_webcam_frame(camera_index: int) -> np.ndarray:
    capture = open_camera(camera_index)
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


def process_webcam_frame(
    processor: ParkingLotProcessor,
    frame: np.ndarray,
    camera_index: int,
    server_url: str | None,
    timeout: float,
    pretty: bool,
) -> ProcessedFrameResult:
    analysis = processor.process_frame(frame, "webcam", str(camera_index))
    emit_payload(analysis.payload, server_url, timeout, pretty)
    return ProcessedFrameResult(frame=frame, analysis=analysis)


def build_parser() -> argparse.ArgumentParser:
    default_model = resolve_default_yolo_model()
    default_model_help = f" Auto-detected default: {default_model}." if default_model is not None else ""

    parser = argparse.ArgumentParser(
        description="Split a parking image into sections, detect and OCR license plates, and return JSON.",
    )
    parser.add_argument("image_path", nargs="?", help="Path to an image to process.")
    parser.add_argument("--webcam", action="store_true", help="Capture frames from a webcam instead of an image.")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index. Default: 0.")
    parser.add_argument("--sections", type=int, default=3, help="Number of parking sections. Default: 3.")
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
    parser.add_argument("--timeout", type=float, default=10.0, help="POST timeout in seconds. Default: 10.")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between webcam OCR runs. Default: 1.")
    parser.add_argument("--loop", action="store_true", help="Continuously process webcam frames.")
    parser.add_argument("--preview", action="store_true", help="Show live preview and crop debug windows.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    return parser


def run_once(args: argparse.Namespace, processor: ParkingLotProcessor) -> int:
    if args.webcam:
        frame = capture_webcam_frame(args.camera)
        payload = processor.process_frame(frame, "webcam", str(args.camera)).payload
    else:
        image_path = Path(args.image_path)
        if not image_path.exists():
            print(f"Image not found: {image_path}", file=sys.stderr)
            return 1
        payload = processor.process_frame(load_image(image_path), "image", str(image_path)).payload

    emit_payload(payload, args.server_url, args.timeout, args.pretty)
    return 0


def run_loop(args: argparse.Namespace, processor: ParkingLotProcessor) -> int:
    capture = open_camera(args.camera)
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError("Unable to read a frame from the webcam.")
            analysis = processor.process_frame(frame, "webcam", str(args.camera))
            emit_payload(analysis.payload, args.server_url, args.timeout, args.pretty)
            time.sleep(args.interval)
    finally:
        capture.release()


def run_preview_loop(args: argparse.Namespace, processor: ParkingLotProcessor) -> int:
    capture = open_camera(args.camera)
    latest_result: ProcessedFrameResult | None = None
    latest_error: str | None = None
    last_completed_at: float | None = None
    last_submission_at = 0.0
    pending_frame: np.ndarray | None = None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        pending: concurrent.futures.Future[ProcessedFrameResult] | None = None
        try:
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise RuntimeError("Unable to read a frame from the webcam.")

                now = time.monotonic()
                if pending is not None and pending.done():
                    try:
                        latest_result = pending.result()
                        latest_error = None
                        last_completed_at = now
                    except Exception as exc:  # pragma: no cover - live preview path
                        latest_error = str(exc)
                    pending = None
                    pending_frame = None

                if pending is None and now - last_submission_at >= args.interval:
                    pending_frame = frame.copy()
                    pending = executor.submit(
                        process_webcam_frame,
                        processor,
                        pending_frame,
                        args.camera,
                        args.server_url,
                        args.timeout,
                        args.pretty,
                    )
                    last_submission_at = now

                section_specs = processor.get_section_specs(frame.shape)
                latest_analysis = latest_result.analysis if latest_result is not None else None
                latest_payload = latest_analysis.payload if latest_analysis is not None else None
                display = draw_preview_frame(
                    frame=frame,
                    section_specs=section_specs,
                    payload=latest_payload,
                    pending=pending is not None,
                    last_completed_at=None if last_completed_at is None else now - last_completed_at,
                    latest_error=latest_error,
                )
                crop_debug_display = draw_crop_debug_window(
                    processed_sections=latest_analysis.sections if latest_analysis is not None else [],
                    section_specs=section_specs,
                )
                cv2.imshow(WINDOW_NAME, display)
                cv2.imshow(CROP_WINDOW_NAME, crop_debug_display)

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    return 0
        finally:
            capture.release()
            cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.webcam and args.image_path:
        parser.error("Choose an image path or --webcam, not both.")
    if not args.webcam and not args.image_path:
        parser.error("Provide an IMAGE_PATH or use --webcam.")
    if args.loop and not args.webcam:
        parser.error("--loop requires --webcam.")
    if args.preview and not args.webcam:
        parser.error("--preview requires --webcam.")
    if args.sections <= 0:
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

    resolved_yolo_model = resolve_yolo_model_argument(args.detector, args.yolo_model)
    if args.detector == "yolo" and resolved_yolo_model is None:
        parser.error("--detector yolo requires --yolo-model or a supported default model in `models/`.")

    try:
        processor = ParkingLotProcessor(
            section_count=args.sections,
            layout=args.layout,
            detector_name=args.detector,
            yolo_model_path=resolved_yolo_model,
            yolo_confidence=args.yolo_conf,
            yolo_image_size=args.yolo_imgsz,
            allow_yolo_fallback=not args.yolo_only,
        )
        if args.preview:
            return run_preview_loop(args, processor)
        if args.loop:
            return run_loop(args, processor)
        return run_once(args, processor)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
