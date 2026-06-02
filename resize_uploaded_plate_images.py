from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import cv2
import firebase_admin
import numpy as np
from azure.storage.blob import BlobServiceClient, ContentSettings
from firebase_admin import credentials, db


TARGET_SIZE = (120, 30)  # width, height


@dataclass(frozen=True)
class BlobRef:
    account_name: str
    container_name: str
    blob_name: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resize existing uploaded plate images in Azure Blob Storage to 120x30."
    )
    parser.add_argument(
        "--service-account",
        required=True,
        help="Path to Firebase service account JSON.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Firebase Realtime Database URL. Default: inferred from project_id.",
    )
    parser.add_argument(
        "--root-path",
        default="parking_lot",
        help="Firebase root path containing plate records. Default: parking_lot.",
    )
    parser.add_argument(
        "--azure-connection-string",
        default=None,
        help="Azure Storage connection string. If omitted, use --azure-secrets-path.",
    )
    parser.add_argument(
        "--azure-secrets-path",
        default=None,
        help="Path to JSON with `azure_storage_connection_string`.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be resized; do not write blobs.",
    )
    return parser.parse_args(argv)


def resolve_database_url(service_account_path: str, explicit_database_url: str | None) -> str:
    if explicit_database_url:
        return explicit_database_url

    with open(service_account_path, "r", encoding="utf-8") as service_account_file:
        service_account = json.load(service_account_file)
    project_id = (service_account.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("`project_id` is missing in service account JSON.")
    return f"https://{project_id}-default-rtdb.firebaseio.com"


def resolve_connection_string(args: argparse.Namespace) -> str:
    if args.azure_connection_string:
        return args.azure_connection_string
    if not args.azure_secrets_path:
        raise ValueError("Provide --azure-connection-string or --azure-secrets-path.")

    with open(args.azure_secrets_path, "r", encoding="utf-8") as secrets_file:
        data = json.load(secrets_file)
    if not isinstance(data, dict):
        raise ValueError("Azure secrets JSON must be an object.")

    connection_string = (data.get("azure_storage_connection_string") or "").strip()
    if not connection_string:
        raise ValueError("`azure_storage_connection_string` is missing in Azure secrets JSON.")
    return connection_string


def parse_blob_url(url: str) -> BlobRef | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    if ".blob.core.windows.net" not in parts.netloc:
        return None

    account_name = parts.netloc.split(".")[0].strip()
    path = parts.path.lstrip("/")
    if "/" not in path:
        return None

    container_name, blob_name_url = path.split("/", 1)
    if not container_name or not blob_name_url:
        return None

    return BlobRef(
        account_name=account_name,
        container_name=container_name,
        blob_name=unquote(blob_name_url),
    )


def load_blob_refs_from_firebase(
    service_account_path: str,
    database_url: str,
    root_path: str,
) -> tuple[dict[str, BlobRef], str]:
    credential = credentials.Certificate(service_account_path)
    app_name = f"resize-images-{abs(hash((service_account_path, database_url, root_path)))}"
    try:
        app = firebase_admin.get_app(app_name)
    except ValueError:
        app = firebase_admin.initialize_app(
            credential,
            options={"databaseURL": database_url},
            name=app_name,
        )

    root = root_path.strip("/") or "parking_lot"
    records = db.reference(root, app=app).get() or {}
    if not isinstance(records, dict):
        raise ValueError(f"Expected object at `{root}`, got {type(records).__name__}.")

    refs: dict[str, BlobRef] = {}
    for plate_key, record in records.items():
        if not isinstance(record, dict):
            continue
        image_url = record.get("image_url")
        if not isinstance(image_url, str) or not image_url.strip():
            continue
        parsed = parse_blob_url(image_url.strip())
        if parsed is None:
            continue
        refs[f"{parsed.account_name}/{parsed.container_name}/{parsed.blob_name}"] = parsed
    return refs, root


def resize_and_overwrite_blob(
    service_client: BlobServiceClient,
    container_name: str,
    blob_name: str,
) -> tuple[bool, tuple[int, int], tuple[int, int]]:
    blob_client = service_client.get_blob_client(container=container_name, blob=blob_name)
    data = blob_client.download_blob().readall()
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return False, (0, 0), (0, 0)

    source_h, source_w = image.shape[:2]
    if source_w == TARGET_SIZE[0] and source_h == TARGET_SIZE[1]:
        return True, (source_w, source_h), (source_w, source_h)

    resized = cv2.resize(image, TARGET_SIZE, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", resized)
    if not ok:
        return False, (source_w, source_h), (0, 0)

    blob_client.upload_blob(
        encoded.tobytes(),
        overwrite=True,
        content_settings=ContentSettings(content_type="image/jpeg"),
    )
    return True, (source_w, source_h), TARGET_SIZE


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args(argv)

    try:
        connection_string = resolve_connection_string(args)
        database_url = resolve_database_url(args.service_account, args.database_url)
        refs, root = load_blob_refs_from_firebase(
            service_account_path=args.service_account,
            database_url=database_url,
            root_path=args.root_path,
        )
        if not refs:
            print(f"No blob image URLs found under `{root}`.")
            return 0

        service_client = BlobServiceClient.from_connection_string(connection_string)
        success = 0
        failed = 0
        skipped_same_size = 0
        mismatched_account = 0

        for ref in refs.values():
            account_from_client = service_client.account_name or ""
            if account_from_client and ref.account_name != account_from_client:
                mismatched_account += 1
                continue

            if args.dry_run:
                success += 1
                continue

            ok, src_size, dst_size = resize_and_overwrite_blob(
                service_client=service_client,
                container_name=ref.container_name,
                blob_name=ref.blob_name,
            )
            if not ok:
                failed += 1
                continue
            if src_size == dst_size == TARGET_SIZE:
                skipped_same_size += 1
            success += 1

        print(f"Root path: {root}")
        print(f"Unique blob URLs found: {len(refs)}")
        print(f"Processed successfully: {success}")
        print(f"Already {TARGET_SIZE[0]}x{TARGET_SIZE[1]}: {skipped_same_size}")
        print(f"Failed: {failed}")
        print(f"Skipped due to account mismatch: {mismatched_account}")
        if args.dry_run:
            print("Dry run only. No blob writes performed.")
        return 0 if failed == 0 else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
