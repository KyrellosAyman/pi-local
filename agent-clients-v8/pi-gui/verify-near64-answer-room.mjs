import assert from "node:assert/strict";
import register from "./near64-answer-room.ts";

const calls = [];
const entries = [];
let beforeRequest;
const key = "local-tokenizer-fixture";
process.env.PI_T03_API_KEY = key;
register({
	on: (event, handler) => {
		assert.equal(event, "before_provider_request");
		beforeRequest = handler;
	},
	appendEntry: (type, data) => entries.push({ type, data }),
});
globalThis.fetch = async (url, options) => {
	assert.equal(new URL(url).origin, "http://127.0.0.1:1235");
	assert.equal(options.redirect, "error");
	assert.equal(options.headers.Authorization, "Bearer " + key);
	const body = JSON.parse(options.body);
	calls.push({ url, body });
	if (url.endsWith("/apply-template")) return { ok: true, json: async () => ({ prompt: String(body.tools.length) }) };
	assert.equal(new URL(url).pathname, "/tokenize");
	return { ok: true, json: async () => ({ tokens: Array(body.content === "4" ? 66000 : 61000) }) };
};

const model = { provider: "qwen-local", baseUrl: "http://127.0.0.1:1235/v1", contextWindow: 64000, maxTokens: 4096 };
const tools = ["read", "write", "codemode", "update_plan"].map((name) => ({ function: { name } }));
const payload = { messages: [{ role: "user", content: "Text fixture" }], tools, max_tokens: 1 };
const fitted = await beforeRequest({ payload }, { model });
assert.deepEqual(fitted.tools.map((tool) => tool.function.name), ["read", "codemode", "update_plan"]);
assert.equal(fitted.max_tokens, 2744);
assert.deepEqual(entries, [{ type: "gui-answer-room", data: {
	promptTokens: 61000, outputTokens: 2744, originalOutputTokens: 1, originalToolCount: 4, offeredToolCount: 3,
} }]);
assert.equal(payload.tools.length, 4);
assert.equal(calls.length, 4);
assert.equal(await beforeRequest({ payload: { ...payload, max_tokens: 256 } }, { model }), undefined);
assert.equal(await beforeRequest({ payload: { ...payload, messages: [{ content: [{ type: "image_url" }] }] } }, { model }), undefined);
assert.equal(await beforeRequest({ payload }, { model: { ...model, baseUrl: "https://example.invalid/v1" } }), undefined);
assert.equal(calls.length, 4);

const review = { ...payload, tool_choice: "required", tools: [{ function: { name: "review_initial_plan" } }] };
const reviewed = await beforeRequest({ payload: review }, { model });
assert.equal(reviewed.tools, review.tools);
assert.equal(reviewed.tool_choice, "required");
assert.equal(reviewed.max_tokens, 2744);
assert.equal(calls.length, 6);
console.log("Verified local-only answer reserve, compact catalog, and required review tool preservation.");
