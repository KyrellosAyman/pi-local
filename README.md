# Pi Local

Pi Local is a Windows desktop harness for local model inference, tool use, and resumable jobs. Pi starts its own model service. The default release uses authenticated loopback, local workspace tools, and a checkout-specific state directory. It needs no API account or API key from the user.

[Research paper, v0.1.7](research/pi-local-v0.1.7.pdf) · [Reproduction guide](docs/reproducibility.md) · [Evaluation ledger](research/evidence/2026-11-22-listening.md) · [Releases](https://github.com/KyrellosAyman/pi-local/releases)

## Install on Windows

1. Download and extract the [latest release](https://github.com/KyrellosAyman/pi-local/releases/latest) into a writable folder.
2. Install [Node.js 24.22.3 x64](https://nodejs.org/dist/v24.22.3/) and use Python 3.12.16 x64 or newer in the 3.12 series, with Tk. If you need Python, download the [verified portable build](docs/reproducibility.md#python-for-windows). Open a new PowerShell window in the extracted repository.
3. Run the two commands below. Setup verifies the model, projector, engine, CUDA libraries, and offline search tools against the [asset manifest](native-qwen/windows-assets.json).

```powershell
& '.\Setup Pi.ps1' -Download
& '.\Start Pi.ps1'
```

For portable Python, add `-Python 'C:\path\to\python\python.exe'` to the setup command. Use the path where you extracted it.

The measured GPU was an RTX 5060 Ti with 16 GB VRAM and 63.8 GiB host RAM. Use a compatible NVIDIA driver and leave approximately 22 GB of disk space for one profile and its extracted runtime. Fit and speed vary with hardware and other running applications. Setup writes configuration and installs dependencies. The model starts when Pi sends its first prompt. Port 1235 must be free for this checkout's service.

In Pi, choose a workspace and send a short prompt. By default this release keeps chats, recoverable jobs and its starter workspace under the ignored `.local/` directory. The settings panel can unload an idle model. Use launcher status and stop commands from the reproduction guide when checking ownership.

When a missing choice materially affects the request, Pi shows three clickable answers, with its recommendation first, and a fourth row for a custom answer. Before starting planned tool work, Pi reviews the initial draft for coverage and adds missing implementation or verification steps.

For local listening reports, install with `-Audio`. Use **Audio report** to inspect one recording, or ask in Pi chat for listening findings on named recordings in your workspace. [Audio setup and checks](docs/reproducibility.md#verify-local-listening)

For cached downloads, an offline setup path, the original no-MTP profile, native smoke checks, optional media and desktop drivers, and the synthetic benchmark, see the [reproduction guide](docs/reproducibility.md).

## Research archive

Starting with 0.1.1, each verified release contains a matching PDF and an editable Markdown source. The evidence ledger records wins, failed variants, and pending qualification separately. Version 0.1.0 was the original desktop source snapshot.

- [Paper source](research/PAPER.md)
- [Release history and update workflow](docs/releasing.md)
- [Strata review](docs/strata-evaluation.md)
- [Security and data handling](SECURITY.md)

## Contributing and license

Contributions are welcome through forks and pull requests. See the [contribution guide](CONTRIBUTING.md) and [code of conduct](CODE_OF_CONDUCT.md).

Pi Local’s original material is available under the [Apache License 2.0](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for separately licensed material.
