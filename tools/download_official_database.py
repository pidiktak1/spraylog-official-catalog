#!/usr/bin/env python3
"""Download and extract the current official ΥΠΑΑΤ pesticide database."""

from pathlib import Path
from zipfile import ZipFile

from playwright.sync_api import sync_playwright

SOURCE = "https://1click.minagric.gr/oneClickUI/frmFytoPro.zul"


def main():
    output = Path("catalog-build")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "official-database.zip"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(SOURCE, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3000)
        with page.expect_download(timeout=120_000) as download_info:
            page.get_by_text("εδώ", exact=True).click(timeout=120_000)
        download_info.value.save_as(archive)
        browser.close()

    with ZipFile(archive) as zipped:
        member = next(name for name in zipped.namelist() if name.lower().endswith(".mdb"))
        with zipped.open(member) as source, (output / "official.mdb").open("wb") as destination:
            while block := source.read(1024 * 1024):
                destination.write(block)


if __name__ == "__main__":
    main()
