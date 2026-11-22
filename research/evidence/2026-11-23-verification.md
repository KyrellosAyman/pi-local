# Desktop completion and required verification

The synthetic desktop task used the same prompt and three unchanged input files in all three live runs. The verifier counted the lines in `artifact.txt` after comparing its digest with `proof.json`. Each live run used a fresh Pi Tk window, the pinned RPC runtime and the same local 64,000-token model service.

| Arm | Observed result |
| --- | --- |
| Initial candidate | The draft and reviewed plan kept the checkpoint and omitted its verifier. Three direct script calls exited zero and returned two lines. None was bound to a planned step. The run was stopped while still open. |
| Explicit verifier binding | The first draft kept the verifier. A second plan call in the same model turn reached the commit path before review. The review gate blocked subsequent work. The run was stopped while still open. |
| Duplicate-safe first review | One draft passed review. The direct verifier exited zero, matched the checkpoint and file revisions, and returned two lines. The plan and job completed in 204.266 seconds. The verifier and both data files stayed byte-identical. |

An independent replay checked the final transcript, the one original user prompt, the review record, the direct tool receipt, the three input hashes, and the normal exit of the owned GUI window. The first two live runs establish failure modes. They do not provide a matched completion-time baseline.

The scripted loopback model test reproduced the duplicate-call defect against the second candidate and passed on the corrected code. The corrected desktop rejected missing, unrelated, failed and stale checks. The passing receipt survived an RPC interruption after verification and before closure. The two premature-final controls left the job for review before executing the verifier, including when the model proposed no plan. Existing first-plan, checkpoint and job-recovery tests passed, together with 96 desktop checks using the pinned RPC runtime.

The release includes the synthetic fixture and run instructions. The study used no third-party agent to execute the verification and published aggregate results from the private live logs. The receipt confirms the planned script ran successfully for the recorded revisions. Acceptance still depends on the script's assertions. [Reproduce the checks](../../docs/reproducibility.md#verify-checkpoints-and-script-receipts)
