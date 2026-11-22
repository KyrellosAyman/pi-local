# Pi Local
## A desktop harness for local inference and recoverable agent work

**KyrellosAyman**

Technical report • Version 0.1.2 • 22 November 2026

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

The next-release candidate verifies declared checkpoint digests at stage closure, recovery, and settlement. It refuses direct writes and edits to completed checkpoint files while their stages remain closed. A changed checkpoint pauses recovery before a provider request. The pinned RPC restart fixture preserved one original prompt and an exact tool result, blocked an edit to a completed artifact, and finished the next output. A separate fixture detected out-of-band drift at settlement. During S01, the model twice retried a plan update that omitted an already completed row. The candidate now carries the row and its proof forward. The restart fixture reproduced the failed revision and verified the corrected plan in the GUI and saved checkpoint. Live installation and a passing productive continuity trial remain open.

### 2.3 Tool routing, rendering, and media

Pi starts new tool work with a brief and a concrete plan, then searches the local skill catalog and activates a relevant procedure. The next-release candidate reuses unchanged skill instructions within a chat. In the fixture, the first skill response was 24,673 bytes and the repeat receipt was 270 bytes. If compaction removes the full response, Pi restores the exact revision before it next calls the provider. The desktop suite passed 89 checks covering streaming, Markdown, scroll following, interruption, tool receipts and chat history.

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

A later guided S01 delivery repair ran in visible Pi for 8,787.78 seconds. Exact output counts and timestamps matched all 160 model requests and nine compactions to the native log. Separate clocks diverged by up to 370 ms during the run. Median decode was 19.21 tokens/s. Of the 160 requests, 103 fell below 20 and none reached 40. The highest sampled context was 43,362 tokens in the 64,000-token profile. The median post-tool wait was 1.47 seconds, with a 248.63-second maximum. Compaction and native prefill explained most of the longest interval. Median transport-to-Tk time was 134.37 ms across observed delays. None of 2,390 host samples reached 95% CPU and RAM together. This single guided workload leaves the sustained near-64k targets open.

The recovered follow-up supplied 85 more matched desktop requests. Native decode had a median of 22.04 tokens/s. Thirteen requests fell below 20 and the largest main input was 39,450 tokens. Four of five compactions matched. The 200.623-second maximum post-tool wait contained 158.035 seconds of matched compaction and 42.139 seconds of native prefill. The first chunk reached Tk in 43 ms. No sample reached 95% CPU and RAM together in 1,307 observations.

The installed uncoached S01 ran for 7,321.82 seconds. The 150 matched requests had a median of 22.15 tokens/s at up to 41,275 input tokens. Seventeen fell below 20 and none reached 40. The longest post-tool wait was 171.19 seconds, almost all in compaction and prefill. Tk received the first chunk in about 40 ms. None of 2,087 samples reached joint 95% CPU and RAM.

## 5. Recovery and accuracy results

### 5.1 Elapsed archive and productive continuity

The original 64k archive trial delivered all 32 originals in order with an exact final reconciliation. It issued 80 provider requests and committed 18 compactions. The same saved job resumed after 7,256.55 seconds at page 13 and 86,570.02 seconds at page 25. Both checkpoint writes were observed exactly once. An elapsed hold proves restart continuity over wall time. The separate productive workload requires three real work blocks spanning at least 48 hours and two hours of verified useful work.

The first productive attempt verified 419.428 productive seconds over a 2,924.500-second first block. Its two tables reproduced all 19 tool counts, while the handbook contained incorrect totals and unsupported claims. After a Windows restart and an 86,400.043-second hold, it continued the correct step with the original prompt and all three checkpointed outputs. A later edit changed the checkpointed handbook and failed preservation. The resumed block ended after 7,986.304 elapsed seconds and at most 2,171.691 eligible seconds. This fell short of two productive hours and produced no second checkpoint.

The protected retest preserved all 15 inputs, six sealed files, and the original transcript at its first controlled interruption. Its next phase remains subject to the full elapsed hold. Independent Windows controls also reproduced a settlement error when the old temporary name reached 275 characters. Short sibling names restored archival. The installed desktop retained and found a new 260-character transcript, and recovery correctly recognized its original user turn.

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

