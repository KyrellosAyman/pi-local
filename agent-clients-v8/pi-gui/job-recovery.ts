import { createHash, randomUUID } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, fsyncSync, lstatSync, openSync, readFileSync, readSync,
	realpathSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { estimateTokens, type ExtensionAPI, type ExtensionContext, type SessionEntry } from "@earendil-works/pi-coding-agent";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AssistantMessage, ToolCall, ToolResultMessage } from "@earendil-works/pi-ai";

const customType = "local-pi-job-recovery";
const jobId = /^[a-f0-9]{32}$/;
const sha256 = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const readOnly = new Set(["read", "grep", "find", "ls", "inspect_input", "view_image_file", "sample_video",
	"analyze_audio", "read_document", "read_website", "list_recent_pngs", "prepare_prompt", "update_plan", "review_initial_plan",
	"find_skills", "use_skill", "read_skill_reference", "research_skill", "save_skill", "get_chrome_state",
	"list_windows", "get_window_state", "mcp__windows__get_chrome_state", "mcp__chrome__get_chrome_state",
	"mcp__windows__list_windows", "mcp__windows__get_window_state"]);

type Job = { id: string; session: string; workspace: string; previous_user: string | null; allow_wide_context?: boolean;
	payload: { message: string; images?: unknown[] } };
type Phase = "running" | "completed" | "stopped" | "failed" | "needs_review";
type Status = "succeeded" | "error" | "applied" | "unapplied";
type StageCheckpointProof = { sha256: string; verifiedAt: string };
type Step = { id: string; title: string; skillQuery: string; status: "pending" | "in_progress" | "completed";
	checkpoint?: string; checkpointProof?: StageCheckpointProof };
type Plan = { steps: Step[]; reason?: string; awaitingSkill?: string; updatedAt?: string;
	initialReview?: { job: string; findings: string[] } };
type WideRequest = { context: 131072; reason: "threshold" | "overflow"; tokensBefore: number; discardedToolTokens: number };
type Preimage = { digest: string; revision: string } | null;
type Call = { id: string; tool: string; input: string; anchor?: string;
	write?: { path: string; digest: string; root: string; before: Preimage } };
type Checkpoint = { id: string; session: string; workspace: string; phase: Phase; pending: Call[];
	completed: (Call & { status: Status })[]; recovered: number; updated_at: string; plan?: Plan; next?: Step; note?: string;
	wideRequested?: WideRequest };
type Run = { job: Job; checkpoint: Checkpoint; resumed: boolean; guarded?: Checkpoint["completed"];
	sealedPaths?: Set<string> };

function samePreimage(before: Preimage, current: Preimage | undefined) {
	return before === null ? current === null : current?.digest === before.digest && current.revision === before.revision;
}

function missing(error: unknown) {
	return (error as NodeJS.ErrnoException)?.code === "ENOENT";
}

function readJson(path: string) {
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch (error) {
		if (!missing(error)) throw error;
	}
}

function pathKey(path: string) {
	const full = resolve(path);
	return process.platform === "win32" ? full.toLowerCase() : full;
}

function normalizedInput(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(normalizedInput);
	if (value && typeof value === "object") {
		return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
			.map(([key, item]) => [key, normalizedInput(item)]));
	}
	return value;
}

const inputHash = (input: unknown) => sha256(JSON.stringify(normalizedInput(input)));
const isDigest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);

const excerptHeading = "[Saved excerpt from a previous tool result. The original result remains in the chat history.]\n";

function savedTail(text: string, available: number) {
	// shortcut: only retain whole trailing lines; use the original tool result for other regions.
	let start = text.length;
	let bytes = 0;
	let encodedBytes = 0;
	for (const line of text.split(/(?<=\n)/).reverse()) {
		bytes += Buffer.byteLength(line);
		encodedBytes += Buffer.byteLength(JSON.stringify(line)) - 2;
		if (bytes > 512 || encodedBytes > available) break;
		start -= line.length;
	}
	const tail = text.slice(start);
	if (tail.trim()) return excerptHeading + tail;
}

