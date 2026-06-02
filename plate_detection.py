from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from parking_types import PlateCandidate, SectionSpec


DEFAULT_YOLO_MODEL_CANDIDATES = (
    Path("models/license-plate-finetune-v1x.pt"),
    Path("models/license-plate-finetune-v1l.pt"),
    Path("models/license-plate-finetune-v1m.pt"),
    Path("models/license-plate-finetune-v1s.pt"),
    Path("models/license-plate-finetune-v1n.pt"),
)


def divide_into_sections(image_shape: tuple[int, int, int], count: int, layout: str) -> list[SectionSpec]:
    if count <= 0:
        raise ValueError("Section count must be greater than 0.")

    height, width = image_shape[:2]
    sections: list[SectionSpec] = []

    if layout == "columns":
        boundaries = np.linspace(0, width, count + 1, dtype=int)
        for index in range(count):
            x1 = int(boundaries[index])
            x2 = int(boundaries[index + 1])
            sections.append(SectionSpec(f"section-{index + 1}", index, (x1, 0, x2, height)))
        return sections

    boundaries = np.linspace(0, height, count + 1, dtype=int)
    for index in range(count):
        y1 = int(boundaries[index])
        y2 = int(boundaries[index + 1])
        sections.append(SectionSpec(f"section-{index + 1}", index, (0, y1, width, y2)))
    return sections


def resolve_default_yolo_model() -> Path | None:
    for candidate in DEFAULT_YOLO_MODEL_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    point_sums = points.sum(axis=1)
    point_diffs = np.diff(points, axis=1)
    ordered[0] = points[np.argmin(point_sums)]
    ordered[2] = points[np.argmax(point_sums)]
    ordered[1] = points[np.argmin(point_diffs)]
    ordered[3] = points[np.argmax(point_diffs)]
    return ordered


def warp_plate(image: np.ndarray, points: np.ndarray) -> np.ndarray | None:
    ordered = order_points(points.astype(np.float32))
    width_top = np.linalg.norm(ordered[1] - ordered[0])
    width_bottom = np.linalg.norm(ordered[2] - ordered[3])
    height_left = np.linalg.norm(ordered[3] - ordered[0])
    height_right = np.linalg.norm(ordered[2] - ordered[1])

    width = int(max(width_top, width_bottom))
    height = int(max(height_left, height_right))
    if width < 30 or height < 10:
        return None

    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(ordered, destination)
    warped = cv2.warpPerspective(image, transform, (width, height))
    return warped if warped.size else None


def rotate_image(image: np.ndarray, angle_degrees: float) -> np.ndarray:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cos_value = abs(matrix[0, 0])
    sin_value = abs(matrix[0, 1])
    bound_width = int((height * sin_value) + (width * cos_value))
    bound_height = int((height * cos_value) + (width * sin_value))
    matrix[0, 2] += (bound_width / 2) - center[0]
    matrix[1, 2] += (bound_height / 2) - center[1]
    return cv2.warpAffine(image, matrix, (bound_width, bound_height), borderValue=(255, 255, 255))


def crop_to_content(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresholded = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    points = cv2.findNonZero(thresholded)
    if points is None:
        return image
    x, y, width, height = cv2.boundingRect(points)
    cropped = image[y:y + height, x:x + width]
    return cropped if cropped.size else image


def normalize_plate_orientation(image: np.ndarray) -> np.ndarray:
    normalized = crop_to_content(image)
    if normalized.shape[0] > normalized.shape[1]:
        normalized = cv2.rotate(normalized, cv2.ROTATE_90_CLOCKWISE)
    return normalized


def find_rotated_plate_crop(image: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    blackhat_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, blackhat_kernel)
    grad_x = cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=3)
    grad_x = cv2.convertScaleAbs(grad_x)
    grad_x = cv2.GaussianBlur(grad_x, (5, 5), 0)
    _, thresholded = cv2.threshold(grad_x, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    mask = cv2.morphologyEx(thresholded, cv2.MORPH_CLOSE, close_kernel)
    mask = cv2.dilate(mask, None, iterations=1)
    mask = cv2.erode(mask, None, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])
    candidates: list[tuple[float, np.ndarray]] = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.05 or area > image_area * 0.98:
            continue

        rect = cv2.minAreaRect(contour)
        (_, _), (width, height), _ = rect
        if width <= 1 or height <= 1:
            continue

        long_side = max(width, height)
        short_side = min(width, height)
        ratio = long_side / short_side
        if ratio < 1.8 or ratio > 8.5:
            continue

        rect_area = width * height
        fill_ratio = area / rect_area if rect_area else 0.0
        if fill_ratio < 0.15:
            continue

        warped = warp_plate(image, cv2.boxPoints(rect))
        if warped is None:
            continue
        score = fill_ratio + (area / image_area) - (abs(ratio - 4.0) * 0.04)
        candidates.append((score, warped))

    if not candidates:
        return None
    return normalize_plate_orientation(max(candidates, key=lambda item: item[0])[1])


