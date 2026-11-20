# Reproduce the public Pi Local results

## Choose a run

The included launcher, GUI, and recovery fixtures use synthetic providers. They exercise the actual pinned desktop client and do not need a GPU inference request. The synthetic archive and uncertainty workloads can be submitted to the real local model. Historical measurements in the paper used a single workstation. A fresh run records its own times and grades.

## Set up from the pinned assets

Use the [Windows quick start](../README.md). For a manual or cached download, use the direct links in [windows-assets.json](../native-qwen/windows-assets.json). Put the engine ZIP, CUDA ZIP, chosen model GGUF, and F16 projector GGUF in `.local/assets/` without renaming the files.

Run `& '.\Setup Pi.ps1'` to install the hash-pinned Python and Node dependencies and verify the cached assets. Once dependencies are already present, add `-OfflineDependencies` for setup without downloads. Use `-Profile standard` to select the published no-MTP 64k preset. The historical archive's original runtime and host are described in the paper. The standard preset uses the same public asset distribution and b12541 engine, so report that difference when comparing with historical timings.

Configuration uses the bundled, pinned chat template by default. Experienced users can bind custom assets with `configure.py --engine ... --vendor-dir ... --model ... --projector ...`. Add `--plan` to see what would be written. Optional `--desktop-driver PATH` and `--enable-web-tools` expose the corresponding tools. Use a compatible independently obtained driver and reconfigure it only if those workflows are needed.

If a cache checksum fails, replace the named local file with its exact upstream download. A file ending in `.part` is a partial download. Setup promotes it only after verifying both byte count and digest. Use a fresh cache directory if an installed runtime file was changed.

### Python for Windows

