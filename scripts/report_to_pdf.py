#!/usr/bin/env python3
"""Turn a downloaded player report into a print-ready landscape PDF.

    python3 scripts/report_to_pdf.py ~/Downloads/owen_bailey_25_26_report.html

RUNS ON THE HOST, NOT IN DOCKER. It drives headless Chromium through Playwright, which is
installed on the machine rather than in the container. That is deliberate: it means the
platform's image gains no rendering dependency, and the PDF comes out of the same engine a
person gets when they print the page from their own browser -- so what you send and what
they would have printed are the same document.

If the output path is omitted the PDF is written beside the HTML with the same stem.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:                                        # pragma: no cover
        sys.exit("Playwright is not installed on this machine. Install it with:\n"
                 "    pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        # print_background keeps the masthead's red bar, which is the document's identity;
        # without it the page prints as anonymous black text on white.
        page.pdf(path=str(pdf_path), landscape=True, format="A4",
                 print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("html", type=Path, help="the downloaded report .html file")
    parser.add_argument("pdf", type=Path, nargs="?", default=None,
                        help="output path (default: alongside the HTML)")
    args = parser.parse_args()

    if not args.html.exists():
        sys.exit(f"no such file: {args.html}")

    pdf_path = args.pdf or args.html.with_suffix(".pdf")
    to_pdf(args.html, pdf_path)
    size_kb = pdf_path.stat().st_size / 1024
    print(f"wrote {pdf_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
