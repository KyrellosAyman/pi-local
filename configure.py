"""Bind this checkout to locally supplied runtime assets without starting a server."""

from argparse import ArgumentParser
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import token_hex
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile


ROOT = Path(__file__).resolve().parent
NATIVE = ROOT / "native-qwen"
GUI = ROOT / "agent-clients-v8/pi-gui"
NODE_VERSION = "v24.18.0"


def existing(parser, name, path, *, directory=False):
    if path is None:
        parser.error(f"{name} is required.")
    resolved = Path(path).expanduser().resolve()
    if not (resolved.is_dir() if directory else resolved.is_file()):
        parser.error(f"{name} must point to an existing {'directory' if directory else 'file'}.")
    return resolved


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def write_json(path, value):
    with NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--engine", required=True)
    parser.add_argument("--vendor-dir")
    parser.add_argument("--model", required=True)
    parser.add_argument("--projector", required=True)
    parser.add_argument("--chat-template", required=True)
    parser.add_argument("--desktop-driver")
    parser.add_argument("--profile", choices=("optimized", "standard"), default="optimized")
    parser.add_argument("--plan", action="store_true", help="Validate inputs and print planned changes without writing.")
    args = parser.parse_args()
    node = existing(parser, "--node", args.node)
    if subprocess.check_output([str(node), "--version"], text=True).strip() != NODE_VERSION:
        parser.error(f"This snapshot uses Node {NODE_VERSION}.")
    engine = existing(parser, "--engine", args.engine)
    vendor = existing(parser, "--vendor-dir", args.vendor_dir or engine.parent, directory=True)
    model = existing(parser, "--model", args.model)
    projector = existing(parser, "--projector", args.projector)
    template = existing(parser, "--chat-template", args.chat_template)
    driver = existing(parser, "--desktop-driver", args.desktop_driver) if args.desktop_driver else None
    profile = json.loads((NATIVE / f"{args.profile}.example.json").read_bytes())
    expected_model = profile.pop("model_filename")
    if model.name.casefold() != expected_model.casefold():
        parser.error(f"The {args.profile} profile expects {expected_model}.")

    secret_dir = ROOT / ".local"
    key = secret_dir / "loopback.key"
    config = {**profile, "executable": str(engine), "vendor_directory": str(vendor), "model": str(model),
              "projector": str(projector), "template": str(template), "api_key_file": str(key)}
    path_entries = dict.fromkeys([str(node.parent), str(Path(sys.executable).parent),
                                  *(entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)])
    runtime = {"node": str(node), "python": sys.executable, "path_entries": list(path_entries),
               "native_config_sha256": sha256(encoded(config)).hexdigest()}
    if driver:
        runtime["desktop_driver"] = str(driver)
    if args.plan:
        print(json.dumps({"profile": args.profile, "endpoint": "127.0.0.1:1235", "context": 64000,
                          "desktop_driver_configured": bool(driver),
                          "planned_files": ["native-qwen/server-config.json",
                                            "agent-clients-v8/pi-gui/runtime-config.json", ".local/loopback.key"]}))
        return
    target = NATIVE / "server-config.json"
    if (NATIVE / "server-state.json").exists() and (
            not target.exists() or target.read_bytes() != encoded(config)):
        parser.error("Stop this checkout's model through its launcher before changing the native configuration.")
    secret_dir.mkdir(exist_ok=True)
    if not key.exists():
        with key.open("x", encoding="utf-8") as stream:
            stream.write(token_hex(32) + "\n")
    write_json(target, config)
    write_json(GUI / "runtime-config.json", runtime)
    print("Configured the local 64k profile. Use Start Pi.ps1 to open the app.")


if __name__ == "__main__":
    main()
