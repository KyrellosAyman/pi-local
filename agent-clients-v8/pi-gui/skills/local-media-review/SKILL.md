---
name: local-media-review
description: Use for local audio analysis, speech transcription, stereo overlap, sound classification, and for reviewing video, FFmpeg exports, captions and audiovisual sync.
---

# Local media review

1. Read the brief and identify the exact source clips, required visuals, approved audio and caption timing. Confirm the runtime you will use locally. Keep source files intact and render a separate candidate until the checks pass.
   For offline Windows narration, `run_script` can use `win32com.client` and the installed `SAPI.SpVoice`. Open a new absolute WAV path with `SAPI.SpFileStream.Open(path, 3, False)`, assign it to `voice.AudioOutputStream`, then call `voice.Speak(text)` and close the stream. Confirm the WAV has decoded, non-silent samples before rendering.
2. Probe the finished file for each stream's codec, duration and start time. Check the required raster, frame rate and decoded frame count. Decode picture and audio through the end. A container duration and the presence of an audio track alone cannot rule out a short picture or digital silence.
3. Inspect the actual export with `sample_video`. Batch up to eight selected timestamps or frame numbers from the same export in one call. Sample the middle of every distinct caption cue when there are only a few. For longer cuts, inspect the longest lines, cut boundaries and any failed intervals. Confirm the first and last words fit with margins and that required source visuals appear within the frame. Use native-size frames to resolve uncertain crops.
4. Check the caption file against the actual media clock and the requested format. Confirm any prescribed numbers, cue order, boundaries and non-overlap. Use `analyze_audio` to check decoded signal or estimate narration when its local runtime is available. Report machine estimates and measured offsets separately from any listening or perceived sync check.
5. Fix observed defects and recheck the affected intervals on the exact final export. If producing a handoff, compare its paths, required fields and hashes against the finished files after the last edit. Report only checks that ran and keep any unverified playback or review requirements open.

For audio analysis, inspect each file once. The default `analyze_audio` result includes separate speech estimates when stereo waveforms differ. Reuse them before requesting an individual channel or a shorter window. Keep these observations distinct in the report.

When the requested chat answer consists of listening findings, use `reply_with_audio_findings` after analyzing the requested files and closing the plan. Pi uses the saved observations to deliver the report. For a requested file or different deliverable, use the appropriate tools for that output.

- The stereo equality field establishes whether the decoded waveforms match sample for sample. Equal peak or RMS levels can accompany different waveforms. If another check disagrees, confirm the exact file and window, then rerun `analyze_audio` for that window before judging the conflict. A stereo PCM16 WAV interleaves two-byte samples for left and right within each frame. Alternating bytes do not isolate channels. Report measured dBFS and referenced relative dB separately. The decoded file leaves the capture setup, processing and speaker identity unresolved.
- A nonzero sample span is a channel envelope. Transcribed words have estimated times. Different isolated transcripts with intersecting estimated word ranges support possible overlap. A shared inspection window alone cannot establish overlap. Leave the actual speech overlap boundaries unresolved unless separately measured.
- Describe event scores as provisional candidates in their own measured windows. A label in one window cannot rule it out in another. Use decoded samples to locate digital silence. An empty transcript leaves speech detection uncertain.
