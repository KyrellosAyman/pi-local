# Publishing a verified Pi milestone

## Release history

| Version | Verified scope | Release |
| --- | --- | --- |
| 0.1.0 | Public Windows desktop snapshot, launcher and workflow fixtures | [Source release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.0) |
| 0.1.1 | Research report, pinned public asset setup, local-only defaults and released synthetic reproductions | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.1) |
| 0.1.2 | Offline audio setup, protected checkpoint fixtures, Windows chat history recovery and expanded trial evidence | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.2) |
| 0.1.3 | Clickable clarification, first-plan review with recovery, and near-64k text workflow evidence | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.3) |
| 0.1.4 | Accept complete plans in one review, route scoped Chrome reads, and document matched prompt-cache experiments | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.4) |
| 0.1.5 | Show the active plan-review phase, correct the shared speed meter, and report the long-context slowdown | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.5) |
| 0.1.6 | Enforce configured MCP OAuth scopes and verify sign-in and refresh through the bundled launcher | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.6) |
| 0.1.7 | Ground Pi chat listening reports in decoded audio, retain separate channel estimates, and verify timing recovery on frozen replays | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.7) |
| 0.1.8 | Bind completion to a required script and current file revisions, preserve first-plan review under duplicate calls, and recover verified outcomes after RPC restart | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.8) |

## Update the record and publish

1. Add the newly verified change and its exact acceptance result to the evidence ledger. Record failed and pending experiments as such. Keep private transcripts, signed-in sessions, model weights, credentials, and unpublished media in their local stores.
2. Update [PAPER.md](../research/PAPER.md), `CITATION.cff`, the release history, and the [reproduction instructions](reproducibility.md). Render `research/pi-local-v<VERSION>.pdf`, run `python -B research/render_paper.py <VERSION> --check`, and review the pages and links. Leave prior tagged papers intact.
3. Run the relevant fixtures and verify the full release from a fresh checkout. Run `gitleaks git --log-opts '--all' --redact .` and `gitleaks git --staged --redact .`. Scan the rendered PDF text and metadata for private data. Recheck the local model bind, tool defaults and asset URLs. Audit dependencies and inspect the release package before publishing.
4. Push the verified source to a topic branch and open a pull request. @KyrellosAyman makes the merge decision. Review the exact contribution revision together and obtain the owner’s explicit merge instruction before merging a contributor’s change. Recheck the pull request head before approving or merging. The sole owner can use GitHub’s pull-request-only exception for their own changes because GitHub does not let authors approve their own pull requests.
5. Verify the merged commit on `main` matches the tested tree. Create the next annotated version tag on that commit and publish the matching PDF with its SHA-256 in the release notes. Published version tags are protected from changes and deletion.
6. Confirm the release and its PDF can be fetched without signing in. Update the durable project checkpoint with the commit, paper hash and evidence.

The source archive and version tag restore a particular public setup. Keep a separate private backup for local chat history, credentials, configuration and restricted assets.
