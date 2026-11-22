import { spawn } from "node:child_process";
import { Type } from "typebox";

const pathArgument = Type.String({ description: "A local path from the message or the selected workspace." });
const nonnegative = Type.Integer({ minimum: 0 });
const regionArgument = Type.Tuple([nonnegative, nonnegative, nonnegative, nonnegative]);

export async function inspect(python, script, mode, input, cwd, signal) {
	return new Promise((resolve, reject) => {
		const env = { ...process.env, PYTHONIOENCODING: "utf-8",
			PYTHONUSERBASE: process.env.PI_LOCAL_ANALYSIS_USERBASE };
		delete env.PI_T03_API_KEY;
		const child = spawn(python, ["-B", script, mode], {
			cwd, signal, windowsHide: true, stdio: ["pipe", "pipe", "pipe"],
			env,
		});
		const output = [];
		const errors = [];
		child.stdout.on("data", (data) => output.push(data));
		child.stderr.on("data", (data) => errors.push(data));
		child.on("error", reject);
		child.stdin.on("error", reject);
		child.on("close", (code) => {
			if (code !== 0) {
				reject(new Error(Buffer.concat(errors).toString("utf8").trim().slice(-1500) ||
					"Local media inspection exited without a result."));
				return;
			}
			try {
				const result = JSON.parse(Buffer.concat(output).toString("utf8"));
				if (result.error) {
					reject(new Error(result.error));
					return;
				}
				const { images = [], ...info } = result;
				resolve({ content: [{ type: "text", text: JSON.stringify(info) }, ...images],
					details: { ...info, imageCount: images.length } });
			} catch (error) {
				reject(error);
			}
		});
		child.stdin.end(JSON.stringify(input));
	});
}

export default function analysisTools(pi) {
	const python = process.env.PI_LOCAL_ANALYSIS_PYTHON;
	const script = process.env.PI_LOCAL_ANALYSIS_SCRIPT;
	if (!python || !script) return;

	const tools = [
		["inspect_input", "Inspect local input", "Identify a local file's size and media streams or list a workspace folder.", "info",
			Type.Object({ path: pathArgument })],
		["view_image_file", "View an image", "Pass an actual local image or animation frame to vision. Check delivered_size for downscaling. Use region [left, top, width, height] in source pixels for a close-up.", "image",
			Type.Object({ path: pathArgument, frame: Type.Optional(nonnegative),
				region: Type.Optional(regionArgument) })],
		["sample_video", "See video frames", "Pass actual frames from local video to vision. Omit selectors for a first sweep. For exact checks, batch up to eight increasing zero-based frames and optionally crop a shared native region [left, top, width, height]. Alternatively use times in seconds.", "video",
			Type.Object({ path: pathArgument,
				times: Type.Optional(Type.Array(Type.Number({ minimum: 0 }), { minItems: 1, maxItems: 8 })),
				frames: Type.Optional(Type.Array(nonnegative, { minItems: 1, maxItems: 8 })),
				region: Type.Optional(regionArgument) })],
		["analyze_audio", "Analyze sound", "Measure decoded audio, classify sound event candidates and optionally transcribe speech using local CPU models. For interpretation use the local-media-review skill. Use the stereo equality field to decide whether samples match. Report nonzero sample spans and estimated speech times separately. A selected window can verify overlap around that region while leaving its boundaries unknown. Recording setup remains unknown. Use successive windows for long recordings.", "audio",
			Type.Object({ path: pathArgument, start: Type.Optional(Type.Number({ minimum: 0,
				description: "Offset from the beginning in seconds. Omit to start at zero. Keep it before the recording ends." })),
				duration: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 30,
					description: "Length of the requested window in seconds. Omit to analyze up to 30 seconds from the offset." })),
				transcribe: Type.Optional(Type.Boolean()),
				channel: Type.Optional(Type.Integer({ minimum: 1, description: "One-based source channel (1 for left, 2 for right in stereo). Omit for mono. For overlapping or differing stereo signals, call both channels separately; time windows do not separate channels." })) })],
		["read_document", "Read a document", "Read a local PDF, Office document, ZIP inventory or source/text file in pages. All offsets start at zero. Follow continuation or next_byte_offset to read further. For saved web pages, set readable_html to true and follow next_offset for the extracted text. PDFs can render a requested page for vision.", "document",
			Type.Object({ path: pathArgument, offset: Type.Optional(nonnegative),
				count: Type.Optional(Type.Integer({ minimum: 1, maximum: 16 })), sheet: Type.Optional(Type.String()),
				render: Type.Optional(Type.Boolean()), char_offset: Type.Optional(nonnegative), readable_html: Type.Optional(Type.Boolean()) })],
		["read_website", "Read a webpage", "Fetch server-rendered HTTP or HTTPS text without browser cookies. Continue with next_offset. Cached or client-rendered content may differ from a signed-in browser.", "webpage",
			Type.Object({ url: Type.String(), offset: Type.Optional(nonnegative) })],
	];
	for (const [name, label, description, mode, parameters] of tools) {
		if (name === "read_website" && process.env.PI_LOCAL_WEB_TOOLS !== "1") continue;
		pi.registerTool({
			name, label, description, parameters,
			async execute(_id, input, signal, _onUpdate, ctx) {
				return inspect(python, script, mode, input, ctx.cwd, signal);
			},
		});
	}
}
