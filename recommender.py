"""Turns a customer's message into the set of phones to show the model.

Two jobs are kept separate on purpose:

* Finding phones is done here with plain SQL — exact and fast, and the model
  never has to remember specs or do arithmetic.
* Deciding whether a message is even about buying a phone, and how to reply, is
  left to the model. This file never gates on "did they say the word phone";
  it only translates whatever shopping signal exists into a query.
"""

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("phones.db")

# A few common ways people name brands -> the brand as stored in the data.
BRAND_ALIASES = {
    "iphone": "Apple",
    "apple": "Apple",
    "galaxy": "Samsung",
    "samsung": "Samsung",
    "redmi": "Xiaomi",
    "poco": "Xiaomi",
    "xiaomi": "Xiaomi",
    "pixel": "Google",
    "google": "Google",
    "oneplus": "OnePlus",
    "oppo": "Oppo",
    "vivo": "Vivo",
    "realme": "Realme",
    "nokia": "Nokia",
    "motorola": "Motorola",
    "moto": "Motorola",
    "huawei": "Huawei",
    "asus": "Asus",
    "sony": "Sony",
    "tecno": "Tecno",
    "infinix": "Infinix",
    "honor": "Honor",
}

# Keyword -> how to sort. Includes indirect ways people describe a need
# ("loves photos" -> camera, "travel a lot" -> battery). English and Uzbek.
SORT_RULES = [
    (("camera", "kamera", "photo", "photos", "photography", "selfie", "foto", "rasm", "surat"),
     "camera_main_mp DESC"),
    (("battery", "batareya", "zaryad", "charge", "long day", "all day", "travel", "lasts"),
     "battery_mah DESC"),
    (("game", "gaming", "gamer", "o'yin", "oyin", "performance", "powerful", "fast", "smooth", "tez", "pubg"),
     "ram_gb DESC, camera_main_mp DESC"),
    (("screen", "ekran", "display", "video", "movie", "movies", "youtube", "watch", "big screen", "katta ekran"),
     "screen_in DESC"),
    (("storage", "xotira", "memory", "space"), "storage_gb DESC"),
]

# The only ORDER BY clauses that can reach the SQL. parse_query never returns
# anything else, so the interpolated value is never user-controlled.
ALLOWED_ORDER = {rule for _, rule in SORT_RULES} | {"price_usd ASC", "price_usd DESC"}


def connect(db_path=DB_PATH, read_only=False):
    """Open the phone database.

    In read_only mode the connection cannot write (PRAGMA query_only) and a
    missing database raises instead of being silently created empty. The app
    uses read_only; the build script and tests open it normally.
    """
    if read_only and str(db_path) != ":memory:":
        if not Path(db_path).exists():
            raise FileNotFoundError(
                f"{Path(db_path).name} not found. Build it first:  python fetch_data.py"
            )
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn


def parse_query(text):
    """Read a message into search hints: budget, brand, priority, cheap flag.

    Inspectable on purpose. It never judges whether the message is on-topic —
    that's the model's call — it only captures the phone-shopping signal.
    """
    low = text.lower()

    # Budget: any number that reads like a dollar price.
    # ponytail: treats bare numbers as USD; UZS/other currencies not converted.
    numbers = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", low)]
    budget = max((n for n in numbers if 30 <= n <= 5000), default=None)

    # All brands mentioned, so "Samsung vs Xiaomi" filters to both.
    brands = []
    for word, mapped in BRAND_ALIASES.items():
        if mapped not in brands and re.search(rf"\b{re.escape(word)}\b", low):
            brands.append(mapped)

    cheap = any(w in low for w in ("cheap", "cheapest", "arzon", "budget", "affordable", "student"))

    priority = None
    for words, rule in SORT_RULES:
        if any(w in low for w in words):
            priority = rule
            break

    if priority:
        order_by = priority
    elif cheap:
        order_by = "price_usd ASC"
    else:
        order_by = "price_usd DESC"  # default: best phone within reach

    assert order_by in ALLOWED_ORDER, order_by  # guards the SQL interpolation below
    return {
        "budget": budget,
        "brands": brands,
        "cheap": cheap,
        "priority": priority,
        "order_by": order_by,
        "signal": bool(budget or brands or cheap or priority),
    }


