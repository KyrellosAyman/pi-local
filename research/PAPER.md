# Pi Local
## A desktop harness for local inference and recoverable agent work

**KyrellosAyman**

Technical report • Version 0.1.1 • 20 November 2026

### Abstract

Pi Local is a Windows desktop harness for running a local multimodal language model, combining local tools, and recovering interrupted work. We developed a desktop client around a pinned Pi RPC runtime and a self-managed llama.cpp service, then evaluated tool routing, source retention, checkpoint integrity, and performance on one consumer workstation. An elapsed recovery trial retained one prompt across two process interruptions, delivered all 32 original archive pages in order, and produced the exact reconciliation after 18 compactions. The optimized 64,000-token profile improved decode on four matched controls without changing their final output bytes. At 59,419 input tokens, it raised decode from 11.61 to 23.69 tokens/s while total response time increased from 123.14 to 144.78 seconds. Larger source, software, audio, and video workloads exposed accuracy and performance failures. This report records the experimental conditions, the negative results, and the boundaries of reproduction. The public release contains the code, presets, synthetic archive inputs, and the procedures for independent checks.

**Keywords**  Local inference, agent harness, checkpointing, source retention, speculative decoding, reproducible evaluation.

## 1. Research questions

Can a desktop harness run its own model and tools on a consumer Windows PC? Can it continue a single task after losing its desktop and RPC processes while preserving original source evidence and completed effects? Which inference changes improve decode, and when do those changes reduce the time a person waits for a correct outcome?

We started from a workflow spread across model serving, agent clients, and media applications. The project moved the main execution and recovery path into Pi and kept legacy clients as comparison references. We treated a completed artifact, a valid source read and an accelerated model response as distinct outcomes. Release 0.1.0 published the first source snapshot. Release 0.1.1 publishes the research record, a verified asset setup path, and a frozen synthetic task that can be run without any cloud inference account.

## 2. Harness design

### 2.1 Desktop and inference boundary

The Tk desktop owns the composer, session navigation, streamed Markdown, tool activity, metrics, and saved job lifecycle. It drives a pinned Pi coding-agent RPC process over local standard input and output. Pi Local extensions provide task briefing, skill discovery, stage planning, tool receipts, and interruption recovery. The pinned Pi package supplies the actual client and tool infrastructure. The Windows launcher owns a single llama.cpp slot and checks process identity and port ownership before reusing or unloading it.

Inference is served on authenticated loopback. The model path, matching vision projector, and chat template are locally verified. The client keeps model serving separate from the desktop presentation layer so the same conversation can survive a model unload and reload. Optional browser, desktop-driver, and media components have their own prerequisites. The public profile does not configure cloud model providers, automatically discover other assistants’ skill directories, or enable webpage and research tools by default.

### 2.2 Source handling and job recovery

Pi records a durable admission tied to a workspace, original user message, session file and owning processes. State changes are associated with tool-call identifiers and recorded effects. Compaction maintains manageable input size but can lose coverage if a summary replaces a needed tool result. We used ordered exact reads, retained excerpts when available, traced full original ranges at the provider boundary, and graded the final artifact independently. A digest establishes byte identity. It cannot establish that the source was interpreted correctly.

Recovery reopens the same session and reconciles pending calls against the transcript and workspace. Confirmed writes should not run again. An interrupted write requires distinguishing bytes that were applied, a demonstrably unchanged preimage, and an uncertain effect. On Windows, a reader that denied delete sharing could transiently block a checkpoint replacement. Shared-delete observations and a bounded rename retry resolved the reproduced transient case while preserving the prior checkpoint on a persistent error.

The later staged checkpoint candidate adds an opt-in artifact manifest and checks actual paths and SHA-256 digests before a declared stage closes. A second candidate rechecks the saved manifest and its referenced files before resuming. On failure, the pinned RPC command emits an extension error even when the prompt RPC is acknowledged. The staged desktop handles that event and displays Needs review. A damaged-file fixture preserved the job and both files and made zero resumed provider requests. These candidates have separate evidence from the public release baseline.

### 2.3 Tool routing, rendering, and media

Pi starts new tool work with a brief and a concrete plan, then searches the local skill catalog and activates a relevant procedure. It keeps dynamic tool catalogs out of the default inline prompt where possible. A staged routing correction stopped a repeated plan from asking for a search that had already completed. The app separates visible reasoning, substantive response text, tool cards, and final output. Rendering tests cover streaming, Markdown, scroll following, interruption, and preserved chat history.

