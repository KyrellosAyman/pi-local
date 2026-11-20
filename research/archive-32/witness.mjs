import { createHash } from "node:crypto";
import { appendFileSync, readFileSync, realpathSync } from "node:fs";
import { resolve } from "node:path";

const publicRoot = realpathSync(process.env.PI_ARCHIVE_WORKSPACE);
const trace = process.env.PI_ARCHIVE_TRACE;
const lines = (text) => text.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n");
const originals = new Map(Array.from({ length: 32 }, (_, n) => {
	const page = String(n + 1).padStart(2, "0");
	const path = resolve(publicRoot, "pages", `${page}.txt`);
	return [path, { page, text: lines(readFileSync(path, "utf8")) }];
}));

export default function witness(pi) {
	pi.on("before_provider_request", ({ payload }, context) => {
		if (realpathSync(context.cwd) !== publicRoot || !Array.isArray(payload?.messages)) return;
		const calls = new Map();
		const visible = [];
		for (const message of payload.messages) {
			for (const call of message.tool_calls ?? []) {
				if (call.function?.name !== "read") continue;
				let args;
				try { args = JSON.parse(call.function.arguments); } catch { continue; }
				if (typeof args?.path !== "string") continue;
				const original = originals.get(resolve(publicRoot, args.path));
				if (original) calls.set(call.id, { original, offset: args.offset ?? 1 });
			}
			const seen = calls.get(message.tool_call_id);
			if (message.role !== "tool" || !seen) continue;
			const { original, offset } = seen;
			if (!Number.isInteger(offset) || offset < 1 || offset > original.text.length) continue;
			const text = typeof message.content === "string" ? message.content :
				(Array.isArray(message.content) ? message.content.filter((part) => part.type === "text")
					.map((part) => part.text).join("\n") : "");
			const observed = lines(text);
			let count = 0;
			while (count < observed.length && observed[count] === original.text[offset + count - 1]) count++;
			if (count) {
				const id = createHash("sha256").update(message.tool_call_id).digest("hex");
				visible.push({ page: original.page, call: id, first: offset, last: offset + count - 1 });
			}
		}
		appendFileSync(trace, JSON.stringify({
			context_window: context.model?.contextWindow ?? null, visible,
		}) + "\n", "utf8");
	});
}
