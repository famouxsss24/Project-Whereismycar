from __future__ import annotations

import threading
from datetime import datetime, timezone

import numpy as np

from parking_types import PlateCandidate, ProcessedFrameAnalysis, ProcessedSectionResult, SectionResult, SectionSpec
from plate_detection import HeuristicPlateDetector, create_plate_detector, divide_into_sections, enhance_plate_image, expand_box
from plate_ocr import PlateReader, is_valid_korean_plate


class ParkingLotProcessor:
    def __init__(
        self,
        section_count: int = 3,
        layout: str = "columns",
        section_boxes: list[tuple[int, int, int, int]] | None = None,
        detector_name: str = "heuristic",
        yolo_model_path: str | None = None,
        yolo_confidence: float = 0.25,
        yolo_image_size: int = 640,
        allow_yolo_fallback: bool = True,
    ) -> None:
        self._custom_section_boxes = None if section_boxes is None else tuple(section_boxes)
        self.section_count = len(self._custom_section_boxes) if self._custom_section_boxes is not None else section_count
        self.layout = "custom" if self._custom_section_boxes is not None else layout
        self.reader = PlateReader()
        self.detector = create_plate_detector(
            detector_name=detector_name,
            yolo_model_path=yolo_model_path,
            yolo_confidence=yolo_confidence,
            yolo_image_size=yolo_image_size,
        )
        self.fallback_detector = HeuristicPlateDetector() if detector_name == "yolo" and allow_yolo_fallback else None
        self._section_cache: dict[
            tuple[tuple[int, ...], int, str, tuple[tuple[int, int, int, int], ...] | None],
            list[SectionSpec],
        ] = {}
        self._section_lock = threading.RLock()

    @property
    def detector_name(self) -> str:
        return self.detector.name

    def uses_custom_section_boxes(self) -> bool:
        with self._section_lock:
            return self._custom_section_boxes is not None

    def set_section_boxes(self, section_boxes: list[tuple[int, int, int, int]] | tuple[tuple[int, int, int, int], ...]) -> None:
        with self._section_lock:
            self._custom_section_boxes = tuple(section_boxes)
            self.section_count = len(self._custom_section_boxes)
            self.layout = "custom"
            self._section_cache.clear()

    def _build_custom_section_specs(self, image_shape: tuple[int, ...]) -> list[SectionSpec]:
        height, width = image_shape[:2]
        specs: list[SectionSpec] = []
        for index, box in enumerate(self._custom_section_boxes):
            x1, y1, x2, y2 = box
            if x1 < 0 or y1 < 0:
                raise ValueError(f"Section box #{index + 1} has negative coordinates: {(x1, y1, x2, y2)}")
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"Section box #{index + 1} has invalid size: {(x1, y1, x2, y2)}")
            if x2 > width or y2 > height:
                raise ValueError(
                    f"Section box #{index + 1} is out of frame bounds "
                    f"{(width, height)}: {(x1, y1, x2, y2)}"
                )
            specs.append(SectionSpec(f"section-{index + 1}", index, box))
        return specs

    def get_section_specs(self, image_shape: tuple[int, ...]) -> list[SectionSpec]:
        with self._section_lock:
            cache_key = (image_shape, self.section_count, self.layout, self._custom_section_boxes)
            if cache_key not in self._section_cache:
                if self._custom_section_boxes is not None:
                    self._section_cache[cache_key] = self._build_custom_section_specs(image_shape)
                else:
                    self._section_cache[cache_key] = divide_into_sections(image_shape, self.section_count, self.layout)
            return self._section_cache[cache_key]

    def _read_plate_candidate(self, candidate_image: np.ndarray):
        primary = self.reader.read_plate_from_image(candidate_image)
        if primary.plate is not None and is_valid_korean_plate(primary.plate) and primary.confidence >= 0.85:
            return primary

        enhanced = self.reader.read_plate_from_image(enhance_plate_image(candidate_image))
        if primary.plate is not None and is_valid_korean_plate(primary.plate):
            enhanced_is_valid = enhanced.plate is not None and is_valid_korean_plate(enhanced.plate)
            if not enhanced_is_valid:
                return primary
            return primary if primary.confidence >= enhanced.confidence else enhanced
        if enhanced.plate is not None and is_valid_korean_plate(enhanced.plate):
            return enhanced
        return primary if primary.confidence >= enhanced.confidence else enhanced

    def _empty_section(self, spec: SectionSpec) -> ProcessedSectionResult:
        return ProcessedSectionResult(
            result=SectionResult(
                section_id=spec.section_id,
                section_index=spec.index,
                occupied=False,
                plate_found=False,
                plate_text=None,
                confidence=0.0,
                ocr_source="none",
                valid_plate=False,
                section_box=spec.box,
                plate_box=None,
                detector=self.detector_name,
                detection_score=0.0,
            ),
            rectified_plate=None,
        )

    def _section_from_candidate(self, spec: SectionSpec, candidate) -> ProcessedSectionResult:
        if candidate is None:
            return self._empty_section(spec)

        x1, y1, _, _ = spec.box
        ocr_result = self._read_plate_candidate(candidate.image)
        valid_plate = bool(ocr_result.plate and is_valid_korean_plate(ocr_result.plate))
        relative_box = candidate.box
        plate_box = (
            x1 + relative_box[0],
            y1 + relative_box[1],
            x1 + relative_box[2],
            y1 + relative_box[3],
        )
        return ProcessedSectionResult(
            result=SectionResult(
                section_id=spec.section_id,
                section_index=spec.index,
                occupied=True,
                plate_found=True,
                plate_text=ocr_result.plate,
                confidence=ocr_result.confidence,
                ocr_source=ocr_result.source,
                valid_plate=valid_plate,
                section_box=spec.box,
                plate_box=plate_box,
                detector=candidate.detector,
                detection_score=candidate.detection_score,
            ),
            rectified_plate=candidate.image,
        )

    def process_section(self, frame: np.ndarray, spec: SectionSpec) -> ProcessedSectionResult:
        x1, y1, x2, y2 = spec.box
        section_image = frame[y1:y2, x1:x2]
        candidate = self.detector.detect(section_image)
        if candidate is None:
            candidate = self._detect_fallback_candidate(frame, spec)
        return self._section_from_candidate(spec, candidate)

    def _detect_fallback_candidate(self, frame: np.ndarray, spec: SectionSpec) -> PlateCandidate | None:
        if self.fallback_detector is None:
            return None

        if self.uses_custom_section_boxes():
            x1, y1, x2, y2 = spec.box
            return self.fallback_detector.detect(frame[y1:y2, x1:x2])

        ex1, ey1, ex2, ey2 = expand_box(spec.box, frame.shape, margin_ratio=0.18)
        expanded_image = frame[ey1:ey2, ex1:ex2]
        fallback_candidate = self.fallback_detector.detect(expanded_image)
        if fallback_candidate is None:
            return None

        fx1, fy1, fx2, fy2 = fallback_candidate.box
        absolute_box = (ex1 + fx1, ey1 + fy1, ex1 + fx2, ey1 + fy2)
        sx1, sy1, sx2, sy2 = spec.box
        clamped_box = (
            max(absolute_box[0], sx1),
            max(absolute_box[1], sy1),
            min(absolute_box[2], sx2),
            min(absolute_box[3], sy2),
        )
        if clamped_box[2] <= clamped_box[0] or clamped_box[3] <= clamped_box[1]:
            return None

        relative_box = (
            clamped_box[0] - sx1,
            clamped_box[1] - sy1,
            clamped_box[2] - sx1,
            clamped_box[3] - sy1,
        )
        return PlateCandidate(
            image=fallback_candidate.image,
            box=relative_box,
            detection_score=fallback_candidate.detection_score,
            detector=fallback_candidate.detector,
        )

    def process_frame(self, frame: np.ndarray, source_kind: str, source_value: str) -> ProcessedFrameAnalysis:
        sections = self.get_section_specs(frame.shape)
        detect_sections = getattr(self.detector, "detect_sections", None)
        use_batch_detection = callable(detect_sections) and not self.uses_custom_section_boxes()
        yolo_candidates = detect_sections(frame, sections) if use_batch_detection else {}

        processed_sections = []
        for spec in sections:
            if use_batch_detection:
                candidate = yolo_candidates.get(spec.section_id)
                if candidate is None:
                    candidate = self._detect_fallback_candidate(frame, spec)
                processed_sections.append(self._section_from_candidate(spec, candidate))
                continue
            processed_sections.append(self.process_section(frame, spec))
        results = [item.result for item in processed_sections]
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": {"kind": source_kind, "value": source_value},
            "section_count": self.section_count,
            "layout": self.layout,
            "detector": self.detector_name,
            "sections": [result.to_dict() for result in results],
        }
        return ProcessedFrameAnalysis(payload=payload, sections=processed_sections)
