# Pi Local
## A desktop harness for local inference and recoverable agent work

**KyrellosAyman**

Technical report • Version 0.1.7 • 22 November 2026

### Abstract

Pi Local is a Windows desktop harness for running a local multimodal language model, combining local tools, and recovering interrupted work. We developed a desktop client around a pinned Pi RPC runtime and a self-managed llama.cpp service, then evaluated tool routing, source retention, checkpoint integrity, and performance on one consumer workstation. An elapsed recovery trial retained one prompt across two process interruptions, delivered all 32 original archive pages in order, and produced the exact reconciliation after 18 compactions. The optimized 64,000-token profile improved decode on four matched controls without changing their final output bytes. At 59,419 input tokens, it raised decode from 11.61 to 23.69 tokens/s while total response time increased from 123.14 to 144.78 seconds. Larger source, software, audio, and video workloads exposed accuracy and performance failures. This report records the experimental conditions, the negative results, and the boundaries of reproduction. The public release contains the code, presets, synthetic archive inputs, and the procedures for independent checks.

In a separate native test near 60,000 input tokens, warming a stable prompt prefix reduced three-request time from 456.887 to 156.467 seconds, including the warmup. The same file-read arguments, plan update, and final code were observed. A matched desktop test cut first-plan review retries from two to zero. Production chat adoption of the cache result remains open.

A later 36-minute desktop run passed strict grading with up to 61,573 input tokens while median near-limit decode fell to 3.20 tokens/s. Changing only the input in a short, near-limit and short control produced decode rates of 32.56, 8.90 and 32.48 tokens/s with an identical answer. The desktop now reports the pending first-plan review and distinguishes a live shared speed sample from the idle rate. [8]

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

The released checkpoint code verifies declared digests at stage closure, recovery, and settlement. It refuses direct writes and edits to completed checkpoint files while their stages remain closed. A changed checkpoint pauses recovery before a provider request. The pinned RPC restart fixture preserved one original prompt and an exact tool result, blocked an edit to a completed artifact, and finished the next output. A separate fixture detected out-of-band drift at settlement. During S01, the model twice retried a plan update that omitted an already completed row. Pi now carries that row and its proof forward. The restart fixture reproduced the failed revision and verified the corrected plan in the GUI and saved checkpoint. Qualification across the full productive continuity run remains open.

### 2.3 Tool routing, rendering, and media

Pi starts new tool work with a brief and a concrete plan, then searches the local skill catalog and activates a relevant procedure. The release reuses unchanged skill instructions within a chat. In the fixture, the first skill response was 24,673 bytes and the repeat receipt was 270 bytes. If compaction removes the full response, Pi restores the exact revision before it next calls the provider. A paired desktop rendering test preserved text, native tags, link ranges and viewport behavior. For a 39,000-character reply, median render time fell from 13.080 to 0.200 seconds on the same host. This measured GUI rendering independently of inference time.

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

The recovered handoff's first block recorded 45 tool returns. Median time to first model output was 5.979 seconds, and median transport-to-Tk time was 32.3 milliseconds. All first output was reasoning. The candidate prompt template moved shared-prefix length from 32 to 60,172 tokens in an offline long serialization fixture. A later native experiment measured actual reuse separately.

A later guided S01 delivery repair ran in visible Pi for 8,787.78 seconds. Exact output counts and timestamps matched all 160 model requests and nine compactions to the native log. Separate clocks diverged by up to 370 ms during the run. Median decode was 19.21 tokens/s. Of the 160 requests, 103 fell below 20 and none reached 40. The highest sampled context was 43,362 tokens in the 64,000-token profile. The median post-tool wait was 1.47 seconds, with a 248.63-second maximum. Compaction and native prefill explained most of the longest interval. Median transport-to-Tk time was 134.37 ms across observed delays. None of 2,390 host samples reached 95% CPU and RAM together. This single guided workload leaves the sustained near-64k targets open.

The recovered follow-up supplied 85 more matched desktop requests. Native decode had a median of 22.04 tokens/s. Thirteen requests fell below 20 and the largest main input was 39,450 tokens. Four of five compactions matched. The 200.623-second maximum post-tool wait contained 158.035 seconds of matched compaction and 42.139 seconds of native prefill. The first chunk reached Tk in 43 ms. No sample reached 95% CPU and RAM together in 1,307 observations.

