"""Provision the six stores and HQ from stores.json. Run from any directory."""
import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".tea"
HQ = {"id": "hq", "name": "品牌總部", "port": 8100}


def registry():
    stores = json.loads((ROOT / "stores.json").read_text(encoding="utf-8"))
    ids, ports = {"hq"}, {HQ["port"]}
    if not isinstance(stores, list) or not stores:
        raise ValueError("至少需要一間分店")
    for row in stores:
        site, name, port = row["id"], row["name"], row["port"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,38}[a-z0-9]", site) or site in ids:
            raise ValueError(f"分店代號無效或重複：{site}")
        if not isinstance(name, str) or not name.strip() or not name.isprintable():
            raise ValueError("店名不可為空或含控制字元")
        if type(port) is not int or not 1024 <= port <= 65535 or port in ports:
            raise ValueError(f"連接埠無效或重複：{port}")
        if "report_url" in row:
            url = urlsplit(row["report_url"])
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("report_url 需為 HTTP(S) 端點")
        ids.add(site)
        ports.add(port)
    return stores


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                            dir=path.parent, delete=False) as stream:
        stream.write(content)
        temp = Path(stream.name)
    temp.replace(path)


def keys(site):
    directory = STATE / "keys"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (site + ".json")
    if not path.exists():
        secret = dict(ADMIN_PASSWORD=secrets.token_urlsafe(20), SESSION_KEY=secrets.token_hex(32))
        if site != "hq":
            secret["REPORT_KEY"] = secrets.token_hex(32)
        # Publish a complete key file without replacing another provisioner's keys.
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
            json.dump(secret, stream)
            temp = Path(stream.name)
        try:
            os.link(temp, path)
        except FileExistsError:
            pass
        finally:
            temp.unlink()
    return json.loads(path.read_text(encoding="utf-8"))


def settings(stores, local):
    nodes = {}
    peers = []
    for store in stores:
        site, port = store["id"], store["port"]
        auth = keys(site)
        nodes[site] = dict(SITE_ID=site, SITE_NAME=store["name"], **auth,
                           DB_PATH=str(STATE / "data" / site / "sales.sqlite") if local else "/data/sales.sqlite")
        default_url = f"http://127.0.0.1:{port}" if local else f"http://{site}:8080"
        peers.append(dict(id=site, name=store["name"], token=auth["REPORT_KEY"],
                          url=store.get("report_url", default_url)))
    nodes["hq"] = dict(SITE_ID="hq", SITE_NAME=HQ["name"], **keys("hq"),
                       PEERS=json.dumps(peers, ensure_ascii=False, separators=(",", ":")))
    return nodes


def initialize(stores):
    nodes = settings(stores, local=False)
    compose = {"name": "tea-chain", "services": {}, "networks": {}, "volumes": {}}
    for row in [HQ, *stores]:
        site = row["id"]
        values = []
        for k, v in nodes[site].items():
            quoted = v.replace("\\", "\\\\").replace("'", "\\'")
            values.append(f"{k}='{quoted}'")
        envfile = f".tea/env/{site}.env"
        write_file(ROOT / envfile, "\n".join(values) + "\n")
        node = {"image": "tea-chain-service:local", "pull_policy": "never",
                "env_file": [envfile], "ports": [f"127.0.0.1:{row['port']}:8080"],
                "restart": "unless-stopped",
                "healthcheck": {"test": ["CMD", "python", "-c",
                    "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/health',timeout=2).read()"],
                    "interval": "10s", "timeout": "4s", "start_period": "5s", "retries": 4}}
        if site == "hq":
            node["build"] = "."
            node["networks"] = ["net-" + s["id"] for s in stores]
        else:
            volume, network = "db-" + site, "net-" + site
            node["volumes"] = [volume + ":/data"]
            node["networks"] = [network]
            compose["volumes"][volume] = {}
            compose["networks"][network] = {}
            standalone = {"name": "tea-chain", "services": {site: dict(node, env_file=[site + ".env"])},
                          "volumes": {volume: {}}, "networks": {network: {}}}
            write_file(STATE / "env" / (site + ".compose.yaml"), json.dumps(standalone, indent=2) + "\n")
        compose["services"][site] = node
    write_file(ROOT / "compose.yaml", json.dumps(compose, indent=2, ensure_ascii=False) + "\n")
    print(f"Ready: HQ + {len(stores)} branches. See README.md for startup.")


def develop(stores):
    nodes = settings(stores, local=True)
    processes = []
    try:
        for row in [*stores, HQ]:
            process = subprocess.Popen([sys.executable, str(ROOT / "manage.py"), "_serve", str(row["port"])],
                                       env={**os.environ, **nodes[row["id"]]}, cwd=ROOT)
            processes.append(process)
        print("HQ: http://127.0.0.1:8100   |   Ctrl+C to stop", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.3)
        raise SystemExit("A service exited; check its output and port.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["init", "dev"]:
        sub.add_parser(command)
    sub.add_parser("password").add_argument("site")
    sub.add_parser("_serve", help=argparse.SUPPRESS).add_argument("port", type=int)
    args = parser.parse_args()
    if args.command == "_serve":
        from wsgiref.simple_server import make_server
        from tea.app import create_app
        with make_server("127.0.0.1", args.port, create_app()) as server:
            server.serve_forever()
        return
    stores = registry()
    if args.command == "init":
        initialize(stores)
    elif args.command == "dev":
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        develop(stores)
    else:
        path = STATE / "keys" / (args.site + ".json")
        if args.site not in {row["id"] for row in [*stores, HQ]} or not path.is_file():
            parser.error("未知的分店，或尚未執行 init")
        print(json.loads(path.read_text(encoding="utf-8"))["ADMIN_PASSWORD"])


if __name__ == "__main__":
    main()
