import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from parking_processor import ParkingLotProcessor
from parking_types import SectionSpec
from parking_pipeline import (
    load_settings_defaults,
    parse_camera_list_argument,
    parse_section_box_argument,
    resolve_configured_section_boxes,
    save_camera_section_boxes,
)
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
        processor._section_lock = threading.RLock()
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

    def test_custom_sections_skip_full_frame_batch_detection(self):
        class Detector:
            name = "yolo"

            def detect_sections(self, _frame, _section_specs):
                raise AssertionError("full-frame batch detection should not run for custom sections")

            def detect(self, _section_image):
                return None

        processor = self._make_custom_processor([(10, 5, 60, 45)])
        processor.detector = Detector()
        processor.fallback_detector = None

        analysis = processor.process_frame(np.zeros((80, 140, 3), dtype=np.uint8), "test", "custom")

        self.assertEqual(analysis.payload["section_count"], 1)
        self.assertEqual(len(analysis.sections), 1)


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
            self.assertEqual(defaults["camera"], [1])
            self.assertEqual(defaults["section_box"], ["10,20,100,60", "150,20,100,60", "290,20,100,60"])

    def test_load_settings_defaults_reads_multiple_cameras(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump({"cameras": [0, 1, 1]}, settings_file)

            defaults = load_settings_defaults(Path(settings_path), [])
            self.assertEqual(defaults["camera"], [0, 1])

    def test_load_settings_defaults_reads_camera_section_boxes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump(
                    {
                        "camera_section_boxes": {
                            "0": [{"x": 10, "y": 20, "width": 100, "height": 60}],
                            "1": ["30,40,120,70"],
                        }
                    },
                    settings_file,
                )

            defaults = load_settings_defaults(Path(settings_path), [])
            self.assertEqual(defaults["camera_section_boxes"][0], ["10,20,100,60"])
            self.assertEqual(defaults["camera_section_boxes"][1], ["30,40,120,70"])

    def test_cli_camera_disables_settings_camera(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump({"cameras": [0, 1]}, settings_file)

            defaults = load_settings_defaults(Path(settings_path), ["--camera", "2"])
            self.assertNotIn("camera", defaults)

    def test_parse_camera_list_argument(self):
        self.assertEqual(parse_camera_list_argument("0, 2"), [0, 2])

    def test_resolve_configured_section_boxes_prefers_camera_specific_boxes(self):
        namespace = mock.Mock()
        namespace.webcam = True
        namespace.section_box = ["1,2,3,4"]
        namespace.camera_section_boxes = {0: ["10,20,100,60"]}

        resolved = resolve_configured_section_boxes(namespace, [0, 1], cli_section_box_override=False)

        self.assertEqual(resolved[0], [(10, 20, 110, 80)])
        self.assertEqual(resolved[1], [(1, 2, 4, 6)])

    def test_resolve_configured_section_boxes_ignores_camera_boxes_for_images(self):
        namespace = mock.Mock()
        namespace.webcam = False
        namespace.section_box = None
        namespace.camera_section_boxes = {0: ["10,20,100,60"]}

        resolved = resolve_configured_section_boxes(namespace, [0], cli_section_box_override=False)

        self.assertEqual(resolved[0], None)

    def test_save_camera_section_boxes_preserves_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump({"webcam": True, "camera_section_boxes": {"0": []}}, settings_file)

            save_camera_section_boxes(settings_path, 1, [(10, 20, 110, 80)])

            with open(settings_path, "r", encoding="utf-8") as settings_file:
                saved = json.load(settings_file)
            self.assertEqual(saved["webcam"], True)
            self.assertEqual(saved["camera_section_boxes"]["0"], [])
            self.assertEqual(
                saved["camera_section_boxes"]["1"],
                [{"x": 10, "y": 20, "width": 100, "height": 60}],
            )

    def test_cli_section_box_disables_settings_section_boxes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = f"{temp_dir}/settings.json"
            with open(settings_path, "w", encoding="utf-8") as settings_file:
                json.dump({"section_boxes": ["10,20,100,60"]}, settings_file)

            defaults = load_settings_defaults(Path(settings_path), ["--section-box", "0,0,50,50"])
            self.assertNotIn("section_box", defaults)


if __name__ == "__main__":
    unittest.main()
