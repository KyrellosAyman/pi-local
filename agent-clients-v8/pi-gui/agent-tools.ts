import { constants, copyFileSync, lstatSync, mkdirSync, openSync, readSync, closeSync, readdirSync, realpathSync, readFileSync } from "node:fs";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { basename, dirname, extname, join, resolve } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { Type } from "typebox";
import { registerSkillWorkflow } from "./skill-workflow.ts";
import { explicitAudioReplyRequested, retainedAudioForStep } from "./audio-findings.ts";
import { POWERSHELL_TIMEOUT_SECONDS, registerStallRecovery } from "./stall-recovery.ts";
import { registerJobRecovery, verifyStageCheckpoint } from "./job-recovery.ts";
import { registerInitialPlanReview } from "./initial-plan-review.ts";

const maxPlanSteps = 12;
const step = Type.Object({
	id: Type.String({ minLength: 1, maxLength: 32 }),
	title: Type.String({ minLength: 1, maxLength: 180 }),
	skillQuery: Type.String({ minLength: 1, maxLength: 180, pattern: "\\S" }),
	status: Type.Union([Type.Literal("pending"), Type.Literal("in_progress"), Type.Literal("completed")]),
	checkpoint: Type.Optional(Type.String({ minLength: 1, description: "Workspace JSON path for a checkpoint the user requires at this stage. Before closing, write finished_files entries with path and sha256." })),
});

async function detachedPilotReceipt(script, args, workspace, call, deadline, signal) {
	const local = process.env.PI_LOCAL_ANALYSIS_SCRIPT;
	const recovery = process.env.PI_GUI_RECOVERY_DIR;
	const media = args.length === 2 && ["--speech", "--wan22"].includes(args[1]);
	if (!local || !recovery || (!media && ![1, 11].includes(args.length)) || extname(args[0]) !== ".json" ||
		realpathSync(script) !== join(dirname(realpathSync(local)), "run_pi_pip_pilot.py") ||
		signal?.aborted || Date.now() >= deadline) return;
	const read = (file) => {
		try {
			return JSON.parse(readFileSync(file, "utf8"));
		} catch (error) {
			if (error.code !== "ENOENT") throw error;
		}
	};
	const output = join(workspace, "output");
	if (!lstatSync(output).isDirectory() || realpathSync(output) !== join(realpathSync(workspace), "output")) return;
	const stem = basename(args[0], ".json");
	const request = read(join(output, stem + "_handoff_request.json"));
	const job = read(join(recovery, "active-job.json"));
	if (!request || request.call !== call || request.rpc_pid !== process.pid ||
		request.job !== job?.id || realpathSync(job.workspace) !== realpathSync(workspace)) return;
	const settingsHash = createHash("sha256").update(readFileSync(resolve(workspace, args[0]))).digest("hex");
	if (settingsHash !== request.settings_sha256) return;
	const statusFile = join(output, stem + "_handoff.json");
	while (Date.now() < deadline && !signal?.aborted) {
		const status = read(statusFile);
		if (!status || status.job !== request.job || status.call !== call ||
			status.wrapper_pid !== request.wrapper_pid || status.settings_sha256 !== settingsHash) return;
		if (status.phase === "completed" && status.renderer_exit_code === 0 && status.restored_native_pid) return status;
		if (status.phase === "failed") throw new Error("Detached render failed. " + JSON.stringify(status));
		await wait(750, undefined, { signal });
	}
}

