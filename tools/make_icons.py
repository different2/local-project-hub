#!/usr/bin/env python3
"""Build the Local Project Hub icon files from the approved source art.

This script RESIZES AND WRAPS ONLY. It does not crop, recolour, or otherwise
alter the artwork — the transparent-background version the artist approved is
used exactly as supplied. Any stray transparent margin is trimmed, since that
is not artwork.

Produces:
  macOS   assets/icon.icns       (16 → 1024)
  Windows assets/icon.ico        (16 → 256)
  Linux   assets/icon.png        (512)
  source  assets/icon_1024.png   (master, reused by the About dialog/taskbar)

Usage:
    python3 tools/make_icons.py [source.png]
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required:  ./.hubenv/bin/pip install Pillow")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS = PROJECT_ROOT / "assets"

DEFAULT_SOURCE = Path("/Users/iff/.hermes/attachments/icon-mashup-2.png")


def trim_transparent_margin(im: Image.Image) -> Image.Image:
    """Remove empty transparent border. Artwork itself is never touched."""
    alpha = im.split()[3]
    bbox = alpha.getbbox()
    if not bbox:
        return im
    # getbbox already excludes fully transparent rows/columns
    return im.crop(bbox)


def square_pad(im: Image.Image) -> Image.Image:
    """Centre the art on a square transparent canvas (no cropping, no scaling)."""
    w, h = im.size
    if w == h:
        return im
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def build_master(source: Path, out: Path, size: int = 1024) -> Image.Image:
    im = Image.open(source).convert("RGBA")
    im = trim_transparent_margin(im)
    im = square_pad(im)
    im = im.resize((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG")
    return im


def make_icns(master: Path, out: Path) -> bool:
    """A real .icns via iconutil on macOS; a PNG-based one elsewhere."""
    if sys.platform == "darwin":
        iconset = out.with_suffix(".iconset")
        if iconset.exists():
            shutil.rmtree(iconset)
        iconset.mkdir(parents=True)
        im = Image.open(master)
        for size in (16, 32, 128, 256, 512, 1024):
            im.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            if size <= 512:
                im.resize((size * 2, size * 2), Image.LANCZOS).save(
                    iconset / f"icon_{size}x{size}@2x.png"
                )
        res = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
            capture_output=True,
            text=True,
        )
        shutil.rmtree(iconset, ignore_errors=True)
        if res.returncode != 0:
            print(f"  iconutil failed: {res.stderr.strip()}")
            return False
        return True

    # Non-macOS host: write a valid PNG-compressed .icns by hand.
    im = Image.open(master)
    chunks = []
    for ostype, size in (("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024)):
        buf = BytesIO()
        im.resize((size, size), Image.LANCZOS).save(buf, "PNG")
        data = buf.getvalue()
        chunks.append(struct.pack(">4sI", ostype.encode(), len(data) + 8) + data)
    payload = b"".join(chunks)
    out.write_bytes(struct.pack(">4sI", b"icns", len(payload) + 8) + payload)
    return True


def make_ico(master: Path, out: Path) -> bool:
    """Multi-size .ico with real alpha for Windows."""
    im = Image.open(master)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(out, sizes=sizes)
    return True


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        sys.exit(f"source image not found: {source}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    master_path = ASSETS / "icon_1024.png"

    print(f"source: {source}")
    print("        (resize + wrap only — artwork is not cropped or recoloured)")
    master = build_master(source, master_path, 1024)
    print(f"master: {master_path}  {master.size[0]}x{master.size[1]}")

    (ASSETS / "icon.png").parent.mkdir(parents=True, exist_ok=True)
    master.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png", "PNG")
    print(f"linux:  assets/icon.png  512x512")

    ok_icns = make_icns(master_path, ASSETS / "icon.icns")
    print(f"macOS:  assets/icon.icns  {'ok' if ok_icns else 'FAILED'}")

    ok_ico = make_ico(master_path, ASSETS / "icon.ico")
    print(f"Windows: assets/icon.ico  {'ok' if ok_ico else 'FAILED'}")

    if not (ok_icns and ok_ico):
        return 1
    print("\nIcon set ready. Next: reference assets/icon.icns (macOS) and")
    print("assets/icon.ico (Windows) from pyproject.toml in Phase 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
