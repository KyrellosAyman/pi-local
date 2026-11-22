"""Verify pinned Windows assets and prepare the local 64k configuration."""

from argparse import ArgumentParser
from hashlib import file_digest
import json
from pathlib import Path
from shutil import copyfileobj
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "native-qwen/windows-assets.json"
CACHE = ROOT / ".local/assets"
GUI = ROOT / "agent-clients-v8/pi-gui"


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
        for attempt in range(3):
            if partial.exists() and partial.stat().st_size >= asset["bytes"]:
                break
            # Start a new request so curl resumes from the current partial file size after a failure.
            result = subprocess.run(["curl.exe", "--disable", "--proto", "=https", "--proto-redir", "=https",
                                     "--fail", "--location", "--connect-timeout", "30", "--speed-time", "120",
                                     "--speed-limit", "1024", "--continue-at", "-", "--output", str(partial),
                                     "--", asset["url"]])
            if result.returncode == 0:
                break
            if attempt == 2:
                result.check_returncode()
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


def install_audio(cache, runtime, pins, download):
    archives = {"ffmpeg": pins["ffmpeg"], "nemo-speech": pins["native_bin"]}
    models = {"parakeet-tdt-0.6b-v3.q8_0.gguf": pins["model"],
              **{f"yamnet/{name}": digest for name, digest in pins["yamnet"].items()}}
    expected = models | {f"{folder}/{name}": digest for folder, files in archives.items()
                         for name, digest in files.items()}
    missing = set()
    for name, checksum in expected.items():
        path = runtime / name
        if not path.resolve().is_relative_to(runtime.resolve()) or path.is_symlink():
            raise ValueError(f"Audio asset path must stay in the Pi runtime: {name}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Expected a regular audio file: {name}")
        if path.is_file():
            installed = digest(path)
            if installed == checksum:
                continue
            if installed != pins.get("legacy_ffmpeg", {}).get(name):
                raise ValueError(f"Installed audio asset does not match its pin: {name}")
        missing.add(name)
    if (runtime / "nemo-speech").is_dir():
        extras = {p.name for p in (runtime / "nemo-speech").iterdir() if p.is_file()} - pins["native_bin"].keys()
        if extras:
            raise ValueError(f"Unexpected files in Pi's speech runtime: {', '.join(sorted(extras))}")
    if not missing:
        return

    runtime.mkdir(exist_ok=True, parents=True)
    with TemporaryDirectory(dir=runtime) as temporary:
        staging = Path(temporary)
        for folder, files in archives.items():
            requested = [name for name in files if f"{folder}/{name}" in missing]
            if requested:
                asset = pins["downloads"][folder]
                archive = obtain(cache, asset, download)
                for name in requested:
                    pending = staging / folder / name
                    pending.parent.mkdir(exist_ok=True)
                    member = f"{asset['bin']}/{name}"
                    with pending.open("xb") as output:
                        if archive.suffix == ".7z":
                            subprocess.run(["tar.exe", "-xOf", str(archive), member], stdout=output, check=True)
                        else:
                            with ZipFile(archive) as bundle, bundle.open(member) as source:
                                copyfileobj(source, output)
        for name in sorted(missing & models.keys()):
            source = obtain(cache, pins["downloads"][name], download)
            pending = staging / name
            pending.parent.mkdir(exist_ok=True)
            with source.open("rb") as input_file, pending.open("xb") as output:
                copyfileobj(input_file, output)
        for name in sorted(missing):
            if digest(staging / name) != expected[name]:
                raise ValueError(f"Audio asset did not match its pin: {name}")
        for name in sorted(missing):
            destination = runtime / name
            destination.parent.mkdir(exist_ok=True)
            (staging / name).replace(destination)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("optimized", "standard"), default="optimized")
    parser.add_argument("--download", action="store_true", help="Fetch missing assets from pinned public HTTPS URLs.")
    parser.add_argument("--audio", action="store_true", help="Prepare the optional local audio runtime.")
    args = parser.parse_args()
    assets = json.loads(MANIFEST.read_bytes())
    selected = ("engine", "cuda", args.profile, "projector")
    workspace_tools = assets["workspace_tools"]
    if not args.download:
        for asset in (*(assets[name] for name in selected), *workspace_tools.values()):
            if not (CACHE / asset["file"]).is_file():
                parser.error(f"Missing {asset['file']} in .local/assets. Use Setup Pi.ps1 -Download or copy the pinned assets.")
    CACHE.mkdir(exist_ok=True, parents=True)
    try:
        engine, cuda, model, projector = (obtain(CACHE, assets[name], args.download) for name in selected)
        runtime, vendor = CACHE / "b12541-runtime", CACHE / "b12541-cuda"
        install_zip(engine, runtime)
        install_zip(cuda, vendor)
        for name, asset in workspace_tools.items():
            install_zip(obtain(CACHE, asset, args.download), CACHE / name)
        if args.audio:
            pins = json.loads((GUI / "media/runtime-pins.json").read_bytes())
            install_audio(CACHE, GUI / "runtime/audio", pins, args.download)
        subprocess.run([sys.executable, "-B", str(ROOT / "configure.py"), "--profile", args.profile,
                        "--engine", str(runtime / "llama-server.exe"), "--vendor-dir", str(vendor),
                        "--model", str(model), "--projector", str(projector)], check=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Setup stopped: {error}\n")


if __name__ == "__main__":
    main()
