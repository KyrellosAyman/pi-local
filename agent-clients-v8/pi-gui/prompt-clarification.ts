import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Type } from "typebox";
import { boundDesktopJob } from "./job-recovery.ts";

const prefix = "PI_CLARIFICATION_V1\n";
const text = (maxLength) => Type.String({ minLength: 1, maxLength });
export const questionsType = Type.Array(Type.Object({
	question: text(280), choices: Type.Array(text(180), { minItems: 3, maxItems: 3 }),
}), { maxItems: 2 });

export const clarificationEnabled = process.env.PI_GUI_CLARIFICATION === "1";

function validQuestions(questions) {
	return Array.isArray(questions) && questions.length >= 1 && questions.length <= 2 && questions.every((item) =>
		typeof item?.question === "string" && item.question.trim() && item.question.length <= 280 &&
		Array.isArray(item.choices) && item.choices.length === 3 && item.choices.every((value) =>
			typeof value === "string" && value.trim() && value.length <= 180) &&
		new Set(item.choices.map((value) => value.trim().toLowerCase())).size === 3);
}

function validAnswer(answer) {
	return answer && typeof answer === "object" && Object.keys(answer).length === 1 &&
		(Number.isInteger(answer.choice) && answer.choice >= 0 && answer.choice < 3 ||
			typeof answer.text === "string" && answer.text.trim());
}

function savedClarification(job) {
	let record;
	try {
		record = JSON.parse(readFileSync(join(process.env.PI_GUI_RECOVERY_DIR, `${job.id}.clarification.json`), "utf8"));
	} catch (error) {
		if (error.code === "ENOENT") return;
		throw error;
	}
	if (record.job !== job.id || record.session !== job.session || typeof record.brief !== "string" || !record.brief.trim() ||
		!Array.isArray(record.checks) || !record.checks.every((check) => typeof check === "string") || !validQuestions(record.questions) ||
		!Array.isArray(record.answers) || record.answers.length > record.questions.length || !record.answers.every(validAnswer)) {
		throw new Error("The saved clarification does not match this Pi task.");
	}
	return record;
}

export async function collectClarification(ctx, signal, draft = undefined) {
	if (!clarificationEnabled) return;
	const job = boundDesktopJob(ctx);
	if (!job) {
		if (draft?.questions.length) throw new Error("Clarification requires the current visible Pi task.");
		return;
	}
	let record = savedClarification(job);
	if (!record) {
		if (!draft?.questions.length) return;
		if (!validQuestions(draft.questions)) throw new Error("Use at most two questions with three distinct choices each.");
		record = { job: job.id, session: job.session, ...draft, answers: [] };
	}
	while (record.answers.length < record.questions.length) {
		const index = record.answers.length;
		const response = await ctx.ui.input(prefix + JSON.stringify({ ...record, index }), "Write your answer", { signal });
		if (response !== "saved") throw new Error("The clarification was cancelled before an answer was submitted.");
		const saved = savedClarification(job);
		if (!saved || saved.answers.length !== index + 1) throw new Error("The clarification answer was not saved.");
		record = saved;
	}
	return { brief: record.brief, checks: record.checks, answers: record.answers.map((answer, index) => ({
		question: record.questions[index].question,
		answer: answer.text ?? record.questions[index].choices[answer.choice],
	})) };
}