Media work uses local inspection and execution tools. Technical validation checks decoded frames, audio packets, sample clocks, raster dimensions, and expected fingerprints. Perceptual review asks whether the picture and sound actually match in real-time playback. Media generation can temporarily release the inference GPU and restore the same owned model profile after the worker exits. Audio assessment separates channel measurements, estimated transcripts, and candidate sound labels.

## 3. Experimental method

### 3.1 Workstation and configurations

The workstation used Windows, an Intel Core i7-12700K, 63.8 GiB of system RAM, and an NVIDIA GeForce RTX 5060 Ti with 16 GB of VRAM. Pi used Node.js 24.18.0, Python 3.11 and a pinned Pi coding-agent package. The released CUDA engine is the Windows x64 llama.cpp b12541 build. The experiment used a dense Qwen-family 27B IQ4_XS GGUF, an F16 projector, and one 64,000-token slot. The optimized profile keeps the original target weights, adds the fused publisher draft head, uses two MTP proposals, and places eight target feed-forward blocks on CPU. It uses Q4_0 K/V caches, Flash Attention, a 256-token batch, and 128-token microbatches. Historical baseline measurements used recorded earlier software and placement settings. The downloadable standard profile recreates a no-MTP configuration on the pinned upstream engine.

Full model and projector hashes, archive sizes, and download paths accompany the release. The original and fused files had 851 byte-identical target tensors and 15 additional draft tensors in the fused file. The release carries the exact extracted-and-adjusted Jinja template. Its installation uses security-patched Node.js 24.22.3 and CPython 3.12.16 with hash-pinned dependencies. A newer prefix-order candidate remains separate.

### 3.2 Comparison and grading

Matched runs froze the task prompt and source inputs, used fresh isolated workspaces, recorded the serving profile, and separated successful natural settlement from deadline expiry or a length stop. We assessed structured artifacts and source coverage independently from the model's report. A source page counted only when the original lines were observed in order at the provider boundary. Timed holds were measured with real clocks against verified process closures. Productive time counts attributable generation and successful useful tool intervals, with overlaps merged. It excludes idle holds and repeated ineffective work.

Decode rate is generated tokens per measured generation interval. Full task time includes prefill, tools, compaction, retries and other elapsed work. First output after a tool may be reasoning. We separately measured time from tool result to first model output and delay from transport to rendering. CPU and RAM figures are host samples. Low and high observations do not establish sustained utilization.

## 4. Performance and optimization results

The four paired controls matched final output bytes against their baseline. Near-64k cold prefill remained expensive even with improved decode. These controls are separate from the natural task runs.

| Control | Estimated input length | Previous tok/s | Optimized tok/s | Outcome |
| --- | ---: | ---: | ---: | --- |
| Short text | 4,791 | 15.69 | 30.39 | Exact response |
| Longer text | 16,361 | 14.63 | 28.41 | Exact response |
| Image fixture | Vision input | 15.99 | 30.53 | Exact response |
| Source retrieval | 59,419 | 11.61 | 23.69 | Exact three passages |

The paired R01 source-conflict task scored 100 on both arms and finished naturally. Decode changed from 15.665 to 26.230 tokens/s and full time from 179.021 to 121.937 seconds. Both matched S02 software-repair arms passed all 45 checks. Decode changed from 15.245 to 26.590 tokens/s and full time from 622.470 to 256.293 seconds. These are workload-specific findings. They do not establish quality equivalence on broader tasks.

Several plausible optimizations failed. Upgrading the upstream runtime alone changed decode by roughly −0.14% to +1.49% over four exact controls. A tested affinity mask slowed all four. An early fused draft placement decoded one longer case at 6.54 tokens/s versus 14.59 and timed out before generating on the 59,419-token case. Repositioning feed-forward work and draft buffers recovered much of the gain. Moving another block to CPU helped some controlled inputs but hurt the matched S02 task, which took 401.08 versus 275.59 seconds. Disabling CUDA graphs did not win the repeated short controls.

The same 4,791-token control also dropped from 29.27 to 17.00 tokens/s with the same response and draft acceptance. The original Field Kit run averaged 12.20 tokens/s, with 20 of 38 requests below 20. Pi S01 averaged 24.63 on the same profile, with two of 66 below 20. Draft acceptance alone did not explain the difference. The 40 tokens/s sustained target and joint 95% sustained CPU and RAM target remain open.

