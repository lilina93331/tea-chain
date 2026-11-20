"""Run only against a fresh demo deployment. This UI test records a real test sale."""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def login(page, site, role):
    password = json.loads((ROOT / ".tea/keys" / (site+".json")).read_text())["ADMIN_PASSWORD"]
    page.get_by_role("button", name=role+"登入", exact=True).click()
    page.get_by_label("管理密碼").fill(password)
    page.get_by_role("button", name="登入", exact=True).click()


def main():
    if os.environ.get("TEA_TEST_DISPOSABLE") != "1":
        raise SystemExit("Use a fresh, disposable test deployment.")
    with sync_playwright() as runner:
        browser = runner.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width":390, "height":844})
        page.goto("http://127.0.0.1:8104")
        expect(page.get_by_role("heading", name="台北店")).to_be_visible()
        expect(page.get_by_text("開心奶茶", exact=True)).to_be_visible()
        login(page, "taipei", "店長")
        page.get_by_role("button", name="新增飲品").click()
        page.get_by_label("飲品名稱").fill("桂花烏龍")
        page.get_by_label("單價（新臺幣）").fill("80")
        page.get_by_role("button", name="加入本店菜單").click()
        expect(page.get_by_text("桂花烏龍",exact=True)).to_be_visible()
        page.get_by_role("button", name="收銀", exact=True).click()
        page.get_by_label("開心奶茶杯數").fill("2")
        page.get_by_label("桂花烏龍杯數").fill("1")
        page.get_by_role("button", name="確認收款並入帳").click()
        expect(page.get_by_role("status")).to_contain_text("已入帳 NT$ 220")
        page.get_by_role("button", name="營收", exact=True).click()
        expect(page.get_by_role("cell", name="NT$ 140", exact=True)).to_be_visible()
        page.get_by_role("button", name="登出").click()
        expect(page.get_by_role("button", name="店長登入")).to_be_visible()
        page.goto("http://127.0.0.1:8106")
        expect(page.get_by_text("本店尚未推出限定飲品。")).to_be_visible()
        page.goto("http://127.0.0.1:8100")
        login(page, "hq", "老闆")
        expect(page.get_by_role("row").filter(has_text="台北店")).to_contain_text("NT$ 220")
        browser.close()
    print("OK browser: specialty, checkout, branch isolation, HQ revenue")


if __name__ == "__main__":
    main()
