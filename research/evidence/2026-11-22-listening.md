# Local listening and word timing in Pi

22 November 2026. Three-recording tests used the regular Windows Pi GUI, one original prompt, a reviewed plan and the same owned 64k local model service. Each case set used neutral WAV filenames. Reference transcripts, source construction and the grader stayed outside the model's workspace. The raw chats and recordings remain private. The public media fixture generates its own inputs.

## What changed

Pi saves audio observations from the current turn and renders its chat report from those observations after completing the reviewed plan. The standalone Audio report uses the same local analyzer. It keeps decoded PCM, speech estimation and sound classification distinct. Different stereo channels can return separate transcripts and time ranges. Sound candidates are labeled with their channel or mix and analyzed interval.

When a recognizer's word range falls outside decoded activity by more than 250 ms, Pi can re-estimate it within the decoded activity window. It accepts the second pass only when its timing is valid and its normalized words closely match the first pass. The accepted words and timing come from that same pass. Differences are disclosed. A materially different or out-of-bounds result leaves the first transcript and unresolved timing.

## Observed results

| Run | Verified grade | Wall time | Model requests | Largest input | Longest mapped post-tool wait |
| --- | --- | ---: | ---: | ---: | ---: |
| Second case set, exact replay | 13 content checks and timing passed, 99 of 99 reference words | 1,136.203 s | 19 | 37,323 tokens | 130.379 s |
| Third case set, first run | 12 of 15 checks passed, left speech time missing | 1,047.156 s | 24 | 38,737 tokens | 76.619 s |
| Third case set, exact replay after repair | 15 of 15 checks passed and independent audit passed | 966.031 s | 17 | 37,667 tokens | 132.418 s |

The third case set used 16, 24 and 48 kHz PCM. One case paired duplicated speech with right-channel waves. The next placed different voices in nonintersecting channel intervals. The third used identical channels with ticking and rain in consecutive windows. Both exact replays used the recordings and prompts frozen before the corresponding first runs. The repair used the timing failure from the third set.

On the third first run, the frozen word extractor included an unresolved-timing sentence when scoring the left transcript. Independent speech-only scoring found 3 errors in 19 words, within the 20% limit. The missing word range and absent evidence of disjoint estimates still failed. The replay recovered both estimates, inside measured activity. Its four source-channel word errors were 2 of 10, 2 of 10, 3 of 19 and 0 of 20. The stored answer used one registered report from six local observations. It disclosed the disputed words and sustained uncertainty about audible overlap, source identity and capture conditions. The test GUI closed normally and preserved its transcript.

The separate decoded-sample and classifier checks passed. Clock-like candidates were retained in the expected window despite higher keyboard scores. Rain was the strongest listed candidate in the later window. A ranking alone cannot establish what produced a sound.

The release candidate passed its visible GUI and pinned RPC listening fixture with a scripted chat provider and real local audio analysis. It checked that observations from both recordings survived the plan transition and supplied the saved report. The generated media tests ran after the documented audio setup. The headless compaction fixture was corrected to use its own plan without a GUI-only review call. Both the normal summary arm and the near-threshold closing arm then passed.

## Reproduction and limits

The case builders used distinct attributed sources from [LibriSpeech](https://www.openslr.org/12/) and the [ESC-50 ESC-10 subset](https://github.com/karolpiczak/ESC-50/tree/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6). For Windows setup, generated media tests and a live report procedure, see the [reproduction guide](../../docs/reproducibility.md#verify-local-listening). The generated test covers disagreement and invalid timing controls. A controlled replay qualifies the particular repair. Measurements here do not establish a speed gain or qualify uncontrolled meeting or field recordings.
