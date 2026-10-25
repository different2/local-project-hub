"""Audit the real suite runner without accepting a crash after printed PASS.

Output files contain ACTUAL subprocess results. Simulated verifier controls live
in tests/test_release_artifacts.py and never enter this evidence directory.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def child_is_clean(code: int, output: str) -> bool:
    return (code == 0 and bool(re.search(r"(?m)^(?:PASS|SKIP)\s+\w+", output))
            and not re.search(r"(?m)^(?:FAIL|ERROR)\s+\w+", output))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    subprocess.run(["git", "diff", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root, check=True)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tmp = out / "tmp"
    tmp.mkdir()
    os.environ.update({"LOCAL_PROJECT_HUB_HOME": str(out / "state"),
                       "TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp)})
    spec = importlib.util.spec_from_file_location("audited_runner", root / "tests/run_all.py")
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    setattr(runner, "interpreter", lambda: sys.executable)
    original = getattr(runner, "run_one")
    records = []

    def observed(*pos, **kw):
        code, output = original(*pos, **kw)
        path = pos[0] if pos else kw["path"]
        extra = pos[2] if len(pos) > 2 else kw.get("extra_args", [])
        log = out / f"{len(records):03d}-{Path(path).name}.log"
        log.write_text(output, encoding="utf-8")
        records.append({"suite": Path(path).name, "args": extra, "exit_code": code,
                        "passed": re.findall(r"(?m)^PASS\s+(\w+)", output),
                        "skipped": re.findall(r"(?m)^SKIP\s+(\w+)", output),
                        "failed": re.findall(r"(?m)^(?:FAIL|ERROR)\s+(\w+)", output),
                        "clean": child_is_clean(code, output), "log": str(log)})
        (out / "raw-child-results.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"RAW_CHILD suite={Path(path).name} args={extra} exit={code}", flush=True)
        return code, output

    setattr(runner, "run_one", observed)
    result = runner.main()
    unchanged = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() == head
    bad = [record for record in records if not record["clean"]]
    strict = 0 if result == 0 and records and not bad and unchanged else 1
    summary = {"source_head": head, "source_head_unchanged": unchanged,
               "interpreter": sys.executable, "ordinary_runner_exit": result,
               "raw_children": len(records), "raw_nonzero_or_failed": bad,
               "passed": sum(len(r["passed"]) for r in records),
               "skipped": sum(len(r["skipped"]) for r in records),
               "failed": sum(len(r["failed"]) for r in records), "strict_exit": strict}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    return strict


if __name__ == "__main__":
    raise SystemExit(main())
