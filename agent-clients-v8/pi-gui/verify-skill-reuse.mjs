import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { registerSkillWorkflow } from "./skill-workflow.ts";

const base = mkdtempSync(join(tmpdir(), "pi-skill-reuse-"));
const name = "long-reuse-fixture";
const file = join(base, name, "SKILL.md");
const body = "---\nname: long-reuse-fixture\ndescription: Use to verify a repeated Pi skill.\n---\n" +
	"Verify the selected source against the expected evidence.\n".repeat(420) + "Final marker XQ-19753.\n";
mkdirSync(join(base, name));
writeFileSync(file, body);
Object.assign(process.env, {
	PI_SKILL_STORE: base,
	PI_SKILL_BUNDLE: fileURLToPath(new URL("./skills", import.meta.url)),
	PI_SKILL_SHARED: "[]",
});
const hooks = new Map();
const tools = new Map();
const journal = [];
const { setPlan } = registerSkillWorkflow({
	on: (name, hook) => hooks.set(name, hook),
	registerTool: (tool) => tools.set(tool.name, tool),
	appendEntry: (kind, fields) => journal.push([kind, fields]),
});
const start = () => hooks.get("before_agent_start")({ messageType: "user", prompt: "Verify reuse.", systemPrompt: "Base" });
const select = async () => {
	await tools.get("find_skills").execute("search", { query: name });
	return tools.get("use_skill").execute("select", { name, reason: "The workflow uses this skill." });
};
const step = (id, skillQuery) => ({ id, skillQuery, status: "in_progress" });
start();
await tools.get("prepare_prompt").execute("prepare", { brief: "Verify reuse." });
const firstStage = step("first", "read and verify incoming records");
setPlan([firstStage]);
const first = await select();
assert.ok(first.content[0].text.includes(body));
const complete = { ...firstStage, status: "completed" };
setPlan([complete, step("report", "summarize the outgoing report")]);
const second = await select();
assert.equal(second.details.skillDigest, first.details.skillDigest);
assert.equal(second.details.stageId, "report");
assert.ok(second.content[0].text.length < 600, "An unchanged skill body was attached again.");
assert.equal(hooks.get("tool_call")({ toolName: "read" }), undefined);

const tool = (id, fn, content) => [
	{ role: "assistant", content: null, tool_calls: [{ id, function: { name: fn } }] },
	{ role: "tool", tool_call_id: id, content },
];
const full = tool("full", "use_skill", first.content[0].text);
const reused = tool("short", "use_skill", second.content[0].text);
const prefix = [{ role: "developer", content: "Base" }, { role: "user", content: "Verify reuse." }];
const outbound = (...pieces) => {
	const messages = [...prefix, ...pieces.flat()];
	return hooks.get("before_provider_request")({ payload: { messages } })?.messages ?? messages;
};
const marker = "Final marker XQ-19753.";
const kept = outbound(full, reused);
assert.equal(kept.slice(-2).map((message) => message.content).join("\n").includes(marker), false);
assert.ok(kept[3].content.includes(marker));
const compacted = outbound(reused);
assert.ok(compacted.at(-1).content.includes(marker), "A retained short receipt must restore the exact body after compaction.");
const unrelated = tool("outside", "read", first.content[0].text);
const spoofed = outbound(unrelated, reused);
assert.ok(spoofed.at(-1).content.includes(marker), "An unrelated tool result does not prove that the skill body was delivered.");
assert.equal(spoofed[3].content, unrelated[1].content);

const updatedBody = body + "A verified revision.\n";
writeFileSync(file, updatedBody);
const updated = await select();
assert.notEqual(updated.details.skillDigest, first.details.skillDigest);
assert.ok(updated.content[0].text.includes(updatedBody));
start();
await tools.get("prepare_prompt").execute("prepare", { brief: "Verify reuse on a new turn." });
setPlan([firstStage]);
assert.ok((await select()).content[0].text.includes(updatedBody));
assert.equal(journal.filter(([, details]) => details.skillEvent === "active").length, 4);
console.log(JSON.stringify({ original_bytes: Buffer.byteLength(first.content[0].text),
	reused_bytes: Buffer.byteLength(second.content[0].text), restored_exact_text: true,
	new_revision_and_new_chat_receive_full_body: true }));
