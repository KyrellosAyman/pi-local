# Desktop responsiveness and long-context decode

This evidence entry reports the results added in v0.1.5. The [v0.1.4 evidence ledger](2026-11-22-follow-up.md) preserves the earlier cache experiments and their scope.

## Installed desktop

An occupied model slot without a fresh speed sample previously displayed the last completed request's rate. The **Shared model speed** meter now waits for samples from the active request. When the slot is idle it shows the last completed native rate. When the service is unavailable it clears the reading. The chat also shows **Reviewing the initial plan** while the saved draft awaits review. The label clears after the review commits, and later plan updates skip review. Workspace and first-plan fixtures exercise these transitions through the pinned Pi RPC runtime.

A 36-minute 46-second visible Pi run submitted the unchanged long-source prompt once. It used one initial reviewer before work, one registered read of the expected workspace file, and seven successful tool calls overall. The closed plan and exact required codes passed independent grading. All seven frozen source files retained their hashes and the test window closed after the saved transcript was checked.

All eight GUI requests matched the native log. Input peaked at 61,573 tokens. All seven near-limit requests decoded below 20 tok/s, with a median of 3.20 tok/s. During the longest 279.59-second mapped wait, Pi continued animating and the chat viewport held its height. The first four post-tool waits took 263–280 seconds each and spent over 99.8% of that time in native prefill. Their first output reached Tk in 16–40 ms. After the registered file read, the next request reused 61,550 of 61,573 tokens and produced its first output in 0.952 seconds. None of 628 host samples reached 95% CPU and RAM together.

## Matched prompt-length comparison

Three serial requests used the same native process and configuration, sampling parameters, output requirement, and disabled cache reuse. The near-limit arm extended the source text. All three returned the same 182-token answer and accepted 121 of 122 draft tokens.

| Arm | Input tokens | Native prefill, seconds | Native decode, tok/s |
| --- | ---: | ---: | ---: |
| Short before | 4,790 | 9.09 | 32.56 |
| Near-limit | 59,537 | 179.13 | 8.90 |
| Short after | 4,790 | 9.07 | 32.48 |

Fifteen guarded samples during the near-limit decode gave a median device PCIe transmit rate of 17,814 MB/s. The short decode intervals yielded too few guarded device samples for a stable paired telemetry comparison. A separate short replay at 32.91 tok/s had eleven guarded samples and a median of 180 MB/s. Earlier byte-matched short runs on the same process reached about 11.5 tok/s. The longer input slowed this controlled run, and shorter runs also varied. The transfer mechanism, causal effect of memory placement, and production cache optimization remain open.

The public package contains the test fixtures and aggregate results. See the [reproduction guide](../../docs/reproducibility.md) for the Windows setup, the desktop checks, and a procedure for repeating the prompt-length comparison with the included synthetic source text.