The installed uncoached S01 ran for 7,321.82 seconds. The 150 matched requests had a median of 22.15 tokens/s at up to 41,275 input tokens. Seventeen fell below 20 and none reached 40. The longest post-tool wait was 171.19 seconds, almost all in compaction and prefill. Tk received the first chunk in about 40 ms. None of 2,087 samples reached joint 95% CPU and RAM.

One fixed long-source text task exposed a separate reply budget error. The stock client sent only one allowed output token at 57,884 and 57,902 input tokens. A reply allowance correction reached the first tools, but the full schema catalog later took the provider input to 77,891 tokens and failed the context limit. A measured request attributed 17,732 tokens to the 43 tool schemas. Pi now consults the authenticated local template and tokenizer for eligible text requests when the estimate allows only one output token. If the full schema catalog still leaves too little room, it offers three direct tools and keeps access to the registered catalog through Codemode.

The final live run reached 61,232 input tokens, matched seven native requests, used one registered file read, and returned all three required codes on one line in 944.57 seconds. No compaction occurred. The median of six near-limit requests was 19.566 tokens/s, three of six fell below 20, and none reached 40. A cached wait after the file tool was 1.22 seconds, while multiple full prompts took about 150 seconds to prepare. None of 263 host samples reached joint 95% CPU and RAM. This result establishes task completion in the tested text case. The tokenizer check excludes image and audio inputs.

Two frozen desktop runs attributed 94.74% and 94.61% of total time to prompt processing. Each had five post-tool waits over 100 seconds. Prompt processing accounted for over 99.5% of those waits. In a separate three-stage raw-completion experiment on the same running model, the current and alternate template orders both recomputed the full prompt at each stage. Their summed request times were 456.887 and 454.055 seconds. With an explicit warmup, the alternate reused 59,651 to 59,655 tokens per request and used 156.467 seconds including the warmup. All three expected operations still matched. Decode ranged from 17.217 to 22.729 tokens/s in the warmed arm. The observer was interrupted after the warmup and recovered the same native task. Request totals exclude that observer interval. The production chat API and desktop trial remain open.

A later uncoached visible Pi run passed the same strict source and answer checks in 2,205.93 seconds. It performed one initial review and seven successful tool calls, including the exact registered file read. All eight requests matched the native log. The maximum input was 61,573 tokens, with seven near-limit requests below 20 tokens/s and a 3.20 tokens/s median. During the first four post-tool waits, native prefill accounted for over 99.8% of their 263–280 seconds. Tk handled the first output in 16–40 ms. The mapped chat viewport held its height and the animation advanced. After the file read, reuse of 61,550 tokens let the next request deliver output in 0.952 seconds. None of 628 host samples met the joint 95% threshold. [8]

A cold short, near-limit and short comparison on the unchanged process measured 4,790, 59,537 and 4,790 input tokens. All three arms produced the same 182-token answer and accepted 121 of 122 draft tokens. Prefill took 9.09, 179.13 and 9.07 seconds. Decode measured 32.56, 8.90 and 32.48 tokens/s. Fifteen guarded samples during the near-limit decode reported a median device PCIe transmit rate of 17,814 MB/s. The short arms yielded too few guarded samples for a paired device comparison. Earlier byte-identical short controls on that process also varied between about 11.5 and 33 tokens/s. The results establish the slowdown for this longer input and motivate a controlled GPU memory placement comparison. The transfer mechanism remains open. [8]

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

### 5.4 Clarification and first-plan review

Pi uses its existing RPC input channel for clarification. Clear prompts can proceed without a question. A material ambiguity can produce one question, with at most two in the same task. Three buttons submit their answer with one click and the first is marked Recommended. The fourth row accepts custom text. Pi saves the question before display and the answer before continuing. A live control asked no question, another accepted one typed answer, and a third accepted one button click and used the selected audience. An earlier live version stored the choice but asked again. Including the saved choice as user input corrected that case without duplicating the original prompt. A controlled restart fixture tested the unanswered card and the interval after committing an answer but before RPC acknowledgment.