export default function agentTools(pi) {
	let planned = false;
	let turnStarted = Date.now();
	let previousSteps = [];
	let planReason;
	// Fingerprint the actual output before the workflow attaches a unique receipt number.
	const recordReview = registerStallRecovery(pi, () => previousSteps.find((item) => item.status === "in_progress")?.id,
		(note) => pauseJob?.(note));
	const workflow = registerSkillWorkflow(pi);
	const downloads = process.env.PI_IMAGE_DOWNLOADS;
	const output = process.env.PI_IMAGE_OUTPUT;
	const reply = (text, details) => ({ content: [{ type: "text", text }], details });

	pi.on("before_agent_start", (event) => {
		const recovery = event.messageType === "custom" && event.message.customType === "local-pi-job-recovery"
			? event.message.details : undefined;
		if (event.messageType === "user" || recovery) {
			turnStarted = Date.now();
			previousSteps = recovery?.plan?.steps ?? [];
			planned = previousSteps.length > 0;
			planReason = undefined;
		}
		return {
			systemPrompt: event.systemPrompt + "\n\nFor new tool work, call update_plan by itself after prepare_prompt. " +
				"Give each step a concrete title and a short skillQuery for its technique or explicitly requested standard. Mark the current step in progress. " +
				"For a signed-in or interactive website in Chrome, start with get_chrome_state and use chrome_action on its verified controls. " +
				"When the user names a registered tool, try it for the matching work before searching source files or switching to shell commands. " +
				`PowerShell commands without a timeout stop after ${POWERSHELL_TIMEOUT_SECONDS} seconds. Use workspace jobs for long scripts. ` +
				"If a check repeats without new evidence, change the method or use an independent reference. " +
				"If new information changes the work, revise the plan and briefly explain why. Mark a step complete only after verifying it.",
		};
	});

	pi.on("tool_call", (event) => {
		if (!planned && event.toolName !== "update_plan" && !workflow.allowed.has(event.toolName)) {
			return { block: true, reason: "Call update_plan by itself before using work tools." };
		}
		if (event.toolName === "powershell" && event.input.timeout === undefined) {
			event.input.timeout = POWERSHELL_TIMEOUT_SECONDS;
		}
	});
	const pauseJob = registerJobRecovery(pi);

	function checkPlan(steps) {
		const ids = new Set(steps.map((item) => item.id));
		if (ids.size !== steps.length || steps.filter((item) => item.status === "in_progress").length > 1) {
			throw new Error("Use unique step IDs and at most one in-progress step.");
		}
		return ids;
	}
	function commitPlan(steps, reason, initialReview, ctx) {
		const proposedIds = checkPlan(steps);
		const updatedSteps = [...steps];
		for (const [index, item] of previousSteps.entries()) {
			if (item.status === "completed" && !proposedIds.has(item.id)) updatedSteps.splice(index, 0, item);
		}
		if (updatedSteps.length > maxPlanSteps) {
			throw new Error(`Use at most ${maxPlanSteps} steps including saved completed steps.`);
		}
		const verified = new Map();
		const scopedAudio = explicitAudioReplyRequested(ctx);
		const measured = ctx && ((step) => {
			const prior = previousSteps.find((item) => item.id === step.id && item.status === "pending");
			if (!prior) return false;
			const isAnalysis = (title) => /^analy[sz]e\b/i.test(title.trim());
			if (scopedAudio ? !isAnalysis(prior.title) || !isAnalysis(step.title) :
				prior.title !== step.title || prior.skillQuery !== step.skillQuery) return false;
			return retainedAudioForStep(ctx, step.title, prior.title);
		});
		const plan = workflow.setPlan(updatedSteps.map(({ id, title, skillQuery, status, checkpoint }) => {
			const previous = previousSteps.find((item) => item.id === id);
			if (checkpoint && previous?.checkpoint && checkpoint !== previous.checkpoint) {
				throw new Error("Keep the declared checkpoint path for stage " + id + ": " + previous.checkpoint);
			}
			if (status === "completed" && previous?.status === "completed") return previous;
			const path = previous?.checkpoint ?? checkpoint;
			if (status === "completed" && path) verified.set(id, verifyStageCheckpoint(ctx.cwd, path));
			return { id, title, skillQuery, status, ...(path ? { checkpoint: path } : {}) };
		}), measured, scopedAudio);
		const note = plan.reopened ? "Pi kept " + plan.reopened + " in progress" +
			(plan.routing ? " because it still needed a skill route." : " for final verification.") : "";
		if (reason && !note) {
			planReason = reason;
			recordReview(reason);
		}
		previousSteps = plan.steps.map((item) => item.status === "completed" && verified.has(item.id)
			? { ...item, checkpointProof: verified.get(item.id) } : item);
		planned = true;
		const details = { steps: previousSteps, reason: note || planReason, awaitingSkill: plan.routing, reopenedStep: plan.reopened,
			updatedAt: new Date().toISOString(), ...(initialReview ? { initialReview } : {}) };
		pi.appendEntry("gui-plan", details);
		const receipts = previousSteps.filter((item) => item.status === "completed" && verified.has(item.id))
			.map((item) => "Verified " + item.checkpoint + " at " + item.checkpointProof.verifiedAt + ".");
		const finalFormat = previousSteps.every((item) => item.status === "completed") ?
			"Follow the user's exact final answer format. If the user asked for one line, put only the requested answer on that line and omit process or verification notes." : "";
		return reply([initialReview ? "Initial review complete. Reviewed plan recorded." : "Plan recorded.",
			note, plan.nextSkillAction, ...receipts, finalFormat].filter(Boolean).join(" "), details);
	}
	const draftInitialPlan = registerInitialPlanReview(pi, workflow.allowed, step, commitPlan);
	pi.registerTool({
		name: "update_plan",
		label: "Update plan",
		description: "Record the current plan and explain changes briefly. Previously completed steps carry forward. Use new IDs for new work or mark a finished step in progress to reopen it. Declare a stage's checkpoint path when the user requires one.",
		parameters: Type.Object({ steps: Type.Array(step, { minItems: 1, maxItems: maxPlanSteps }), reason: Type.Optional(Type.String({ maxLength: 300 })) }),
		async execute(_id, { steps, reason }, _signal, _onUpdate, ctx) {
			if (!planned) {
				checkPlan(steps);
				const draft = draftInitialPlan(steps);
				if (draft) return reply("Initial plan recorded for review. Wait for the review before starting work.", draft);
			}
			return commitPlan(steps, reason, undefined, ctx);
		},
	});

	pi.registerTool({
		name: "run_script",
		label: "Run saved script",
		description: "Run one saved Node.js (.js/.mjs/.cjs) or Python (.py) script without a shell. Use write to save source code, keep reference data in separate files, and pass each argument as its own string. Prefer this for program code and byte-sensitive checks.",
		parameters: Type.Object({ path: Type.String({ minLength: 1 }),
			args: Type.Optional(Type.Array(Type.String(), { maxItems: 64 })),
			timeout: Type.Optional(Type.Integer({ minimum: 1, maximum: 600 })) }),
		async execute(_id, { path, args = [], timeout = 90 }, signal, _onUpdate, ctx) {
			const script = resolve(ctx.cwd, path);
			const type = extname(script).toLowerCase();
			const executable = type === ".py" ? process.env.PI_LOCAL_ANALYSIS_PYTHON :
				[".js", ".mjs", ".cjs"].includes(type) ? process.execPath : undefined;
			if (!executable) throw new Error("Select a saved Node.js or Python script with a supported extension.");
			if (!lstatSync(script).isFile()) throw new Error("Select an existing regular script file.");
			const env = { ...process.env, PYTHONIOENCODING: "utf-8" };
			delete env.PI_T03_API_KEY;
			const deadline = Date.now() + timeout * 1000;
			const argv = type === ".py" ? ["-B", script, ...args] : [script, ...args];
			return new Promise((done, fail) => {
				execFile(executable, argv, { cwd: ctx.cwd, signal, env, windowsHide: true,
					timeout: timeout * 1000, maxBuffer: 64 * 1024 }, async (error, stdout, stderr) => {
					const output = [stdout.trimEnd(), stderr.trimEnd()].filter(Boolean).join("\n");
					if (error) {
						try {
							const pilot = await detachedPilotReceipt(script, args, ctx.cwd, _id, deadline, signal);
							if (pilot) {
								done(reply("Render completed after its waiting process exited.\n" + JSON.stringify(pilot),
									{ path: script, exitCode: 0, detachedPilot: true }));
								return;
							}
						} catch (receiptError) {
							fail(receiptError);
							return;
						}
						const status = error.code === "ABORT_ERR" ? "Script aborted." :
							error.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER" ? "Script output exceeded 64 KiB per stream." :
							error.killed ? "Script timed out." : `Script failed (${error.code ?? "no exit code"}).`;
						fail(new Error([status, output].filter(Boolean).join("\n")));
						return;
					}
					done(reply(output || "Script exited with code 0.", { path: script, exitCode: 0 }));
				});
			});
		},
	});

	if (!downloads || !output) return;

	function recentPngs() {
		const directory = realpathSync(downloads);
		return readdirSync(directory, { withFileTypes: true })
			.filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith(".png"))
			.flatMap(({ name }) => {
				try {
					const file = join(directory, name);
					const stat = lstatSync(file);
					return stat.isFile() && !stat.isSymbolicLink() && stat.birthtimeMs >= turnStarted &&
						stat.size > 8 ? [{ name, bytes: stat.size, file }] : [];
				} catch (error) {
					if (error.code !== "ENOENT") throw error;
					return [];
				}
			});
	}

	pi.registerTool({
		name: "list_recent_pngs",
		label: "List PNG downloads",
		description: "List completed PNG files created in the Windows Downloads folder since this prompt started.",
		parameters: Type.Object({}),
		async execute() {
			const files = recentPngs().map(({ name, bytes }) => ({ name, bytes }));
			return reply(JSON.stringify(files), { files });
		},
	});
	pi.registerTool({
		name: "copy_downloaded_png",
		label: "Copy original PNG",
		description: "Copy a recent PNG by its exact download filename into this workspace's output folder. Does not replace files or modify the source.",
		parameters: Type.Object({ download: Type.String(), name: Type.String({ pattern: "^[A-Za-z0-9][A-Za-z0-9._ -]{0,96}\\.png$" }) }),
		async execute(_id, { download, name }) {
			const candidate = recentPngs().find((item) => item.name === download);
			if (!candidate || basename(name) !== name) throw new Error("Select a filename from list_recent_pngs and a simple PNG output name.");
			const fd = openSync(candidate.file, "r");
			const marker = Buffer.alloc(8);
			try {
				if (readSync(fd, marker, 0, 8, 0) !== 8 || marker.toString("hex") !== "89504e470d0a1a0a") {
					throw new Error("The downloaded file has no PNG signature.");
				}
			} finally {
				closeSync(fd);
			}
			mkdirSync(output, { recursive: true });
			const outputRoot = realpathSync(output);
			if (dirname(outputRoot).toLowerCase() !== realpathSync(dirname(output)).toLowerCase()) {
				throw new Error("The output directory resolves outside this workspace.");
			}
			const destination = join(outputRoot, name);
			copyFileSync(candidate.file, destination, constants.COPYFILE_EXCL);
			return reply(destination, { source: candidate.name, destination, bytes: candidate.bytes });
		},
	});
}
