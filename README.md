# Pi Local

Pi Local is a Windows desktop workspace for local model inference, tool use, and resumable jobs. Pi starts and stops its own authenticated loopback model service. Chats, workspaces, and recovery records stay on the computer.

The first release is a source snapshot of the Windows setup. It includes the desktop app, local launcher, 64k tuning presets, workflow and recovery extensions, MCP examples, and test fixtures. Runtime binaries, weights, and machine-specific configuration are supplied locally.

## Run from source

Use Windows with Python 3.11, Tk, and Node.js 24.18.0. Supply a compatible CUDA llama-server build and its vendor DLL directory, matching model and projector GGUF files, and the model's chat template. The [optimized profile](native-qwen/optimized.example.json) lists the exact engine flags and expected model filename. The standard profile is also available.

Create the Python environment and install the pinned Pi client:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci --prefix .\agent-clients-v8
```

Preview the setup with your asset paths:

```powershell
& .\.venv\Scripts\python.exe .\configure.py --plan `
  --engine 'C:\LocalAI\engine\llama-server.exe' `
  --vendor-dir 'C:\LocalAI\engine\cuda' `
  --model 'C:\LocalAI\models\Qwen3.8-27B-Uncensored-IQ4_XS.gguf' `
  --projector 'C:\LocalAI\models\mmproj.gguf' `
  --chat-template 'C:\LocalAI\models\chat-template.jinja'
```

Repeat the command with `--plan` removed, then run `& '.\Start Pi.ps1'`. Add `--desktop-driver` with the path to a compatible Windows MCP driver to enable desktop and Chrome actions. The source snapshot starts with the 64k profile. Port 1235 must be available for a new native service.

### Optional local media

Install `PyMuPDF==1.27.2.2` in the Python environment for PDF tools. Use `numpy==2.2.6` and `onnxruntime==1.20.1` for audio analysis. Supply the media assets under `agent-clients-v8/pi-gui/runtime/audio/`.

- `ffmpeg/` contains the FFmpeg and FFprobe executables. Both are used by local media inspection.
- `yamnet/` contains `yamnet.onnx` and `yamnet_class_map.csv` for sound event estimates.
- `nemo-speech/` contains the application and DLLs used for speech recognition. Place `parakeet-tdt-0.6b-v3.q8_0.gguf` alongside that directory.

The audio tools verify the binary and model digests from the [media manifest](agent-clients-v8/pi-gui/media/runtime-pins.json) and the sound event model pin in [inspect_input.py](agent-clients-v8/pi-gui/inspect_input.py).

## Use Pi

Select a workspace and send a prompt from the composer. The plan, tool activity, and model metrics appear alongside chat. Stop cancels the active Pi job. The recovery record stays with the chat and allows Pi to reconcile tool effects after interruption. Built-in skills guide tool discovery and stage verification.

The [text MCP example](agent-clients-v8/pi-gui/examples/text-integrity-mcp.py) and [workspace job server](agent-clients-v8/pi-gui/pi_process_mcp.py) can be registered in Pi's local profile. The [Pi tool catalog skill](agent-clients-v8/pi-gui/skills/pi-tool-catalog/SKILL.md) covers discovery and schema lookup.

## Check the setup

After configuring a checkout, run the recovery fixture from PowerShell:

```powershell
& .\.venv\Scripts\python.exe -B .\agent-clients-v8\pi-gui\verify_job_recovery.py
```

It uses a loopback mock provider to test restart, compaction, file readback, and duplicate-write refusal. See the [release workflow](docs/releasing.md) and the [Strata evaluation](docs/strata-evaluation.md).