In the initial L01 pytest comparison, separate executable checks passed for all three candidates, but their report, scope or settlement checks failed. A follow-up matched one run per client on the same optimized serving process, with 618 files per checkout and one frozen prompt each. All three passed strict acceptance. Pi took 281.69 seconds and generated 5,949 tokens. Hermes took 979.60 seconds and generated 19,678. OpenCode took 629.59 seconds and generated 12,028. The longest prompt among the three was 41,929 tokens. Larger-repository replication and the final original-profile Meridian arm remain open.

### 5.3 Capstones and Android

In S01, Pi naturally finished in 2,384.212 seconds. It received 88.7789% from the frozen evaluator and failed the required manifest shape; the 30 validator checks passed in a separate diagnostic replay. Hermes reached the response limit and produced no release artifacts. OpenCode reached its final stop in 2,517.206 seconds but wrote a script outside output and was refused strict settlement. Its independent artifact diagnostic scored 99.3399%, while browser replay exposed a JavaScript error and missing dashboard rows.

In S04, Pi scored 87.931% without a natural finish and lacked the final report and dashboard. Hermes scored zero after stopping without the required result and evidence files. OpenCode received 96.5517% automatically but missed two live evidence checks and failed strict acceptance. For Field Kit, the first Android submission had no installable APK. Independent compilation found 26 Java errors, so that run ended before Android transaction grading.

Pi's focused S01 repair was guided by the earlier defects. All 44 frozen inputs remained intact. Its final validator passed 30 separate checks, its local suite passed 21 assertions, and the dashboard passed six independent checks, including keyboard filtering and operation without external requests. The 30-second export decoded completely and contained narration covering the three days, 30 activities and 596 attendees. Its longest caption clipped and the required floorplan was absent. A malformed evidence file caused the frozen evaluator to skip later checks. The automated score was 88.1188% and strict acceptance failed.

The next repair was saved at the video stage when Windows restarted. Visible Pi resumed that same prompt and preserved the 44 inputs and six accepted deliverables. The new export included the original floorplan, fit all five caption cues, and preserved all 1,293 AAC packet payloads. The isolated grader passed the test suite, browser checks, and all ten manifest hashes. Its 99.67% automated score missed the required numeric forms of the two caption totals. A separate operator control used those numeric forms and passed all 345 reported checks. Both results are retained. Perceived playback and the separate live-research lane remain open.

At the 110-minute cutoff, uncoached S01 in ordinary Pi scored 85.4785% and preserved all 44 inputs. The schedule, 120 booking records and 16 submitted tests passed. A separate validator replay found a missed equipment limit. Dashboard filtering worked, but totals were wrong and invalid UTF-8 prevented later rubric checks. The report, video, captions and manifest stayed absent. When the stalled job was stopped through the GUI after 122 minutes, its score and all output hashes matched the cutoff. This arm used ordinary Pi tools as a separate comparison.

A focused installed repair produced a non-silent WAV, a strict UTF-8 HTML receipt and a successful PowerShell import without cache files. Offline speech recognition recovered the exact five-word reference. The 863.56-second desktop run added prose around the requested exact answer. In a separate uncoached retest, all 120 booking rows and the revised three-day schedule passed. At 110 minutes the score was 85.1485%, with all 44 inputs preserved. The days field had the wrong type and the validator, dashboard and audiovisual handoff were absent.

The guided Field Kit repair produced an APK whose unsigned entries matched an independent offline rebuild. On Android API 35 at 320 × 640 and 130% text, it rejected invalid quantities without changing inventory, preserved a checkout across a force stop, and passed the return cancellation and confirmation checks. Wi-Fi stayed off and the package requested no internet permission. This evidence covers the guided repair and the tested interface flows.

## 6. Standalone, audio, and video findings

The regular desktop initiated and used the native model in an isolated profile while the legacy applications were closed. The cold-start test took 54.88 seconds from GUI launch to verified settlement. A later test unloaded the idle model and started a new native process on the next prompt in the same chat, preserving the chat byte prefix and exact outputs. Five MCP registrations, a local checksum tool discovery and invocation, and a scoped Windows Calculator calculation passed. Detached history retained 2,990 messages and returned an exact 8,933-character sample across five pages. The public repository excludes the archive itself. With Chrome renderer accessibility enabled, Pi's adapter identified the approved document and profile control in a signed-in tab. Chat-driven production use, production OAuth, broader integrations and retirement checks remain open.

