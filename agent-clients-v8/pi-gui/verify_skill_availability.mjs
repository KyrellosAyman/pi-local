import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import registerAnalysisTools from "./analysis-tools.ts";
import { registerSkillWorkflow } from "./skill-workflow.ts";

const standard = "RFC 999999";
const stage = [{ id: "review", skillQuery: standard, status: "in_progress" }];
for (const enabled of [false, true]) {
    process.env.PI_SKILL_STORE = mkdtempSync(join(tmpdir(), "pi-research-route-"));
    process.env.PI_SKILL_BUNDLE = fileURLToPath(new URL("./skills", import.meta.url));
    process.env.PI_SKILL_SHARED = "[]";
    process.env.PI_LOCAL_WEB_TOOLS = enabled ? "1" : "0";
    const hooks = new Map(), tools = new Map();
    const { setPlan } = registerSkillWorkflow({
        on: (name, hook) => hooks.set(name, hook),
        registerTool: (tool) => tools.set(tool.name, tool),
        appendEntry() {},
    });
    hooks.get("before_agent_start")({ messageType: "user", prompt: "Check " + standard, systemPrompt: "" });
    await tools.get("prepare_prompt").execute("brief", { brief: "Check " + standard });
    setPlan(stage);
    const search = await tools.get("find_skills").execute("search", { query: standard });
    const searchAction = JSON.parse(search.content[0].text.split("\n")[0]).next;
    const { nextSkillAction } = setPlan(stage);
    assert.equal(tools.has("research_skill"), enabled);
    assert.equal(searchAction.includes("research_skill"), enabled);
    assert.equal(nextSkillAction.includes("research_skill"), enabled);
    if (!enabled) {
        assert.match(searchAction, /local skill/);
        assert.match(nextSkillAction, /local skill/);
    }
}
console.log("Both local and opted-in research routes give instructions for registered tools.");

process.env.PI_SKILL_STORE = mkdtempSync(join(tmpdir(), "pi-local-audio-route-"));
process.env.PI_LOCAL_WEB_TOOLS = "0";
process.env.PI_LOCAL_ANALYSIS_PYTHON = process.execPath;
process.env.PI_LOCAL_ANALYSIS_SCRIPT = "inspect_input.py";
const hooks = new Map(), tools = new Map();
const pi = {
    on: (name, hook) => hooks.set(name, hook),
    registerTool: (tool) => tools.set(tool.name, tool),
    appendEntry() {},
};
const { setPlan } = registerSkillWorkflow(pi);
registerAnalysisTools(pi);
const audio = tools.get("analyze_audio");
assert.match(audio.description, /local-media-review/);
assert.match(audio.description, /estimated speech times separately/);
hooks.get("before_agent_start")({ messageType: "user", prompt: "Analyze a local interview.", systemPrompt: "" });
await tools.get("prepare_prompt").execute("brief", { brief: "Analyze a local interview." });
setPlan([{ id: "audio", skillQuery: "audio analysis", status: "in_progress" }]);
const search = await tools.get("find_skills").execute("search", { query: "audio analysis" });
assert(JSON.parse(search.content[0].text).matches.some((item) => item.name === "local-media-review"));
const selected = await tools.get("use_skill").execute("skill", { name: "local-media-review", reason: "Interpret evidence." });
assert.equal(selected.details.source, "Built-in");
assert.match(selected.content[0].text, /Leave the actual speech overlap boundaries unresolved/);
console.log("Local audio interpretation routes to a built-in Pi skill with no shared skill library.");

const browser = await hooks.get("before_agent_start")({
    messageType: "user", prompt: "Read one control in the approved Chrome window.", systemPrompt: "",
});
assert.match(browser.systemPrompt, /scoped Chrome MCP state read, use the exact skillQuery pi-tool-catalog/);
await tools.get("prepare_prompt").execute("brief", { brief: "Read the requested control without changing the page." });
setPlan([{ id: "browser", skillQuery: "pi-tool-catalog", status: "in_progress" }]);
assert.equal(hooks.get("tool_call")({ toolName: "codemode" }).block, true);
const catalogSearch = await tools.get("find_skills").execute("search", { query: "pi-tool-catalog" });
assert.equal(JSON.parse(catalogSearch.content[0].text).matches[0].name, "pi-tool-catalog");
const catalog = await tools.get("use_skill").execute("skill", { name: "pi-tool-catalog", reason: "Read the requested control." });
assert.match(catalog.content[0].text, /tools\.mcp__chrome__get_chrome_state\([\s\S]+screenshot: false/);
assert.equal(hooks.get("tool_call")({ toolName: "codemode" }), undefined);
console.log("The scoped Chrome read uses the built-in catalog and retains the skill gate.");