def rectify_plate_crop(image: np.ndarray) -> np.ndarray:
    rotated_crop = find_rotated_plate_crop(image)
    if rotated_crop is not None:
        return rotated_crop

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    edges = cv2.Canny(gray, 60, 180)
    points = cv2.findNonZero(edges)
    if points is None:
        return normalize_plate_orientation(image)

    rect = cv2.minAreaRect(points)
    angle = rect[2]
    width, height = rect[1]
    if width < height:
        angle += 90
    rotated = rotate_image(image, angle)
    return normalize_plate_orientation(rotated)


def expand_box(box: tuple[int, int, int, int], image_shape: tuple[int, int, int], margin_ratio: float = 0.08) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    height, width = image_shape[:2]
    pad_x = int((x2 - x1) * margin_ratio)
    pad_y = int((y2 - y1) * margin_ratio)
    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_y),
        min(width, x2 + pad_x),
        min(height, y2 + pad_y),
    )


def enhance_plate_image(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    upscaled = cv2.resize(enhanced, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    padded = cv2.copyMakeBorder(
        upscaled,
        18,
        18,
        28,
        28,
        borderType=cv2.BORDER_CONSTANT,
        value=255,
    )
    return cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)


class HeuristicPlateDetector:
    name = "heuristic"

    def detect(self, section_image: np.ndarray) -> PlateCandidate | None:
        gray = cv2.cvtColor(section_image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        blackhat_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, blackhat_kernel)

        grad_x = cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=3)
        grad_x = cv2.convertScaleAbs(grad_x)
        grad_x = cv2.GaussianBlur(grad_x, (5, 5), 0)
        _, thresholded = cv2.threshold(grad_x, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5))
        mask = cv2.morphologyEx(thresholded, cv2.MORPH_CLOSE, close_kernel)
        mask = cv2.erode(mask, None, iterations=1)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        section_area = float(section_image.shape[0] * section_image.shape[1])
        candidates: list[tuple[float, np.ndarray, tuple[int, int, int, int]]] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < section_area * 0.01 or area > section_area * 0.7:
                continue

            rect = cv2.minAreaRect(contour)
            (_, _), (width, height), _ = rect
            if width <= 1 or height <= 1:
                continue

            long_side = max(width, height)
            short_side = min(width, height)
            ratio = long_side / short_side
            if ratio < 2.0 or ratio > 6.5:
                continue

            rectangle_area = width * height
            fill_ratio = area / rectangle_area if rectangle_area else 0.0
            if fill_ratio < 0.2:
                continue

            box_points = cv2.boxPoints(rect)
            x, y, w, h = cv2.boundingRect(box_points.astype(np.int32))
            score = (area / section_area) + (fill_ratio * 0.5) - (abs(ratio - 4.0) * 0.05)
            candidates.append((score, box_points.astype(np.float32), (x, y, x + w, y + h)))

        if not candidates:
            return None

        for score, box_points, bounds in sorted(candidates, key=lambda item: item[0], reverse=True):
            warped = warp_plate(section_image, box_points)
            if warped is None:
                continue
            return PlateCandidate(rectify_plate_crop(warped), bounds, score, self.name)
        return None


