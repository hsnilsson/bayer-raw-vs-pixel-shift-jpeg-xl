"""Remove only superseded generated assets after validating the replacement.

Default is a dry run. Original captures, encodes, results and metadata history
are outside the strictly confined site/assets deletion scope.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from check_verified_release import check
from incremental_cache import atomic_write_json,sha256_file


def prune(site,apply=False):
    site=site.resolve();check(site)
    if site!=(ROOT/"site").resolve():raise ValueError("Pruning is limited to this checkout's generated site")
    release=json.loads((site/"data/release.json").read_text(encoding="utf-8"))
    build=json.loads((site/"data/site-build.json").read_text(encoding="utf-8"))
    keep=set(release["asset_hashes"])|set(build["redirects"])
    scope=(site/"assets").resolve();remove=[]
    for path in scope.rglob("*"):
        if not path.is_file():continue
        if not path.resolve().is_relative_to(scope) or path.is_symlink():raise ValueError("Unsafe generated asset target")
        relative=path.relative_to(site).as_posix()
        if relative not in keep:remove.append({"file":relative,"bytes":path.stat().st_size,"sha256":sha256_file(path)})
    receipt={"release_id":release["run_id"],"files":remove,"bytes":sum(p["bytes"] for p in remove),"applied":apply}
    atomic_write_json(ROOT/"results/site-prune.json",receipt)
    if apply:
        for item in remove:
            path=site/item["file"]
            if not path.resolve().is_relative_to(scope):raise ValueError("Target escaped generated assets")
            path.unlink()
    print(json.dumps({"files":len(remove),"MiB":receipt["bytes"]/2**20,"applied":apply}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    prune(ROOT/"site",parser.parse_args().apply)