def _name_tokens(text):
    """Tokens that look like a phone model identifier — they contain a digit,
    e.g. 's21', 'a14', '13'. A plain 3+ digit number is a budget, not a model."""
    return [
        tok for tok in re.findall(r"[a-z0-9]+", text.lower())
        if any(c.isdigit() for c in tok) and not (tok.isdigit() and len(tok) >= 3)
    ]


def name_matches(conn, text, brands=None, cap=8):
    """Phones the customer named directly, e.g. 'is the iPhone 13 good?' or
    'Galaxy S21 vs iPhone 12'. When a brand was mentioned the search is scoped
    to it, so a loose token like '30' can't pull in unrelated models."""
    brand_clause, brand_params = "", []
    if brands:
        brand_clause = f" AND brand IN ({','.join('?' * len(brands))})"
        brand_params = list(brands)
    sql = ("SELECT * FROM phones WHERE (lower(model) LIKE ? OR lower(brand) LIKE ?)"
           f"{brand_clause} LIMIT ?")
    seen, rows = set(), []
    for tok in _name_tokens(text):
        like = f"%{tok}%"
        for r in conn.execute(sql, [like, like, *brand_params, cap]):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
            if len(rows) >= cap:
                return rows
    return rows


def _constraint_rows(conn, q, limit):
    where, params = [], []
    if q["budget"] is not None:
        where.append("price_usd <= ?")
        params.append(q["budget"])
    if q["brands"]:
        where.append(f"brand IN ({','.join('?' * len(q['brands']))})")
        params += q["brands"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM phones {clause} ORDER BY {q['order_by']} LIMIT ?",
        params + [limit],
    ).fetchall()
    # Tight budget+brand with no hit: drop the brand so we still suggest something.
    if not rows and q["brands"] and q["budget"] is not None:
        rows = conn.execute(
            "SELECT * FROM phones WHERE price_usd <= ? ORDER BY price_usd DESC LIMIT ?",
            [q["budget"], limit],
        ).fetchall()
    return rows


def diverse_sample(conn, limit):
    """A spread of phones across price tiers, for messages that give no hints
    (a greeting, or 'just recommend me a phone'). Better than handing the model
    only the most expensive models."""
    rows = conn.execute("SELECT * FROM phones ORDER BY price_usd").fetchall()
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]


def candidates(conn, text, limit=25):
    """The phones to put in front of the model for this message.

    Directly-named phones come first, then phones matching the budget / brand /
    priority, then (only if there were no hints at all) a spread across prices.
    """
    q = parse_query(text)
    named = name_matches(conn, text, q["brands"])

    if q["signal"]:
        base = _constraint_rows(conn, q, limit)
    elif named:
        base = []
    else:
        base = diverse_sample(conn, limit)

    seen, merged = set(), []
    for r in named + base:
        if r["id"] not in seen:
            seen.add(r["id"])
            merged.append(r)
    merged = merged[:limit]

    if not merged:  # last resort, never hand the model an empty menu
        merged = conn.execute(
            "SELECT * FROM phones ORDER BY price_usd DESC LIMIT ?", [limit]
        ).fetchall()
    return merged


def to_lines(rows):
    """Compact one-line-per-phone text the model reads as its catalog."""
    return "\n".join(
        f"{r['brand']} {r['model']} | ${r['price_usd']} | "
        f"{r['ram_gb']}GB RAM | {r['storage_gb']}GB | "
        f"{r['battery_mah']}mAh | {r['screen_in']}\" | {r['camera_main_mp']}MP cam"
        for r in rows
    )