export function retainToolEvidence(messages: AgentMessage[], branch: SessionEntry[]): AgentMessage[] | undefined {
	const summary = messages.findLastIndex((message) => message.role === "compactionSummary");
	if (summary < 0) return;
	const user = branch.findLastIndex((entry) => entry.type === "message" && entry.message.role === "user");
	if (user < 0) return;
	const represented = new Set<string>();
	for (const message of messages) {
		if (message.role === "toolResult") represented.add(message.toolCallId);
		if (message.role === "assistant") for (const item of message.content) {
			if (item.type === "toolCall") represented.add(item.id);
		}
	}
	const calls = new Map<string, { assistant: AssistantMessage; call: ToolCall }>();
	const results: ToolResultMessage[] = [];
	for (const entry of branch.slice(user + 1)) {
		if (entry.type !== "message") continue;
		const message = entry.message;
		if (message.role === "assistant") for (const call of message.content) {
			if (call.type === "toolCall") calls.set(call.id, { assistant: message, call });
		}
		if (message.role === "toolResult" && !message.isError && ["run_script", "read"].includes(message.toolName)) results.push(message);
	}
	const seen = new Set<string>();
	let room = 12 * 1024;
	const retained: { index: number; pair: AgentMessage[] }[] = [];
	const exact: { index: number; pair: AgentMessage[]; bytes: number }[] = [];
	const excerpts: { index: number; assistant: AssistantMessage; call: ToolCall; result: ToolResultMessage; text: string }[] = [];
	for (const tool of ["read", "run_script"]) {
		if (tool === "run_script") exact.sort((a, b) => a.bytes - b.bytes);
		for (let index = results.length - 1; index >= 0; index--) {
			const result = results[index];
			const origin = calls.get(result.toolCallId);
			if (!origin || result.toolName !== tool || origin.call.name !== tool) continue;
			const key = tool + ":" + inputHash(origin.call.arguments);
			if (seen.has(key)) continue;
			seen.add(key);
			if (represented.has(result.toolCallId) || !result.content.every((part) => part.type === "text")) continue;
			// Retain the recorded call and returned bytes, without executing the tool or creating another user turn.
			const bytes = Buffer.byteLength(JSON.stringify([origin.call, result.content]));
			const assistant = { ...origin.assistant, content: [origin.call] };
			if (tool === "read" && bytes > 4096) {
				const part = result.content.length === 1 ? result.content[0] : undefined;
				if (part?.type === "text") excerpts.push({ index, assistant, call: origin.call, result, text: part.text });
				continue;
			}
			if (bytes <= 8192) exact.push({ index, pair: [assistant, result], bytes });
		}
	}
	// Leave room for original source excerpts before admitting whole tool results.
	const reserve = Math.min(room / 4, excerpts.length * 768);
	for (const result of exact) {
		if (result.bytes > room - reserve) continue;
		room -= result.bytes;
		retained.push(result);
	}
	for (const [position, excerpt] of excerpts.entries()) {
		// Leave a share for each older read after preserving the exact small results.
		const share = Math.floor(room / (excerpts.length - position));
		const overhead = Buffer.byteLength(JSON.stringify([excerpt.call, [{ type: "text", text: excerptHeading }]]));
		const tail = savedTail(excerpt.text, share - overhead);
		if (!tail) continue;
		const content = [{ type: "text" as const, text: tail }];
		room -= Buffer.byteLength(JSON.stringify([excerpt.call, content]));
		retained.push({ index: excerpt.index, pair: [excerpt.assistant, { ...excerpt.result, content }] });
	}
	if (!retained.length) return;
	retained.sort((a, b) => a.index - b.index);
	return [...messages.slice(0, summary + 1), ...retained.flatMap(({ pair }) => pair), ...messages.slice(summary + 1)];
}

