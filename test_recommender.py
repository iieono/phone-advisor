"""Checks for the query parsing and candidate selection.

These cover the deterministic part of the pipeline (turning a message into a
database query). Whether a message is on-topic, and the wording of the reply,
are the model's job and are checked by running the app, not here.

Run with:  python test_recommender.py
"""

import recommender

SAMPLE = [
    {"brand": "Xiaomi", "model": "Redmi 10", "storage_gb": 64, "ram_gb": 4,
     "screen_in": 6.5, "camera": "50+8", "camera_main_mp": 50, "battery_mah": 5000, "price_usd": 150},
    {"brand": "Apple", "model": "iPhone 14", "storage_gb": 128, "ram_gb": 6,
     "screen_in": 6.1, "camera": "12+12", "camera_main_mp": 12, "battery_mah": 3279, "price_usd": 799},
    {"brand": "Samsung", "model": "Galaxy A14", "storage_gb": 64, "ram_gb": 4,
     "screen_in": 6.6, "camera": "50+2+2", "camera_main_mp": 50, "battery_mah": 5000, "price_usd": 200},
]


def make_conn():
    conn = recommender.connect(":memory:")
    conn.execute("""CREATE TABLE phones (id INTEGER PRIMARY KEY, brand TEXT, model TEXT,
        storage_gb INT, ram_gb INT, screen_in REAL, camera TEXT, camera_main_mp INT,
        battery_mah INT, price_usd INT)""")
    conn.executemany(
        "INSERT INTO phones (brand, model, storage_gb, ram_gb, screen_in, camera, "
        "camera_main_mp, battery_mah, price_usd) VALUES "
        "(:brand,:model,:storage_gb,:ram_gb,:screen_in,:camera,:camera_main_mp,:battery_mah,:price_usd)",
        SAMPLE,
    )
    return conn


def models(rows):
    return {r["model"] for r in rows}


def test_budget_excludes_pricier_phones():
    conn = make_conn()
    rows = recommender.candidates(conn, "phone under 250")
    assert rows and all(r["price_usd"] <= 250 for r in rows)
    assert "iPhone 14" not in models(rows)


def test_brand_filter():
    conn = make_conn()
    rows = recommender.candidates(conn, "show me an apple please")
    assert {r["brand"] for r in rows} == {"Apple"}


def test_uzbek_cheap_sorts_ascending():
    assert recommender.parse_query("eng arzon telefon")["order_by"] == "price_usd ASC"


def test_camera_keyword_sorts_by_camera():
    assert recommender.parse_query("best camera phone")["order_by"].startswith("camera_main_mp")


def test_implicit_need_is_understood():
    # No literal "camera" word, but "loves photos" should map to camera.
    assert recommender.parse_query("something for my mum who loves photos")["order_by"].startswith("camera_main_mp")
    # "travel a lot" should map to battery.
    assert recommender.parse_query("I travel a lot, need it to last")["order_by"].startswith("battery_mah")


def test_named_phone_is_surfaced():
    conn = make_conn()
    rows = recommender.candidates(conn, "is the iphone 14 good?")
    assert "iPhone 14" in models(rows)


def test_comparison_surfaces_both_phones():
    conn = make_conn()
    rows = recommender.candidates(conn, "compare galaxy a14 and redmi 10")
    assert {"Galaxy A14", "Redmi 10"} <= models(rows)


def test_multi_brand_filters_to_both():
    conn = make_conn()
    rows = recommender.candidates(conn, "samsung or xiaomi?")
    assert {r["brand"] for r in rows} == {"Samsung", "Xiaomi"}


def test_offtopic_message_does_not_crash():
    # Relevance is the model's call; retrieval must still return safely.
    conn = make_conn()
    rows = recommender.candidates(conn, "what is the weather today?")
    assert isinstance(rows, list) and rows


def test_order_by_is_always_whitelisted():
    for text in ["", "anything", "best CAMERA and battery", "arzon 300", "'; drop table"]:
        assert recommender.parse_query(text)["order_by"] in recommender.ALLOWED_ORDER


def test_sql_injection_is_harmless():
    conn = make_conn()
    rows = recommender.candidates(conn, "'; DROP TABLE phones; -- under 500")
    assert isinstance(rows, list)  # no crash
    assert conn.execute("SELECT COUNT(*) FROM phones").fetchone()[0] == len(SAMPLE)


def test_no_match_falls_back_to_budget():
    conn = make_conn()
    rows = recommender.candidates(conn, "nokia under 300")  # no Nokia in data
    assert rows and all(r["price_usd"] <= 300 for r in rows)


def test_read_only_connection_cannot_write():
    import sqlite3
    conn = recommender.connect(":memory:", read_only=True)
    try:
        conn.execute("CREATE TABLE x (a)")
        assert False, "read-only connection should reject writes"
    except sqlite3.OperationalError:
        pass


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all good")
