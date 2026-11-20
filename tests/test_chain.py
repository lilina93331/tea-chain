import json
import secrets
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import manage
from tea import ledger
from tea.app import create_app


class Silent(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class Threaded(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Node:
    def __init__(self, config):
        self.config = config
        self.server = make_server("127.0.0.1", 0, create_app(config), Threaded, Silent)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.worker.start()
        self.token = self.call("/api/login", {"password":config["ADMIN_PASSWORD"]})[1]["token"]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()

    def call(self, path, body=None, token=None):
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type":"application/json", "Authorization":"Bearer " + (token or "")})
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=8)
        except HTTPError as err:
            response = err
        with response:
            return response.status, json.load(response)


class ChainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.nodes, peers = [], []
        for row in manage.registry():
            config = dict(SITE_ID=row["id"], SITE_NAME=row["name"], DB_PATH=str(Path(tmp.name) / (row["id"]+".db")),
                          ADMIN_PASSWORD=secrets.token_urlsafe(), SESSION_KEY=secrets.token_hex(), REPORT_KEY=secrets.token_hex())
            node = Node(config)
            self.addCleanup(node.close)
            self.nodes.append(node)
            peers.append(dict(id=row["id"], name=row["name"], token=config["REPORT_KEY"], url=node.url))
        self.hq = Node(dict(SITE_ID="hq", SITE_NAME="品牌總部", ADMIN_PASSWORD=secrets.token_urlsafe(),
                            SESSION_KEY=secrets.token_hex(), PEERS=json.dumps(peers)))
        self.addCleanup(self.hq.close)

    def test_fixed_menu_and_local_specials(self):
        expected = [("開心奶茶",70),("快樂紅茶",55),("烏龍綠茶",60),("茉莉花茶",70),("甘蔗青茶",65)]
        a, b = self.nodes[:2]
        for node in self.nodes:
            self.assertEqual([(i["name"],i["price"]) for i in node.call("/api/site")[1]["menu"]], expected)
        item = {"name":"桂花烏龍", "price":80}
        self.assertEqual(a.call("/api/specials", item, a.token)[0], 201)
        self.assertEqual(a.call("/api/specials", item, a.token)[0], 409)
        self.assertEqual(a.call("/api/specials", dict(name="開心奶茶", price=1), a.token)[0], 409)
        self.assertEqual(a.call("/api/specials", dict(name="其他", price=-1), a.token)[0], 400)
        self.assertEqual(len(a.call("/api/site")[1]["menu"]), 6)
        self.assertEqual(len(b.call("/api/site")[1]["menu"]), 5)

    def test_roles_and_report_date(self):
        a, b = self.nodes[:2]
        for token in [None, b.token, self.hq.token, a.config["REPORT_KEY"]]:
            self.assertEqual(a.call("/api/report", token=token)[0], 401)
        self.assertEqual(self.hq.call("/api/report", token=a.token)[0], 401)
        self.assertEqual(a.call("/internal/report", token=a.token)[0], 403)
        self.assertEqual(a.call("/internal/report", token=b.config["REPORT_KEY"])[0], 403)
        self.assertEqual(a.call("/api/login", {"password":"nope"})[0], 401)
        self.assertEqual(a.call("/api/report?day=bad", token=a.token)[0], 400)
        self.assertEqual(a.call("/api/sales", {}, b.token)[0], 401)
        self.assertEqual(a.call("/api/specials", {}, None)[0], 401)

    def test_concurrent_retry_price_snapshot_and_aggregation(self):
        a, b = self.nodes[:2]
        special = a.call("/api/specials", {"name":"桂花烏龍","price":80}, a.token)[1]
        order = dict(request_id=str(uuid.uuid4()), items=[dict(id="milk",qty=2,price=1),dict(id=special["id"],qty=1)])
        with ThreadPoolExecutor(max_workers=5) as pool:
            receipts = list(pool.map(lambda _: a.call("/api/sales", order, a.token), range(5)))
        self.assertEqual(sorted(s for s, _ in receipts), [200,200,200,200,201])
        self.assertEqual({r["total"] for _, r in receipts}, {220})
        order["items"][0]["qty"] = 1
        self.assertEqual(a.call("/api/sales", order, a.token)[0], 409)
        order["request_id"] = str(uuid.uuid4())
        self.assertEqual(b.call("/api/sales", order, b.token)[0], 400)
        order["items"] = [dict(id="black", qty=1)]
        self.assertEqual(b.call("/api/sales", order, b.token)[1]["total"], 55)
        report = self.hq.call("/api/report", token=self.hq.token)[1]
        self.assertTrue(report["complete"])
        self.assertEqual((report["reporting"],report["orders"],report["cups"],report["revenue"]), (len(self.nodes),2,4,275))
        details = a.call("/api/report", token=a.token)[1]
        self.assertEqual(details["day"], datetime.now(ledger.TAIPEI).date().isoformat())
        self.assertEqual(sorted((p["name"],p["cups"],p["revenue"]) for p in details["products"]),
                         sorted([("開心奶茶",2,140),("桂花烏龍",1,80)]))
        self.assertEqual(self.hq.call("/api/report?day=2000-01-01", token=self.hq.token)[1]["revenue"], 0)
        # A new application instance on the same volume must preserve the ledger and catalog.
        restarted = Node(a.config)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.call("/api/report", token=restarted.token)[1]["revenue"], 220)
        self.assertEqual(len(restarted.call("/api/site")[1]["menu"]), 6)
        with self.assertRaises(ValueError):
            ledger.initialize(a.config["DB_PATH"], "wrong-store")

    def test_outage_and_recovery(self):
        a, b = self.nodes[:2]
        order = dict(request_id=str(uuid.uuid4()), items=[dict(id="black",qty=2)])
        self.assertEqual(a.call("/api/sales", order, a.token)[0], 201)
        a.close()
        self.assertEqual(b.call("/api/sales", order, b.token)[0], 201)
        partial = self.hq.call("/api/report", token=self.hq.token)[1]
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["reporting"], len(self.nodes)-1)
        self.assertFalse(partial["branches"][0]["available"])
        self.assertNotIn("revenue", partial["branches"][0])
        self.assertEqual(partial["revenue"], 110)
        # Same endpoint and persistent database reconnect without resending any sales.
        server = make_server("127.0.0.1", a.server.server_port, create_app(a.config), Threaded, Silent)
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval":0.02}, daemon=True)
        worker.start()
        try:
            complete = self.hq.call("/api/report", token=self.hq.token)[1]
            self.assertTrue(complete["complete"])
            self.assertEqual(complete["revenue"], 220)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