Use a registered Python 3.12.16 x64 or newer in the 3.12 series, with Tk, or pass the interpreter path with `-Python`. The verified portable build is [Astral's CPython 3.12.16 Windows x64 archive](https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz). Before extracting it, run `Get-FileHash -Algorithm SHA256` on the downloaded file and compare the result to `355ee61b8207b91574491b1c6dc9b0ebb4408fc56bfafe498f3ef439314b52dc`. Extract the archive into a new directory, then pass the enclosed `python\python.exe` to setup. Windows `tar.exe -xf` supports this archive format.

### Local model smoke check

Start Pi and enter `Reply with exactly PI-READY-64000`. Confirm the exact visible reply and 64,000-token context. In a separate PowerShell window, use the checkout’s own launcher to inspect the service:

```powershell
& .\.venv\Scripts\python.exe -B .\native-qwen\launcher.py status
```

Use Pi’s **Settings → Unload local model** after the response settles. Submit another prompt in the same chat and verify both replies remain visible after reload. The launcher refuses a foreign listener on port 1235. Close or unload the application that owns an occupied port before running a second checkout.

### Offline fixture checks

Run these from the repository root after installing the desktop dependencies.

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s native-qwen -p test_launcher.py
& .\.venv\Scripts\python.exe -B -m unittest discover -s scripts -p test_prepare_assets.py
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_gui.py
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_job_recovery.py
node .\agent-clients-v8\pi-gui\verify_stall_recovery.mjs
& .\.venv\Scripts\python.exe -B .\research\archive-32\grade.py --recorded
```

The GUI fixtures use Tk and a separate mock loopback port. They cover profile defaults, exact tool writes, stream and rendering state, and process restart. The recorded archive check reproduces exact input hashes and sequential line-range coverage from the released summary.

## Repeat the 32-page archive workload

1. Configure the standard profile and keep an exclusive model slot. Run `& .\.venv\Scripts\python.exe -B .\research\archive-32\run.py`. The runner copies the frozen input into `.local/archive-32/workspace` and opens the normal Pi composer against isolated state.
2. Submit the exact text from [PROMPT.txt](../research/archive-32/workspace/PROMPT.txt) once. The coverage witness records verified source line ranges, pseudonymized tool-call identifiers, and context width in `.local/archive-32/ranges.jsonl`. The grader and answer key stay outside the model's workspace.
3. For an ordinary reproduction, let Pi settle. For an elapsed recovery experiment, independently observe the checkpoint after pages 12 and 24. Use only an isolated test instance. Verify file hashes and exact GUI and RPC ownership before interrupting. The historical run resumed after real holds of at least two hours and 24 hours. Record actual process closure, elapsed time, and the next original page read. Reopen with `& .\.venv\Scripts\python.exe -B .\research\archive-32\run.py --resume` and continue the same saved job without a second prompt. The ordinary Stop button marks a job stopped and is a different operation.
4. After a natural finish, run `& .\.venv\Scripts\python.exe -B .\research\archive-32\grade.py`. Verify the two checkpoint objects, exact output, and all original line ranges. Judge real hold duration, natural completion, original user count, compaction, and exact-once writes from your separately recorded session and process evidence. The grader checks artifact and range evidence only.

The checkpoint and source checks can pass on a short reproduction. Count neither fixture time nor idle holds toward sustained productive work.

### Compare time and correctness

Run a fresh and warm chat per profile on the same prompt, files, tool access, sampler and completion criteria. Keep the host otherwise idle. Pass `--latency-trace .local/timing.jsonl` through the desktop launcher to record local tool-to-output, output-to-render, model and host intervals. For reproducible comparisons, report request context counts, decode tokens/s, elapsed task time and the independent artifact verdict. Keep successful, length-limited and failed runs visible in the report. A short quick-start check verifies local model service ownership and wiring.

## Repeat the uncertainty tasks

Copy each [R03 and R05 workspace](../research/uncertainty/) to separate scratch folders. Open each folder in a fresh Pi chat and submit its PROMPT.txt once. Compare output/result.json and output/report.md to each BRIEF.md and scoring-checks.json. Recheck every supplied input SHA-256 from input-manifest.json. Review the prose separately for unsupported facts or approval claims. The matched three-client reference measurements are in [uncertainty.csv](../research/evidence/uncertainty.csv).

## Optional local components

- Local MCP examples include the [text checksum server](../agent-clients-v8/pi-gui/examples/text-integrity-mcp.py) and [workspace script server](../agent-clients-v8/pi-gui/pi_process_mcp.py). Register only explicitly chosen servers in the checkout's local Pi profile.
- PDF inspection uses PyMuPDF 1.27.2.2. Audio analysis uses NumPy 2.2.6 and ONNX Runtime 1.20.1. Install only the extra modules you need into the same Python environment.
- Place verified audio and video components under `agent-clients-v8/pi-gui/runtime/audio/`. Use `ffmpeg/` for the pinned FFmpeg and FFprobe files, `yamnet/` for the ONNX model and CSV label map, and `nemo-speech/` for the native speech engine and DLLs. Place the pinned Parakeet GGUF beside those directories. Compare digests to the [media asset manifest](../agent-clients-v8/pi-gui/media/runtime-pins.json) and [sound model pin](../agent-clients-v8/pi-gui/inspect_input.py). Optional media branches need their compatible upstream downloads. Their private historical media and production workspaces are outside this reproduction bundle.

The paper discusses additional science, Android, repository, video, and integration cases. The public release includes their measured summaries. Exact reruns that depend on private projects, signed-in accounts, or unpublished graders still need a separate public fixture. Use your own equivalent input and document the difference.

## Build the paper

Install [the paper requirements](../research/requirements.txt) in the same virtual environment, then build the PDF.

```powershell
& .\.venv\Scripts\python.exe -m pip install -r .\research\requirements.txt
& .\.venv\Scripts\python.exe -B .\research\render_paper.py 0.1.1
```

The [editable source](../research/PAPER.md) and [rendered PDF](../research/pi-local-v0.1.1.pdf) are both part of the release.
