from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import firebase_admin
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from firebase_admin import credentials, db


@dataclass(frozen=True)
class BlobRef:
    account_name: str
    container_name: str
    blob_name: str
    base_url: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh all Azure Blob SAS image URLs stored in Firebase Realtime Database."
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
        help="Root path where plate records exist. Default: parking_lot.",
    )
    parser.add_argument(
        "--azure-connection-string",
        default=None,
        help="Azure Storage connection string. If omitted, use --azure-secrets-path.",
    )
    parser.add_argument(
        "--azure-secrets-path",
        default=None,
        help="Path to JSON containing azure_storage_connection_string.",
    )
    parser.add_argument(
        "--ttl-hours",
        type=float,
        default=24.0,
        help="SAS validity in hours from now. Default: 24.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to Firebase.",
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

    value = (data.get("azure_storage_connection_string") or "").strip()
    if not value:
        raise ValueError("`azure_storage_connection_string` is missing in Azure secrets JSON.")
    return value


def connection_string_value(connection_string: str, key: str) -> str:
    for segment in connection_string.split(";"):
        if "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        if name.strip().lower() == key.lower():
            return value.strip()
    return ""


def normalize_sas_token(token: str) -> str:
    return token.lstrip("?").strip()


def account_name_from_blob_endpoint(endpoint: str) -> str:
    if not endpoint:
        return ""
    parts = urlsplit(endpoint.strip())
    host = parts.netloc
    if not host:
        return ""
    return host.split(".")[0].strip()


def parse_blob_url(url: str) -> BlobRef | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc
    if not host or ".blob.core.windows.net" not in host:
        return None

    account_name = host.split(".")[0].strip()
    path = parts.path.lstrip("/")
    if not account_name or "/" not in path:
        return None

    container_name, blob_name = path.split("/", 1)
    if not container_name or not blob_name:
        return None

    base_url = urlunsplit((parts.scheme, host, parts.path, "", ""))
    return BlobRef(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        base_url=base_url,
    )


def generate_read_sas_url(blob_ref: BlobRef, account_key: str, ttl_hours: float) -> str:
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(hours=ttl_hours)
    sas_token = generate_blob_sas(
        account_name=blob_ref.account_name,
        container_name=blob_ref.container_name,
        blob_name=blob_ref.blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        start=now - timedelta(minutes=5),
        expiry=expiry,
        protocol="https",
    )
    return f"{blob_ref.base_url}?{sas_token}"


def build_url_from_account_sas(blob_ref: BlobRef, account_sas: str) -> str:
    return f"{blob_ref.base_url}?{normalize_sas_token(account_sas)}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    if args.ttl_hours <= 0:
        print("--ttl-hours must be > 0.", file=sys.stderr)
        return 1

    try:
        connection_string = resolve_connection_string(args)
        account_name = connection_string_value(connection_string, "AccountName")
        if not account_name:
            account_name = account_name_from_blob_endpoint(connection_string_value(connection_string, "BlobEndpoint"))
        account_key = connection_string_value(connection_string, "AccountKey")
        account_sas = connection_string_value(connection_string, "SharedAccessSignature")
        if not account_name:
            raise ValueError("Azure connection string is missing AccountName.")
        if not account_key and not account_sas:
            raise ValueError("Azure connection string must contain AccountKey or SharedAccessSignature.")

        database_url = resolve_database_url(args.service_account, args.database_url)
        credential = credentials.Certificate(args.service_account)
        app_name = f"refresh-sas-{abs(hash((args.service_account, database_url)))}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                credential,
                options={"databaseURL": database_url},
                name=app_name,
            )

        root = args.root_path.strip("/") or "parking_lot"
        root_ref = db.reference(root, app=app)
        data = root_ref.get() or {}
        if not isinstance(data, dict):
            raise ValueError(f"Expected object at `{root}`, got {type(data).__name__}.")

        updates: dict[str, str] = {}
        total_records = 0
        matched_blob_urls = 0

        for plate_key, record in data.items():
            if not isinstance(record, dict):
                continue
            total_records += 1
            image_url = record.get("image_url")
            if not isinstance(image_url, str) or not image_url.strip():
                continue

            blob_ref = parse_blob_url(image_url.strip())
            if blob_ref is None:
                continue
            if blob_ref.account_name != account_name:
                continue

            matched_blob_urls += 1
            if account_key:
                new_url = generate_read_sas_url(blob_ref, account_key=account_key, ttl_hours=args.ttl_hours)
            else:
                new_url = build_url_from_account_sas(blob_ref, account_sas=account_sas)
            updates[f"{plate_key}/image_url"] = new_url

        print(f"Root path: {root}")
        print(f"Total plate records: {total_records}")
        print(f"Azure blob image URLs matched: {matched_blob_urls}")
        print(f"URLs to update: {len(updates)}")
        if account_sas and not account_key:
            print("SAS mode: using SharedAccessSignature from connection string for all refreshed URLs.")

        if args.dry_run:
            print("Dry run only. No writes performed.")
            return 0

        if not updates:
            print("No updates needed.")
            return 0

        root_ref.update(updates)
        print("Firebase update completed.")
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