The audio analyzer identified 7,760 full-scale samples on one channel, found the other channel digitally silent, and reported the measured 6.02 dB downmix change in a fresh blind Pi chat. Real overlapping recordings tested channel selection. One narration transcription differed in spelling normalization, and a non-speech classifier made an unsupported animal suggestion on a speech sample. An empty transcript and high classification scores require separate interpretation. Broader fresh-chat listening accuracy remains open.

Another Pi audio call failed because its restricted Windows child lacked NumPy. The staged setup pins five optional Python packages in Pi's own environment. A fresh installation and offline check passed. The registered tool returned the same synthetic narration with both CPU runtimes. In nine windows from three archived recording mixtures, the new environment matched four previous transcript and sound classification results and kept the recording setup unknown in every case. With overlapping speech, the mono transcript contained seven errors against the dominant 22-word reference. Separate channels yielded zero errors in that reference and only a title abbreviation in the other. The installer used fixture asset provisioning, and the audio checks used separately verified local media assets.

The regular GUI's Audio report independently passed checks against decoded PCM across five windows of those recordings. One stereo report measured the second channel at 6.10 dB below the first in peak and 9.97 dB below it in RMS. Its decoded nonzero interval was 3.000–8.855 seconds. The report left the recording setup unknown and labeled the transcript and sound candidates as estimates. The first check on the installed desktop found a missing runtime manifest. Provisioning the exact pinned media assets fixed the same open report.

The later audio asset installer built a fresh offline runtime from five verified source downloads. It verified all 27 installed files, reproduced the five decoded PCM and report checks with FFmpeg 9.1, and rejected a modified classifier label map. The full Windows setup also passed from a clean copy of the 136 candidate source files with the pinned Python and Node environments and cached assets. Both the clean package and the installed desktop reproduced the five checks. The visible stereo report used local audio processing without a chat model.

A matched installed chat gave the correct channel levels while inferring that the difference arose at capture. The analyzer then explicitly limited these measurements to the decoded file. With the same prompt, recordings and model profile, a fresh chat finished in 320.15 seconds. It used one analyzer call, reported both differences with the correct reference, and left the recording conditions unresolved. Three window replays preserved every other measured value. The result establishes the focused stereo case. Broader listening and freeform interpretation still require separate evaluation.

In the full blind chat, 21 analyzer calls recovered distinct voices, relative channel levels and provisional water labels in 1,438.31 seconds. Strict grading found an unsupported mono-source inference, timing based on a chosen inspection window, and an overstated silence label. Median native decode was 21.14 tokens/s across 20 matched requests, with four below 20. The longest wait was 137.82 seconds, including 61.70 seconds of compaction and 75.55 seconds of prefill. The revised Pi skill activated without a shared library and its tool passed two exact PCM controls.

The same prompt, recordings and model profile ran with the revised skill and media runtime in 1,089.40 seconds. All 25 analyzer calls succeeded. Pi identified unequal stereo samples and separated measured silence from the classification. It omitted recoverable opening words and relative levels, overestimated the overlap interval and missed the shift from ocean-like to rain-like candidates. Strict listening remains open. Median decode was 20.52 tokens/s and seven of 20 requests fell below 20. Concurrent setup and transfers limit elapsed-time comparisons.

The private Moonlit Map assembly decoded at 1× for 30 seconds. The frame and audio packet checks could locate specific beak, mouth-cue and sync defects. The initial independent AV model contradicted some known dialogue. Shot B's exact local repair, C's normal-speed sync, D and E perceptual review, and the 30-minute production trial require separate acceptance.

The initial Wan2.2 5B shot moved about 209 pixels left and clipped the right edge. A second control used a single upright start image. The car stayed in view and advanced 10.56 pixels right, with a late reversal and shape distortion. Each clip had 121 frames at 640 × 384 and 24 fps. The 5B validator rejected 25-frame source overlap, which preflight now catches before the GPU handoff. The workstation trials used quantized weights and an exclusive handoff. [5]

The 14B start-and-end route rendered 81 progressive frames at 640 × 384 and 16 fps in 1,111.84 seconds and restored the chat model. The upright car advanced 144.07 pixels right and held within 0.33 pixels over the final 12 frames. A single 18.28-pixel jump failed the raw motion grade. Pi reproduced a reviewed motion-compensated correction byte for byte, reducing the largest step to 4.86 pixels. The chat confused the 128 fps intermediate with the eightfold rate multiplier. The wheel surfaces leave rotation unverified.

