"""Read-only end-to-end check against a running default six-store deployment."""
import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
opener = build_opener(ProxyHandler({}))


def request(port, path, **options):
    with opener.open(Request(f"http://127.0.0.1:{port}{path}", **options), timeout=15) as response:
        return json.load(response)


def check(condition, message):
    if not condition:
        sys.exit(message)


def main():
    stores = json.loads((ROOT / "stores.json").read_text(encoding="utf-8"))
    base = json.loads((ROOT / "tea" / "catalog.json").read_text(encoding="utf-8"))
    for row in stores:
        site = request(row["port"], "/api/site")
        check(site["id"] == row["id"], "Unexpected branch identity")
        common = [{k:v for k,v in item.items() if k != "kind"} for item in site["menu"] if item["kind"] == "共通"]
        check(common == base, "Brand menu mismatch")
        print("OK", site["id"])
    keys = json.loads((ROOT / ".tea/keys/hq.json").read_text(encoding="utf-8"))
    session = request(8100, "/api/login", data=json.dumps({"password":keys["ADMIN_PASSWORD"]}).encode(),
                      headers={"Content-Type":"application/json"})
    report = request(8100, "/api/report", headers={"Authorization":"Bearer " + session["token"]})
    check(report["complete"] and report["reporting"] == len(stores), "HQ received a partial report")
    print(f"OK HQ: {len(stores)}/{len(stores)} branches reporting")


if __name__ == "__main__":
    main()
