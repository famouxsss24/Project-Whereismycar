from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np


REGIONS = (
    "\uC11C\uC6B8",
    "\uBD80\uC0B0",
    "\uB300\uAD6C",
    "\uC778\uCC9C",
    "\uAD11\uC8FC",
    "\uB300\uC804",
    "\uC6B8\uC0B0",
    "\uC138\uC885",
    "\uACBD\uAE30",
    "\uAC15\uC6D0",
    "\uCDA9\uBD81",
    "\uCDA9\uB0A8",
    "\uC804\uBD81",
    "\uC804\uB0A8",
    "\uACBD\uBD81",
    "\uACBD\uB0A8",
    "\uC81C\uC8FC",
)
REGION_ALT = "|".join(REGIONS)
MODERN_PATTERN = re.compile(r"^\d{2,3}[\uAC00-\uD7A3]\d{4}$")
REGIONAL_PATTERN = re.compile(rf"^(?:{REGION_ALT})\d{{2}}[\uAC00-\uD7A3]\d{{4}}$")
TAIL_PATTERN = re.compile(r"\d{2,3}[\uAC00-\uD7A3]\d{4}")
KEEP_TEXT_PATTERN = re.compile(r"[^\d\u3131-\u318E\uAC00-\uD7A3]+")


@dataclass(frozen=True)
class OCRFragment:
    text: str
    score: float
    source: str


@dataclass(frozen=True)
class PlateResult:
    plate: str | None
    confidence: float
    source: str


