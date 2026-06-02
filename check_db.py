from __future__ import annotations

import argparse
import json
import sys

import firebase_admin
from firebase_admin import credentials, db


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read parking plate data from Firebase Realtime Database.")
    parser.add_argument(
        "--service-account",
        required=True,
        help="Path to Firebase service account JSON.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Firebase Realtime Database URL. Default: inferred from project_id in service account.",
    )
    parser.add_argument(
        "--root-path",
        default="parking_lot",
        help="Root path to read. Default: parking_lot",
    )
    parser.add_argument(
        "--plate",
        default=None,
        help="Optional full plate key to read one record only (example: 123가4568).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
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


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    try:
        database_url = resolve_database_url(args.service_account, args.database_url)
        credential = credentials.Certificate(args.service_account)
        app_name = f"check-db-{abs(hash((args.service_account, database_url)))}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                credential,
                options={"databaseURL": database_url},
                name=app_name,
            )

        root = args.root_path.strip("/") or "parking_lot"
        path = f"{root}/{args.plate}" if args.plate else root
        data = db.reference(path, app=app).get()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.pretty:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
