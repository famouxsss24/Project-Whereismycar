from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from parking_types import ProcessedSectionResult, SectionSpec


WINDOW_NAME = "Parking OCR Preview"
CROP_WINDOW_NAME = "Parking OCR Crop Debug"


@lru_cache(maxsize=8)
def load_overlay_font(size: int):
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        windir / "Fonts" / "malgun.ttf",
        windir / "Fonts" / "malgunsl.ttf",
        windir / "Fonts" / "batang.ttc",
        windir / "Fonts" / "gulim.ttc",
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def draw_text_panel(frame: np.ndarray, lines: list[tuple[str, int, tuple[int, int, int]]]) -> np.ndarray:
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image, "RGBA")
    padding = 14
    line_gap = 8
    x = 20
    y = 18

    metrics: list[tuple[str, object, tuple[int, int, int], int, int]] = []
    max_width = 0
    total_height = 0
    for text, font_size, color in lines:
        font = load_overlay_font(font_size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        width = right - left
        height = bottom - top
        metrics.append((text, font, color, width, height))
        max_width = max(max_width, width)
        total_height += height + line_gap

    panel_bottom = y + total_height + padding - line_gap
    draw.rounded_rectangle(
        (x - padding, y - padding, x + max_width + padding, panel_bottom),
        fill=(10, 10, 10, 185),
        radius=14,
    )

    cursor_y = y
    for text, font, color, _, height in metrics:
        draw.text((x, cursor_y), text, fill=color, font=font)
        cursor_y += height + line_gap

    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    return f"{seconds:.1f}s ago"


def preview_lines_from_payload(
    payload: dict[str, object] | None,
    pending: bool,
    last_completed_at: float | None,
    latest_error: str | None,
) -> list[tuple[str, int, tuple[int, int, int]]]:
    status = "Scanning..." if pending else "Ready"
    lines: list[tuple[str, int, tuple[int, int, int]]] = [(f"Status: {status}", 28, (255, 255, 255))]

    if payload is None:
        lines.append(("No OCR result yet", 24, (255, 220, 120)))
    else:
        for section in payload["sections"]:
            section_id = section["section_id"]
            plate_text = section["plate_text"]
            valid_plate = bool(section["valid_plate"])
            occupied = bool(section["occupied"])
            confidence = float(section["confidence"])
            detector_name = section.get("detector", "unknown")
            if valid_plate and plate_text:
                text = f"{section_id}: {plate_text} ({confidence:.2f}) [{detector_name}]"
                color = (115, 235, 140)
            elif occupied and plate_text:
                text = f"{section_id}: OCR {plate_text} ({confidence:.2f}) [{detector_name}]"
                color = (255, 220, 120)
            elif occupied:
                text = f"{section_id}: plate candidate found [{detector_name}]"
                color = (255, 220, 120)
            else:
                text = f"{section_id}: empty"
                color = (220, 220, 220)
            lines.append((text, 24, color))

    lines.append((f"Last OCR: {format_elapsed(last_completed_at)}", 20, (220, 220, 220)))
    lines.append(("Press q or Esc to quit.", 20, (220, 220, 220)))
    if latest_error:
        lines.append((f"Error: {latest_error}", 20, (255, 140, 140)))
    return lines


def draw_preview_frame(
    frame: np.ndarray,
    section_specs: list[SectionSpec],
    payload: dict[str, object] | None,
    pending: bool,
    last_completed_at: float | None,
    latest_error: str | None,
) -> np.ndarray:
    display = frame.copy()
    payload_sections: dict[str, dict[str, object]] = {}

    if payload is not None:
        payload_sections = {
            section["section_id"]: section
            for section in payload["sections"]
        }

    for spec in section_specs:
        section_data = payload_sections.get(spec.section_id)
        x1, y1, x2, y2 = spec.box
        if section_data is None:
            color = (180, 180, 180)
        elif section_data["valid_plate"]:
            color = (90, 220, 90)
        elif section_data["occupied"]:
            color = (70, 170, 255)
        else:
            color = (180, 180, 180)

        cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
        if section_data and section_data["plate_box"]:
            plate_box = section_data["plate_box"]
            cv2.rectangle(
                display,
                (plate_box["x1"], plate_box["y1"]),
                (plate_box["x2"], plate_box["y2"]),
                color,
                2,
            )

    return draw_text_panel(display, preview_lines_from_payload(payload, pending, last_completed_at, latest_error))


def resize_to_fit(image: np.ndarray, max_width: int, max_height: int) -> np.ndarray:
    height, width = image.shape[:2]
    if height == 0 or width == 0:
        return np.zeros((max_height, max_width, 3), dtype=np.uint8)

    scale = min(max_width / width, max_height / height)
    new_width = max(1, int(width * scale))
    new_height = max(1, int(height * scale))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(image, (new_width, new_height), interpolation=interpolation)


def make_crop_panel(
    processed_section: ProcessedSectionResult | None,
    section_id: str,
    panel_width: int = 360,
    panel_height: int = 260,
) -> np.ndarray:
    panel = np.full((panel_height, panel_width, 3), 24, dtype=np.uint8)
    content_top = 70
    content_height = panel_height - content_top - 16
    content_width = panel_width - 24

    section_view = np.full((content_height, content_width, 3), 36, dtype=np.uint8)
    text_color = (220, 220, 220)
    text_line = f"{section_id}: empty"

    if processed_section is not None:
        result = processed_section.result
        detector_name = result.detector
        if processed_section.rectified_plate is not None:
            section_view = processed_section.rectified_plate.copy()
        if result.valid_plate and result.plate_text:
            text_color = (115, 235, 140)
            text_line = f"{section_id}: {result.plate_text} ({result.confidence:.2f}) [{detector_name}]"
        elif result.occupied and result.plate_text:
            text_color = (255, 220, 120)
            text_line = f"{section_id}: OCR {result.plate_text} ({result.confidence:.2f}) [{detector_name}]"
        elif result.occupied:
            text_color = (255, 220, 120)
            text_line = f"{section_id}: candidate found [{detector_name}]"

    fitted = resize_to_fit(section_view, content_width, content_height)
    fit_height, fit_width = fitted.shape[:2]
    x_offset = (panel_width - fit_width) // 2
    y_offset = content_top + (content_height - fit_height) // 2
    panel[y_offset:y_offset + fit_height, x_offset:x_offset + fit_width] = fitted

    lines = [
        (f"Crop Debug: {section_id}", 22, (255, 255, 255)),
        (text_line, 20, text_color),
    ]
    return draw_text_panel(panel, lines)


def draw_crop_debug_window(
    processed_sections: list[ProcessedSectionResult],
    section_specs: list[SectionSpec],
) -> np.ndarray:
    section_map = {item.result.section_id: item for item in processed_sections}

    panels = []
    for spec in section_specs:
        panels.append(make_crop_panel(section_map.get(spec.section_id), spec.section_id))

    if not panels:
        return np.zeros((260, 360, 3), dtype=np.uint8)
    return np.hstack(panels)
