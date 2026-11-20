import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "count_utf8_bytes",
		label: "Count UTF-8 bytes",
		description: "Report the UTF-8 byte length of exact text.",
		parameters: Type.Object({ text: Type.String({ maxLength: 4096 }) }),
		annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
		async execute(_id, { text }) {
			const utf8Bytes = Buffer.byteLength(text, "utf8");
			return {
				content: [{ type: "text", text: String(utf8Bytes) }],
				details: { utf8Bytes },
			};
		},
	});
}
