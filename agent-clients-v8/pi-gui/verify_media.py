"""Verify attachment formats and local analysis with reproducible fixtures."""
from datetime import datetime, timezone
from io import BytesIO
import base64
import json
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
import wave

from PIL import Image

import inspect_input as tool


def pixel(encoded):
    with Image.open(BytesIO(base64.b64decode(encoded['data']))) as image:
        image.load()
        return image.getpixel((image.width // 2, image.height // 2))


def speech_recheck_controls(base):
    import numpy as np

    pcm = np.array([0]*10 + [1000]*40 + [0]*50, dtype='<i2')
    location = base / 'recognition'
    span = 'estimated_word_span_seconds_from_excerpt_start'
    original = tool.recognize_speech

    def check(alternate_text, alternate_end):
        def response(text, start, end):
            return {'speech_text': text, 'transcription_status': 'estimated_words_returned',
                    'words_relative_to_excerpt': [{'word': text, 'start': start, 'end': end}]}
        reads = iter([response('The bell rings after noon.', 1.2, 8), response(alternate_text, .2, alternate_end)])
        tool.recognize_speech = lambda *_: next(reads)
        return tool.speech_estimate(location, location, pcm, 10)

    try:
        close = check('The bell rings after dusk.', 3.5)
        different = check('Completely different result.', 3.5)
        out_of_range = check('The bell rings after noon.', 6)
    finally:
        tool.recognize_speech = original
    return (close['speech_text'] == 'The bell rings after dusk.' and close[span] == [1.2, 4.5]
            and close['words_relative_to_excerpt'][0]['word'] == close['speech_text']
            and close.get('word_recognition_disagreement') is True
            and all(item['speech_text'] == 'The bell rings after noon.' and span not in item
                    and item['word_timing_status'] == 'inconsistent_with_decoded_activity'
                    for item in (different, out_of_range)))


def fixture_checks(base):
    checks = {}
    picture = base / 'green.png'
    with Image.new('RGB', (120, 90), (20, 190, 70)) as image:
        image.save(picture)
    checked = tool.picture(picture, region=[20, 20, 40, 40])
    checks['image_crop_has_actual_pixels'] = checked['original_size'] == [120, 90] and pixel(checked['images'][0])[1] > 180

    video = base / 'red-then-blue.mp4'
    tool.ff('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=red:size=160x120:rate=10:d=1',
                      '-f', 'lavfi', '-i', 'color=blue:size=160x120:rate=10:d=1',
                      '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono',
                      '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
                      '-map', '[v]', '-map', '2:a', '-t', '2', '-c:v', 'libx264', '-threads', '2', '-c:a', 'aac', video])
    first, second = map(pixel, tool.video_frames(video, [.4, 1.4])['images'])
    checks['two_video_timestamps_have_distinct_pixels'] = first[0] > 200 and second[2] > 200
    silence = tool.audio_excerpt(video, .25, 1.2)
    checks['video_audio_uses_the_requested_window'] = silence['digital_silence'] and silence['samples'] == 19200 and abs(silence['end_seconds'] - 1.45) < .0001

    for name, stereo_pair in [('opposite-phase', (4096, -4096, 4096, -4096)),
                              ('left-full-scale', (32767, 0, -32768, 0))]:
        audio = base / f'{name}.wav'
        with wave.open(str(audio), 'wb') as wav:
            wav.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(pack('<hhhh', *stereo_pair) * 8000)
        measured = tool.audio_excerpt(audio, duration=1, transcribe=False)
        if name == 'opposite-phase':
            checks['stereo_cancellation_is_only_mono_analysis_silence'] = (
                measured['mono_analysis_silence'] and not measured['digital_silence']
                and [channel['peak_dbfs'] for channel in measured['channels']] == [-18.06, -18.06])
            checks['gain_headroom_uses_original_channel_peaks'] = (
                [channel['gain_headroom_db'] for channel in measured['channels']] == [18.06, 18.06])
            checks['silent_mono_has_no_finite_peak_change'] = measured['mono_peak_change_from_loudest_channel_db'] is None
            selected = tool.audio_excerpt(audio, .125, .625, transcribe=False, channel=2)
            checks['selected_channel_bypasses_cancelling_mix'] = (
                selected['analysis_channel'] == 2 and not selected['analysis_channel_silence']
                and selected['peak_dbfs'] == -18.06 and selected['samples'] == 10000
                and selected['end_seconds'] == .75 and selected['channels'] == measured['channels'])
        else:
            checks['one_channel_full_scale_survives_mono_downmix'] = (
                measured['peak_dbfs'] < -6 and [channel['samples_at_full_scale']
                                              for channel in measured['channels']] == [16000, 0])
            checks['full_scale_has_no_headroom_and_silence_has_no_peak'] = (
                [channel['gain_headroom_db'] for channel in measured['channels']] == [0.0, None])
            checks['silent_channel_is_distinguished_from_missing_data'] = (
                [channel['digital_silence'] for channel in measured['channels']] == [False, True])
            checks['mono_attenuation_is_measured_from_original_peak'] = (
                measured['mono_peak_change_from_loudest_channel_db'] == -6.02)
            checks['sound_labels_describe_candidates'] = 'scores do not verify an event' in measured['scope']
            checks['full_scale_scope_covers_both_polarities'] = 'include either polarity' in measured['scope']
            selected = tool.audio_excerpt(audio, duration=1, channel=2)
            checks['silent_selection_keeps_original_channel_evidence'] = (
                selected['analysis_channel_silence'] and not selected['digital_silence']
                and selected['channels'] == measured['channels'] and not selected['sound_event_hints']
                and 'speech_text' not in selected and 'mono_peak_change_from_loudest_channel_db' not in selected)
            try:
                tool.audio_excerpt(audio, channel=3)
            except ValueError as error:
                checks['out_of_range_channel_is_rejected'] = '1 to 2' in str(error)
            else:
                checks['out_of_range_channel_is_rejected'] = False

    checks['word_timing_retains_matching_transcript_and_flags_disagreement'] = speech_recheck_controls(base)
    return checks


if __name__ == '__main__':
    with TemporaryDirectory(prefix='pi-media-fixture-') as temporary:
        result = fixture_checks(Path(temporary))
    if not all(result.values()):
        raise RuntimeError(result)
    print(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'checks': result}, indent=2))
