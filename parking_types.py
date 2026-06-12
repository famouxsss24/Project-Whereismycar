from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


Box = tuple[int, int, int, int]
SECTION_NAME_PATTERN = re.compile(r"^[a-z]+$")


def section_name_from_index(index: int) -> str:
    if index < 0:
        raise ValueError("Section index must be >= 0.")

    name = ""
    current = index
    while True:
        current, remainder = divmod(current, 26)
        name = chr(ord("a") + remainder) + name
        if current == 0:
            return name
        current -= 1


def normalize_section_name(value: str, key: str = "section name") -> str:
    normalized = value.strip().lower()
    if not SECTION_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(f"{key} must contain only lowercase letters a-z.")
    return normalized


def box_to_dict(box: Box) -> dict[str, int]:
    x1, y1, x2, y2 = box
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


@dataclass(frozen=True)
class ScanArea:
    name: str
    box: Box


@dataclass(frozen=True)
class SectionSpec:
    section_id: str
    index: int
    box: Box
    section_name: str | None = None

    @property
    def display_name(self) -> str:
        return self.section_name or self.section_id


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
    section_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        section_name = self.section_name or self.section_id
        return {
            "section_id": self.section_id,
            "section_name": section_name,
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
class ProcessedSectionResult:
    result: SectionResult
    section_image: np.ndarray | None
    rectified_plate: np.ndarray | None


@dataclass(frozen=True)
class ProcessedFrameAnalysis:
    payload: dict[str, object]
    sections: list[ProcessedSectionResult]
