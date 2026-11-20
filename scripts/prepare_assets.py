"""Verify pinned Windows assets and prepare the local 64k configuration."""

from argparse import ArgumentParser
from hashlib import file_digest
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "native-qwen/windows-assets.json"
CACHE = ROOT / ".local/assets"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify(path, asset):
    if path.stat().st_size != asset["bytes"] or digest(path) != asset["sha256"]:
        raise ValueError(f"Byte count or SHA-256 mismatch for {path.name}. Replace it with the pinned download.")


def obtain(cache, asset, download):
    target = cache / asset["file"]
    if not target.exists():
        if not download:
            raise FileNotFoundError(f"Place {target.name} under .local/assets, or rerun with -Download.")
        partial = target.with_name(target.name + ".part")
        if not partial.exists() or partial.stat().st_size != asset["bytes"]:
            subprocess.run(["curl.exe", "--disable", "--proto", "=https", "--proto-redir", "=https",
                            "--fail", "--location", "--retry", "2", "--continue-at", "-", "--output", str(partial),
                            "--", asset["url"]], check=True)
        verify(partial, asset)
        partial.replace(target)
    else:
        verify(target, asset)
    return target


def install_zip(archive, destination):
    # The release hash is verified before opening the upstream archive.
    with ZipFile(archive) as bundle:
        if destination.exists():
            expected_paths = {entry.filename for entry in bundle.infolist() if not entry.is_dir()}
            installed = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
            if destination.is_symlink() or installed != expected_paths:
                raise ValueError(f"Installed runtime differs from the pinned archive: {destination.name}")
            for entry in bundle.infolist():
                if entry.is_dir():
                    continue
                path = destination / entry.filename
                with bundle.open(entry) as stream:
                    expected = file_digest(stream, "sha256").hexdigest()
                if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()) or digest(path) != expected:
                    raise ValueError(f"Installed runtime file differs from the pinned archive: {path.name}")
            return
        with TemporaryDirectory(dir=destination.parent) as directory:
            extracted = Path(directory) / "extracted"
            bundle.extractall(extracted)
            extracted.rename(destination)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("optimized", "standard"), default="optimized")
    parser.add_argument("--download", action="store_true", help="Fetch missing assets from pinned public HTTPS URLs.")
    args = parser.parse_args()
    assets = json.loads(MANIFEST.read_bytes())
    if not args.download:
        for name in ("engine", "cuda", args.profile, "projector"):
            if not (CACHE / assets[name]["file"]).is_file():
                parser.error(f"Missing {assets[name]['file']} in .local/assets. Use Setup Pi.ps1 -Download or copy the pinned assets.")
    CACHE.mkdir(exist_ok=True, parents=True)
    try:
        engine, cuda, model, projector = (obtain(CACHE, assets[name], args.download)
                                          for name in ("engine", "cuda", args.profile, "projector"))
        runtime, vendor = CACHE / "b12541-runtime", CACHE / "b12541-cuda"
        install_zip(engine, runtime)
        install_zip(cuda, vendor)
        subprocess.run([sys.executable, "-B", str(ROOT / "configure.py"), "--profile", args.profile,
                        "--engine", str(runtime / "llama-server.exe"), "--vendor-dir", str(vendor),
                        "--model", str(model), "--projector", str(projector)], check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Setup stopped: {error}\n")


if __name__ == "__main__":
    main()
