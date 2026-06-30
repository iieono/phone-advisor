"""Download the phone dataset and (re)build the local SQLite database.

Run this whenever you want to refresh the data:

    python fetch_data.py

The app reads phones.db, which is committed to the repo, so you only need to
run this if you want fresher data. Source data is a public CSV on GitHub.
"""

import csv
import io
import re
import sqlite3
import urllib.request
from pathlib import Path

DATA_URL = "https://raw.githubusercontent.com/Senka2112/VIS2023-datasets/main/MobilePhonePrice.csv"
DB_PATH = Path(__file__).with_name("phones.db")

_INT_RE = re.compile(r"\d[\d,]*")
_FLOAT_RE = re.compile(r"\d+(?:\.\d+)?")


def _int(value):
    # Pull the first whole number out of messy values like "128 GB" or "$1,099".
    m = _INT_RE.search(str(value or ""))
    if not m:
        return None
    try:
        return int(m.group().replace(",", ""))
    except ValueError:
        return None


def _float(value):
    m = _FLOAT_RE.search(str(value or ""))
    return float(m.group()) if m else None


# Recent and locally-popular models (Tecno, Infinix, Honor and current
# flagships) that the public dataset predates. Specs/prices are approximate and
# meant for comparison. Columns: brand, model, storage GB, RAM GB, screen",
# camera (main first), battery mAh, price $.
_EXTRA = [
    ("Tecno", "Spark 10", 128, 8, 6.6, "50+2", 5000, 150),
    ("Tecno", "Camon 20 Pro", 256, 8, 6.67, "64+2", 5000, 230),
    ("Tecno", "Pova 5", 256, 8, 6.78, "50+2", 6000, 200),
    ("Infinix", "Hot 30", 128, 8, 6.78, "50+2", 5000, 140),
    ("Infinix", "Note 30 Pro", 256, 8, 6.67, "108+2+2", 5000, 250),
    ("Infinix", "Zero 30 5G", 256, 12, 6.78, "108+13+2", 5000, 300),
    ("Honor", "X9b", 256, 8, 6.78, "108+5+2", 5800, 300),
    ("Honor", "90", 256, 12, 6.7, "200+12+2", 5000, 400),
    ("Honor", "Magic5 Pro", 512, 12, 6.81, "50+50+50", 5100, 900),
    ("Samsung", "Galaxy A34 5G", 128, 6, 6.6, "48+8+5", 5000, 300),
    ("Samsung", "Galaxy A54 5G", 256, 8, 6.4, "50+12+5", 5000, 400),
    ("Samsung", "Galaxy S23", 256, 8, 6.1, "50+12+10", 3900, 800),
    ("Samsung", "Galaxy S24 Ultra", 256, 12, 6.8, "200+50+12+10", 5000, 1300),
    ("Xiaomi", "Redmi Note 13", 128, 6, 6.67, "108+8+2", 5000, 200),
    ("Xiaomi", "Redmi Note 13 Pro", 256, 8, 6.67, "200+8+2", 5100, 300),
    ("Xiaomi", "Poco X6 Pro", 256, 8, 6.67, "64+8+2", 5000, 350),
    ("Xiaomi", "13T Pro", 512, 12, 6.67, "50+50+12", 5000, 700),
    ("Apple", "iPhone 15", 128, 6, 6.1, "48+12", 3349, 800),
    ("Apple", "iPhone 15 Pro Max", 256, 8, 6.7, "48+12+12", 4441, 1200),
    ("Google", "Pixel 7a", 128, 8, 6.1, "64+13", 4385, 400),
    ("Google", "Pixel 8", 128, 8, 6.2, "50+12", 4575, 700),
    ("Realme", "11 Pro 5G", 256, 8, 6.7, "100+2", 5000, 330),
    ("OnePlus", "Nord 3 5G", 256, 16, 6.74, "50+8+2", 5000, 450),
    ("OnePlus", "12", 256, 12, 6.82, "50+64+48", 5400, 800),
]
EXTRA_PHONES = [
    {"brand": b, "model": m, "storage_gb": s, "ram_gb": r, "screen_in": sc,
     "camera": cam, "camera_main_mp": _int(cam), "battery_mah": bat, "price_usd": p}
    for (b, m, s, r, sc, cam, bat, p) in _EXTRA
]


def download_rows(url=DATA_URL):
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # skip header
    rows = []
    for row in reader:
        if len(row) < 8:
            continue
        brand, model, storage, ram, screen, camera, battery, price = row[:8]
        brand, model, camera = brand.strip(), model.strip(), camera.strip()
        if not brand or not model:
            continue
        rows.append({
            "brand": brand,
            "model": model,
            "storage_gb": _int(storage),
            "ram_gb": _int(ram),
            "screen_in": _float(screen),
            "camera": camera,
            "camera_main_mp": _int(camera),  # first number = main sensor
            "battery_mah": _int(battery),
            "price_usd": _int(price),
        })
    return dedupe(rows + EXTRA_PHONES)


def dedupe(rows):
    # The source concatenates a few datasets, so models repeat with different
    # completeness. Keep one row per (brand, model): the most filled-in, and
    # prefer rows that actually have a price.
    def score(r):
        filled = sum(r[k] is not None for k in
                     ("storage_gb", "ram_gb", "screen_in", "camera_main_mp", "battery_mah", "price_usd"))
        return (r["price_usd"] is not None, filled)

    best = {}
    for r in rows:
        key = (r["brand"].lower(), r["model"].lower())
        if key not in best or score(r) > score(best[key]):
            best[key] = r
    return list(best.values())


def build_db(rows, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS phones")
    conn.execute("""
        CREATE TABLE phones (
            id             INTEGER PRIMARY KEY,
            brand          TEXT,
            model          TEXT,
            storage_gb     INTEGER,
            ram_gb         INTEGER,
            screen_in      REAL,
            camera         TEXT,
            camera_main_mp INTEGER,
            battery_mah    INTEGER,
            price_usd      INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO phones "
        "(brand, model, storage_gb, ram_gb, screen_in, camera, camera_main_mp, battery_mah, price_usd) "
        "VALUES (:brand, :model, :storage_gb, :ram_gb, :screen_in, :camera, :camera_main_mp, :battery_mah, :price_usd)",
        rows,
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    rows = download_rows()
    build_db(rows)
    print(f"Saved {len(rows)} phones to {DB_PATH.name}")
