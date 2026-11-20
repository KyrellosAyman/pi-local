---
name: windows-input-recovery
description: Use for Windows input, an approved signed-in Chrome page, and recovery from stale controls, unconfirmed typing, or a pane that did not scroll.
---

# Windows input recovery

For a Windows app, use `list_windows` to identify the intended app and window. Call `get_window_state` with that PID and window ID. Retain both IDs on later captures and actions. Use accessibility elements from that snapshot for fields and buttons. Use a fresh screenshot when visual layout is needed, and follow the tool's coordinate space. An unqualified foreground capture may show a different window.

For an approved page in regular Chrome, use `get_chrome_state` to confirm its address and visible controls. If several windows match, pass the exact window ID. Act once with `chrome_action` using a visible element number from that state. This route accepts click, type in an editable element, the supported named keys, and scroll. Read the page again after each action. If a page or control changed, find it in the new snapshot. Leave unrelated tabs and sign-in or permission dialogs alone.

Prefer an accessibility read to confirm typing, a button state, or a known end marker. A delivery receipt alone does not establish that the app changed. Before retrying, read the intended window or page and inspect the current value. Avoid entering text a second time if it already arrived.

Modern Notepad can reject background Ctrl+S when the Save accelerator is behind its closed File menu. Re-read the exact window. When foreground input is authorized, use one `hotkey` call with `keys: ["ctrl", "s"]`, the same PID and window ID, and `delivery_mode: "foreground"`. For a file task, confirm the saved file independently when readback is authorized. The editor's visible value and tab status can differ from the on-disk contents.

When a Windows app fails to scroll, focus the intended pane and use a point within it from the latest screenshot. Use foreground delivery only when it is needed and authorized. For a failed shortcut, focus the verified editor and use the Windows `press_key` or `hotkey` action that matches the tool schema. Chrome page actions use the narrower `chrome_action` key list.

After two unchanged results, inspect the target, window identity, focus and actual tool receipts. Use an observed alternative control or report the concrete blocker. When the requested effect is visible, continue to the remaining task and its independent output checks.
