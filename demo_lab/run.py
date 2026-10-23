"""Entry point, run INSIDE a buyer-agent interpreter (CONTRACTS.md):

    PYTHONPATH=<ba>/src:<ba>:<demo-lab> DATABASE_URL=sqlite:///<tmp> \
        <ba>/.venv/bin/python -m demo_lab.run --change pacing|creatives|negotiation|all \
        --label before|after|check --out <dir>

Writes <out>/<change>.<label>.json per change. Never crashes on a missing
feature: those are recorded as "not_available" / "error".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import common

CHANGES = ("pacing", "creatives", "negotiation")
LAB_VERSION = "1.0.0"


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


def buyer_agent_info(ba_dir: Path | None) -> dict[str, Any]:
    info: dict[str, Any] = {"python": platform.python_version(), "executable": sys.executable}
    try:
        import ad_buyer

        info["ad_buyer_file"] = ad_buyer.__file__
        info["ad_buyer_version"] = getattr(ad_buyer, "__version__", None)
        if ba_dir is None:
            ba_dir = Path(ad_buyer.__file__).resolve().parents[2]
    except Exception as exc:  # noqa: BLE001
        info["ad_buyer_import_error"] = str(exc)
    if ba_dir is not None:
        info["dir"] = str(ba_dir)
        info["git_sha"] = _git(["rev-parse", "HEAD"], ba_dir)
        info["git_branch"] = _git(["rev-parse", "--abbrev-ref", "HEAD"], ba_dir)
        st = _git(["status", "--porcelain"], ba_dir)
        info["uncommitted_files"] = None if st is None else len([ln for ln in st.splitlines() if ln.strip()])
    return info


async def _run_change(name: str, workdir: Path) -> dict[str, Any]:
    if name == "pacing":
        from .runners import pacing

        return await pacing.run(workdir)
    if name == "creatives":
        from .runners import creatives

        return await creatives.run()
    from .runners import negotiation

    return await negotiation.run()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_lab.run")
    ap.add_argument("--change", required=True, choices=[*CHANGES, "all"])
    ap.add_argument("--label", required=True, choices=["before", "after", "check"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--buyer-agent-dir", default=None)
    a = ap.parse_args(argv)

    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"demo-lab-{a.label}-"))
    if not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = f"sqlite:///{workdir / 'lab.db'}"
    common.install_network_guard()
    logging.disable(logging.WARNING)

    ba = buyer_agent_info(Path(a.buyer_agent_dir).resolve() if a.buyer_agent_dir else None)
    written = []
    for name in (CHANGES if a.change == "all" else (a.change,)):
        started = datetime.now(UTC)
        try:
            section = asyncio.run(_run_change(name, workdir))
            section.setdefault("status", "ok")
        except Exception as exc:  # noqa: BLE001
            section = common.error(exc)
        doc = {
            "lab": {"version": LAB_VERSION, "schema": 1},
            "change": name,
            "label": a.label,
            "buyer_agent": ba,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "database_url": os.environ["DATABASE_URL"],
            "network": {"outbound_attempts_blocked": list(common.NETWORK_ATTEMPTS)},
            "result": section,
        }
        path = out_dir / f"{name}.{a.label}.json"
        path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
        written.append(str(path))
    for p in written:
        print(p)
    sys.stdout.flush()
    sys.stderr.flush()
    # Hard exit: some buyer-agent dependencies register atexit handlers that
    # can hang interpreter shutdown (see ad_buyer/_telemetry_shim.py).
    os._exit(0)


if __name__ == "__main__":
    main()
