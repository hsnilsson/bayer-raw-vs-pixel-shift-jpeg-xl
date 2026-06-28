from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "testdata/download_manifest.json"
DEFAULT_LOCK = ROOT / "testdata/downloaded_manifest.json"
USER_AGENT = "jpegxl-vs-dngpixelshift-testdata/0.1"
GITHUB_REGULAR_GIT_HARD_LIMIT = 100 * 1024 * 1024
RETRYABLE_ERRORS = (
    TimeoutError,
    OSError,
    http.client.HTTPException,
    urllib.error.URLError,
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_lock_records(lock_file: Path, new_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    if lock_file.exists():
        try:
            existing = read_json(lock_file)
            for record in existing.get("files", []):
                key = record.get("path") or record.get("id")
                if key:
                    merged[str(key)] = record
        except (json.JSONDecodeError, OSError):
            pass
    for record in new_records:
        key = record.get("path") or record.get("id")
        if key:
            merged[str(key)] = record
    return [merged[key] for key in sorted(merged)]


def request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe relative path in manifest: {path}")
    return candidate


def download(url: str, destination: Path, force: bool) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        return {
            "status": "exists",
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
        }

    tmp = destination.with_suffix(destination.suffix + ".download")
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request(url), timeout=60) as response:
                with tmp.open("wb") as f:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
            os.replace(tmp, destination)
            break
        except RETRYABLE_ERRORS:
            if tmp.exists():
                tmp.unlink()
            if attempt == 3:
                raise
            time.sleep(1.5 * attempt)

    return {
        "status": "downloaded",
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def write_sidecar(destination: Path, entry: dict[str, Any], result: dict[str, Any]) -> None:
    sidecar = destination.with_suffix(destination.suffix + ".source.json")
    data = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "file": str(destination.relative_to(ROOT)),
        "url": entry["url"],
        "source_page": entry.get("source_page"),
        "rights": entry.get("rights"),
        "role": entry.get("role"),
        "bytes": result["bytes"],
        "sha256": result["sha256"],
    }
    write_json(sidecar, data)


def warn_if_github_large(path: Path, size: int) -> None:
    if size > GITHUB_REGULAR_GIT_HARD_LIMIT:
        print(
            f"  warning: {path} is {size / 1024 / 1024:.1f} MiB; "
            "regular GitHub pushes block files over 100 MiB. This repo marks "
            "testdata images for Git LFS; otherwise use release assets."
        )


def download_direct_entries(
    manifest: dict[str, Any],
    out_dir: Path,
    force: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry in manifest.get("direct_downloads", []):
        relative = safe_relative_path(entry["path"])
        destination = out_dir / relative
        print(f"{entry['id']}: {entry['url']}")
        print(f"  -> {destination}")
        if dry_run:
            continue

        result = download(entry["url"], destination, force=force)
        expected = entry.get("sha256")
        if expected and expected.lower() != result["sha256"].lower():
            raise RuntimeError(
                f"sha256 mismatch for {destination}: "
                f"expected {expected}, got {result['sha256']}"
            )
        write_sidecar(destination, entry, result)
        warn_if_github_large(destination, result["bytes"])
        records.append({"id": entry["id"], **entry, **result, "path": str(relative)})
    return records


def fetch_json(url: str) -> dict[str, Any]:
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request(url), timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except RETRYABLE_ERRORS:
            if attempt == 3:
                raise
            time.sleep(1.5 * attempt)
    raise RuntimeError("unreachable retry loop")


def iter_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(iter_strings(item))
    return found


def extension_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for extension in [".tif", ".tiff", ".jp2", ".jxl", ".png", ".jpg", ".jpeg"]:
        if path.endswith(extension):
            return extension
    return ""


def without_fragment(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def loc_derived_urls(url: str) -> list[str]:
    candidates: list[str] = []
    clean = without_fragment(url)

    if "/image-services/iiif/" in clean and "/pct:" in clean:
        candidates.append(re.sub(r"/full/pct:[^/]+/0/default\.jpg$", "/full/full/0/default.jpg", clean))

    for match in re.finditer(r"(?:resource/|loc\.pnp/)([a-z0-9]+)\.(\d+)", clean):
        collection, number = match.groups()
        bucket = f"{(int(number) // 100) * 100:05d}"
        base = f"https://tile.loc.gov/storage-services"
        candidates.extend(
            [
                f"{base}/master/pnp/{collection}/{bucket}/{number}a.tif",
                f"{base}/master/pnp/{collection}/{bucket}/{number}.tif",
                f"{base}/service/pnp/{collection}/{bucket}/{number}v.jpg",
                f"{base}/service/pnp/{collection}/{bucket}/{number}r.jpg",
            ]
        )

    return candidates


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def score_image_url(url: str, preferred_extensions: list[str]) -> int:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return -1
    extension = extension_from_url(url)
    if not extension:
        return -1

    lower = url.lower()
    score = 0
    if extension in preferred_extensions:
        score += (len(preferred_extensions) - preferred_extensions.index(extension)) * 100
    else:
        score += 10
    if "loc.gov" in parsed.netloc:
        score += 20
    if "/master/" in lower or "/original/" in lower:
        score += 60
    if "/image-services/iiif/" in lower and "/full/full/" in lower:
        score += 40
    if "/pct:" in lower:
        score -= 80
    if "thumb" in lower or "small" in lower:
        score -= 50
    return score


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:80] or fallback


def resolve_loc_records(query: dict[str, Any], count: int) -> list[dict[str, Any]]:
    api_url = query["api_url"]
    preferred = [item.lower() for item in query.get("prefer_extensions", [])]
    records: list[dict[str, Any]] = []

    page = 1
    while len(records) < count:
        url = api_url
        separator = "&" if "?" in url else "?"
        if "sp=" not in url:
            url = f"{url}{separator}sp={page}"
        data = fetch_json(url)
        results = data.get("results", [])
        if not results:
            break

        for item in results:
            raw_urls = [s for s in iter_strings(item) if s.startswith(("http://", "https://"))]
            expanded_urls = raw_urls[:]
            for raw_url in raw_urls:
                expanded_urls.extend(loc_derived_urls(raw_url))
            urls = sorted(
                unique_preserve_order(expanded_urls),
                key=lambda s: score_image_url(s, preferred),
                reverse=True,
            )
            urls = [u for u in urls if score_image_url(u, preferred) >= 0]
            if not urls:
                continue

            image_url = urls[0]
            extension = extension_from_url(image_url) or ".img"
            title = item.get("title") or item.get("item", {}).get("title") or query["id"]
            item_url = item.get("url") or item.get("id")
            identifier = item.get("id") or item.get("number") or title
            base_name = slugify(str(identifier).split("/")[-1] or title, f"loc-{len(records)+1}")
            records.append(
                {
                    "id": f"{query['id']}-{len(records)+1}",
                    "url": image_url,
                    "candidate_urls": urls[:8],
                    "path_base": str(Path(query["path"]) / base_name),
                    "path": str(Path(query["path"]) / f"{base_name}{extension}"),
                    "source_page": item_url,
                    "rights": query.get("rights"),
                    "role": query.get("role"),
                    "loc_title": title,
                    "loc_item": item,
                }
            )
            if len(records) >= count:
                break

        page += 1
        time.sleep(0.25)

    return records


def download_loc_entries(
    manifest: dict[str, Any],
    out_dir: Path,
    force: bool,
    dry_run: bool,
    loc_count: int | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for query in manifest.get("loc_queries", []):
        count = loc_count if loc_count is not None else int(query.get("count", 1))
        print(f"{query['id']}: resolving {count} Library of Congress image(s)")
        resolved = resolve_loc_records(query, count=count) if not dry_run else []
        if dry_run:
            print(f"  API: {query['api_url']}")
            continue
        if not resolved:
            raise RuntimeError(f"LOC query {query['id']} did not resolve any image files")

        for entry in resolved:
            print(f"  {entry.get('loc_title', entry['id'])}")
            errors: list[str] = []
            result: dict[str, Any] | None = None
            destination: Path | None = None
            used_url: str | None = None
            for candidate_url in entry.get("candidate_urls", [entry["url"]]):
                extension = extension_from_url(candidate_url) or extension_from_url(entry["url"]) or ".img"
                relative = safe_relative_path(f"{entry.get('path_base', Path(entry['path']).with_suffix(''))}{extension}")
                candidate_destination = out_dir / relative
                print(f"  trying {candidate_url}")
                try:
                    result = download(candidate_url, candidate_destination, force=force)
                    destination = candidate_destination
                    used_url = candidate_url
                    break
                except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                    errors.append(f"{candidate_url}: {exc}")
            if result is None or destination is None or used_url is None:
                raise RuntimeError(
                    "all LOC image candidates failed for "
                    f"{entry['id']}:\n" + "\n".join(errors)
                )
            entry["url"] = used_url
            entry["path"] = str(destination.relative_to(out_dir))
            print(f"  -> {destination}")
            write_sidecar(destination, entry, result)
            warn_if_github_large(destination, result["bytes"])
            public_entry = {k: v for k, v in entry.items() if k != "loc_item"}
            records.append({**public_entry, **result, "path": str(relative)})
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download public test data for the JPEG XL vs DNG/PixelShift project."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=ROOT)
    parser.add_argument("--force", action="store_true", help="redownload existing files")
    parser.add_argument("--dry-run", action="store_true", help="print planned downloads")
    parser.add_argument(
        "--include-loc",
        action="store_true",
        help="also resolve and download Library of Congress public-domain images",
    )
    parser.add_argument(
        "--loc-count",
        type=int,
        default=None,
        help="override number of LOC images per query",
    )
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="download only deterministic direct URLs; this is the default",
    )
    parser.add_argument(
        "--skip-direct",
        action="store_true",
        help="skip deterministic direct URLs; useful when testing LOC resolution",
    )
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = read_json(args.manifest)
    records: list[dict[str, Any]] = []

    if not args.skip_direct:
        records.extend(
            download_direct_entries(
                manifest=manifest,
                out_dir=args.out_dir,
                force=args.force,
                dry_run=args.dry_run,
            )
        )

    if args.include_loc and not args.direct_only:
        records.extend(
            download_loc_entries(
                manifest=manifest,
                out_dir=args.out_dir,
                force=args.force,
                dry_run=args.dry_run,
                loc_count=args.loc_count,
            )
        )

    if not args.dry_run:
        merged_records = merge_lock_records(args.lock_file, records)
        lock = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "manifest": str(args.manifest.relative_to(ROOT) if args.manifest.is_relative_to(ROOT) else args.manifest),
            "files": merged_records,
        }
        write_json(args.lock_file, lock)
        print(f"Wrote {args.lock_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
