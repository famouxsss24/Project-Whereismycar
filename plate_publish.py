from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from parking_types import ProcessedFrameAnalysis, ProcessedSectionResult
from transport import post_json

try:
    import firebase_admin
    from firebase_admin import credentials, db
except ImportError:  # pragma: no cover - optional dependency
    firebase_admin = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    db = None  # type: ignore[assignment]

try:
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas
except ImportError:  # pragma: no cover - optional dependency
    ResourceExistsError = None  # type: ignore[assignment]
    BlobSasPermissions = None  # type: ignore[assignment]
    BlobServiceClient = None  # type: ignore[assignment]
    ContentSettings = None  # type: ignore[assignment]
    generate_blob_sas = None  # type: ignore[assignment]


DIGITS_PATTERN = re.compile(r"\d")
INVALID_FILE_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]+')


@dataclass(frozen=True)
class PlateUpdate:
    plate: str
    zone: str
    last4: str
    image: np.ndarray | None


class _QuietStaticFileHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return


class LocalImageWebPublisher:
    def __init__(
        self,
        image_dir: str = "plate_images",
        base_url: str | None = None,
        serve: bool = True,
        host: str = "127.0.0.1",
        port: int = 8787,
    ) -> None:
        self._root_dir = Path(image_dir).resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/") if base_url else None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

        if self._base_url is None and serve:
            self._start_server(host=host, port=port)
        if self._base_url:
            print(f"Local plate image URL base: {self._base_url}", file=sys.stderr)

    def save_and_get_url(self, update: PlateUpdate) -> str:
        if update.image is None or update.image.size == 0:
            return ""

        ok, encoded = cv2.imencode(".jpg", update.image)
        if not ok:
            return ""

        plate_folder = _sanitize_path_segment(update.plate)
        plate_dir = self._root_dir / plate_folder
        plate_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.jpg"
        image_path = plate_dir / filename
        image_path.write_bytes(encoded.tobytes())

        if not self._base_url:
            return ""
        return f"{self._base_url}/{quote(plate_folder)}/{quote(filename)}"

    def _start_server(self, host: str, port: int) -> None:
        handler = partial(_QuietStaticFileHandler, directory=str(self._root_dir))
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

        public_host = host
        if host in ("0.0.0.0", "::"):
            public_host = "localhost"
        self._base_url = f"http://{public_host}:{self._server.server_port}"


