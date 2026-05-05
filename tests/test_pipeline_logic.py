import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from parking_processor import ParkingLotProcessor
from parking_types import SectionSpec
from parking_pipeline import load_settings_defaults, parse_section_box_argument
from plate_detection import YoloPlateDetector, divide_into_sections
from plate_ocr import PlateResult


class _StubReader:
    def __init__(self, results):
        self._results = list(results)
        self._index = 0

    def read_plate_from_image(self, _image):
        result = self._results[self._index]
        self._index += 1
        return result


class ParkingProcessorReadCandidateTests(unittest.TestCase):
    def _make_processor_with_reader(self, reader):
        processor = ParkingLotProcessor.__new__(ParkingLotProcessor)
        processor.reader = reader
        return processor

    def test_keeps_primary_when_primary_is_valid_and_enhanced_is_invalid(self):
        reader = _StubReader(
            [
                PlateResult(plate="12\uac003456", confidence=0.60, source="full"),
                PlateResult(plate="abc", confidence=0.99, source="enhanced"),
            ]
        )
        processor = self._make_processor_with_reader(reader)
        image = np.zeros((32, 120, 3), dtype=np.uint8)

        result = processor._read_plate_candidate(image)

        self.assertEqual(result.plate, "12\uac003456")
        self.assertEqual(result.source, "full")

    def test_prefers_higher_confidence_when_both_are_valid(self):
        reader = _StubReader(
            [
                PlateResult(plate="12\uac003456", confidence=0.65, source="full"),
                PlateResult(plate="12\uac003456", confidence=0.92, source="enhanced"),
            ]
        )
        processor = self._make_processor_with_reader(reader)
        image = np.zeros((32, 120, 3), dtype=np.uint8)

        result = processor._read_plate_candidate(image)

        self.assertEqual(result.source, "enhanced")
        self.assertAlmostEqual(result.confidence, 0.92)


class YoloSectionCropTests(unittest.TestCase):
    def test_detect_sections_uses_clamped_crop(self):
        detector = YoloPlateDetector.__new__(YoloPlateDetector)
        detector.name = "yolo"
        detector._predict_ranked_boxes_adaptive = lambda _image: [(0.95, (0, 0, 80, 40))]

        frame = np.zeros((40, 100, 3), dtype=np.uint8)
        section_specs = [
            SectionSpec("section-1", 0, (0, 0, 50, 40)),
            SectionSpec("section-2", 1, (50, 0, 100, 40)),
        ]

        with mock.patch("plate_detection.rectify_plate_crop", side_effect=lambda image: image):
            detected = detector.detect_sections(frame, section_specs)

        self.assertIn("section-1", detected)
        candidate = detected["section-1"]
        self.assertEqual(candidate.box, (0, 0, 50, 40))
        self.assertEqual(candidate.image.shape[1], 50)


class DivideIntoSectionsTests(unittest.TestCase):
    def test_columns_cover_full_width_without_gaps(self):
        sections = divide_into_sections((40, 101, 3), 3, "columns")

        self.assertEqual(sections[0].box[0], 0)
        self.assertEqual(sections[-1].box[2], 101)
        for previous, current in zip(sections, sections[1:]):
            self.assertEqual(previous.box[2], current.box[0])

    def test_rows_cover_full_height_without_gaps(self):
        sections = divide_into_sections((99, 80, 3), 4, "rows")

        self.assertEqual(sections[0].box[1], 0)
        self.assertEqual(sections[-1].box[3], 99)
        for previous, current in zip(sections, sections[1:]):
            self.assertEqual(previous.box[3], current.box[1])


class SectionBoxParsingTests(unittest.TestCase):
    def test_parse_section_box_argument(self):
        parsed = parse_section_box_argument("10,20,100,50")
        self.assertEqual(parsed, (10, 20, 110, 70))

    def test_parse_section_box_rejects_invalid_shape(self):
        with self.assertRaises(ValueError):
            parse_section_box_argument("10,20,100")


class CustomSectionSpecTests(unittest.TestCase):
    def _make_custom_processor(self, boxes):
        processor = ParkingLotProcessor.__new__(ParkingLotProcessor)
        processor._custom_section_boxes = tuple(boxes)
        processor.section_count = len(boxes)
        processor.layout = "custom"
        processor._section_cache = {}
        return processor

    def test_custom_section_specs_are_used(self):
        processor = self._make_custom_processor([(10, 5, 60, 45), (70, 5, 120, 45)])
        specs = processor.get_section_specs((80, 140, 3))

        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0].box, (10, 5, 60, 45))
        self.assertEqual(specs[1].box, (70, 5, 120, 45))

    def test_custom_section_box_out_of_bounds_raises(self):
        processor = self._make_custom_processor([(10, 5, 200, 45)])
        with self.assertRaises(ValueError):
            processor.get_section_specs((80, 140, 3))


class SettingsLoadingTests(unittest.TestCase):
    def test_load_settings_defaults_reads_all_supported_shapes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump(
                    {
                        "webcam": True,
                        "camera": 1,
                        "section_boxes": [
                            {"x": 10, "y": 20, "width": 100, "height": 60},
                            "150,20,100,60",
                            [290, 20, 100, 60],
                        ],
                    },
                    settings_file,
                )

            defaults = load_settings_defaults(Path(settings_path), [])
            self.assertEqual(defaults["webcam"], True)
            self.assertEqual(defaults["camera"], 1)
            self.assertEqual(defaults["section_box"], ["10,20,100,60", "150,20,100,60", "290,20,100,60"])

    def test_cli_section_box_disables_settings_section_boxes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump({"section_boxes": ["10,20,100,60"]}, settings_file)

            defaults = load_settings_defaults(Path(settings_path), ["--section-box", "0,0,50,50"])
            self.assertNotIn("section_box", defaults)


if __name__ == "__main__":
    unittest.main()
