---
name: pi-tool-catalog
description: Find, inspect, and invoke registered MCP tools through Pi's catalog, including a scoped Chrome browser state read.
---

# Pi tool catalog

Use the registered `codemode` tool for Pi's in-chat catalog. Its argument is a `code` string. Keep discovery, schema inspection, and invocation in the same plan stage unless the task requires separate decisions.

For a read-only Chrome check with a supplied window ID and control label, call Pi's built-in reader in one `codemode` call. Use the exact requested values. This reads the matching control with no screenshot.

```js
text(await tools.mcp__chrome__get_chrome_state({
  target_window: 12345,
  query: "Exact control label",
  screenshot: false,
}));
```

If that tool is unavailable, use catalog discovery. If the reader refuses the scope or the control is missing, report the result and keep the requested window.

For other tools, discover and validate the schema before invoking them.

1. Find candidates with `text(await searchTools("the operation you need", { limit: 6 }))`.
2. From the result, take the exact registered name and inspect it with `text(await describeTool("exact_registered_name"))`.
3. Pass the validated inputs to the discovered tool. For example, if the schema showed the name `mcp__example__lookup` and a required string `query`, run `text(await tools.mcp__example__lookup({ query: "the user's value" }))`.
4. Check the actual tool result. Preserve exact input characters and report failures or missing fields without filling them in.

These helpers run inside `codemode`. They require only the catalog already offered in Pi. If `codemode` is absent, report that the catalog is unavailable in this session. Do not substitute a shell command, an external MCP CLI, or a guessed tool name when the user requested this route.