The recovered handoff's first block recorded 45 tool returns. Median time to first model output was 5.979 seconds, and median transport-to-Tk time was 32.3 milliseconds. All first output was reasoning. The candidate prompt template moved shared-prefix length from 32 to 60,172 tokens in an offline long serialization fixture. Live latency and correctness under that candidate remain unverified.

## 5. Recovery and accuracy results

### 5.1 Elapsed archive and productive continuity

The original 64k archive trial delivered all 32 originals in order with an exact final reconciliation. It issued 80 provider requests and committed 18 compactions. The same saved job resumed after 7,256.55 seconds at page 13 and 86,570.02 seconds at page 25. Both checkpoint writes were observed exactly once. An elapsed hold proves restart continuity over wall time. The separate productive workload requires three real work blocks spanning at least 48 hours and two hours of verified useful work.

The productive workload's first block measured 419.428 independently attributable productive seconds over 2,924.500 elapsed seconds. It preserved one original prompt, all 15 frozen inputs, and three checkpointed outputs. Both tables reproduced the 19 source tool counts, but the handbook totals were wrong. It also cited the wrong quantization, attributed unsupported process actions to an MCP server, and overstated an isolated Codemode test as a general live result. Its generated timestamps preceded admission. The quality gate failed regardless of intact bytes. Both later resumptions remain pending at this report's cutoff.

### 5.2 Matched uncertainty and repository work

All six R03 and R05 arms finished naturally and received full automated artifact credit. Independent prose review detected unsupported claims in both OpenCode notes. Pi and Hermes passed the separate prose review. The faster OpenCode R05 completion did not settle the correctness question.

| Workload | Client | Full time, s | Decode, tok/s | Prose review |
| --- | --- | ---: | ---: | --- |
| R03 evidence | Pi | 85.91 | 17.96 | Pass |
| R03 evidence | Hermes | 212.11 | 14.43 | Pass |
| R03 evidence | OpenCode | 584.33 | 11.55 | Correction needed |
| R05 missing input | Pi | 81.34 | 18.47 | Pass |
| R05 missing input | Hermes | 261.29 | 13.33 | Pass |
| R05 missing input | OpenCode | 73.04 | 16.54 | Correction needed |

In the matched L01 pytest task, all three preserved candidates passed seven selector checks and 243 original upstream tests with one expected failure. Pi's report contained a contradiction. Hermes changed unrelated scanner behavior and cited upstream incorrectly. OpenCode hit a deadline and the original checkout failed sealing at a Windows reparse point. A tracked-file snapshot passed isolated grading but still had a prose error. Expanded larger-repository and Meridian comparisons remain open.

### 5.3 Capstones and Android

In S01, Pi naturally finished in 2,384.212 seconds. It received 88.7789% from the frozen evaluator and failed the required manifest shape; the 30 validator checks passed in a separate diagnostic replay. Hermes reached the response limit and produced no release artifacts. OpenCode reached its final stop in 2,517.206 seconds but wrote a script outside output and was refused strict settlement. Its independent artifact diagnostic scored 99.3399%, while browser replay exposed a JavaScript error and missing dashboard rows.

In S04, Pi scored 87.931% without a natural finish and lacked the final report and dashboard. Hermes scored zero after stopping without the required result and evidence files. OpenCode received 96.5517% automatically but missed two live evidence checks and failed strict acceptance. For Field Kit, the first Android submission had no installable APK. Independent compilation found 26 Java errors. Offline checkout, return, and accessibility checks remain open for a clean candidate.

## 6. Standalone, audio, and video findings

The regular desktop initiated and used the native model in an isolated profile while the legacy applications were closed. The cold-start test took 54.88 seconds from GUI launch to verified settlement. A later test unloaded the idle model and started a new native process on the next prompt in the same chat, preserving the chat byte prefix and exact outputs. Five MCP registrations, a local checksum tool discovery and invocation, and a scoped Windows Calculator calculation passed. Detached history retained 2,990 messages and returned an exact 8,933-character sample across five pages. The public repository excludes the archive itself. Production OAuth, broader standalone integrations and independent retirement checks remain open.

The audio analyzer identified 7,760 full-scale samples on one channel, found the other channel digitally silent, and reported the measured 6.02 dB downmix change in a fresh blind Pi chat. Real overlapping recordings tested channel selection. One narration transcription differed in spelling normalization, and a non-speech classifier made an unsupported animal suggestion on a speech sample. An empty transcript and high classification scores require separate interpretation. Broader fresh-chat listening accuracy remains open.

