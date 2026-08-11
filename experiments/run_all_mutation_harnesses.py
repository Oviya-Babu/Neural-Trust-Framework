"""Runs every mutation harness fresh and writes a single summary JSON
(artifacts/mutation_summary.json) for the dashboard (Phase E) and for a
one-command "is everything still green" check. Does not modify any
harness's own pass/fail behaviour -- this only captures their stdout kill-
rate line and aggregates it.

Run: python3 -m experiments.run_all_mutation_harnesses
"""

import pathlib
import re
import subprocess
import sys
import json

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESSES_DIR = REPO_ROOT / "harnesses"

HARNESSES = sorted(p.name for p in HARNESSES_DIR.glob("mutation_check*.py"))

KILL_RATE_RE = re.compile(r"(\d+)/(\d+)")


def main():
    results = []
    for name in HARNESSES:
        proc = subprocess.run([sys.executable, str(HARNESSES_DIR / name)], cwd=REPO_ROOT,
                               capture_output=True, text=True, timeout=180)
        first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
        m = KILL_RATE_RE.search(first_line)
        killed, total = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        results.append({"harness": name, "line": first_line, "killed": killed, "total": total,
                         "all_killed": (killed == total) if killed is not None else False,
                         "returncode": proc.returncode})
        print(f"{name}: {first_line}")

    out = {"harnesses": results, "all_100_percent": all(r["all_killed"] for r in results)}
    out_path = REPO_ROOT / "artifacts" / "mutation_summary.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
