# Reproduce the public Pi Local results

## Choose a run

The included launcher, GUI, and recovery fixtures use synthetic providers. They exercise the actual pinned desktop client and do not need a GPU inference request. The synthetic archive and uncertainty workloads can be submitted to the real local model. Historical measurements in the paper used a single workstation. A fresh run records its own times and grades.

## Set up from the pinned assets

Use the [Windows quick start](../README.md). For a manual or cached download, use the direct links in [windows-assets.json](../native-qwen/windows-assets.json). Put the engine ZIP, CUDA ZIP, chosen model GGUF, and F16 projector GGUF in `.local/assets/` without renaming the files.

Run `& '.\Setup Pi.ps1'` to install the hash-pinned Python and Node dependencies and verify the cached assets. Once dependencies are already present, add `-OfflineDependencies` for setup without downloads. Use `-Profile standard` to select the published no-MTP 64k preset. The historical archive's original runtime and host are described in the paper. The standard preset uses the same public asset distribution and b12541 engine, so report that difference when comparing with historical timings.

Setup verifies and unpacks the ripgrep and fd archives listed in `native-qwen/windows-assets.json`. Pi uses these binaries for its offline `grep` and `find` tools. To prepare an offline installation, copy the two pinned ZIP files into `.local/assets` with the other runtime assets.

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
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_prompt_clarification.py
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_initial_plan_review.py
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_initial_plan_review.py --accept
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_stage_receipts.py
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_stage_receipts.py --early-stop
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_stage_receipts.py --no-plan
node .\agent-clients-v8\pi-gui\verify-near64-answer-room.mjs
node .\agent-clients-v8\pi-gui\verify_stall_recovery.mjs
node .\agent-clients-v8\pi-gui\verify_skill_availability.mjs
node .\agent-clients-v8\pi-gui\verify-skill-reuse.mjs
node .\agent-clients-v8\pi-gui\verify-checkpoint-protection.mjs
& .\.venv\Scripts\python.exe -B .\research\archive-32\grade.py --recorded
```

The launcher suite reads the tracked profile example and uses temporary fixture files. It runs before asset download or model configuration. The GUI fixtures use Tk and a separate mock loopback port. They cover profile defaults, exact tool writes, stream and rendering state, and process restart. The Python script runner suppresses import bytecode caches. The restart fixture checks that an imported input produces no cache file. The recorded archive check reproduces exact input hashes and sequential line-range coverage from the released summary.

The clarification fixture drives actual Tk buttons and the fourth-row text field, with interruptions before an answer and after saving it. The review fixture starts with a broad draft that lacks a read and a comparison, then checks that the reviewer runs before work and that later plan updates skip it. The near-context fixture tests the loopback tokenizer call, output allowance, and smaller direct tool catalog without starting a model.

The desktop checks exercise the **Shared model speed** meter during idle, active and unavailable service states. The two first-plan fixtures check that **Reviewing the initial plan** appears while a draft is pending and clears before work proceeds, including recovery on both sides of the review.

### Verify checkpoints and script receipts

For a stage that declares a checkpoint, keep the completed outputs listed under `finished_files` in its checkpoint JSON, with `path` and `sha256` on each entry. Pi refuses direct writes and edits to those paths while their owning stage remains completed. It checks the saved digests on resume and settlement. Write a separate revision or explicitly reopen the step for a planned change.

For a desktop step that needs an executable check, put the checkpoint path and `verifyWith` script path in the reviewed plan. You can also tell Pi, “In the Pi plan, require the checkpoint proof.json and the verifier script verify.py.” Pi binds that explicitly named pair before plan review and keeps the job open for review if the plan or check is missing. Keep the script inside the workspace and pass the exact checkpoint path as its sole argument in a direct `run_script` call. The script should exit nonzero if its check fails and leave the checkpoint and its files unchanged. Pi binds a successful run to the current job and file revisions, and shows the verification status in the plan. A script run establishes the checks that script performed. Review its assertions against the intended result.

The `verify_stage_receipts.py` fixture submits two first-plan calls in one model response, tests rejected and passing checks, and restarts the pinned RPC before completing the verified step. The `--early-stop` and `--no-plan` cases test a final answer before the planned verifier runs and before the model proposes a plan, respectively.

### Compare short and near-limit decode

Use the optimized 64k profile with one local model process and an idle slot. Prepare two versions of the same request using text from `research/archive-32/workspace/pages/`. Keep the short version near 4,800 input tokens and repeat the public source text to bring the longer version near 59,500 tokens. End each request with `Write exactly the integers from 1 through 48 in order, separated by commas. Output only the sequence.`

1. Submit short, near-limit and short in order through the same local model endpoint. Keep sampling and reasoning settings identical and disable cache reuse for all three arms. Leave enough input room for the full answer.
2. Verify the actual input lengths, byte-exact answer, identical output token counts, and equal draft acceptances. Record native prefill and decode separately. Record a changed answer or a missing timing record as a failed comparison.
3. If collecting GPU counters, align samples to the completed native requests and keep samples that fall completely within the measured phase. Report sample counts alongside medians. This procedure uses the released synthetic text. The [evidence ledger](../research/evidence/2026-11-22-desktop-performance.md) reports the historical run's aggregate measurements.

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
- For an OAuth server, a nonempty `oauth.scope` in `mcp.json` limits the scopes Pi requests and accepts. Sign in again after narrowing that setting if an earlier grant exceeded the new scope or did not report its scope. Run `node .\scripts\verify_mcp_scope_policy.mjs .\agent-clients-v8` after setup to check the bundled launcher against a temporary local issuer.
- PDF inspection uses PyMuPDF 1.27.2.2. To set up audio analysis, run `& '.\Setup Pi.ps1' -Audio -Download` from the checkout. Setup installs the pinned audio packages in Pi’s Python environment and verifies the local media runtime against the published digests. For an offline setup, use `-OfflineDependencies -Audio` with the audio Python packages already installed. Provide the files named in the media manifest under `.local/assets/` or keep the verified installed runtime. [Pinned audio packages](../requirements-audio.txt) [Media manifest](../agent-clients-v8/pi-gui/media/runtime-pins.json)

Place verified audio and video components under `agent-clients-v8/pi-gui/runtime/audio/`.

- The FFmpeg 9.1 Essentials archive supplies the pinned `ffmpeg.exe` and `ffprobe.exe` in `ffmpeg/`. The reports prior to this installation used the 30 November 2023 build from revision `a30adf9f96`. [FFmpeg 9.1 Windows release](https://github.com/GyanD/codexffmpeg/releases/tag/9.1)
- From NVIDIA's [NeMo-Speech.cpp v0.3.0 release](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0), download `nemo-speech-0.3.0-windows-x86_64-vulkan.zip`, verify its release SHA-256, and copy the archive's `bin/` contents to `nemo-speech/`. Pi invokes the speech engine on the CPU.
- Put the pinned [Parakeet Q8 GGUF](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3/blob/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/parakeet-tdt-0.6b-v3.q8_0.gguf) next to these folders. Place `yamnet.onnx` and `yamnet_class_map.csv` from the [pinned YAMNet conversion](https://huggingface.co/audiomagic/yamnet-onnx/tree/f25b741c2f0bdc6d7e6db24b5fddda23347dbafd) in `yamnet/`. The label map's SHA-256 is `cdf24d193e196d9e95912a2667051ae203e92a2ba09449218ccb40ef787c6df2`.

For the optional Chrome workflow, open the approved page in the intended Chrome window. Pi checks that the current address and the accessible page document identify the same page before exposing its controls. To reproduce a scoped read, give Pi the approved window ID and exact control label. Ask it to read that control without a screenshot or page action. Compare the result with the control in Chrome. If Windows exposes only Chrome’s toolbar, finish your browser work and exit Chrome completely. Start Chrome with `--force-renderer-accessibility=complete` and reopen the approved page. See the [Chromium accessibility documentation](https://chromium.googlesource.com/chromium/src/+/HEAD/tools/accessibility/inspect/).

In Pi, select **Audio report**, choose a local recording, then set the window and optional channel. Pi displays decoded levels and their channel references, plus provisional sound labels and a speech transcript. This route uses the local media runtime directly and requires no chat model. The audio alone leaves the recording setup and speaker identities unresolved.

### Verify local listening

After setup with `& '.\Setup Pi.ps1' -Audio -Download`, run the generated media fixtures from the checkout. They exercise decoded samples, stereo comparisons, image and video inspection, and correction of an invalid speech time range. The speech timing control substitutes known recognizer outputs. It checks how Pi pairs words with timestamps.

```powershell
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_media.py
```

For a live check, open a scratch workspace in Pi with two WAV files you can independently review, each under 30 seconds. Submit a single prompt such as “Analyze recording-01.wav and recording-02.wav. Report recoverable speech, channel differences, timed sound candidates and what remains uncertain.” Let Pi finish its reviewed plan. Compare the saved report with the files. Confirm that each recording has measured channel levels, the source and analysis rates are separate, and speech times are marked as estimates. Compare the words and sound windows against your independent reference. Use the same files and prompt when retesting a change.

The reported studies used controlled mixtures from independently attributed recordings. The public fixtures generate their own inputs. Read the [listening evidence](../research/evidence/2026-11-22-listening.md) for the frozen grading criteria, failures and matched replays.

The paper discusses additional science, Android, repository, video, and integration cases. The public release includes their measured summaries. Exact reruns that depend on private projects, signed-in accounts, or unpublished graders still need a separate public fixture. Use your own equivalent input and document the difference.

## Build the paper

Install [the paper requirements](../research/requirements.txt) in the same virtual environment, then build the PDF.

```powershell
& .\.venv\Scripts\python.exe -m pip install -r .\research\requirements.txt
& .\.venv\Scripts\python.exe -B .\research\render_paper.py 0.1.6
& .\.venv\Scripts\python.exe -B .\research\render_paper.py 0.1.6 --check
```

This checkout contains the [editable report](../research/PAPER.md) and the [0.1.6 PDF](../research/pi-local-v0.1.6.pdf). The [release history](releasing.md#release-history) links to the previous papers.
