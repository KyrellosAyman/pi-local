# Publishing a verified Pi milestone

Keep the public source checkout separate from live workspaces. Add each source change deliberately, review its diff, and run the relevant fixture or smoke test. Inspect every new file before putting it in the index. Generated local configuration, model assets, credentials, private chats, and evidence from development stay in their local stores.

After a verified milestone, commit the reviewed files, push `main`, create the next annotated version tag, and publish that tag as a GitHub release. Describe the tested behavior and the prerequisites in the release notes. The source archive and tag make it possible to recover a particular published setup. A private backup is still needed for local model assets, configuration, and sessions.