The private Moonlit Map assembly decoded at 1× for 30 seconds. The frame and audio packet checks could locate specific beak, mouth-cue and sync defects. The initial independent AV model contradicted some known dialogue. Shot B's exact local repair, C's normal-speed sync, D and E perceptual review, and the 30-minute production trial require separate acceptance. A Wan2.2 render produced 121 distinct frames at 640 × 384 and 24 fps and restored the model profile. The subject entered clipped from the wrong side and disappeared, so the visual result failed. The image-conditioned follow-up remains unqualified.

## 7. Related work and engineering lessons

Speculative decoding pairs a draft and verifier to reduce serial target steps under specified sampling conditions. Its theoretical distribution guarantee does not make a particular runtime-and-model pairing automatically faster or bitwise identical under every setting. The PagedAttention paper motivates treating KV memory layout and reuse as practical throughput constraints. Pi uses those ideas as context and does not implement PagedAttention. [1] [2]

Strata combines CPU and GPU expert placement, adaptive caching, and prompt reuse for different model architectures. We inspected its pinned engine, API, grading and tuning code. The targeted audit passed 239 Python tests with five tokenizer-dependent skips, 13,534 standalone cache assertions and 72 synthetic sampling cases. These are code tests. The closest published community report used the same GPU with another CPU and model, reaching about 49 tokens/s at 128k while waiting about 69 seconds for first output. Pi’s current dense qwen35 model is outside the audited Strata engine families. Borrowing prompt reuse, telemetry, and paired tuning is the next development path. A backend swap requires fresh matched outcomes. [3]

A recurring lesson is to publish failures on the same footing as wins. Exact checks should cover both detail and aggregate claims, distinguish source evidence from model prose, separate prefill from generation, and track forced holds separately from useful work. A successful transport response does not prove that a command executed or that state was preserved.

## 8. Reproducibility, privacy, and limitations

The release bundles the Windows desktop source, launcher, pinned setup assets, local fixture scripts, synthetic archive data and answer grader, editable paper source, and measured public summaries. Users can verify the package and run desktop, restart, and launcher fixtures with a local mock model. To repeat inference, obtain the exact pinned public model and runtime assets and use one isolated workspace per arm. Use the original task prompt, record actual model profile and time, and grade shape, sources and semantics separately. Asset setup does not require a provider account. Dependency and model downloads are optional inbound setup operations.

The reported experiments come from one workstation and individual matched runs. Different drivers, memory pressure, revisions, and task context can change performance. Raw transcripts, signed-in sessions, private deliveries, local configuration, and credentials are outside the release. Synthetic reproductions and released rollups provide comparable checks without publishing those records. Desktop tools execute under the current Windows account. The local model service is loopback-only; the desktop does not provide an operating-system sandbox for scripts.

This is a versioned technical report. Each successful milestone adds a dated evidence entry, documents regressions and open conditions, regenerates the PDF, and attaches it to the matching release. Experimental candidates stay labeled until their independent checks pass.

## 9. Conclusion

Pi has demonstrated a standalone local model lifecycle, exact elapsed archive recovery, and strong improvements on several controlled workloads. Real tasks also revealed slowdown, unsupported claims, and incomplete handoffs that isolated speed and fixture checks would miss. The next evaluation must verify both live productive resumptions, measure near-64k prompt reuse in the desktop, finish the remaining task and media grades, and close the remaining standalone parity gaps.

### References and artifacts

[1] Leviathan, Y., Kalman, M., and Matias, Y. 2023. [Fast Inference from Transformers via Speculative Decoding](https://proceedings.mlr.press/v202/leviathan23a.html). ICML, PMLR 202, 19274–19286.

[2] Kwon, W. et al. 2023. [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180). SOSP.

[3] Niko1221 and contributors. 2026. [Strata source at the audited revision](https://github.com/Niko1221/Strata/tree/3142b66b96e9c0e775e30f620b11b191a1427c2a) and [Pi Local source review](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/docs/strata-evaluation.md).

[4] ggml-org and contributors. 2026. [llama.cpp release b12541](https://github.com/ggml-org/llama.cpp/releases/tag/b12541). JonathanColetti. 2026. [Pinned model revision](https://huggingface.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF/tree/45d0fc0ad6cfcf9eeee6008ddaea925536409b18).

[5] Wan-Video and contributors. [Wan2.2 reference code and model instructions](https://github.com/Wan-Video/Wan2.2).

[6] KyrellosAyman. 2026. [Pi Local v0.1.1 software and paper](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.1), [reproduction guide](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/docs/reproducibility.md), and [public result ledger](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/research/evidence/2026-11-20.md).