The first actionable draft becomes a pending plan. The same local model makes a constrained review pass using the request, clarified brief, and draft. Pi blocks work tools while review is pending, commits one accepted plan, and applies later progress updates directly. It assigns the first reviewed step in progress and preserves already declared checkpoint paths. One earlier attempt needed a status correction. A later attempt reported missing steps but returned the broad draft unchanged. The final implementation assigns statuses itself and rejects an unchanged plan with unresolved findings.

In a live file-copy test, the reviewer converted one broad step into reading and hashing the original, copying it byte for byte, and comparing both files. It committed the plan on one review call before any work tools ran. The task closed all three steps. Independent grading matched the two 76-byte files and the original fixture. Controlled restarts before and after review recovered one committed plan and no repeat review after plan updates. The tests establish those behaviors on the specified workloads. Broader semantic quality remains a separate evaluation.

A subsequent matched browser test exposed two retries when the reviewer described already satisfied checks as requested fixes. The reviewer can now commit the complete saved draft without rewriting its steps. Revision still retains declared checkpoint paths and requires changed steps when a correction is claimed. The matched workflow committed once with zero retries. Draft-to-accept time fell from 64.336 to 13.065 seconds and full time from 306.540 to 159.128 seconds in this pair. Recovery tests exercised both accepting and revising the draft.

## 6. Standalone, audio, and video findings

The regular desktop initiated and used the native model in an isolated profile while the legacy applications were closed. The cold-start test took 54.88 seconds from GUI launch to verified settlement. A later test unloaded the idle model and started a new native process on the next prompt in the same chat, preserving the chat byte prefix and exact outputs. Five MCP registrations, a local checksum tool discovery and invocation, and a scoped Windows Calculator calculation passed. Detached history retained 2,990 messages and returned an exact 8,933-character sample across five pages. The public repository excludes the archive itself. In a signed-in Chrome tab, a normal Pi chat verified one approved control using its own catalog and filtered reader. The run made no page action and returned only the requested control from the browser tool. The routing change removed a redundant skill search and a discovery call in the matched retake. Production OAuth, broader integrations and retirement checks remain open.

Pi applies explicitly configured MCP OAuth scopes during sign-in, stored-token use and refresh. The bundled CLI passed five loopback scenarios, including rejection of broader grants and an authenticated catalog read after refresh in a new process. Fresh and offline setups reproduced the result. The five configured servers still listed 69 tools. A production read-only endpoint produced a read-only authorization request with PKCE and the expected resource and loopback callback. The production test stopped at browser handoff. Account consent and an authenticated read remain open. [9]

The audio analyzer identified 7,760 full-scale samples on one channel, found the other channel digitally silent, and reported the measured 6.02 dB downmix change in a fresh blind Pi chat. Real overlapping recordings tested channel selection. One narration transcription differed in spelling normalization, and a non-speech classifier made an unsupported animal suggestion on a speech sample. An empty transcript and high classification scores require separate interpretation. Broader fresh-chat listening accuracy remains open.

Another Pi audio call failed because its restricted Windows child lacked NumPy. The staged setup pins five optional Python packages in Pi's own environment. A fresh installation and offline check passed. The registered tool returned the same synthetic narration with both CPU runtimes. In nine windows from three archived recording mixtures, the new environment matched four previous transcript and sound classification results and kept the recording setup unknown in every case. With overlapping speech, the mono transcript contained seven errors against the dominant 22-word reference. Separate channels yielded zero errors in that reference and only a title abbreviation in the other. The installer used fixture asset provisioning, and the audio checks used separately verified local media assets.

The regular GUI's Audio report independently passed checks against decoded PCM across five windows of those recordings. One stereo report measured the second channel at 6.10 dB below the first in peak and 9.97 dB below it in RMS. Its decoded nonzero interval was 3.000–8.855 seconds. The report left the recording setup unknown and labeled the transcript and sound candidates as estimates. The first check on the installed desktop found a missing runtime manifest. Provisioning the exact pinned media assets fixed the same open report.

