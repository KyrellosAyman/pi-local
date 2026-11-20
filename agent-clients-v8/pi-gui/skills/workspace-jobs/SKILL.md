---
name: workspace-jobs
description: Use when Pi needs to start, resume polling, or verify a local background workspace job with the workspace_jobs MCP server, including start_workspace_script, poll_workspace_script, exit code, and stdout.
---

# Workspace jobs

Use the connected `workspace_jobs` MCP tools for a saved Python or PowerShell script in the current workspace. Use `run_script` for a short foreground check whose output is needed before the next step.

Call `mcp__workspace_jobs__start_workspace_script` once with the saved script path and individual arguments. Keep the returned job ID in the plan or a local checkpoint when another session needs to resume it. Continue independent work while the script runs. When its result matters, call `mcp__workspace_jobs__poll_workspace_script` with the same ID in the same workspace.

Use the terminal status and exit code to report whether it ran successfully. Check the relevant output artifact when the task requires one. The result contains bounded stdout and stderr tails. If the process outcome is unknown, inspect its saved outputs before considering a retry.
