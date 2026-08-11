#!/usr/bin/env python3
"""One command for the whole dataset: download, verify, extract, convert.

    python3 scripts/setup_chia.py

Every step is idempotent and skipped when its output is already in place, so
re-running this is cheap and safe. Stdlib only -- no venv or `uv sync` needed.

Any extra arguments are forwarded to `prepare_chia.py`, e.g.

    python3 scripts/setup_chia.py --neg-ratio 3.0

The corpus is Chia (Kury et al., Scientific Data 7, 2020), CC-BY-4.0, fetched
from the `bigbio/chia` mirror of the figshare release. Both files are checked
against the published MD5 and byte size before anything reads them.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import prepare_chia  # noqa: E402

BASE_URL = "https://huggingface.co/datasets/bigbio/chia/resolve/main/data"

#: Published MD5 and byte size for each release archive.
RELEASES = {
    "without_scope": ("e5b4578b11139b80d64aeca0cc4a76b8", 2_397_117),
    "with_scope": ("54b33164da88da88e47b2a009e150a82", 2_512_094),
}

#: Each archive holds 2,000 `.txt`/`.ann` pairs plus 4 brat `.conf` files.
EXPECTED_TXT_FILES = 2000


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(variant: str, raw_dir: Path, *, force: bool) -> Path:
    """Download one archive unless a byte-correct copy is already present."""
    expected_md5, expected_size = RELEASES[variant]
    zip_path = raw_dir / f"chia_{variant}.zip"

    if zip_path.exists() and not force:
        if zip_path.stat().st_size == expected_size and md5(zip_path) == expected_md5:
            log(f"  {zip_path.name}: already present and verified, skipping")
            return zip_path
        log(f"  {zip_path.name}: present but does not verify, re-downloading")

    url = f"{BASE_URL}/{zip_path.name}"
    log(f"  {zip_path.name}: downloading from {url}")
    tmp_path = zip_path.with_suffix(".zip.part")
    try:
        with urllib.request.urlopen(url) as response, tmp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.URLError as exc:
        tmp_path.unlink(missing_ok=True)
        raise SystemExit(
            f"could not download {url}: {exc}\n"
            "Check the network, or fetch the archives by hand into "
            f"{raw_dir} and re-run."
        ) from exc

    # Verify before the file is given its real name, so a bad download can
    # never be mistaken for a good one on the next run.
    actual_size, actual_md5 = tmp_path.stat().st_size, md5(tmp_path)
    if (actual_md5, actual_size) != (expected_md5, expected_size):
        tmp_path.unlink(missing_ok=True)
        raise SystemExit(
            f"{zip_path.name} does not match the published release:\n"
            f"  expected md5 {expected_md5} size {expected_size:,}\n"
            f"  got      md5 {actual_md5} size {actual_size:,}"
        )

    tmp_path.replace(zip_path)
    log(f"  {zip_path.name}: downloaded and verified ({actual_size:,} bytes)")
    return zip_path


def extract(zip_path: Path, target: Path, *, force: bool) -> Path:
    """Extract an archive into its own directory.

    The archives are flat -- 4,004 files at the root, no enclosing folder -- so
    the destination directory has to be named here rather than taken from the
    archive.
    """
    if target.exists() and not force:
        found = len(list(target.glob("*.txt")))
        if found == EXPECTED_TXT_FILES:
            log(f"  {target.name}/: already extracted ({found} .txt files), skipping")
            return target
        log(f"  {target.name}/: has {found} .txt files, not "
            f"{EXPECTED_TXT_FILES}; re-extracting")

    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target)
    log(f"  {target.name}/: extracted {len(list(target.iterdir())):,} files")
    return target


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Unrecognised arguments are forwarded to prepare_chia.py.",
    )
    ap.add_argument("--raw-dir", type=Path, default=root / "data" / "raw",
                    help="where the archives live and are extracted")
    ap.add_argument("--with-scope", action="store_true",
                    help="also fetch the 'with scope' variant; nothing in this "
                         "repo reads it, so it is skipped by default")
    ap.add_argument("--force", action="store_true",
                    help="re-download and re-extract even if already verified")
    ap.add_argument("--no-prepare", action="store_true",
                    help="stop after extracting; do not build the dataset")
    args, forwarded = ap.parse_known_args(argv)

    variants = ["without_scope"] + (["with_scope"] if args.with_scope else [])
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    log(f"[1/3] fetching {len(variants)} archive(s) into {args.raw_dir}")
    archives = {v: fetch(v, args.raw_dir, force=args.force) for v in variants}

    log("[2/3] extracting")
    for variant, zip_path in archives.items():
        extract(zip_path, args.raw_dir / variant, force=args.force)

    if args.no_prepare:
        log("[3/3] skipped (--no-prepare)")
        return 0

    log("[3/3] building the dataset")
    return prepare_chia.main(
        ["--source", str(args.raw_dir / "without_scope"), *forwarded]
    )


if __name__ == "__main__":
    raise SystemExit(main())