function isCall(value: Call) {
	return value && typeof value.id === "string" && typeof value.tool === "string" && isDigest(value.input) &&
		(value.anchor === undefined || typeof value.anchor === "string") &&
		(value.write === undefined || value.write && typeof value.write.path === "string" && isAbsolute(value.write.path) &&
			isDigest(value.write.digest) && typeof value.write.root === "string" && (value.write.before === null ||
				isDigest(value.write.before?.digest) && typeof value.write.before?.revision === "string"));
}

function planFrom(value: unknown): Plan | undefined {
	const plan = value as Plan | undefined;
	if (!plan || !Array.isArray(plan.steps) || !plan.steps.every((step) => step && typeof step.id === "string" &&
		typeof step.title === "string" && typeof step.skillQuery === "string" &&
		["pending", "in_progress", "completed"].includes(step.status) &&
		(step.checkpoint === undefined || typeof step.checkpoint === "string" && step.checkpoint.length > 0) &&
		(step.status !== "completed" || !step.checkpoint || Boolean(step.checkpointProof)) &&
		(step.checkpointProof === undefined || step.status === "completed" && Boolean(step.checkpoint) &&
			isDigest(step.checkpointProof?.sha256) && typeof step.checkpointProof?.verifiedAt === "string" &&
			Number.isFinite(Date.parse(step.checkpointProof.verifiedAt))))) return;
	return { steps: plan.steps, reason: typeof plan.reason === "string" ? plan.reason : undefined,
		awaitingSkill: typeof plan.awaitingSkill === "string" ? plan.awaitingSkill : undefined,
		updatedAt: typeof plan.updatedAt === "string" ? plan.updatedAt : undefined,
		initialReview: typeof plan.initialReview?.job === "string" && jobId.test(plan.initialReview.job) &&
			Array.isArray(plan.initialReview.findings) && plan.initialReview.findings.every((item) => typeof item === "string") ?
			plan.initialReview : undefined };
}

