"""Capture Apps Store screenshots from a running Odoo.

Store screenshots are read at thumbnail size first and full size second,
so they are taken at a wide viewport and a 2x device scale: text stays
legible when the store scales the image down, which is where most store
listings lose the reader.
"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8169"
LOGIN, PASSWORD = "admin", "admin"
WIDTH, HEIGHT = 1500, 950


def login(page):
    # Odoo keeps a long poll open for the bus, so "networkidle" never
    # fires and every wait on it times out. Wait for the thing that
    # actually marks the page ready instead.
    page.goto(BASE + "/web/login", wait_until="domcontentloaded")
    page.fill("input[name='login']", LOGIN)
    page.fill("input[name='password']", PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_selector(".o_main_navbar", timeout=60000)


def settle(page, pause=1.4):
    page.wait_for_selector(".o_action_manager", timeout=60000)
    time.sleep(pause)


def shoot(page, path, clip_main=True):
    settle(page)
    page.screenshot(path=path, full_page=False)
    print("saved", path)


def main(targets):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": globals().get("WIDTH", 1500), "height": HEIGHT},
            device_scale_factor=2,
        )
        page = context.new_page()
        login(page)
        for name, action in targets:
            try:
                action(page)
                shoot(page, name)
            except Exception as exc:  # noqa: BLE001
                print("FAILED", name, exc, file=sys.stderr)
        browser.close()


if __name__ == "__main__":
    print("import this module and call main() with your own targets")
