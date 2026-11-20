# Publishing a verified Pi milestone

## Release history

| Version | Verified scope | Release |
| --- | --- | --- |
| 0.1.0 | Public Windows desktop snapshot, launcher and workflow fixtures | [Source release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.0) |
| 0.1.1 | Research report, pinned public asset setup, local-only defaults and released synthetic reproductions | [Research release](https://github.com/KyrellosAyman/pi-local/releases/tag/v0.1.1) |

## Update the record and publish

1. Add the newly verified change and its exact acceptance result to the evidence ledger. Record failed and pending experiments as such. Keep private transcripts, signed-in sessions, model weights, credentials, and unpublished media in their local stores.
2. Update [PAPER.md](../research/PAPER.md), `CITATION.cff`, the release history, and the [reproduction instructions](reproducibility.md). Render `research/pi-local-v<VERSION>.pdf`, run `python -B research/render_paper.py <VERSION> --check`, and review the pages and links. Leave prior tagged papers intact.
3. Run the relevant fixtures and verify the full release from a fresh checkout. Run `gitleaks git --log-opts '--all' --redact .` and `gitleaks git --staged --redact .`. Scan the rendered PDF text and metadata for private data. Recheck the local model bind, tool defaults and asset URLs. Audit dependencies and inspect the release package before publishing.
4. Commit the reviewed source under the verified maintainer account. Push the branch, create the next annotated version tag, and verify that it points to the tested commit. Attach the matching PDF to the GitHub release and record its SHA-256 in the release notes.
5. Confirm the release and its PDF can be fetched without signing in. Update the durable project checkpoint with the commit, paper hash and evidence.

The source archive and version tag restore a particular public setup. Keep a separate private backup for local chat history, credentials, configuration and restricted assets.