@contextlib.contextmanager
def suppress_native_output() -> Iterable[None]:
    """Hide native OCR library output during model initialization."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
        yield
    finally:
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)
        os.close(devnull_fd)


def clean_text(text: str) -> str:
    return KEEP_TEXT_PATTERN.sub("", text.strip())


def is_valid_korean_plate(text: str) -> bool:
    return bool(MODERN_PATTERN.fullmatch(text) or REGIONAL_PATTERN.fullmatch(text))


def load_image(image_path: str | Path) -> np.ndarray:
    path = Path(image_path)
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Unable to decode image: {path}")
    return image


class PlateReader:
    def __init__(self) -> None:
        self._ocr = self._build_ocr()
        self._prediction_cache: OrderedDict[str, list[OCRFragment]] = OrderedDict()
        self._prediction_cache_size = 128

    @staticmethod
    def _build_ocr():
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        try:
            with suppress_native_output():
                from paddleocr import PaddleOCR

                try:
                    return PaddleOCR(
                        lang="korean",
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                except TypeError:
                    # Backward compatibility for PaddleOCR versions that do not support these options.
                    return PaddleOCR(lang="korean")
        except Exception as exc:  # pragma: no cover - surfaced in CLI mode
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            raise RuntimeError(
                "PaddleOCR could not be initialized. "
                "Use Python 3.12 with `pip install -r requirements.txt`. "
                f"Current interpreter: {version}."
            ) from exc

    @staticmethod
    def _image_cache_key(image: np.ndarray) -> str:
        if image.size == 0:
            return "empty"
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        max_dim = 160
        height, width = gray.shape[:2]
        largest_side = max(height, width)
        if largest_side > max_dim:
            scale = max_dim / float(largest_side)
            gray = cv2.resize(
                gray,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        digest = hashlib.blake2b(gray.tobytes(), digest_size=12).hexdigest()
        resized_height, resized_width = gray.shape[:2]
        return f"{resized_width}x{resized_height}:{digest}"

    def _cache_get(self, key: str) -> list[OCRFragment] | None:
        cached = self._prediction_cache.get(key)
        if cached is None:
            return None
        self._prediction_cache.move_to_end(key)
        return cached

    def _cache_set(self, key: str, value: list[OCRFragment]) -> None:
        self._prediction_cache[key] = value
        self._prediction_cache.move_to_end(key)
        while len(self._prediction_cache) > self._prediction_cache_size:
            self._prediction_cache.popitem(last=False)

    def _predict_fragments(self, image: np.ndarray, source: str) -> list[OCRFragment]:
        cache_key = self._image_cache_key(image)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            predictions = self._ocr.predict(image)
        except Exception:
            return []

        fragments: list[OCRFragment] = []
        for item in predictions:
            texts = item.get("rec_texts", [])
            scores = item.get("rec_scores", [])
            for text, score in zip(texts, scores):
                cleaned = clean_text(text)
                if cleaned:
                    fragments.append(OCRFragment(cleaned, float(score), source))
        self._cache_set(cache_key, fragments)
        return fragments

    @staticmethod
    def _candidate_sequences(fragments: list[OCRFragment]) -> list[tuple[str, float]]:
        if not fragments:
            return []

        texts = [fragment.text for fragment in fragments]
        scores = [fragment.score for fragment in fragments]
        sequences = [("".join(texts), sum(scores) / len(scores))]

        max_span = min(4, len(fragments))
        for start in range(len(fragments)):
            for end in range(start + 1, min(len(fragments), start + max_span) + 1):
                candidate = "".join(texts[start:end])
                average_score = sum(scores[start:end]) / (end - start)
                sequences.append((candidate, average_score))
        return sequences

    @staticmethod
    def _find_direct_plate(fragments: list[OCRFragment]) -> PlateResult | None:
        candidates = [
            PlateResult(text, score, "direct")
            for text, score in PlateReader._candidate_sequences(fragments)
            if is_valid_korean_plate(text)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (len(item.plate or ""), item.confidence))

    @staticmethod
    def _find_region(fragments: list[OCRFragment]) -> OCRFragment | None:
        matches: list[OCRFragment] = []
        for fragment in fragments:
            if fragment.text in REGIONS:
                matches.append(fragment)
                continue
            for region in REGIONS:
                if region in fragment.text:
                    matches.append(OCRFragment(region, fragment.score, fragment.source))
                    break
        if not matches:
            return None
        return max(matches, key=lambda item: (len(item.text), item.score))

    @staticmethod
    def _find_tail(fragments: list[OCRFragment]) -> OCRFragment | None:
        matches: list[OCRFragment] = []
        for candidate, score in PlateReader._candidate_sequences(fragments):
            match = TAIL_PATTERN.search(candidate)
            if match:
                matches.append(OCRFragment(match.group(0), score, "tail"))
        if not matches:
            return None
        return max(matches, key=lambda item: (len(item.text), item.score))

    def _scan_region_crops(self, image: np.ndarray) -> OCRFragment | None:
        width = image.shape[1]
        crop_widths = [
            90,
            110,
            int(width * 0.32),
            int(width * 0.36),
            int(width * 0.40),
        ]
        seen_widths: set[int] = set()
        best_region: OCRFragment | None = None

        for crop_width in crop_widths:
            if crop_width <= 50 or crop_width >= width or crop_width in seen_widths:
                continue
            seen_widths.add(crop_width)
            crop = image[:, :crop_width]
            for scale in (1, 2):
                scaled = crop
                if scale > 1:
                    scaled = cv2.resize(
                        crop,
                        None,
                        fx=scale,
                        fy=scale,
                        interpolation=cv2.INTER_CUBIC,
                    )
                fragments = self._predict_fragments(scaled, f"region_crop:{crop_width}:{scale}")
                region = self._find_region(fragments)
                if region is None:
                    continue
                if best_region is None or region.score > best_region.score:
                    best_region = region
                if region.text in REGIONS and region.score >= 0.90:
                    return region
        return best_region

    def read_plate_from_image(self, image: np.ndarray) -> PlateResult:
        if image.size == 0:
            return PlateResult(None, 0.0, "none")

        full_fragments = self._predict_fragments(image, "full")
        direct_match = self._find_direct_plate(full_fragments)
        if direct_match is not None:
            return direct_match

        region = self._find_region(full_fragments)
        tail = self._find_tail(full_fragments)
        if region is None:
            region = self._scan_region_crops(image)

        if region and tail:
            assembled = f"{region.text}{tail.text}"
            if is_valid_korean_plate(assembled):
                return PlateResult(assembled, (region.score + tail.score) / 2.0, "region+tail")

        if tail and is_valid_korean_plate(tail.text):
            return PlateResult(tail.text, tail.score, "tail")

        joined_text = "".join(fragment.text for fragment in full_fragments)
        if joined_text:
            confidence = sum(fragment.score for fragment in full_fragments) / len(full_fragments)
            return PlateResult(joined_text, confidence, "raw")

        return PlateResult(None, 0.0, "none")

    def read_plate(self, image_path: str | Path) -> PlateResult:
        return self.read_plate_from_image(load_image(image_path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read a Korean license plate from an image.")
    parser.add_argument("image_path", help="Path to the input image.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    image_path = Path(args.image_path)
    if not image_path.exists():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 1

    try:
        result = PlateReader().read_plate(image_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result.plate is None:
        print("No plate text detected.")
        return 1

    print(f"Plate: {result.plate}")
    print(f"Confidence: {result.confidence:.4f}")
    print(f"Valid Korean plate: {is_valid_korean_plate(result.plate)}")
    print(f"Source: {result.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
