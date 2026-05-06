from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from parking_types import ProcessedFrameAnalysis, ProcessedSectionResult
from transport import post_json

try:
    import firebase_admin
    from firebase_admin import credentials, db, storage
except ImportError:  # pragma: no cover - optional dependency
    firebase_admin = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    db = None  # type: ignore[assignment]
    storage = None  # type: ignore[assignment]


DIGITS_PATTERN = re.compile(r"\d")


@dataclass(frozen=True)
class PlateUpdate:
    plate: str
    zone: str
    last4: str
    image: np.ndarray | None


class FirebasePlatePublisher:
    def __init__(
        self,
        service_account_path: str,
        database_url: str,
        storage_bucket: str,
        root_path: str = "parking_lot",
    ) -> None:
        if firebase_admin is None:
            raise RuntimeError("firebase-admin is required. Run `pip install firebase-admin`.")
        if not database_url:
            raise ValueError("Firebase database URL is required.")
        if not storage_bucket:
            raise ValueError("Firebase storage bucket is required.")

        credential = credentials.Certificate(service_account_path)
        app_name = f"wimc-{hash((service_account_path, database_url, storage_bucket))}"
        try:
            self._app = firebase_admin.get_app(app_name)
        except ValueError:
            self._app = firebase_admin.initialize_app(
                credential,
                options={
                    "databaseURL": database_url,
                    "storageBucket": storage_bucket,
                },
                name=app_name,
            )
        self._bucket_name = storage_bucket
        self._bucket = storage.bucket(name=self._bucket_name, app=self._app)
        self._fallback_bucket_name = _derive_fallback_bucket_name(self._bucket_name)
        self._root_path = root_path.strip("/") or "parking_lot"
        self._storage_disabled = False
        self._storage_disable_reason: str | None = None

    def publish(self, update: PlateUpdate) -> str:
        image_url = self._upload_plate_image(update)
        payload = {
            "zone": update.zone,
            "last4": update.last4,
            "image_url": image_url,
        }
        db.reference(f"{self._root_path}/{update.plate}", app=self._app).set(payload)
        return image_url

    def _upload_plate_image(self, update: PlateUpdate) -> str:
        if self._storage_disabled:
            return ""
        if update.image is None or update.image.size == 0:
            return ""

        ok, encoded = cv2.imencode(".jpg", update.image)
        if not ok:
            return ""

        timestamp = int(time.time())
        blob_name = f"{self._root_path}/{update.plate}/{timestamp}.jpg"
        image_bytes = encoded.tobytes()
        uploaded_url, error_message = self._upload_blob(self._bucket, blob_name, image_bytes)
        if uploaded_url:
            return uploaded_url

        if self._fallback_bucket_name:
            fallback_bucket = storage.bucket(name=self._fallback_bucket_name, app=self._app)
            uploaded_url, fallback_error_message = self._upload_blob(fallback_bucket, blob_name, image_bytes)
            if uploaded_url:
                self._bucket = fallback_bucket
                self._bucket_name = self._fallback_bucket_name
                self._fallback_bucket_name = None
                return uploaded_url
            error_message = fallback_error_message or error_message

        self._maybe_disable_storage(error_message)
        return ""

    def _upload_blob(self, bucket, blob_name: str, image_bytes: bytes) -> tuple[str, str]:
        try:
            blob = bucket.blob(blob_name)
            blob.upload_from_string(image_bytes, content_type="image/jpeg")
            blob.make_public()
            return blob.public_url, ""
        except Exception as exc:
            print(f"Storage upload skipped: {exc}", file=sys.stderr)
            return "", str(exc)

    def _maybe_disable_storage(self, error_message: str) -> None:
        normalized = error_message.lower()
        if "specified bucket does not exist" in normalized or "status code', 404" in normalized:
            if not self._storage_disabled:
                self._storage_disabled = True
                self._storage_disable_reason = error_message
                print(
                    "Storage disabled for this run because bucket was not found. "
                    "DB updates will continue with empty image_url.",
                    file=sys.stderr,
                )