The later audio asset installer built a fresh offline runtime from five verified source downloads. It verified all 27 installed files, reproduced the five decoded PCM and report checks with FFmpeg 9.1, and rejected a modified classifier label map. The full Windows setup also passed from a clean copy of the 136 candidate source files with the pinned Python and Node environments and cached assets. Both the clean package and the installed desktop reproduced the five checks. The visible stereo report used local audio processing without a chat model.

A matched installed chat gave the correct channel levels while inferring that the difference arose at capture. The analyzer then explicitly limited these measurements to the decoded file. With the same prompt, recordings and model profile, a fresh chat finished in 320.15 seconds. It used one analyzer call, reported both differences with the correct reference, and left the recording conditions unresolved. Three window replays preserved every other measured value. The result establishes the focused stereo case. Broader listening and freeform interpretation still require separate evaluation.

In the full blind chat, 21 analyzer calls recovered distinct voices, relative channel levels and provisional water labels in 1,438.31 seconds. Strict grading found an unsupported mono-source inference, timing based on a chosen inspection window, and an overstated silence label. Median native decode was 21.14 tokens/s across 20 matched requests, with four below 20. The longest wait was 137.82 seconds, including 61.70 seconds of compaction and 75.55 seconds of prefill. The revised Pi skill activated without a shared library and its tool passed two exact PCM controls.

The same prompt, recordings and model profile ran with the revised skill and media runtime in 1,089.40 seconds. All 25 analyzer calls succeeded. Pi identified unequal stereo samples and separated measured silence from the classification. It omitted recoverable opening words and relative levels, overestimated the overlap interval and missed the shift from ocean-like to rain-like candidates. Strict listening remains open. Median decode was 20.52 tokens/s and seven of 20 requests fell below 20. Concurrent setup and transfers limit elapsed-time comparisons.

The subsequent listening workflow grounds the final chat report in the current turn’s local measurement records. It renders PCM levels, decoded activity, separate stereo speech estimates and tentative sound candidates scoped to their observed windows. When a full-window recognition has invalid word times, a valid activity-window pass can replace it if the normalized words closely agree. Pi keeps the replacement words and their own times together and discloses any lexical disagreement.

Two controlled case sets passed in the visible local Pi chat after exact-input replays. The second set passed 13 content checks and the timing checks, with 99 of 99 reference words recovered. The third set originally passed 12 of 15 checks. An independent audit found that one word score included an explanatory note and that the missing left speech time remained a real failure. The unchanged third replay passed all 15 checks. Four speech estimates were within their frozen error limits. The left and right estimates of 0.59–10.11 and 11.19475–19.51475 seconds were both inside their independently decoded activity, and the report left audible overlap unresolved. The run took 966.031 seconds over 17 requests, with a 132.418-second longest mapped post-tool wait. These controlled replays establish the targeted repairs on the exercised inputs. Unaltered multi-speaker recordings and real-world listening accuracy have yet to pass a comparable test. [10]

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

[6] KyrellosAyman. 2026. [Pi Local releases](https://github.com/KyrellosAyman/pi-local/releases), [v0.1.3 fixtures and results](https://github.com/KyrellosAyman/pi-local/blob/v0.1.3/research/evidence/2026-11-22.md).

[7] KyrellosAyman. 2026. [v0.1.4 matched results](https://github.com/KyrellosAyman/pi-local/blob/v0.1.4/research/evidence/2026-11-22-follow-up.md). ggml-org and contributors. [Pinned native server completion and prompt-cache documentation](https://github.com/ggml-org/llama.cpp/blob/b12541/tools/server/README.md).

[8] KyrellosAyman. 2026. [v0.1.5 desktop and long-context results](https://github.com/KyrellosAyman/pi-local/blob/v0.1.5/research/evidence/2026-11-22-desktop-performance.md).

[9] KyrellosAyman. 2026. [v0.1.6 MCP OAuth scope results](https://github.com/KyrellosAyman/pi-local/blob/v0.1.6/research/evidence/2026-11-22-mcp-oauth.md).

[10] KyrellosAyman. 2026. [v0.1.7 local listening and timing results](https://github.com/KyrellosAyman/pi-local/blob/v0.1.7/research/evidence/2026-11-22-listening.md).
