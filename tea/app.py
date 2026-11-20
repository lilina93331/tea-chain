import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime
from http import HTTPStatus
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import ledger
from .ledger import Problem

STATIC = Path(__file__).parent / "web"
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}


def encode(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()


def credentials_match(left, right):
    return hmac.compare_digest(left.encode(), right.encode())


def signature(secret, payload):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_session(secret):
    payload = f"{int(time.time()) + 8 * 3600}.{secrets.token_hex(12)}"
    return f"{payload}.{signature(secret, payload)}"


def valid_session(secret, token):
    try:
        expiry, nonce, sig = token.split(".")
        return int(expiry) > time.time() and credentials_match(sig, signature(secret, f"{expiry}.{nonce}"))
    except ValueError:
        return False


def read_json(env):
    if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
        raise Problem(415, "請使用 JSON 格式")
    try:
        size = int(env.get("CONTENT_LENGTH") or 0)
        if not 0 < size <= 32768:
            raise Problem(413, "請求內容大小超出限制")
        body = json.loads(env["wsgi.input"].read(size))
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, RecursionError):
        raise Problem(400, "JSON 格式錯誤") from None


def report_day(query):
    today = datetime.now(ledger.TAIPEI).date()
    value = parse_qs(query, keep_blank_values=True).get("day", [today.isoformat()])[0]
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return value
    except ValueError:
        raise Problem(400, "日期格式為 YYYY-MM-DD") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def pull_report(peer, day):
    request = Request(peer["url"].rstrip("/") + "/internal/report?" + urlencode({"day": day}),
                      headers={"Authorization": "Bearer " + peer["token"]})
    result = {"id": peer["id"], "name": peer["name"], "available": False}
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
            data = json.load(response)
        if data["branch"] != peer["id"] or data["day"] != day:
            return result
        metrics = {k: data[k] for k in ("orders", "cups", "revenue")}
        if any(type(v) is not int or v < 0 for v in metrics.values()):
            return result
        return dict(result, **metrics, available=True)
    except (OSError, URLError, ValueError, KeyError, TypeError, EOFError, HTTPException):
        return result


def chain_report(peers, day):
    with ThreadPoolExecutor(max_workers=min(16, len(peers))) as pool:
        rows = list(pool.map(lambda peer: pull_report(peer, day), peers))
    live = [r for r in rows if r["available"]]
    totals = {k: sum(r[k] for r in live) for k in ("orders", "cups", "revenue")}
    return dict(day=day, branches=rows, reporting=len(live), complete=len(live) == len(rows), **totals)


def create_app(config=None):
    env = os.environ if config is None else config
    site, name = env["SITE_ID"], env["SITE_NAME"]
    admin_pw, session_key = env["ADMIN_PASSWORD"], env["SESSION_KEY"]
    hq = site == "hq"
    peers = json.loads(env["PEERS"]) if hq else []
    dbfile = None if hq else env["DB_PATH"]
    internal_key = "" if hq else env["REPORT_KEY"]
    if not hq:
        ledger.initialize(dbfile, site)

    def api(e):
        path, method = e["PATH_INFO"], e["REQUEST_METHOD"]
        if (method, path) == ("GET", "/health"):
            return 200, {"status": "ok", "site": site}
        if (method, path) == ("GET", "/api/site"):
            data = dict(id=site, name=name, role="hq" if hq else "branch")
            if not hq:
                with closing(sqlite3.connect(dbfile)) as db:
                    data["menu"] = ledger.menu(db)
            return 200, data
        if (method, path) == ("POST", "/api/login"):
            password = read_json(e).get("password")
            if not isinstance(password, str) or not credentials_match(password, admin_pw):
                raise Problem(401, "密碼不正確")
            return 200, {"token": issue_session(session_key)}
        auth = e.get("HTTP_AUTHORIZATION", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if (method, path) == ("GET", "/internal/report") and not hq:
            if not credentials_match(internal_key, token):
                raise Problem(403, "需要總部查詢金鑰")
        elif not valid_session(session_key, token):
            raise Problem(401, "請先登入")
        if path in ("/api/report", "/internal/report") and method == "GET":
            day = report_day(e.get("QUERY_STRING", ""))
            if hq and path == "/api/report":
                return 200, chain_report(peers, day)
            if not hq:
                with closing(sqlite3.connect(dbfile)) as db, db:
                    return 200, ledger.report(db, site, day)
        if not hq and path in ("/api/specials", "/api/sales") and method == "POST":
            body = read_json(e)
            with closing(sqlite3.connect(dbfile, timeout=5)) as db, db:
                db.execute("PRAGMA foreign_keys=ON")
                if path == "/api/specials":
                    return 201, ledger.add_special(db, body)
                sale = ledger.record_sale(db, body)
                return (200 if sale["replay"] else 201), sale
        raise Problem(404, "找不到此路徑")

    def app(e, respond):
        mime = "application/json"
        try:
            if e["REQUEST_METHOD"] == "GET" and e["PATH_INFO"] in ASSETS:
                file, mime = ASSETS[e["PATH_INFO"]]
                status, body = 200, (STATIC / file).read_bytes()
            else:
                status, result = api(e)
                body = encode(result)
        except Problem as error:
            status, body = error.status, encode({"error": str(error)})
        except sqlite3.OperationalError:
            status, body = 503, encode({"error": "門市資料庫暫時無法使用，請稍後重試"})
        respond(f"{status} {HTTPStatus(status).phrase}", [
            ("Content-Type", mime + "; charset=utf-8"), ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
            ("Referrer-Policy", "no-referrer")])
        return [body]

    return app
