"""Prove an unchanged complete local rebuild skips every heavy stage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"scripts")]
import rebuild_verified_report as rebuild
from incremental_cache import fingerprint,sha256_file
from run_responsive import lower_priority


def main():
    lower_priority()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results",type=Path,default=ROOT/"results/verified_report")
    args=p.parse_args()
    environment=json.loads((args.results/"environment.json").read_text(encoding="utf-8"))
    for relative,expected in environment["code"].items():
        if sha256_file(ROOT/relative)!=expected:raise ValueError("Analysis code changed: "+relative)
    inventory=json.loads((args.results/"private_inventory.json").read_text(encoding="utf-8"))["frames"]
    run_args=SimpleNamespace(results=args.results,level=rebuild.LEVELS,scratch=args.results,tools=Path("unused"))
    reject=AssertionError("Unchanged rebuild attempted a heavy stage")
    with patch.object(rebuild,"prepare_scopes",side_effect=reject),patch.object(rebuild,"prepare_candidate",side_effect=reject),patch.object(rebuild,"run",side_effect=reject):
        for item in inventory:
            directory=args.results/item["slug"]/item["set_id"]
            before={p:sha256_file(p) for p in directory.glob("*.json")}
            audit=json.loads((directory/"source_audit.json").read_text(encoding="utf-8"))
            rebuild.process_frame(audit,run_args,fingerprint(environment))
            if any(sha256_file(p)!=expected for p,expected in before.items()):raise ValueError("Reuse changed a checkpoint")
    print(f"Verified {len(inventory)} unchanged frames: no rendering, encoding, decoding or metric preparation")
    return 0


if __name__=="__main__":raise SystemExit(main())
