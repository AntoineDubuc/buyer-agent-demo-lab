"""Pass/fail acceptance check for one buyer-agent checkout.

    python -m demo_lab.check <buyer-agent-checkout> <pacing|creatives|negotiation|all> [--out DIR]
    python -m demo_lab.check --results <change>.<label>.json [...]   # evaluate files you already have

Runs the lab inside the checkout's own ``.venv/bin/python`` (empty environment,
throw-away SQLite database, network blocked), then prints one line per
criterion: ``PASS  <criterion> — <observed>`` or ``FAIL  <criterion> — <observed>``.
Exit code: 0 only if every criterion of every requested change passes; 1 if any
fails; 2 if the checkout cannot be run at all. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import acceptance

LAB_DIR = Path(__file__).resolve().parent.parent
RUN_TIMEOUT_SECONDS = 900


def run_lab(checkout: Path, change: str, out_dir: Path) -> tuple[int, str]:
    """Run ``demo_lab.run`` inside the checkout; return (exit code, stderr tail)."""
    py = checkout / ".venv" / "bin" / "python"
    work = Path(tempfile.mkdtemp(prefix="demo-lab-check-"))
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ.get("HOME", str(work)),
        "PYTHONPATH": os.pathsep.join([str(checkout / "src"), str(checkout), str(LAB_DIR)]),
        "DATABASE_URL": f"sqlite:///{work / 'lab.db'}",
    }
    proc = subprocess.run(
        [str(py), "-m", "demo_lab.run", "--change", change, "--label", "check", "--out", str(out_dir),
         "--buyer-agent-dir", str(checkout)],
        cwd=work, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS, check=False)
    return proc.returncode, "\n".join(proc.stderr.strip().splitlines()[-15:])


def load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def report(change: str, doc: dict[str, Any] | None) -> bool:
    checks = acceptance.evaluate(change, doc)
    ba = (doc or {}).get("buyer_agent") or {}
    where = Path(str(ba.get("dir") or "")).name
    sha = str(ba.get("git_sha") or "")[:12]
    print(f"== {change}" + (f"  (checkout {where}, commit {sha}, {ba.get('uncommitted_files')} uncommitted files)"
                            if where else ""))
    for c in checks:
        print(c.line())
    for n in acceptance.notes(change, doc):
        print(f"NOTE  {n}")
    ok = acceptance.passed(checks)
    print(f"{'PASS' if ok else 'FAIL'}  {change}: {sum(c.ok for c in checks)} of {len(checks)} criteria pass")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_lab.check", description=__doc__.split("\n\n")[0])
    ap.add_argument("checkout", nargs="?", help="path to a buyer-agent checkout (installed: uv sync --locked --extra dev)")
    ap.add_argument("change", nargs="?", choices=[*acceptance.CHANGES, "all"])
    ap.add_argument("--out", default=None, help="keep the raw result JSON here (default: a temp folder)")
    ap.add_argument("--results", nargs="+", default=None,
                    help="evaluate existing <change>.<label>.json files instead of running the lab")
    a = ap.parse_args(argv)

    if a.results:
        results = [(Path(p).name.split(".")[0], Path(p)) for p in a.results]
        bad = [n for n, _ in results if n not in acceptance.CHANGES]
        if bad:
            ap.error(f"result file names must start with one of {acceptance.CHANGES}: {bad}")
        return 0 if all([report(n, load(p)) for n, p in results]) else 1

    if not a.checkout or not a.change:
        ap.error("give a checkout path and a change (pacing, creatives, negotiation or all)")
    checkout = Path(a.checkout).expanduser().resolve()
    py = checkout / ".venv" / "bin" / "python"
    if not (checkout / "src" / "ad_buyer").is_dir() or not py.exists():
        print(f"FAIL  buyer-agent checkout is installed — {checkout.name}: needs src/ad_buyer and .venv/bin/python "
              "(run `uv sync --locked --extra dev` in the checkout)")
        return 2
    out_dir = Path(a.out).resolve() if a.out else Path(tempfile.mkdtemp(prefix="demo-lab-results-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    changes = list(acceptance.CHANGES) if a.change == "all" else [a.change]
    try:
        code, err = run_lab(checkout, a.change, out_dir)
    except subprocess.TimeoutExpired:
        code, err = -1, f"timed out after {RUN_TIMEOUT_SECONDS}s"
    results = {c: load(out_dir / f"{c}.check.json") for c in changes}
    if any(v is None for v in results.values()):
        print(f"FAIL  the lab ran — exit code {code}; {err or 'no results written'}")
        return 2
    oks = [report(c, results[c]) for c in changes]
    print(f"RESULT: {'PASS' if all(oks) else 'FAIL'}  ({checkout.name}: "
          + ", ".join(f"{c} {'PASS' if ok else 'FAIL'}" for c, ok in zip(changes, oks)) + ")")
    print(f"Raw results: {out_dir}")
    return 0 if all(oks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