class PlateUpdateDispatcher:
    def __init__(
        self,
        server_url: str | None,
        timeout: float,
        cooldown_seconds: float = 30.0,
        firebase_publisher: FirebasePlatePublisher | None = None,
    ) -> None:
        self._server_url = server_url
        self._timeout = timeout
        self._cooldown_seconds = cooldown_seconds
        self._firebase_publisher = firebase_publisher
        self._last_sent: dict[str, float] = {}

    def emit(self, analysis: ProcessedFrameAnalysis, pretty: bool) -> None:
        indent = 2 if pretty else None
        print(json.dumps(analysis.payload, ensure_ascii=False, indent=indent))

        updates = self._collect_updates(analysis.sections)
        for update in updates:
            if not self._is_cooldown_elapsed(update.plate):
                continue

            image_url = self._send_to_firebase(update)
            self._send_to_server(update, image_url)
            self._last_sent[update.plate] = time.monotonic()

    def _collect_updates(self, sections: list[ProcessedSectionResult]) -> list[PlateUpdate]:
        updates: dict[str, PlateUpdate] = {}
        for section in sections:
            result = section.result
            plate = (result.plate_text or "").strip()
            if not plate:
                continue
            if not result.valid_plate:
                continue
            if result.detector != "yolo":
                continue
            if plate in updates:
                continue

            updates[plate] = PlateUpdate(
                plate=plate,
                zone=self._zone_from_index(result.section_index),
                last4=self._last_four_digits(plate),
                image=section.rectified_plate,
            )
        return list(updates.values())

    def _send_to_server(self, update: PlateUpdate, image_url: str) -> None:
        if not self._server_url:
            return

        payload = {
            "parking_lot": {
                update.plate: {
                    "zone": update.zone,
                    "last4": update.last4,
                    "image_url": image_url,
                }
            }
        }
        status, content = post_json(self._server_url, payload, self._timeout)
        print(f"POST {self._server_url} -> {status}", file=sys.stderr)
        if content:
            print(content, file=sys.stderr)

    def _send_to_firebase(self, update: PlateUpdate) -> str:
        if self._firebase_publisher is None:
            return ""
        return self._firebase_publisher.publish(update)

    def _is_cooldown_elapsed(self, plate: str) -> bool:
        if self._cooldown_seconds <= 0:
            return True
        previous = self._last_sent.get(plate)
        if previous is None:
            return True
        return (time.monotonic() - previous) >= self._cooldown_seconds

    @staticmethod
    def _zone_from_index(section_index: int) -> str:
        if 0 <= section_index < 26:
            return chr(ord("A") + section_index)
        return f"S{section_index + 1}"

    @staticmethod
    def _last_four_digits(plate: str) -> str:
        digits = "".join(DIGITS_PATTERN.findall(plate))
        return digits[-4:] if len(digits) >= 4 else digits


def normalize_firebase_database_url(project_id: str, explicit_url: str | None) -> str:
    if explicit_url:
        return explicit_url
    normalized = project_id.strip()
    return f"https://{normalized}-default-rtdb.firebaseio.com"


def normalize_firebase_storage_bucket(project_id: str, explicit_bucket: str | None) -> str:
    if explicit_bucket:
        return explicit_bucket
    return f"{project_id.strip()}.firebasestorage.app"


def resolve_project_id_from_service_account(service_account_path: str) -> str:
    path = Path(service_account_path)
    with path.open("r", encoding="utf-8") as service_account_file:
        data = json.load(service_account_file)
    project_id = (data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("`project_id` is missing in Firebase service account JSON.")
    return project_id


def _derive_fallback_bucket_name(bucket_name: str) -> str | None:
    if bucket_name.endswith(".appspot.com"):
        return bucket_name.replace(".appspot.com", ".firebasestorage.app")
    if bucket_name.endswith(".firebasestorage.app"):
        return bucket_name.replace(".firebasestorage.app", ".appspot.com")
    return None