## 7. Related work and engineering lessons

Speculative decoding pairs a draft and verifier to reduce serial target steps under specified sampling conditions. Its theoretical distribution guarantee does not make a particular runtime-and-model pairing automatically faster or bitwise identical under every setting. The PagedAttention paper motivates treating KV memory layout and reuse as practical throughput constraints. Pi uses those ideas as context and does not implement PagedAttention. [1] [2]

Strata combines CPU and GPU expert placement, adaptive caching, and prompt reuse for different model architectures. We inspected its pinned engine, API, grading and tuning code. The targeted audit passed 239 Python tests with five tokenizer-dependent skips, 13,534 standalone cache assertions and 72 synthetic sampling cases. These are code tests. The closest published community report used the same GPU with another CPU and model, reaching about 49 tokens/s at 128k while waiting about 69 seconds for first output. Pi’s current dense qwen35 model is outside the audited Strata engine families. Borrowing prompt reuse, telemetry, and paired tuning is the next development path. A backend swap requires fresh matched outcomes. [3]

A recurring lesson is to publish failures on the same footing as wins. Exact checks should cover both detail and aggregate claims, distinguish source evidence from model prose, separate prefill from generation, and track forced holds separately from useful work. A successful transport response does not prove that a command executed or that state was preserved.

## 8. Reproducibility, privacy, and limitations

The release bundles the Windows desktop source, launcher, pinned setup assets, local fixture scripts, synthetic archive data and answer grader, editable paper source, and measured public summaries. Users can verify the package and run desktop, restart, and launcher fixtures with a local mock model. To repeat inference, obtain the exact pinned public model and runtime assets and use one isolated workspace per arm. Use the original task prompt, record actual model profile and time, and grade shape, sources and semantics separately. Asset setup does not require a provider account. Dependency and model downloads are optional inbound setup operations.

The reported experiments come from one workstation and individual matched runs. Different drivers, memory pressure, revisions, and task context can change performance. Raw transcripts, signed-in sessions, private deliveries, local configuration, and credentials are outside the release. Synthetic reproductions and released rollups provide comparable checks without publishing those records. Desktop tools execute under the current Windows account. The local model service is loopback-only; the desktop does not provide an operating-system sandbox for scripts.

This is a versioned technical report. Each successful milestone adds a dated evidence entry, documents regressions and open conditions, regenerates the PDF, and attaches it to the matching release. Experimental candidates stay labeled until their independent checks pass.

## 9. Conclusion

Pi has demonstrated a standalone local model lifecycle, exact elapsed archive recovery, and improvements on several controlled workloads. Real tasks also revealed slowdown, unsupported claims, and incomplete handoffs. The next evaluation must pass productive continuity with preserved artifacts, measure near-64k prompt reuse in the desktop, finish the remaining task and media grades, and close the remaining standalone parity gaps.

### References and artifacts

[1] Leviathan, Y., Kalman, M., and Matias, Y. 2023. [Fast Inference from Transformers via Speculative Decoding](https://proceedings.mlr.press/v202/leviathan23a.html). ICML, PMLR 202, 19274–19286.

[2] Kwon, W. et al. 2023. [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180). SOSP.

[3] Niko1221 and contributors. 2026. [Strata source at the audited revision](https://github.com/Niko1221/Strata/tree/3142b66b96e9c0e775e30f620b11b191a1427c2a) and [Pi Local source review](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/docs/strata-evaluation.md).

[4] ggml-org and contributors. 2026. [llama.cpp release b12541](https://github.com/ggml-org/llama.cpp/releases/tag/b12541). JonathanColetti. 2026. [Pinned model revision](https://huggingface.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF/tree/45d0fc0ad6cfcf9eeee6008ddaea925536409b18).

[5] Wan-Video and contributors. [Wan2.2 reference code and model instructions](https://github.com/Wan-Video/Wan2.2).

[6] KyrellosAyman. 2026. [Pi Local v0.1.1 software and paper](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.1), [reproduction guide](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/docs/reproducibility.md), and [public result ledger](https://github.com/KyrellosAyman/pi-local/blob/v0.1.1/research/evidence/2026-11-20.md).