class AzureBlobImagePublisher:
    def __init__(
        self,
        connection_string: str,
        container_name: str,
        blob_prefix: str = "plate_images",
        sas_ttl_minutes: int = 0,
    ) -> None:
        if BlobServiceClient is None or ContentSettings is None:
            raise RuntimeError("azure-storage-blob is required. Run `pip install azure-storage-blob`.")
        if not connection_string.strip():
            raise ValueError("Azure storage connection string is required.")
        if not container_name.strip():
            raise ValueError("Azure blob container name is required.")

        self._service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name.strip()
        self._blob_prefix = blob_prefix.strip().strip("/")
        self._sas_ttl_minutes = max(0, int(sas_ttl_minutes))
        self._account_name = _connection_string_value(connection_string, "AccountName")
        self._account_key = _connection_string_value(connection_string, "AccountKey")

        container_client = self._service_client.get_container_client(self._container_name)
        try:
            container_client.create_container()
        except Exception as exc:
            if ResourceExistsError is None or not isinstance(exc, ResourceExistsError):
                raise

    def upload_and_get_url(self, update: PlateUpdate) -> str:
        if update.image is None or update.image.size == 0:
            return ""

        ok, encoded = cv2.imencode(".jpg", update.image)
        if not ok:
            return ""

        plate_folder = _sanitize_path_segment(update.plate)
        filename = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}.jpg"
        blob_name = "/".join(part for part in (self._blob_prefix, plate_folder, filename) if part)
        blob_client = self._service_client.get_blob_client(container=self._container_name, blob=blob_name)
        blob_client.upload_blob(
            encoded.tobytes(),
            overwrite=True,
            content_settings=ContentSettings(content_type="image/jpeg"),
        )
        return self._resolve_blob_url(blob_client, blob_name)

    def _resolve_blob_url(self, blob_client: object, blob_name: str) -> str:
        if (
            self._sas_ttl_minutes <= 0
            or not self._account_name
            or not self._account_key
            or generate_blob_sas is None
            or BlobSasPermissions is None
        ):
            return blob_client.url  # type: ignore[attr-defined]

        expiry = datetime.now(timezone.utc) + timedelta(minutes=self._sas_ttl_minutes)
        sas_token = generate_blob_sas(
            account_name=self._account_name,
            container_name=self._container_name,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        return f"{blob_client.url}?{sas_token}"  # type: ignore[attr-defined]


class FirebasePlatePublisher:
    def __init__(
        self,
        service_account_path: str,
        database_url: str,
        root_path: str = "parking_lot",
    ) -> None:
        if firebase_admin is None:
            raise RuntimeError("firebase-admin is required. Run `pip install firebase-admin`.")
        if not database_url:
            raise ValueError("Firebase database URL is required.")

        credential = credentials.Certificate(service_account_path)
        app_name = f"wimc-{hash((service_account_path, database_url))}"
        try:
            self._app = firebase_admin.get_app(app_name)
        except ValueError:
            self._app = firebase_admin.initialize_app(
                credential,
                options={"databaseURL": database_url},
                name=app_name,
            )
        self._root_path = root_path.strip("/") or "parking_lot"

    def publish(self, update: PlateUpdate, image_url: str) -> None:
        payload = {
            "zone": update.zone,
            "last4": update.last4,
            "image_url": image_url,
        }
        db.reference(f"{self._root_path}/{update.plate}", app=self._app).set(payload)


class PlateUpdateDispatcher:
    def __init__(
        self,
        server_url: str | None,
        timeout: float,
        cooldown_seconds: float = 30.0,
        firebase_publisher: FirebasePlatePublisher | None = None,
        local_image_publisher: LocalImageWebPublisher | None = None,
        azure_image_publisher: AzureBlobImagePublisher | None = None,
    ) -> None:
        self._server_url = server_url
        self._timeout = timeout
        self._cooldown_seconds = cooldown_seconds
        self._firebase_publisher = firebase_publisher
        self._local_image_publisher = local_image_publisher
        self._azure_image_publisher = azure_image_publisher
        self._last_sent: dict[str, float] = {}

    def emit(self, analysis: ProcessedFrameAnalysis, pretty: bool) -> None:
        indent = 2 if pretty else None
        print(json.dumps(analysis.payload, ensure_ascii=False, indent=indent))

        updates = self._collect_updates(analysis.sections)
        for update in updates:
            if not self._is_cooldown_elapsed(update.plate):
                continue

            try:
                image_url = self._build_image_url(update)
                self._send_to_firebase(update, image_url)
                self._send_to_server(update, image_url)
                self._last_sent[update.plate] = time.monotonic()
            except Exception as exc:
                print(f"Publish error: {exc}", file=sys.stderr)

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

    def _build_image_url(self, update: PlateUpdate) -> str:
        if self._azure_image_publisher is not None:
            return self._azure_image_publisher.upload_and_get_url(update)
        if self._local_image_publisher is None:
            return ""
        return self._local_image_publisher.save_and_get_url(update)

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

    def _send_to_firebase(self, update: PlateUpdate, image_url: str) -> None:
        if self._firebase_publisher is None:
            return
        self._firebase_publisher.publish(update, image_url)

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


def resolve_project_id_from_service_account(service_account_path: str) -> str:
    path = Path(service_account_path)
    with path.open("r", encoding="utf-8") as service_account_file:
        data = json.load(service_account_file)
    project_id = (data.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("`project_id` is missing in Firebase service account JSON.")
    return project_id


def _sanitize_path_segment(value: str) -> str:
    sanitized = INVALID_FILE_CHARS_PATTERN.sub("_", value.strip())
    return sanitized or "unknown_plate"


def _connection_string_value(connection_string: str, key: str) -> str:
    for segment in connection_string.split(";"):
        if "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        if name.strip().lower() == key.lower():
            return value.strip()
    return ""
