from __future__ import annotations

import json
import sys

import firebase_admin
from firebase_admin import credentials, db

SERVICE_ACCOUNT = "secrets/firebase-service-account.json"
DATABASE_URL    = "https://wimc-51ff9-default-rtdb.asia-southeast1.firebasedatabase.app"
ROOT_PATH       = "parking_lot"

PLATES = [
    {"plate": "184다4056", "zone": "A", "last4": "4056"},
    {"plate": "12아2971",  "zone": "B", "last4": "2971"},
    {"plate": "136가1362", "zone": "C", "last4": "1362"},
    {"plate": "476나6798", "zone": "D", "last4": "6798"},
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

credential = credentials.Certificate(SERVICE_ACCOUNT)
app = firebase_admin.initialize_app(credential, options={"databaseURL": DATABASE_URL})

for entry in PLATES:
    ref = db.reference(f"{ROOT_PATH}/{entry['plate']}", app=app)
    ref.update({
        "zone":      entry["zone"],
        "last4":     entry["last4"],
    })
    print(f"✓ {entry['plate']} → {entry['zone']}구역")

print("완료")
