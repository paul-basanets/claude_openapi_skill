#!/usr/bin/env python3
"""Bundle the openapi-reader plugin into dist/openapi-reader.zip."""

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src" / "openapi-reader"
DIST = ROOT / "dist"
OUT_DIR = DIST / "openapi-reader"
ZIP = DIST / "openapi-reader.zip"


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    shutil.copytree(SRC, OUT_DIR)

    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(OUT_DIR.rglob("*")):
            zf.write(file, file.relative_to(DIST))

    print(f"Created {ZIP} ({ZIP.stat().st_size / 1024:.1f} KB)")
    print(f"  {sum(1 for _ in OUT_DIR.rglob('*') if _.is_file())} files")


if __name__ == "__main__":
    main()
