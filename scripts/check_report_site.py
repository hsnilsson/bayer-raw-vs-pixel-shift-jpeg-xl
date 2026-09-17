"""Validate references against the directory actually uploaded to GitHub Pages."""
from __future__ import annotations

import argparse
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".rgb16le", ".gz", ".html"}


def asset_strings(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from asset_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from asset_strings(item)
    elif isinstance(value, str) and Path(urlsplit(value).path).suffix.lower() in ASSET_SUFFIXES:
        yield value


class PageReferences(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.references: set[str] = set()
        self.ids: set[str] = set()
        self.json_script = False
        self.script_parts: list[str] = []
        self.feed(text)
        self.close()
        # Standalone crop viewers embed a JSON file map in JavaScript.
        for match in re.finditer(r"\bconst files\s*=\s*", text):
            files, _ = json.JSONDecoder().raw_decode(text[match.end():])
            self.references.update(asset_strings(files))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        for name in ("href", "src", "data-normal", "data-highlight", "data-shadow"):
            if attributes.get(name):
                self.references.add(attributes[name])
        if tag == "script" and attributes.get("type") == "application/json":
            self.json_script = True
            self.script_parts = []

    def handle_data(self, data: str) -> None:
        if self.json_script:
            self.script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.json_script:
            self.references.update(asset_strings(json.loads("".join(self.script_parts))))
            self.json_script = False


def check_site(site: Path) -> tuple[int, list[str]]:
    site = site.resolve()
    files = {path.relative_to(site).as_posix(): path for path in site.rglob("*") if path.is_file()}
    pages = {name: PageReferences(path.read_text(encoding="utf-8"))
             for name, path in files.items() if path.suffix == ".html"}
    errors = []
    if "index.html" not in pages:
        errors.append("missing site/index.html")
    checked = 0
    for name, page in pages.items():
        for reference in sorted(page.references):
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                continue
            checked += 1
            path = unquote(url.path)
            if path.startswith("/") or "\\" in path:
                errors.append(f"{name} -> {reference}: not relative to the published site")
                continue
            # Keep the URL's spelling: Path.resolve() canonicalizes filename case
            # on Windows, which would hide a failure on GitHub Pages/Linux.
            target = Path(os.path.abspath(files[name].parent / path)) if path else files[name]
            try:
                target.resolve().relative_to(site)
                relative = target.relative_to(site).as_posix()
            except ValueError:
                errors.append(f"{name} -> {reference}: outside the published site")
                continue
            if target.is_dir():
                relative = (target / "index.html").relative_to(site).as_posix()
            # Compare exact names, even when running on a case-insensitive filesystem.
            if relative not in files:
                errors.append(f"{name} -> {reference}: missing file or incorrect filename case")
            elif url.fragment and relative in pages and unquote(url.fragment) not in pages[relative].ids:
                errors.append(f"{name} -> {reference}: missing section anchor")
    return checked, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    checked, errors = check_site(args.site)
    for error in errors:
        print(f"FAIL: {error}")
    print(f"Checked {checked} local references; {len(errors)} errors.")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
