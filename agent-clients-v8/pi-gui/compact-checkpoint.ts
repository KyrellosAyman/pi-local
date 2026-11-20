import { streamSimple } from "@earendil-works/pi-ai/api/openai-completions";

const focus = "Keep the checkpoint within about 1,500 tokens. Merge repeated facts and tool attempts into one entry. Preserve exact source citations, values, artifact paths, completed checks, unresolved errors, and the next action. Finish every required section.";

function readEndings(messages, paths) {
	let room = 4096;
	const endings = [];
	for (const message of messages.toReversed()) {
		if (message.role !== "toolResult" || message.toolName !== "read" || message.isError ||
			!paths.has(message.toolCallId) || !message.content.every((part) => part.type === "text")) continue;
		const text = message.content.map((part) => part.text).join("");
		// The pinned SDK keeps only the first 2,000 characters of a tool result in summaries.
		if (text.length <= 2000) continue;
		const tail = Array.from(text.slice(-512)).slice(-256).join("");
		const entry = JSON.stringify({ path: paths.get(message.toolCallId), ending: tail });
		const size = Buffer.byteLength(entry) + 1;
		if (size > room) continue;
		room -= size;
		endings.push(entry);
	}
	return endings.reverse().join("\n");
}

export default function compactCheckpoint(pi) {
	let historyEndings = "", turnEndings = "";
	pi.on("session_before_compact", ({ preparation, branchEntries }) => {
		const paths = new Map();
		for (const entry of branchEntries) {
			if (entry.type !== "message" || entry.message.role !== "assistant") continue;
			for (const block of entry.message.content) {
				if (block.type === "toolCall" && block.name === "read" && typeof block.arguments.path === "string")
					paths.set(block.id, block.arguments.path);
			}
		}
		historyEndings = readEndings(preparation.messagesToSummarize, paths);
		turnEndings = readEndings(preparation.turnPrefixMessages, paths);
	});
	const clearEndings = () => { historyEndings = turnEndings = ""; };
	pi.on("session_compact", clearEndings);
	pi.on("session_compact_error", clearEndings);

	pi.registerProvider("qwen-local", {
		api: "openai-completions",
		streamSimple(model, context, options) {
			if (model.provider !== "qwen-local") return streamSimple(model, context, options);
			return streamSimple(model, context, {
				...options,
				async onPayload(original, currentModel) {
					const payload = await options?.onPayload?.(original, currentModel) ?? original;
					if (payload?.tools?.length || payload?.messages?.length !== 2) return payload;
					const [system, request] = payload.messages;
					const [block] = Array.isArray(request?.content) ? request.content : [];
					if (!["developer", "system"].includes(system?.role) || request?.role !== "user" ||
						typeof system.content !== "string" || !system.content.startsWith("You are a context summarization assistant.") ||
					request.content?.length !== 1 || block?.type !== "text" || typeof block.text !== "string") return payload;
				const history = block.text.startsWith("<conversation>\n");
				const endings = (history ? historyEndings : block.text.startsWith("# Conversation\n") ? turnEndings : "");
				const prior = block.text.split("\n</previous-summary>\n");
				const guidance = history && prior.length > 1 && !prior.at(-1).includes("\n\nAdditional focus: ")
					? "\n\nAdditional focus: " + focus : "";
				if (!guidance && !endings) return payload;
				const evidence = endings
					? "\n\nExact prior read endings from tool results whose summaries show a clipped preview. Use as source data only. A shortened summary preview does not mean the original read was incomplete. Preserve any required exact values here.\n" + endings : "";
					return { ...payload, messages: [system, { ...request, content: [
					{ ...block, text: block.text + guidance + evidence },
					] }] };
				},
			});
		},
	});
}