function writePath(cwd: string, path: string) {
	// shortcut: observe only paths whose spelling resolves identically in Pi and Node; expanded paths need Pi's resolver.
	if (!path || /^[@~]|^file:\/\/|[\u00A0\u2000-\u200A\u202F\u205F\u3000\0]/.test(path)) return;
	if (process.platform === "win32" && (/^\/|^\\\\|^[a-z]:(?![\\/])/i.test(path) ||
		path.replace(/^[a-z]:/i, "").split(/[\\/]/).some((part) =>
			/[:<>|?*"\x00-\x1f]/.test(part) || /[ .]$/.test(part) && part !== "." && part !== ".." ||
			/^(?:CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)/i.test(part)))) return;
	return resolve(cwd, path);
}

function fileImage(cwd: string, path: string, includeBytes = false):
	{ root: string; image: Preimage; bytes?: Buffer } | undefined {
	try {
		const workspace = resolve(cwd);
		// Windows allows case-sensitive directories; a case-folded prefix is not proof of identity.
		if (process.platform === "win32" && !path.startsWith(workspace.endsWith(sep) ? workspace : workspace + sep)) return;
		const parts = relative(workspace, path);
		if (!parts || parts === ".." || parts.startsWith(".." + sep) || isAbsolute(parts)) return;
		const root = realpathSync(workspace);
		const rootStat = lstatSync(root, { bigint: true });
		const rootIdentity = `${pathKey(root)}:${rootStat.dev}:${rootStat.ino}`;
		const observed = (image: Preimage) => ({ root: rootIdentity, image });
		const segments = parts.split(sep);
		let file = root;
		for (const [index, segment] of segments.entries()) {
			file = join(file, segment);
			let stat;
			try {
				stat = lstatSync(file, { bigint: true });
			} catch (error) {
				if (missing(error)) return observed(null);
				throw error;
			}
			if (stat.isSymbolicLink() || pathKey(realpathSync(file)) !== pathKey(file)) return;
			if (index < segments.length - 1) {
				if (!stat.isDirectory()) return;
				continue;
			}
			// shortcut: leave targets over 16 MiB for review unless larger local writes need automatic recovery.
			if (!stat.isFile() || stat.nlink !== 1n || stat.size > 16n * 1024n * 1024n) return;
			const revision = (s: typeof stat) => `${s.dev}:${s.ino}:${s.size}:${s.mtimeNs}:${s.ctimeNs}`;
			const fd = openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
			try {
				if (revision(fstatSync(fd, { bigint: true })) !== revision(stat)) return;
				const bytes = Buffer.alloc(Number(stat.size));
				for (let offset = 0; offset < bytes.length;) {
					const count = readSync(fd, bytes, offset, bytes.length - offset, offset);
					if (!count) return;
					offset += count;
				}
				const latest = lstatSync(file, { bigint: true });
				if (revision(latest) !== revision(stat) ||
					pathKey(realpathSync(file)) !== pathKey(file)) return;
				return { ...observed({ digest: sha256(bytes), revision: revision(stat) }),
					...(includeBytes ? { bytes } : {}) };
			} finally {
				closeSync(fd);
			}
		}
	} catch {
		// Unknown path or changing file is not evidence of an unapplied write.
	}
}

function stageCheckpoint(cwd: string, name: string) {
	const path = writePath(cwd, name);
	const manifest = path ? fileImage(cwd, path, true) : undefined;
	if (!path || !manifest?.image || !manifest.bytes) {
		throw new Error("Write the declared checkpoint within this workspace before closing the stage: " + name);
	}
	let files: unknown;
	try {
		files = JSON.parse(manifest.bytes.toString("utf8").replace(/^\uFEFF/, ""))?.finished_files;
	} catch {
		throw new Error("Repair the checkpoint JSON before closing the stage: " + name);
	}
	if (!Array.isArray(files) || !files.length) {
		throw new Error("List the checkpointed paths and SHA-256 values in finished_files before closing the stage.");
	}
	const seen = new Set([pathKey(path)]);
	for (const file of files) {
		const target = typeof file?.path === "string" ? writePath(cwd, file.path) : undefined;
		if (!target || seen.has(pathKey(target)) || !isDigest(file?.sha256) ||
			fileImage(cwd, target)?.image?.digest !== file.sha256) {
			throw new Error("Checkpoint artifact could not be verified: " + JSON.stringify(file?.path));
		}
		seen.add(pathKey(target));
	}
	return { sha256: manifest.image.digest, paths: seen };
}

export function verifyStageCheckpoint(cwd: string, name: string): StageCheckpointProof {
	return { sha256: stageCheckpoint(cwd, name).sha256, verifiedAt: new Date().toISOString() };
}

function completedCheckpointPaths(cwd: string, plan?: Plan) {
	const paths = new Set<string>();
	for (const step of plan?.steps ?? []) {
		if (step.status !== "completed" || !step.checkpoint || !step.checkpointProof) continue;
		try {
			const current = stageCheckpoint(cwd, step.checkpoint);
			if (current.sha256 !== step.checkpointProof.sha256) {
				throw new Error("The checkpoint manifest differs from the saved verification receipt.");
			}
			for (const path of current.paths) paths.add(path);
		} catch (error) {
			throw new Error(`The verified checkpoint ${step.checkpoint} could not be read back. ` + (error as Error).message);
		}
	}
	return paths;
}

function originalUser(job: Job, ctx: ExtensionContext) {
	const messages = ctx.sessionManager.getBranch().flatMap((entry) =>
		entry.type === "message" && entry.message.role === "user" ? [{ id: entry.id, content: entry.message.content }] : []);
	const latest = messages.at(-1);
	if (!latest || latest.id === job.previous_user || (messages.at(-2)?.id ?? null) !== job.previous_user) return;
	const text = typeof latest.content === "string" ? latest.content :
		latest.content.find((part) => part.type === "text")?.text;
	if (text === job.payload.message || job.payload.images?.length && text?.startsWith(job.payload.message + "\n\n")) return latest.id;
}

function lastUserId(ctx: ExtensionContext) {
	return ctx.sessionManager.getBranch().findLast((entry) => entry.type === "message" && entry.message.role === "user")?.id ?? null;
}

export function boundDesktopJob(ctx: ExtensionContext, directory = process.env.PI_GUI_RECOVERY_DIR): Job | undefined {
	if (ctx.mode !== "rpc" || !directory || !isAbsolute(directory)) return;
	const value = readJson(join(directory, "active-job.json")) as Job | undefined;
	const session = ctx.sessionManager.getSessionFile();
	if (!value || !session || typeof value.session !== "string" || !isAbsolute(value.session) ||
		!value.session.toLowerCase().endsWith(".jsonl") || pathKey(value.session) !== pathKey(session)) return;
	if (typeof value.id !== "string" || !jobId.test(value.id) || typeof value.workspace !== "string" ||
		!isAbsolute(value.workspace) || pathKey(ctx.cwd) !== pathKey(value.workspace) ||
		typeof value.payload?.message !== "string" || !(value.previous_user === null || typeof value.previous_user === "string")) {
		throw new Error("Pi recovery job is not bound to this workspace and session.");
	}
	return value;
}

export function registerJobRecovery(pi: ExtensionAPI) {
	const directory = process.env.PI_GUI_RECOVERY_DIR;
	if (!directory || !isAbsolute(directory)) return;
	const launched = new Set<string>();
	let active: Run | undefined;
	let queued: Run | undefined;
	let fault: string | undefined;

	const boundJob = (ctx: ExtensionContext) => boundDesktopJob(ctx, directory);

	function load(job: Job): Checkpoint {
		const value = readJson(join(directory!, job.id + ".json")) as Checkpoint | undefined;
		if (value === undefined) return { id: job.id, session: job.session, workspace: job.workspace, phase: "running",
			pending: [], completed: [], recovered: 0, updated_at: new Date().toISOString() };
		if (!value || value.id !== job.id || value.session !== job.session || value.workspace !== job.workspace ||
			!["running", "completed", "stopped", "failed", "needs_review"].includes(value.phase) ||
			!Array.isArray(value.pending) || !value.pending.every(isCall) ||
			!Array.isArray(value.completed) || !value.completed.every((call) => isCall(call) &&
				["succeeded", "error", "applied", "unapplied"].includes(call.status)) ||
			!Number.isSafeInteger(value.recovered) || value.recovered < 0 || value.plan && !planFrom(value.plan)) {
			throw new Error("Pi recovery checkpoint is invalid. Preserve the session and review it before continuing.");
		}
		return value;
	}

	function save(run: Run, changes: Partial<Checkpoint>) {
		const checkpoint = { ...run.checkpoint, ...changes, updated_at: new Date().toISOString() };
		checkpoint.next = checkpoint.plan?.steps.find((step) => step.status === "in_progress") ??
			checkpoint.plan?.steps.find((step) => step.status === "pending");
		const path = join(directory!, checkpoint.id + ".json");
		const temp = path + "." + randomUUID() + ".tmp";
		try {
			const fd = openSync(temp, "wx", 0o600);
			try {
				writeFileSync(fd, JSON.stringify(checkpoint) + "\n", "utf8");
				fsyncSync(fd);
			} finally {
				closeSync(fd);
			}
			for (let delay = 10; ; delay *= 2) {
				try {
					renameSync(temp, path);
					break;
				} catch (error) {
					// Windows readers can briefly hold the old file without delete sharing.
					const code = (error as NodeJS.ErrnoException).code;
					if (process.platform !== "win32" || delay > 160 ||
						!["EPERM", "EACCES", "EBUSY"].includes(code ?? "")) throw error;
					Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delay);
				}
			}
			// Node cannot fsync a Windows directory, so the rename is process-crash safe but not a power-loss guarantee.
			if (process.platform !== "win32") {
				const parent = openSync(directory!, "r");
				try { fsyncSync(parent); } finally { closeSync(parent); }
			}
			run.checkpoint = checkpoint;
		} finally {
			if (existsSync(temp)) unlinkSync(temp);
		}
	}

	const stopped = (job: Job) => existsSync(join(directory, job.id + ".stop"));
	const blocked = (reason: string) => ({ block: true, reason });

	pi.on("session_start", (_event, ctx) => {
		active = queued = undefined;
		fault = undefined;
		const job = boundJob(ctx);
		if (job) load(job); // Validate any existing checkpoint; admission can change while Pi stays open.
	});

	pi.on("before_agent_start", (event, ctx) => {
		active = undefined;
		fault = undefined;
		try {
			const job = boundJob(ctx);
			if (event.messageType === "custom") {
				if (event.message.customType !== customType) return;
				if (!job || !queued || queued.job.id !== job.id ||
					(event.message.details as { id?: string })?.id !== job.id || !originalUser(job, ctx)) {
					throw new Error("The admitted Pi job changed before continuation.");
				}
				active = queued;
				queued = undefined;
			} else {
				if (!job) return;
				if (event.prompt !== job.payload.message || lastUserId(ctx) !== job.previous_user) return;
				active = { job, checkpoint: load(job), resumed: false };
				if (active.checkpoint.phase !== "running" || active.checkpoint.pending.length || active.checkpoint.completed.length) {
					throw new Error("Pi will not replay an admitted job with existing tool activity.");
				}
			}
			if (stopped(job)) throw new Error("The job was stopped before starting.");
			save(active, {});
		} catch (error) {
			fault = (error as Error).message;
			ctx.abort();
			throw error;
		}
	});

	pi.on("tool_call", (event, ctx) => {
		if (readOnly.has(event.toolName)) return;
		if (fault) return blocked("Recovery checkpoint unavailable: " + fault);
		if (!active) return;
		if (stopped(active.job)) return blocked("Pi was stopped for this job.");
		if (active.checkpoint.phase !== "running") return blocked("Pi recovery requires review before running another tool.");
		const args = event.input as Record<string, unknown>;
		const input = inputHash(args);
		const target = (event.toolName === "write" || event.toolName === "edit") && typeof args.path === "string"
			? writePath(active.job.workspace, args.path) : undefined;
		if (target && active.sealedPaths?.has(pathKey(target))) {
			return blocked("This file belongs to a completed checkpoint. Write a new version or reopen its stage before editing it.");
		}
		const file = event.toolName === "write" && typeof args.content === "string" ? target : undefined;
		const observation = file ? fileImage(active.job.workspace, file) : undefined;
		const digest = file && typeof args.content === "string" ? sha256(args.content) : undefined;
		const replay = active.guarded?.find((call) => {
			if (call.tool !== event.toolName) return false;
			if (!call.write || !file || !digest) return call.input === input;
			if (pathKey(call.write.path) !== pathKey(file) || call.write.digest !== digest) return false;
			const current = observation?.root === call.write.root ? observation.image : undefined;
			// A successful write may have been followed by an edit worth preserving.
			return call.status === "unapplied" ? !samePreimage(call.write.before, current)
				: call.status === "applied" || call.status === "error" || (current !== null && current !== undefined);
		});
		if (replay) return blocked(`Recovery refused to repeat ${event.toolName} (receipt ${replay.id}). Check the current result and continue with the next action.`);
		if (active.checkpoint.pending.some((call) => call.id === event.toolCallId)) {
			return blocked("Recovery has an unsettled action with this tool call ID.");
		}
		const call: Call = { id: event.toolCallId, tool: event.toolName, input, anchor: ctx.sessionManager.getLeafId() ?? undefined };
		if (file && digest && observation) call.write = { path: file, digest, root: observation.root, before: observation.image };
		try {
			save(active, { pending: [...active.checkpoint.pending, call] });
		} catch (error) {
			fault = (error as Error).message;
			return blocked("Recovery could not record this action: " + fault);
		}
	});

	pi.on("tool_result", (event, ctx) => {
		if (!active) return;
		try {
			if (["update_plan", "review_initial_plan"].includes(event.toolName) && !event.isError) {
				if ((event.details as { reviewPending?: boolean })?.reviewPending) return;
				const plan = planFrom(event.details);
				if (plan) {
					const sealedPaths = completedCheckpointPaths(active.job.workspace, plan);
					save(active, { plan });
					active.sealedPaths = sealedPaths;
				}
				return;
			}
			if (readOnly.has(event.toolName)) return;
			const call = active.checkpoint.pending.find((item) => item.id === event.toolCallId &&
				item.tool === event.toolName && item.input === inputHash(event.input));
			if (!call || (event.isError && ctx.signal?.aborted)) return;
			save(active, { pending: active.checkpoint.pending.filter((item) => item !== call),
				completed: [...active.checkpoint.completed, { ...call, status: event.isError ? "error" : "succeeded" }] });
		} catch (error) {
			fault = (error as Error).message;
			throw error;
		}
	});

	pi.on("agent_settled", (event, ctx) => {
		if (!active) return;
		const run = active;
		active = undefined;
		if (stopped(run.job)) return save(run, { phase: "stopped", note: "Stopped by the user." });
		// Stdin EOF also aborts Pi when the GUI crashes. Only the durable Stop marker means user cancellation.
		if (event.aborted || run.checkpoint.phase !== "running") return;
		if (fault || run.checkpoint.pending.length) {
			return save(run, { phase: "needs_review", note: fault ? "Recovery checkpoint error: " + fault
				: "One or more tools have no confirmed outcome. Review the recorded calls before repeating them." });
		}
		const branch = ctx.sessionManager.getBranch();
		const start = run.resumed ? branch.findLastIndex((entry) => entry.type === "custom_message" &&
			entry.customType === customType && (entry.details as { id?: string })?.id === run.job.id)
			: branch.findIndex((entry) => entry.id === originalUser(run.job, ctx));
		const answer = start >= 0 ? branch.slice(start + 1).findLast((entry) => entry.type === "message" &&
			entry.message.role === "assistant") : undefined;
		const reason = answer?.type === "message" && answer.message.role === "assistant" ? answer.message.stopReason : undefined;
		if (reason === "stop") {
			try {
				completedCheckpointPaths(run.job.workspace, run.checkpoint.plan);
			} catch (error) {
				return save(run, { phase: "needs_review", note: (error as Error).message });
			}
		}
		save(run, reason === "stop" ? { phase: "completed", note: undefined }
			: { phase: "failed", note: "Pi settled without a final answer" + (reason ? ` (${reason}).` : ".") });
	});

	pi.on("context", (event, ctx) => {
		if (!active) return;
		const messages = retainToolEvidence(event.messages, ctx.sessionManager.getBranch());
		if (messages) return { messages };
	});

	pi.on("session_before_compact", (event, ctx) => {
		const run = active;
		if (process.env.PI_GUI_AUTO_CONTEXT !== "1" || ctx.model?.contextWindow !== 64000 || !run ||
			run.job.allow_wide_context === false || fault ||
			run.checkpoint.phase !== "running" || run.checkpoint.wideRequested || run.checkpoint.pending.length ||
			stopped(run.job) || event.reason === "manual") return;
		const recent = event.branchEntries.findLast((entry) => entry.type === "message" && entry.message.role === "assistant");
		const previousStop = recent?.type === "message" && recent.message.role === "assistant" ? recent.message.stopReason : undefined;
		const { preparation, reason } = event;
		const discardedToolTokens = [...preparation.messagesToSummarize, ...preparation.turnPrefixMessages]
			.filter((message) => message.role === "toolResult" && !message.isError)
			.reduce((total, message) => total + estimateTokens(message), 0);
		if (reason === "threshold" && (previousStop !== "toolUse" || discardedToolTokens <= preparation.settings.keepRecentTokens)) return;
		save(run, { wideRequested: { context: 131072, reason, tokensBefore: preparation.tokensBefore, discardedToolTokens } });
		ctx.abort();
		return { cancel: true };
	});

	pi.registerCommand("local-pi-recover", {
		description: "Continue an interrupted Pi GUI job after reconciling its recorded tools.",
		async handler(args, ctx) {
			const job = boundJob(ctx);
			const user = job && originalUser(job, ctx);
			if (!job || args.trim() !== job.id || !ctx.isIdle() || !user || queued || launched.has(job.id)) {
				throw new Error("No matching interrupted Pi job can be continued in this session.");
			}
			const checkpoint = load(job);
			const run: Run = { job, checkpoint, resumed: true };
			if (stopped(job)) {
				save(run, { phase: "stopped", note: "Stopped by the user." });
				throw new Error("This Pi job was stopped by the user.");
			}
			if (checkpoint.phase !== "running") throw new Error(checkpoint.note || "The job is no longer recoverable.");
			const branch = ctx.sessionManager.getBranch();
			const afterUser = branch.slice(branch.findIndex((entry) => entry.id === user) + 1);
			const completed = [...checkpoint.completed];
			const pending = [];
			for (const call of checkpoint.pending) {
				const anchor = call.anchor ? afterUser.findIndex((entry) => entry.id === call.anchor) : -1;
				const receipt = anchor >= 0 && afterUser.slice(anchor + 1).some((entry) => entry.type === "message" &&
					entry.message.role === "toolResult" && entry.message.toolCallId === call.id &&
					entry.message.toolName === call.tool && !entry.message.isError);
				if (call.write) {
					const before = call.write.before;
					const observation = fileImage(job.workspace, call.write.path);
					const current = observation?.root === call.write.root ? observation.image : undefined;
					if (current?.digest === call.write.digest) {
						completed.push({ ...call, status: "applied" });
						continue;
					}
					if (!receipt && samePreimage(before, current)) {
						completed.push({ ...call, status: "unapplied" });
						continue;
					}
				} else if (receipt) {
					completed.push({ ...call, status: "succeeded" });
					continue;
				}
				pending.push(call);
			}
			const lastPlan = afterUser.findLast((entry) => entry.type === "custom" && entry.customType === "gui-plan");
			const loggedPlan = lastPlan?.type === "custom" ? planFrom(lastPlan.data) : undefined;
			const plan = !checkpoint.plan || loggedPlan?.updatedAt && loggedPlan.updatedAt > (checkpoint.plan.updatedAt ?? "")
				? loggedPlan : checkpoint.plan;
			if (pending.length) {
				const calls = pending.slice(0, 4).map((call) => `${call.tool} (${call.id})`).join(", ");
				const note = "Review these interrupted calls before continuing: " + calls +
					(pending.length > 4 ? ` and ${pending.length - 4} more.` : ".");
				save(run, { phase: "needs_review", note, pending, completed, plan });
				throw new Error(note);
			}
			try {
				run.sealedPaths = completedCheckpointPaths(job.workspace, plan);
			} catch (error) {
				const note = "Pi paused recovery. " + (error as Error).message;
				save(run, { phase: "needs_review", note, pending, completed, plan });
				throw new Error(note);
			}
			save(run, { recovered: checkpoint.recovered + 1, pending, completed, plan, note: undefined });
			run.guarded = completed;
			const receipts = completed.slice(-16).map((call) => ({ tool: call.tool, id: call.id, path: call.write?.path,
				result: call.status === "applied" ? "requested file bytes verified on disk" : call.status === "unapplied"
					? "preimage unchanged; requested file bytes were not applied" : call.status === "error"
						? "tool reported an error; inspect its effects before further action" : "tool reported success" }));
			const content = "Continue the interrupted job in this session. The original user message and any images remain in the transcript. " +
				"Continue the saved brief, plan and verified skill route when available. Complete any missing setup before new work. Keep completed stages and verify current state before further actions. " +
				"Do not repeat recorded effects. Use the native tool receipts for details.\n" +
				JSON.stringify({ goal: job.payload.message, plan, next: run.checkpoint.next, recentReceipts: receipts });
			queued = run;
			launched.add(job.id);
			pi.sendMessage({ customType, content, display: false, details: { id: job.id, prompt: job.payload.message, plan } },
				{ triggerTurn: true });
		},
	});
	return (note: string) => {
		if (active?.checkpoint.phase === "running" && !stopped(active.job)) {
			save(active, { phase: "needs_review", note });
		}
	};
}
