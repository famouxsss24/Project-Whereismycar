from __future__ import annotations

from dataclasses import dataclass

import numpy as np


Box = tuple[int, int, int, int]


def box_to_dict(box: Box) -> dict[str, int]:
    x1, y1, x2, y2 = box
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


@dataclass(frozen=True)
class SectionSpec:
    section_id: str
    index: int
    box: Box


@dataclass
class PlateCandidate:
    image: np.ndarray
    box: Box
    detection_score: float
    detector: str


@dataclass(frozen=True)
class SectionResult:
    section_id: str
    section_index: int
    occupied: bool
    plate_found: bool
    plate_text: str | None
    confidence: float
    ocr_source: str
    valid_plate: bool
    section_box: Box
    plate_box: Box | None
    detector: str
    detection_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "section_index": self.section_index,
            "occupied": self.occupied,
            "plate_found": self.plate_found,
            "plate_text": self.plate_text,
            "confidence": round(self.confidence, 4),
            "ocr_source": self.ocr_source,
            "valid_plate": self.valid_plate,
            "section_box": box_to_dict(self.section_box),
            "plate_box": box_to_dict(self.plate_box) if self.plate_box else None,
            "detector": self.detector,
            "detection_score": round(self.detection_score, 4),
        }


@dataclass(frozen=True)
class ProcessedFrameResult:
    frame: np.ndarray
    analysis: ProcessedFrameAnalysis


@dataclass(frozen=True)
class ProcessedSectionResult:
    result: SectionResult
    rectified_plate: np.ndarray | None


@dataclass(frozen=True)
class ProcessedFrameAnalysis:
    payload: dict[str, object]
    sections: list[ProcessedSectionResult]
