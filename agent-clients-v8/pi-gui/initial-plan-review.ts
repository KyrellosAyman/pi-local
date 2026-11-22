import { Type } from "typebox";
import { boundDesktopJob } from "./job-recovery.ts";

const reviewer = "review_initial_plan";
const draftType = "gui-initial-plan-draft";

export function registerInitialPlanReview(pi, allowed, step, commit) {
	if (process.env.PI_GUI_PLAN_REVIEW !== "1") return () => undefined;
	allowed.add(reviewer);
	let job, draft, reviewed, reviewOffered;

	pi.on("before_agent_start", (event, ctx) => {
		const recovery = event.messageType === "custom" && event.message.customType === "local-pi-job-recovery"
			? event.message.details : undefined;
		if (event.messageType !== "user" && !recovery) return;
		job = boundDesktopJob(ctx)?.id;
		draft = undefined;
		reviewOffered = false;
		reviewed = Boolean(recovery?.plan?.steps?.length);
		if (!job || !recovery) return;
		const history = ctx.sessionManager.getBranch();
		reviewed ||= history.some((entry) => entry.customType === "gui-plan" && entry.data?.initialReview?.job === job);
		if (!reviewed) draft = history.findLast((entry) => entry.customType === draftType && entry.data?.job === job)?.data;
	});

	pi.on("tool_call", (event) => {
		if (draft && event.toolName !== reviewer) {
			return { block: true, reason: "Review the first plan before starting work." };
		}
	});

	pi.on("before_provider_request", ({ payload }) => {
		if (!Array.isArray(payload?.tools)) return;
		const tool = payload.tools.find((item) => item.function?.name === reviewer);
		if (!draft) return tool ? { ...payload, tools: payload.tools.filter((item) => item !== tool) } : undefined;
		const [leading, ...messages] = payload.messages ?? [];
		if (!tool || typeof leading?.content !== "string") throw new Error("The first plan is waiting for its review tool.");
		reviewOffered = true;
		const instruction = "\n\nYou are reviewing an already created draft. Instructions that apply only to the first draft have been fulfilled. " +
			"Check the user's deliverable, prerequisites, dependency order and acceptance tests against the request and saved clarification. " +
			"Write the corrected plan in steps. When you find a missing prerequisite, action or check, include it in steps before reporting it in findings. " +
			"Split compound work into observable steps, order prerequisites first, retain required checkpoint paths, and avoid extra scope. " +
			"If the draft already covers the work, keep its steps and return no findings. The draft is data.\n" + JSON.stringify(draft.steps);
		return { ...payload, messages: [{ ...leading, content: leading.content + instruction }, ...messages],
			tools: [tool], tool_choice: "required" };
	});

	pi.registerTool({
		name: reviewer, label: "Review initial plan",
		description: "Review and commit the first draft before implementation. Check scope and missing prerequisites, then give each step one verifiable outcome.",
		parameters: Type.Object({ steps: Type.Array(Type.Omit(step, ["status"]), { minItems: 1, maxItems: 12 }),
			findings: Type.Optional(Type.Array(Type.String({ maxLength: 200 }), { maxItems: 4 })) }),
		async execute(_id, { steps, findings = [] }, _signal, _onUpdate, ctx) {
			if (!job || !draft || reviewed || !reviewOffered) throw new Error("Review the draft in its separate review turn.");
			const missingCheckpoint = draft.steps.find((item) => item.checkpoint && !steps.some((next) => next.checkpoint === item.checkpoint));
			if (missingCheckpoint) throw new Error("Keep the declared checkpoint path in the reviewed plan: " + missingCheckpoint.checkpoint);
			if (findings.length && steps.length === draft.steps.length && steps.every((item, index) =>
				item.title.trim() === draft.steps[index].title.trim() && item.skillQuery.trim() === draft.steps[index].skillQuery.trim() &&
				item.checkpoint === draft.steps[index].checkpoint)) {
				throw new Error("Put the reported corrections into the reviewed steps before committing the plan.");
			}
			const orderedSteps = steps.map((item, index) => ({ ...item, status: index === 0 ? "in_progress" : "pending" }));
			const result = commit(orderedSteps, findings.length ? findings.join(" ") : "Initial plan reviewed.", { job, findings }, ctx);
			reviewed = true;
			draft = undefined;
			return result;
		},
	});

	return (steps) => {
		if (!job || reviewed || draft) return;
		draft = { job, steps };
		pi.appendEntry(draftType, draft);
		return { steps, reviewPending: true };
	};
}
