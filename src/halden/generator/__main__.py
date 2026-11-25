"""Build the Halden Roasters raw files and ground truth.

    python -m halden.generator --out data

The build goes into a temporary folder first and only replaces data/raw and
data/ground_truth once every file is written, so a crash halfway never leaves
a mix of old and new files behind.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from halden.common.log import setup_logging

from . import config as cfg
from .defects import catalogue_frame
from .export import Exporter
from .truth import monthly_metrics
from .world import simulate

log = logging.getLogger("halden.generator")


def write_ground_truth(world, defects, root: Path):
    root.mkdir(parents=True)
    w = world
    w.persons.to_csv(root / "gt_persons.csv", index=False)
    w.accounts.to_csv(root / "gt_accounts.csv", index=False)
    w.subscriptions.to_csv(root / "gt_subscriptions.csv", index=False)
    w.orders.to_csv(root / "gt_orders.csv", index=False)
    w.order_lines.to_csv(root / "gt_order_lines.csv", index=False)
    w.transactions.to_csv(root / "gt_transactions.csv", index=False)
    w.shipments.to_csv(root / "gt_shipments.csv", index=False)
    w.assignments.to_csv(root / "gt_experiment_assignments.csv", index=False)
    defects.frame().to_csv(root / "gt_defects.csv", index=False)
    catalogue_frame().to_csv(root / "gt_defect_catalogue.csv", index=False)
    monthly_metrics(w).to_csv(root / "gt_monthly_metrics.csv", index=False)
    params = {"seed": cfg.SEED, "data_start": str(cfg.DATA_START), "data_end": str(cfg.DATA_END),
              "volumes": asdict(cfg.VOLUMES), "churn": asdict(cfg.CHURN), "payments": asdict(cfg.PAYMENTS),
              "fulfilment": asdict(cfg.FULFILMENT), "experiment": asdict(cfg.EXPERIMENT)}
    (root / "gt_parameters.json").write_text(json.dumps(params, indent=2, default=str) + "\n")


def build_summary(world, defects, landing) -> dict:
    """The headline numbers quoted in the docs. A test checks the docs against this file."""
    land = pd.DataFrame(landing.rows)
    acc = world.accounts
    per_person = acc.groupby("person_id").size()
    return {
        "persons": len(world.persons),
        "accounts": len(acc),
        "persons_with_account": int(per_person.size),
        "persons_with_multiple_accounts": int((per_person > 1).sum()),
        "duplicate_accounts": int(len(acc) - per_person.size),
        "subscriptions": len(world.subscriptions),
        "orders": len(world.orders),
        "transactions": len(world.transactions),
        "shipments": len(world.shipments),
        "experiment_assignments": len(world.assignments),
        "raw_files": len(land),
        "raw_megabytes": round(land["bytes"].sum() / 1e6, 1),
        "files_by_source": land.groupby("source").size().to_dict(),
        "defect_records": len(defects.rows),
        "defect_types": int(defects.frame()["defect_code"].nunique()),
    }


def checksums(folder: Path) -> list[str]:
    lines = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != "_checksums.sha256":
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(folder).as_posix()}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="data", type=Path)
    ap.add_argument("--seed", default=cfg.SEED, type=int)
    args = ap.parse_args(argv)
    setup_logging()
    t0 = time.perf_counter()
    out: Path = args.out
    build = out / f"_build_{int(time.time())}"
    if build.exists():
        shutil.rmtree(build)
    try:
        log.info("simulating seed=%d window=%s..%s", args.seed, cfg.DATA_START, cfg.DATA_END)
        world = simulate(args.seed)
        log.info("exporting raw files")
        defects, landing = Exporter(world, build / "raw", args.seed).run()
        write_ground_truth(world, defects, build / "ground_truth")
        summary = build_summary(world, defects, landing)
        (build / "ground_truth" / "gt_build_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        for sub in ("raw", "ground_truth"):
            (build / sub / "_checksums.sha256").write_text("\n".join(checksums(build / sub)) + "\n")
    except Exception:
        log.exception("build failed; nothing in %s was changed", out)
        shutil.rmtree(build, ignore_errors=True)
        return 1
    for sub in ("raw", "ground_truth"):
        target = out / sub
        if target.exists():
            shutil.rmtree(target)
        (build / sub).rename(target)
    build.rmdir()
    land = pd.DataFrame(landing.rows)
    log.info("done in %.1fs: files=%d bytes=%d defects=%d", time.perf_counter() - t0, len(land),
             int(land["bytes"].sum()), len(defects.rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
