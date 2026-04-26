import re
import sys
from paddleocr import PaddleOCR


# Korean plate Hangul classes
PLATE_HANGUL = "가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주하허호배"

PATTERN_MODERN = re.compile(
    rf"^\d{{2,3}}[{PLATE_HANGUL}]\d{{4}}$"
)

PATTERN_REGION = re.compile(
    rf"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    rf"\d{{2}}[{PLATE_HANGUL}]\d{{4}}$"
)


def clean_text(text: str) -> str:
    """Remove symbols/spaces often produced by OCR."""
    text = text.strip()
    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace(".", "")
    return text


def is_valid_korean_plate(text: str) -> bool:
    return bool(PATTERN_MODERN.match(text) or PATTERN_REGION.match(text))


def extract_best_plate(ocr_result):
    """
    PaddleOCR result format is nested.
    This extracts OCR text candidates and chooses the best valid plate.
    """
    candidates = []

    if not ocr_result:
        return None, 0.0

    for page in ocr_result:
        if not page:
            continue

        for line in page:
            # line = [bbox, (text, confidence)]
            text, conf = line[1]
            text = clean_text(text)

            candidates.append((text, conf))

    # First prefer valid Korean plate patterns
    valid_candidates = [
        (text, conf) for text, conf in candidates
        if is_valid_korean_plate(text)
    ]

    if valid_candidates:
        return max(valid_candidates, key=lambda x: x[1])

    # Fallback: return highest confidence raw OCR
    if candidates:
        return max(candidates, key=lambda x: x[1])

    return None, 0.0


def read_plate(image_path: str):
    # For cropped plate images, det=False is usually better.
    # rec=True means recognition only.
    ocr = PaddleOCR(
        lang="korean",
        use_angle_cls=False,
        show_log=False
    )

    result = ocr.ocr(image_path, det=False, rec=True)

    # det=False result format differs from full OCR mode
    candidates = []
    for item in result:
        if isinstance(item, tuple):
            text, conf = item
            candidates.append((clean_text(text), conf))
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, tuple):
                    text, conf = sub
                    candidates.append((clean_text(text), conf))

    valid = [(t, c) for t, c in candidates if is_valid_korean_plate(t)]

    if valid:
        return max(valid, key=lambda x: x[1])

    if candidates:
        return max(candidates, key=lambda x: x[1])

    return None, 0.0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python plate_reader.py path/to/plate.jpg")
        sys.exit(1)

    image_path = sys.argv[1]
    plate, confidence = read_plate(image_path)

    if plate:
        print(f"Plate: {plate}")
        print(f"Confidence: {confidence:.4f}")
        print(f"Valid Korean plate: {is_valid_korean_plate(plate)}")
    else:
        print("No plate text detected.")