class YoloPlateDetector:
    name = "yolo"

    def __init__(self, model_path: str | Path, confidence: float = 0.25, image_size: int = 640) -> None:
        self.model_path = Path(model_path)
        self.confidence = confidence
        self.image_size = image_size
        self._model = self._load_model()

    def _load_model(self):
        if not self.model_path.exists():
            raise RuntimeError(f"YOLO model not found: {self.model_path}")
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError(
                "Ultralytics is not installed. Run `pip install -r requirements.txt` "
                "or use `--detector heuristic`."
            ) from exc
        return YOLO(str(self.model_path))

    @staticmethod
    def _clip_box(
        box: tuple[int, int, int, int],
        image_shape: tuple[int, int, int],
    ) -> tuple[int, int, int, int] | None:
        x1, y1, x2, y2 = box
        image_height, image_width = image_shape[:2]
        clipped = (
            max(0, min(image_width, x1)),
            max(0, min(image_height, y1)),
            max(0, min(image_width, x2)),
            max(0, min(image_height, y2)),
        )
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            return None
        return clipped

    def _predict_ranked_boxes_with_confidence(
        self,
        image: np.ndarray,
        confidence: float,
    ) -> list[tuple[float, tuple[int, int, int, int]]]:
        results = self._model.predict(
            source=image,
            conf=confidence,
            imgsz=self.image_size,
            verbose=False,
        )
        if not results:
            return []

        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []

        ranked: list[tuple[float, tuple[int, int, int, int]]] = []
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            x1 = int(xyxy[0])
            y1 = int(xyxy[1])
            x2 = int(xyxy[2])
            y2 = int(xyxy[3])
            expanded = expand_box((x1, y1, x2, y2), image.shape)
            clipped = self._clip_box(expanded, image.shape)
            if clipped is None:
                continue
            confidence = float(box.conf[0].item()) if hasattr(box.conf[0], "item") else float(box.conf[0])
            ranked.append((confidence, clipped))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    @staticmethod
    def _enhance_for_detection(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    def _predict_ranked_boxes_adaptive(self, image: np.ndarray) -> list[tuple[float, tuple[int, int, int, int]]]:
        ranked = self._predict_ranked_boxes_with_confidence(image, self.confidence)
        if ranked:
            return ranked

        fallback_conf = max(0.12, self.confidence * 0.6)
        if fallback_conf < self.confidence:
            ranked = self._predict_ranked_boxes_with_confidence(image, fallback_conf)
            if ranked:
                return ranked

        # Last pass: boost contrast for low-contrast/off-axis plates.
        enhanced = self._enhance_for_detection(image)
        return self._predict_ranked_boxes_with_confidence(enhanced, fallback_conf)

    @staticmethod
    def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        width = ix2 - ix1
        height = iy2 - iy1
        if width <= 0 or height <= 0:
            return 0
        return width * height

    def detect_sections(
        self,
        frame: np.ndarray,
        section_specs: list[SectionSpec],
    ) -> dict[str, PlateCandidate]:
        ranked_boxes = self._predict_ranked_boxes_adaptive(frame)
        if not ranked_boxes or not section_specs:
            return {}

        best_per_section: dict[str, tuple[float, tuple[int, int, int, int]]] = {}
        for score, absolute_box in ranked_boxes:
            best_section_id: str | None = None
            best_overlap = 0
            for spec in section_specs:
                overlap = self._intersection_area(absolute_box, spec.box)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_section_id = spec.section_id
            if best_section_id is None or best_overlap == 0:
                continue
            current = best_per_section.get(best_section_id)
            if current is None or score > current[0]:
                best_per_section[best_section_id] = (score, absolute_box)

        section_lookup = {spec.section_id: spec for spec in section_specs}
        detected_sections: dict[str, PlateCandidate] = {}
        for section_id, (score, absolute_box) in best_per_section.items():
            x1, y1, x2, y2 = absolute_box
            spec = section_lookup[section_id]
            sx1, sy1, sx2, sy2 = spec.box
            clamped_box = (
                max(x1, sx1),
                max(y1, sy1),
                min(x2, sx2),
                min(y2, sy2),
            )
            if clamped_box[2] <= clamped_box[0] or clamped_box[3] <= clamped_box[1]:
                continue
            cx1, cy1, cx2, cy2 = clamped_box
            crop = frame[cy1:cy2, cx1:cx2].copy()
            if crop.size == 0:
                continue
            relative_box = (
                clamped_box[0] - sx1,
                clamped_box[1] - sy1,
                clamped_box[2] - sx1,
                clamped_box[3] - sy1,
            )
            detected_sections[section_id] = PlateCandidate(
                rectify_plate_crop(crop),
                relative_box,
                score,
                self.name,
            )
        return detected_sections

    def detect(self, section_image: np.ndarray) -> PlateCandidate | None:
        for confidence, expanded_box in self._predict_ranked_boxes_adaptive(section_image):
            ex1, ey1, ex2, ey2 = expanded_box
            crop = section_image[ey1:ey2, ex1:ex2].copy()
            if crop.size == 0:
                continue
            return PlateCandidate(
                rectify_plate_crop(crop),
                expanded_box,
                confidence,
                self.name,
            )
        return None


def create_plate_detector(
    detector_name: str,
    yolo_model_path: str | Path | None,
    yolo_confidence: float,
    yolo_image_size: int,
):
    if detector_name == "yolo":
        resolved_model = Path(yolo_model_path) if yolo_model_path is not None else resolve_default_yolo_model()
        if resolved_model is None:
            raise RuntimeError("`--detector yolo` requires `--yolo-model PATH` or a default model in `models/`.")
        return YoloPlateDetector(resolved_model, yolo_confidence, yolo_image_size)
    return HeuristicPlateDetector()
