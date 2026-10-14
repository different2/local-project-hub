"""Guard every string the app and test runner can put on a console.

Windows defaults stdout to cp1252, which cannot encode the box-drawing and
ellipsis characters that had crept into the runner's failure output. Printing
one raised UnicodeEncodeError *from inside the failure path*, so CI exited 1
with a traceback and never reported which test actually failed.

That is the worst possible place for such a bug: it only fires when something
is already broken, and it destroys the evidence needed to diagnose it.

These tests keep all user-visible output ASCII-only and prove the runner's own
reporting survives a console that cannot encode anything above 0x7F.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

import run_all  # noqa: E402

SOURCE_FILES = sorted(PROJECT_ROOT.glob("hub/*.py")) + [
    PROJECT_ROOT / "main.py",
    HERE / "run_all.py",
]

# Matches print/emit/log/output calls, allowing for f-string prefixes and
# surrounding whitespace. Anchoring only on the opening quote right after the
# paren silently skipped every f-string, which is where the runner's box
# characters lived -- a guard that cannot see the bug is not a guard.
OUTPUT_CALL = re.compile(r"(?:emit|log|output|print)\s*\(\s*(?:[fFrRbBuU]{1,2})?(['\"])")


def test_no_non_ascii_in_output_strings() -> None:
    """No string handed to print/emit/output may contain non-ASCII."""
    offenders = []
    for path in SOURCE_FILES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in OUTPUT_CALL.finditer(line):
                quote = m.group(1)
                # crude but effective: everything after the call on this line
                rest = line[m.end() - 1 :]
                if any(ch > "\x7f" for ch in rest):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()[:90]}")
    assert not offenders, (
        "these output strings contain non-ASCII and will crash a cp1252 console:\n"
        + "\n".join(offenders)
    )


class _AsciiStdout:
    """A stdout that rejects non-ASCII, like the Windows cp1252 console.

    Enforcing at write time (rather than faking an `encoding` attribute) means
    the test fails for the same reason CI did, instead of passing because the
    real console happened to accept the character.
    """

    def __init__(self, sink) -> None:
        self._sink = sink

    def write(self, s: str) -> int:
        s.encode("ascii")  # raises UnicodeEncodeError exactly like cp1252 would
        self._sink(s)
        return len(s)

    def flush(self) -> None:
        pass


def test_emit_survives_a_console_that_cannot_encode() -> None:
    """run_all.emit must not raise when stdout cannot encode the text.

    Forced with a codec that rejects everything above ASCII, reproducing the
    Windows cp1252 failure exactly: the runner used to die here with
    UnicodeEncodeError instead of printing the test's failure detail.
    """
    written = []
    saved = sys.stdout
    sys.stdout = _AsciiStdout(written.append)
    try:
        run_all.emit("           \u2500\u2500 last output \u2500\u2500")
        run_all.emit("plain ascii is fine")
    finally:
        sys.stdout = saved
    joined = "".join(written)
    assert "-- last output --" in joined, "the box rule should degrade to ASCII"
    assert all(ord(c) < 128 for c in joined), "emit must never pass non-ASCII through"



def test_runner_reports_failures_under_an_ascii_only_console() -> None:
    """End to end: the runner still reports a failure under an ASCII console.

    Drives the real reporting path with stdout pointed at a codec that rejects
    everything above 0x7F, which reproduces the Windows cp1252 failure exactly.
    Before the fix the runner died with UnicodeEncodeError here instead of
    printing the test output that would have explained the failure.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        broken = tmp / "test_broken_on_purpose.py"
        broken.write_text(
            "import sys\n"
            "print('PASS test_fine')\n"
            "print('FAIL test_deliberate: this failure must be reported')\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        code, out = run_all.run_one(broken, needs_gui=False)
        assert code == 1, f"the deliberately broken suite should report exit 1, got {code}"

        saved, written = sys.stdout, []
        sys.stdout = _AsciiStdout(written.append)
        try:
            final = run_all.report_suite("test_broken_on_purpose.py", code, 1, 1, out)
        finally:
            sys.stdout = saved

        assert final == 1, "a real failure must keep the suite red"
        joined = "".join(written)
        assert "this failure must be reported" in joined, (
            "the failure detail was lost"
        )
        assert "-- last output --" in joined, "the failure header was not printed"
        assert all(ord(c) < 128 for c in joined), "output must be ASCII-only"




if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                # Only AssertionError used to be caught, so any other exception
                # killed the runner mid-suite: later tests never printed and the
                # summary claimed "N passed, 1 failed" with no FAIL line to name
                # the 1. An unexpected error is a failure -- report it as one.
                fails += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print("---", "FAILURES" if fails else "all passed")
    sys.exit(1 if fails else 0)
