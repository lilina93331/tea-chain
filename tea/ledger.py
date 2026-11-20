"""Each branch owns one SQLite ledger. Prices and names are snapshotted at sale."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

TAIPEI = timezone(timedelta(hours=8))
BASE = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
BASE_NAMES = {item["name"] for item in BASE}


class Problem(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def integer(value, upper, label):
    if type(value) is not int or not 1 <= value <= upper:
        raise Problem(400, f"{label}須為 1 到 {upper} 的整數")
    return value


def menu(db):
    special = db.execute("SELECT id, name, price FROM specials ORDER BY rowid")
    return [dict(**item, kind="共通") for item in BASE] + [
        dict(id=i, name=n, price=p, kind="特色") for i, n, p in special
    ]


def initialize(path, branch):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS identity (slot INTEGER PRIMARY KEY CHECK(slot=1), branch TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS specials (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, price INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sales (id TEXT PRIMARY KEY, payload TEXT NOT NULL, day TEXT NOT NULL,
                                               paid_at TEXT NOT NULL, total INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS sales_day ON sales(day);
            CREATE TABLE IF NOT EXISTS lines (sale TEXT NOT NULL REFERENCES sales(id), item TEXT NOT NULL,
                name TEXT NOT NULL, price INTEGER NOT NULL, qty INTEGER NOT NULL, PRIMARY KEY(sale,item));
        """)
        db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)", (branch,))
        if db.execute("SELECT branch FROM identity").fetchone()[0] != branch:
            raise ValueError("資料庫與門市代號不符")


def add_special(db, body):
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or not name.isprintable():
        raise Problem(400, "請輸入 1 至 40 個字的飲品名稱")
    name = name.strip()
    price = integer(body.get("price"), 9999, "單價")
    if name in BASE_NAMES:
        raise Problem(409, "已經有同名的共通飲品")
    item = dict(id=uuid.uuid4().hex, name=name, price=price, kind="特色")
    try:
        db.execute("INSERT INTO specials VALUES(:id,:name,:price)", item)
    except sqlite3.IntegrityError:
        raise Problem(409, "本店已經有同名飲品") from None
    return item


def record_sale(db, body):
    try:
        sale_id = str(uuid.UUID(body.get("request_id", "")))
    except (ValueError, TypeError, AttributeError):
        raise Problem(400, "交易識別碼無效") from None
    lines = body.get("items")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise Problem(400, "每筆交易需要 1 至 100 種飲品")
    quantities = {}
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("id"), str):
            raise Problem(400, "品項格式錯誤")
        item = line["id"]
        if item in quantities:
            raise Problem(400, "同一品項請合併數量")
        quantities[item] = integer(line.get("qty"), 999, "杯數")
    fingerprint = hashlib.sha256(json.dumps(quantities, sort_keys=True).encode()).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    previous = db.execute("SELECT payload, total, paid_at FROM sales WHERE id=?", (sale_id,)).fetchone()
    if previous:
        if previous[0] != fingerprint:
            raise Problem(409, "同一交易識別碼已用於其他內容")
        return dict(id=sale_id, total=previous[1], paid_at=previous[2], replay=True)
    catalog = {row["id"]: row for row in menu(db)}
    entries = []
    for item, qty in quantities.items():
        if item not in catalog:
            raise Problem(400, "菜單上找不到這款飲品")
        row = catalog[item]
        entries.append((sale_id, item, row["name"], row["price"], qty))
    total = sum(price * qty for _, _, _, price, qty in entries)
    now = datetime.now(TAIPEI)
    db.execute("INSERT INTO sales VALUES(?,?,?,?,?)",
               (sale_id, fingerprint, now.date().isoformat(), now.isoformat(), total))
    db.executemany("INSERT INTO lines VALUES(?,?,?,?,?)", entries)
    return dict(id=sale_id, total=total, paid_at=now.isoformat(), replay=False)


def report(db, branch, day):
    db.execute("BEGIN")  # Both queries observe the same committed snapshot.
    count, revenue = db.execute("SELECT count(*), coalesce(sum(total),0) FROM sales WHERE day=?", (day,)).fetchone()
    rows = db.execute("""
        SELECT l.name, sum(l.qty) AS cups, sum(l.qty*l.price) AS amount
        FROM lines l JOIN sales s ON s.id=l.sale WHERE s.day=?
        GROUP BY l.item,l.name ORDER BY cups DESC, l.name
    """, (day,))
    products = [dict(name=n, cups=c, revenue=a) for n, c, a in rows]
    return dict(branch=branch, day=day, orders=count, revenue=revenue,
                cups=sum(row["cups"] for row in products), products=products)
