import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { detectSupportedImageMimeTypeFromFile } from "@earendil-works/pi-coding-agent";

const checkTools = new Set(["powershell", "bash", "run_script", "read", "grep", "find", "ls", "read_website", "read_document"]);
const visualTools = new Set(["view_image_file", "sample_video"]);
const viewsPerReview = 8;
const reviewMessage = "Record what the inspected frames established and what specific change or comparison will resolve the remaining question. Put that in update_plan's reason using at most 300 characters. Keep every completed step in the plan.";
const message = "The recent checks returned the same evidence. Change the verification method or consult an independent reference. If the stage is blocked, report the missing evidence and preserve partial files.";
const failureMessage = "The same diagnostic recurred across attempts. Verify the actual deliverable in its required representation against an independent reference, and change the verification method before retrying. If the stage is blocked, preserve partial files and report the missing evidence.";
const scriptRecovery = "Use write to save a standalone script and run_script to run it by itself. Keep source fixture data in a separate file. Verify the actual deliverable against an independent reference before retrying the failed check.";
const inlineScript = /(?:^|[;\s])(?:node|python)(?:\.exe)?\s+(?:-e|-c|--eval)(?:\s|$)/i;
const fingerprint = (value) => createHash("sha256").update(value).digest("hex");

export function registerStallRecovery(pi, currentStage, pauseJob) {
	const checks = new Map();
	const failures = new Map();
	const shellRecovery = new Set();
	const failedCommands = new Set();
	const scriptRefusals = new Map();
	const reviews = new Map();
	const visualHashes = new Map();
	let revision = 0;
	pi.on("before_agent_start", (event) => {
		if (event.messageType === "user") {
			checks.clear();
			failures.clear();
			shellRecovery.clear();
			failedCommands.clear();
			scriptRefusals.clear();
			reviews.clear();
			visualHashes.clear();
			revision = 0;
		}
	});
	// A frame removed by compaction may be needed again, but the review batch still counts.
	pi.on("session_compact", () => visualHashes.clear());
	pi.on("before_provider_request", ({ payload }) => {
		const review = reviews.get(currentStage());
		if (!review?.refusals || ![undefined, "auto"].includes(payload?.tool_choice) ||
			!Array.isArray(payload?.tools)) return;
		const plan = payload.tools.find((tool) => tool.type === "function" && tool.function?.name === "update_plan");
		// The native server ignores object-form tool_choice.
		if (plan) {
			review.requested = true;
			return { ...payload, tools: [plan], tool_choice: "required" };
		}
	});
	pi.on("turn_end", ({ toolResults }, ctx) => {
		const stage = currentStage();
		const review = reviews.get(stage);
		if (!review?.requested) return;
		review.requested = false;
		review.planAttempts = (review.planAttempts ?? 0) + 1;
		if (review.planAttempts < 3) return;
		const note = "Pi paused after three attempts without a valid visual review checkpoint. The last valid plan and workspace files were preserved.";
		try {
			pauseJob?.(note);
			pi.appendEntry("gui-stall", { stage, tool: "update_plan",
				toolCallId: toolResults.find((result) => result.toolName === "update_plan")?.toolCallId,
				action: "pause_review" });
		} finally {
			ctx.abort();
		}
	});
	const key = (event) => JSON.stringify([currentStage(), event.toolName,
		Object.entries(event.input ?? {}).sort(([a], [b]) => a.localeCompare(b))]);

	function refuseVisual(event, stage, review) {
		const terminate = ++review.refusals >= 3;
		pi.appendEntry("gui-stall", { stage, tool: event.toolName, toolCallId: event.toolCallId,
			action: terminate ? "terminate" : "review_required" });
		return { block: true, terminate, reason: reviewMessage };
	}

	function checkRepeat(event) {
		if (!checkTools.has(event.toolName)) return;
		const id = key(event);
		if (event.toolName === "powershell" && (failedCommands.has(id) ||
			(shellRecovery.has(currentStage()) && inlineScript.test(event.input?.command ?? "")))) {
			const stage = currentStage();
			const refusals = (scriptRefusals.get(stage) ?? 0) + 1;
			scriptRefusals.set(stage, refusals);
			const terminate = refusals >= 3;
			pi.appendEntry("gui-stall", { stage, tool: event.toolName,
				toolCallId: event.toolCallId, action: terminate ? "terminate" : "block_repeat" });
			return { block: true, terminate, reason: "Repeated check refused. " + scriptRecovery };
		}
		const previous = checks.get(id);
		if (previous?.revision !== revision || (previous.count < 2 && (failures.get(previous.failure) ?? 0) < 2)) return;
		previous.refusals += 1;
		const terminate = previous.refusals >= 3;
		pi.appendEntry("gui-stall", { stage: currentStage(), tool: event.toolName,
			toolCallId: event.toolCallId, action: terminate ? "terminate" : "block_repeat" });
		return { block: true, terminate, reason: "Repeated check refused. " + (previous.failure ? failureMessage : message) };
	}

	pi.on("tool_call", (event, context) => {
		const stage = currentStage();
		const review = reviews.get(stage);
		if (review?.views >= viewsPerReview) {
			if (visualTools.has(event.toolName)) return refuseVisual(event, stage, review);
			if (event.toolName === "read" && typeof event.input?.path === "string" && context?.cwd) {
				return detectSupportedImageMimeTypeFromFile(resolve(context.cwd, event.input.path)).then(
					(mime) => mime ? refuseVisual(event, stage, review) : checkRepeat(event),
					() => checkRepeat(event));
			}
		}
		return checkRepeat(event);
	});

	pi.on("tool_result", (event) => {
		const stage = currentStage();
		const images = !event.isError && (visualTools.has(event.toolName) || event.toolName === "read")
			? event.content.filter((part) => part.type === "image") : [];
		if (images.length) {
			const review = reviews.get(stage) ?? { views: 0, refusals: 0 };
			// Other images in a parallel batch may already have passed the call gate.
			if (review.views >= viewsPerReview) {
				pi.appendEntry("gui-stall", { stage, tool: event.toolName, toolCallId: event.toolCallId, action: "review_required" });
				return { isError: true, content: [{ type: "text", text: reviewMessage }], details: { stallRecovery: reviewMessage } };
			}
			review.views += 1;
			reviews.set(stage, review);
			const hash = fingerprint(JSON.stringify(images.map((part) => [part.mimeType, part.data])));
			const previous = visualHashes.get(hash);
			if (!previous) visualHashes.set(hash, event.toolCallId);
			const guidance = [previous && "This visual evidence matches an earlier view. Use the earlier result or inspect a different frame, crop, or artifact.",
				review.views === viewsPerReview && reviewMessage].filter(Boolean).join("\n");
			if (!guidance) return;
			pi.appendEntry("gui-stall", { stage, tool: event.toolName, toolCallId: event.toolCallId,
				action: previous ? "duplicate_visual" : "review_checkpoint", previous });
			const content = previous ? event.content.filter((part) => part.type === "text") : event.content;
			return { content: [...content, { type: "text", text: guidance }],
				structuredContent: previous ? undefined : event.structuredContent, details: { ...event.details, stallRecovery: guidance } };
		}
		if (!event.isError && ["write", "edit"].includes(event.toolName)) revision += 1;
		if (!checkTools.has(event.toolName) || event.content.some((part) => part.type !== "text")) return;
		const output = event.content.map((part) => part.text.trim()).join("\n");
		if (!output || output.startsWith("Repeated check refused.")) return;
		const id = key(event);
		// Runtime stack frames and shell wrappers can change without changing the error.
		const parserFailure = event.toolName === "powershell" && event.isError &&
			/\bParserError\b|Unexpected token [^\r\n]+ in expression or statement\./i.test(output);
		const diagnostic = event.isError && output.match(/^\s*(?:(?:[A-Za-z]*Error|[A-Za-z]*Exception):[^\r\n]+|[^\r\n:]{1,100}: FAIL\b)/m)?.[0]
			.trim().replace(/<CR>$/, "").trimEnd();
		const failure = diagnostic && fingerprint(JSON.stringify([currentStage(), diagnostic]));
		if (failure) failures.set(failure, (failures.get(failure) ?? 0) + 1);
		const hash = failure || fingerprint(`${event.isError}\n${output}`);
		const previous = checks.get(id);
		const count = previous?.hash === hash ? previous.count + 1 : 1;
		const refusals = previous?.hash === hash ? previous.refusals : 0;
		checks.set(id, { hash, count, revision, refusals, failure });
		const repeatsFailure = failure && failures.get(failure) >= 2;
		const runs = (event.input?.command ?? "").match(/(?:^|;\s*)(?:node|python)(?:\.exe)?\s/gi);
		const repeatsCompound = event.toolName === "powershell" && repeatsFailure && (runs?.length ?? 0) > 1;
		if (parserFailure) shellRecovery.add(currentStage());
		if (parserFailure || repeatsCompound) failedCommands.add(id);
		if (count < 2 && !repeatsFailure && !parserFailure) return;
		const guidance = parserFailure || repeatsCompound ? scriptRecovery : repeatsFailure ? failureMessage : message;
		pi.appendEntry("gui-stall", { stage: currentStage(), tool: event.toolName,
			toolCallId: event.toolCallId, action: "change_approach", repeatedDiagnostic: repeatsFailure || undefined });
		return { content: [...event.content, { type: "text", text: guidance }],
			structuredContent: event.structuredContent, details: { ...event.details, stallRecovery: guidance } };
	});
	return (reason) => {
		const review = reviews.get(currentStage());
		const note = reason?.trim().replace(/\s+/g, " ").toLowerCase();
		if (review?.views >= viewsPerReview && note && note !== review.note) {
			Object.assign(review, { views: 0, refusals: 0, planAttempts: 0, requested: false, note });
		}
	};
}
