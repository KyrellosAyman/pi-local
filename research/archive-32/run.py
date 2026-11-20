"""Open the synthetic archive in Pi with a local coverage witness."""

from argparse import ArgumentParser
from pathlib import Path
import runpy
from shutil import copytree
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GUI = ROOT / "agent-clients-v8/pi-gui"


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    local = ROOT / ".local/archive-32"
    workspace, state = local / "workspace", local / "state"
    trace = local / "ranges.jsonl"
    if args.resume:
        if not (state / "recovery/active-job.json").is_file():
            parser.error("This archive trial has no saved active job.")
    elif local.exists():
        parser.error("An archive trial already exists. Move it aside before starting a fresh one.")
    else:
        copytree(HERE / "workspace", workspace)

    sys.path.insert(0, str(GUI))
    import pi_backend as backend

    original_command, original_prepare = backend.command, backend.prepare

    def command(*values, **options):
        return [*original_command(*values, **options), "--extension", str(HERE / "witness.mjs")]

    def prepare(*values, **options):
        return {**original_prepare(*values, **options), "PI_ARCHIVE_WORKSPACE": str(workspace),
                "PI_ARCHIVE_TRACE": str(trace)}

    backend.command, backend.prepare = command, prepare
    sys.argv = [str(GUI / "app.py"), "--workspace", str(workspace), "--state-dir", str(state)]
    if args.resume:
        sys.argv.append("--recover-only")
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
