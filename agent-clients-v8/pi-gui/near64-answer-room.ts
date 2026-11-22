const localRoot = "http://127.0.0.1:1235";
const tokenizerMargin = 256;
const directTools = new Set(["codemode", "read", "update_plan"]);

export default function registerLocalAnswerRoom(pi) {
	pi.on("before_provider_request", async ({ payload }, { model }) => {
		const key = process.env.PI_T03_API_KEY;
		if (!key || model?.provider !== "qwen-local" || model?.baseUrl !== localRoot + "/v1" ||
			model.contextWindow !== 64000 || !Number.isInteger(model.maxTokens) || model.maxTokens <= 1 ||
			payload?.max_tokens !== 1 || !Array.isArray(payload.messages)) return;
		// The text tokenizer cannot account for tokens added by images or audio encoders.
		if (payload.messages.some(({ content }) => content != null && typeof content !== "string" &&
			(!Array.isArray(content) || content.some((part) => part?.type !== "text" || typeof part.text !== "string")))) return;
		const signal = AbortSignal.timeout(8000);
		async function localPost(path, body) {
			const reply = await fetch(localRoot + path, {
				method: "POST", redirect: "error", signal,
				headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" }, body: JSON.stringify(body),
			});
			if (!reply.ok) throw new Error("The local tokenizer refused the request.");
			return reply.json();
		}
		async function countPrompt(request) {
			const { messages, tools, tool_choice, chat_template_kwargs, reasoning_effort } = request;
			const templateOptions = { ...chat_template_kwargs };
			if (reasoning_effort && !templateOptions.reasoning_effort) templateOptions.reasoning_effort = reasoning_effort;
			const { prompt } = await localPost("/apply-template", {
				messages, tools, tool_choice, add_generation_prompt: true, chat_template_kwargs: templateOptions,
			});
			if (typeof prompt !== "string" || !prompt) throw new Error("The local template returned no prompt.");
			const { tokens } = await localPost("/tokenize", { content: prompt, parse_special: true, add_special: false });
			if (!Array.isArray(tokens) || !tokens.length) throw new Error("The local tokenizer returned no count.");
			return tokens.length;
		}
		const minimumReply = Math.max(0, Number(payload.reasoning_budget_tokens) || 0) + 128;
		const replyBudget = (count) => Math.min(model.maxTokens, model.contextWindow - count - tokenizerMargin);
		let request = payload;
		let promptTokens;
		try {
			promptTokens = await countPrompt(payload);
			if (replyBudget(promptTokens) < minimumReply && [undefined, "auto"].includes(payload.tool_choice) &&
				Array.isArray(payload.tools) && payload.tools.some((tool) => tool.function?.name === "codemode")) {
				const tools = payload.tools.filter((tool) => directTools.has(tool.function?.name));
				if (tools.length < payload.tools.length) {
					// Codemode still discovers the full registered catalog without putting every schema in the prompt.
					request = { ...payload, tools };
					promptTokens = await countPrompt(request);
				}
			}
		} catch {
			return;
		}
		const outputTokens = replyBudget(promptTokens);
		if (outputTokens < minimumReply) return;
		const catalog = request === payload ? {} : { originalToolCount: payload.tools.length, offeredToolCount: request.tools.length };
		pi.appendEntry("gui-answer-room", { promptTokens, outputTokens, originalOutputTokens: 1, ...catalog });
		return { ...request, max_tokens: outputTokens };
	});
}
