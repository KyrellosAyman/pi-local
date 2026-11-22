import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { registerJobRecovery, verifyStageCheckpoint } from "./job-recovery.ts";

const tempParent = realpathSync(tmpdir());
const workspace = mkdtempSync(join(tempParent, "pi-checkpoint-protection-"));
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
const id = "a".repeat(32);
const session = join(workspace, "session.jsonl");
const ledger = join(workspace, `${id}.json`);
const prompt = "Keep completed stage files and write the next stage separately.";
const file = join(workspace, "finished.txt");
const manifest = join(workspace, "checkpoint.json");
const original = "finished result\n";
const priorRecoveryDir = process.env.PI_GUI_RECOVERY_DIR;
const events = new Map();
const commands = new Map();
const branch = [];
let resumed = false;
const ctx = {
	mode: "rpc", cwd: workspace, isIdle: () => true,
	sessionManager: { getSessionFile: () => session, getBranch: () => branch, getLeafId: () => branch.at(-1)?.id },
};

try {
	process.env.PI_GUI_RECOVERY_DIR = workspace;
	writeFileSync(join(workspace, "active-job.json"), JSON.stringify({ id, session, workspace,
		previous_user: null, payload: { message: prompt } }));
	writeFileSync(file, original);
	writeFileSync(manifest, JSON.stringify({ finished_files: [{ path: "finished.txt", sha256: digest(original) }] }));
	const pi = {
		on: (name, handler) => events.set(name, handler),
		registerCommand: (name, command) => commands.set(name, command.handler),
		sendMessage: () => { resumed = true; },
	};
	registerJobRecovery(pi);
	events.get("before_agent_start")({ messageType: "user", prompt }, ctx);
	branch.push({ type: "message", id: "original", message: { role: "user", content: prompt } });
	const step = { id: "first", title: "Seal output", skillQuery: "general-task", checkpoint: "checkpoint.json" };
	const complete = { ...step, status: "completed", checkpointProof: verifyStageCheckpoint(workspace, step.checkpoint) };
	const plan = (details) => events.get("tool_result")({ toolName: "update_plan", details: { steps: [details] } }, ctx);
	const action = (toolName, path, toolCallId = "guarded") => events.get("tool_call")({
		toolName, toolCallId, input: { path, ...(toolName === "write" ? { content: "replacement" } : {}) },
	}, ctx);
	plan(complete);
	assert.equal(action("edit", "finished.txt")?.block, true);
	assert.equal(action("write", manifest)?.block, true);
	assert.equal(action("read", "finished.txt"), undefined);
	assert.equal(JSON.parse(readFileSync(ledger)).pending.length, 0);
	assert.equal(readFileSync(file, "utf8"), original);

	plan({ ...step, status: "in_progress" });
	assert.equal(action("edit", "finished.txt", "reopened"), undefined);
	events.get("tool_result")({ toolName: "edit", toolCallId: "reopened", input: { path: "finished.txt" }, isError: true }, ctx);
	plan(complete);
	assert.equal(action("write", "next.txt", "new-output"), undefined);
	events.get("tool_result")({ toolName: "write", toolCallId: "new-output", input: { path: "next.txt", content: "replacement" } }, ctx);
	assert.equal(JSON.parse(readFileSync(ledger)).pending.length, 0);

	const interrupted = readFileSync(ledger);
	// An external edit to a completed file must surface at both settlement and recovery.
	writeFileSync(file, "altered result!\n");
	branch.push({ type: "message", id: "final", message: { role: "assistant", stopReason: "stop" } });
	events.get("agent_settled")({ aborted: false }, ctx);
	const settled = JSON.parse(readFileSync(ledger));
	assert.equal(settled.phase, "needs_review");
	assert.match(settled.note, /checkpoint.*could not be read back/i);
	branch.pop();
	writeFileSync(ledger, interrupted);
	await assert.rejects(commands.get("local-pi-recover")(id, ctx), /checkpoint.*could not be read back/i);
	assert.equal(resumed, false);
	assert.equal(JSON.parse(readFileSync(ledger)).phase, "needs_review");
	assert.equal(readFileSync(file, "utf8"), "altered result!\n");
	console.log("Verified checkpoint guards, ordinary reads, reopening, new output, and drift checks at settlement and recovery.");
} finally {
	if (priorRecoveryDir === undefined) delete process.env.PI_GUI_RECOVERY_DIR;
	else process.env.PI_GUI_RECOVERY_DIR = priorRecoveryDir;
	assert.equal(dirname(realpathSync(workspace)), tempParent);
	rmSync(workspace, { recursive: true, force: true });
}
