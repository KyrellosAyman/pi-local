"""Prepare local document pages, vision frames and audio evidence for Pi."""
import base64
import csv
from difflib import SequenceMatcher
from hashlib import file_digest
from io import BytesIO
from itertools import islice
import json
import math
import os
import ipaddress
from pathlib import Path
import re
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import wave
from xml.etree import ElementTree
from zipfile import ZipFile

from PIL import Image, ImageOps

MEDIA = Path(__file__).resolve().parent / 'media'
SPEECH = MEDIA.parent / 'runtime/audio'
FF = SPEECH / 'ffmpeg'
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.ico', '.avif'}
AV_EXT = {'.mov', '.mp4', '.mkv', '.webm', '.avi', '.m4v', '.mpg', '.mpeg', '.ts', '.wmv',
          '.flv', '.3gp', '.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma', '.aif', '.aiff'}
YAMNET = SPEECH / 'yamnet'


def digest(path):
    with path.open('rb') as file:
        return file_digest(file, 'sha256').hexdigest()


def ff(binary, args, timeout=45):
    name = binary + '.exe'
    pin = json.loads((MEDIA / 'runtime-pins.json').read_text(encoding='utf-8'))['ffmpeg'][name]
    executable = FF / name
    if digest(executable) != pin:
        raise RuntimeError(f'{name} no longer matches the verified local installation.')
    result = subprocess.run([str(executable), *map(str, args)], stdin=subprocess.DEVNULL,
                            capture_output=True, check=False, timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'{name}: {result.stderr.decode("utf-8", "replace")[-750:].strip()}')
    return result.stdout


def input_flags(path):
    flags = ['-protocol_whitelist', 'file,pipe']
    if path.suffix.lower() in {'.mp4', '.mov', '.m4a', '.m4v', '.3gp'}:
        flags += ['-enable_drefs', '0', '-use_absolute_path', '0']
    return flags


def media_info(path):
    if path.suffix.lower() not in AV_EXT:
        raise ValueError('Expected a supported local audio or video container.')
    fields = 'format=duration,format_name:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate,duration'
    return json.loads(ff('ffprobe', ['-v', 'error', *input_flags(path),
                                    '-show_entries', fields, '-of', 'json', path]))


def image_content(image):
    image.thumbnail((1440, 1440), Image.Resampling.LANCZOS)
    handle = BytesIO()
    image.convert('RGB').save(handle, format='JPEG', quality=91)
    return {'type': 'image', 'mimeType': 'image/jpeg', 'data': base64.b64encode(handle.getvalue()).decode('ascii')}


def picture(path, frame=0, region=None):
    with Image.open(path) as source:
        original = source.size
        source.seek(frame)
        image = ImageOps.exif_transpose(source)
        if region:
            left, top, width, height = region
            if min(left, top) < 0 or min(width, height) <= 0 or left + width > image.width or top + height > image.height:
                raise ValueError(f'Crop is outside the oriented {image.width}×{image.height} image.')
            image = image.crop((left, top, left + width, top + height))
        input_size = image.size
        content = image_content(image)
        return {'format': source.format, 'original_size': list(original), 'frame': frame,
                'frame_count': getattr(source, 'n_frames', 1), 'crop': region,
                'delivered_size': list(image.size), 'downscaled': image.size != input_size, 'images': [content]}


def video_frames(path, times=None, frames=None, region=None):
    meta = media_info(path)
    streams = [stream for stream in meta.get('streams', []) if stream.get('codec_type') == 'video']
    if not streams:
        raise ValueError('No video stream was found.')
    if frames is not None:
        if times is not None or not 1 <= len(frames) <= 8 or any(type(n) is not int or n < 0 for n in frames) \
                or frames != sorted(set(frames)):
            raise ValueError('Use 1 to 8 distinct, increasing zero-based frame numbers and omit times.')
        return numbered_video_frames(path, meta, streams[0], frames, region)
    if region is not None:
        raise ValueError('Use frames with a native-pixel region.')
    raw_duration = meta.get('format', {}).get('duration')
    duration = float(raw_duration) if raw_duration and raw_duration != 'N/A' else None
    if times is None:
        times = [duration * part for part in (.05, .33, .65, .92)] if duration else [0]
    output = []
    for seconds in times:
        if not math.isfinite(seconds) or seconds < 0 or duration is not None and seconds >= duration:
            raise ValueError(f'Timestamp {seconds} is outside the video.')
        raw = ff('ffmpeg', ['-v', 'error', '-nostdin', '-ss', f'{seconds:.4f}', *input_flags(path),
                            '-i', path, '-map', f"0:{streams[0]['index']}", '-frames:v', '1',
                            '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease',
                            '-c:v', 'mjpeg', '-f', 'image2pipe', 'pipe:1'])
        with Image.open(BytesIO(raw)) as decoded:
            output.append(image_content(decoded))
    return {'metadata': meta, 'sampled_seconds': times, 'images': output,
            'scope': 'Only these timestamps were sampled. Request additional timestamps around changes or needed detail.'}


def numbered_video_frames(path, meta, stream, frames, region):
    width, height = stream['width'], stream['height']
    filters = 'select=' + '+'.join(f'eq(n\\,{n})' for n in frames)
    if region is not None:
        left, top, crop_width, crop_height = region
        if min(left, top) < 0 or min(crop_width, crop_height) <= 0 \
                or left + crop_width > width or top + crop_height > height:
            raise ValueError(f'Crop is outside the native {width}×{height} video raster.')
        filters += f',format=rgb24,crop={crop_width}:{crop_height}:{left}:{top}:exact=1'
        width, height = crop_width, crop_height
    output, samples = [], []
    with TemporaryDirectory(prefix='pi-frames-') as temp:
        target = Path(temp) / '%02d.png'
        ff('ffmpeg', ['-v', 'error', '-nostdin', '-xerror', '-threads', '2', '-noautorotate',
                      *input_flags(path), '-i', path, '-map', f"0:{stream['index']}",
                      '-vf', filters, '-fps_mode', 'passthrough', '-frames:v', len(frames),
                      '-threads:v', '1', '-start_number', '1', target])
        files = sorted(Path(temp).glob('*.png'))
        if len(files) != len(frames):
            raise ValueError('At least one requested frame is past the end of this video.')
        for n, file in zip(frames, files):
            with Image.open(file) as decoded:
                if decoded.size != (width, height):
                    raise ValueError('Decoded size differs from the requested native raster.')
                output.append(image_content(decoded))
                samples.append({'frame': n, 'delivered_size': list(decoded.size),
                                'downscaled': decoded.size != (width, height)})
    return {'metadata': meta, 'sampled_frames': samples, 'crop': region, 'images': output,
            'scope': 'Frame numbers are zero-based in presentation order. Images follow the same order.'}


def sound_events(samples, start, sample_rate, channels=None):
    import numpy as np
    import onnxruntime as ort

    model = YAMNET / 'yamnet.onnx'
    labels_file = YAMNET / 'yamnet_class_map.csv'
    pins = json.loads((MEDIA / 'runtime-pins.json').read_text(encoding='utf-8'))['yamnet']
    if any(digest(path) != pins[path.name] for path in (model, labels_file)):
        raise RuntimeError('The pinned sound event model or label map does not match its checksum.')
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    engine = ort.InferenceSession(str(model), options, providers=['CPUExecutionProvider'])
    with labels_file.open(encoding='utf-8', newline='') as labels:
        names = {int(row['index']): row['display_name'] for row in csv.DictReader(labels)}

    def top(waveform):
        if not np.any(waveform):
            return []
        scores = engine.run(['output_0'], {'waveform': waveform})[0]
        if scores.ndim != 2 or scores.shape[1] != 521 or not np.isfinite(scores).all():
            raise RuntimeError('The sound event model returned an unexpected score tensor.')
        maxima = scores.max(axis=0)
        return [{'label': names[int(index)], 'score': round(float(maxima[index]), 4)}
                for index in maxima.argsort()[-8:][::-1]]

    def describe(signal):
        info = {'sound_event_hints': top(signal)}
        if len(signal) >= sample_rate * 6:
            middle = len(signal) // 2
            halves = ((0, middle), (middle, len(signal)))
            windows = [{'window_seconds': [start + left / sample_rate, start + right / sample_rate],
                        'hints': top(signal[left:right])} for left, right in halves]
            missing = {hint['label'] for hint in info['sound_event_hints']} - {
                hint['label'] for window in windows for hint in window['hints']}
            if missing and len(signal) >= sample_rate * 8:
                for left, right in halves:
                    midpoint = (left + right) // 2
                    for first, end in ((left, midpoint), (midpoint, right)):
                        hints = [hint for hint in top(signal[first:end]) if hint['label'] in missing]
                        if hints:
                            windows.append({'window_seconds': [start + first / sample_rate, start + end / sample_rate],
                                            'hints': hints})
            info['sound_event_time_windows'] = windows
        return info

    result = describe(samples)
    if channels is not None:
        result['channel_sound_events'] = [
            {'channel': index, **describe(channel.astype(np.float32) / 32768)}
            for index, channel in enumerate(channels.T, 1)]
    return result


def dbfs(level):
    return round(20 * math.log10(float(level)), 2) if level else None


def recognize_speech(excerpt, output):
    if str(MEDIA) not in sys.path:
        sys.path.insert(0, str(MEDIA))
    from transcribe_local import transcribe as pinned_transcribe

    receipt = pinned_transcribe(excerpt, output)
    text = receipt['text']
    result = {'speech_text': text, 'transcription_status':
              'estimated_words_returned' if text.strip() else 'no_words_returned'}
    raw = json.loads(Path(receipt['transcript_path']).read_text(encoding='utf-8'))
    if isinstance(raw.get('words'), list):
        result['words_relative_to_excerpt'] = raw['words']
    return result


def word_span(words):
    ranges = [(word.get('start'), word.get('end')) for word in words if isinstance(word, dict)]
    ranges = [(start, end) for start, end in ranges
              if all(isinstance(value, (int, float)) and math.isfinite(value) for value in (start, end))
              and 0 <= start <= end]
    return [min(start for start, _ in ranges), max(end for _, end in ranges)] if len(ranges) == len(words) and ranges else None


def write_mono_pcm(path, samples, rate):
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(samples.tobytes())


def transcript_words(text):
    return re.findall(r"\w+(?:'\w+)*", text.casefold().replace('’', "'"))


def speech_estimate(excerpt, output, samples, rate):
    result = recognize_speech(excerpt, output)
    span_key = 'estimated_word_span_seconds_from_excerpt_start'
    span = word_span(result.get('words_relative_to_excerpt', ()))
    if result['transcription_status'] != 'estimated_words_returned' or not span:
        return result
    active = samples != 0
    first, end = int(active.argmax()), len(samples) - int(active[::-1].argmax())
    # Recognition edges are estimates. This tolerance flags substantial disagreement with digital silence.
    tolerance = .25

    def fits(estimate):
        return first/rate - tolerance <= estimate[0] and estimate[1] <= end/rate + tolerance

    if fits(span):
        return {**result, span_key: span}
    if end - first < len(samples):
        recheck = output.with_name(output.name + '-activity.wav')
        try:
            write_mono_pcm(recheck, samples[first:end], rate)
            alternate = recognize_speech(recheck, output.with_name(output.name + '-activity'))
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
            alternate = {}
        words = alternate.get('words_relative_to_excerpt', ())
        cropped_span = word_span(words)
        baseline_words = transcript_words(result['speech_text'])
        cropped_words = transcript_words(alternate.get('speech_text', ''))
        # A crop uses the same PCM, but only retain its timing with its own closely agreeing transcript.
        agreement = SequenceMatcher(None, baseline_words, cropped_words, autojunk=False).ratio()
        if cropped_span and baseline_words and cropped_words and agreement >= .8:
            offset = first/rate
            adjusted = [round(value + offset, 6) for value in cropped_span]
            if fits(adjusted):
                result.update({span_key: adjusted, 'word_timing_status': 'reestimated_on_decoded_activity',
                               'speech_text': alternate['speech_text'],
                               'words_relative_to_excerpt': [{**word, 'start': round(word['start'] + offset, 6),
                                                               'end': round(word['end'] + offset, 6)} for word in words]})
                if baseline_words != cropped_words:
                    result['word_recognition_disagreement'] = True
                return result
    result['word_timing_status'] = 'inconsistent_with_decoded_activity'
    result['unverified_word_span_seconds_from_excerpt_start'] = span
    result.pop('words_relative_to_excerpt', None)
    return result


def stereo_signal(stereo, rate, limit):
    import numpy as np

    with wave.open(str(stereo), 'rb') as wav:
        count = wav.getnframes()
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (2, 2, rate) or not 0 < count <= limit:
            raise ValueError('Unexpected sample clock in the separate stereo analysis.')
        channels = np.frombuffer(wav.readframes(count), dtype='<i2').reshape(-1, 2)
        if len(channels) != count:
            raise ValueError('The separate stereo analysis was incomplete.')
    return channels


def stereo_speech_estimates(channels, directory, rate):
    estimates = []
    for index, samples in enumerate(channels.T, 1):
        estimate = {'channel': index, 'transcription_status': 'analysis_signal_digital_silence'}
        if samples.any():
            mono = directory / f'channel-{index}.wav'
            write_mono_pcm(mono, samples, rate)
            estimate.update(speech_estimate(mono, directory / f'transcript-{index}', samples, rate))
            estimate.pop('words_relative_to_excerpt', None)
        estimates.append(estimate)
    return estimates


def audio_excerpt(path, start=0, duration=30, transcribe=True, channel=None):
    import numpy as np

    if not all(map(math.isfinite, (start, duration))) or start < 0 or not 0 < duration <= 30:
        raise ValueError('Use a nonnegative offset and a window up to 30 seconds.')
    meta = media_info(path)
    audio = next((stream for stream in meta.get('streams', []) if stream.get('codec_type') == 'audio'), None)
    if audio is None:
        raise ValueError('No audio stream was found.')
    raw_duration = meta.get('format', {}).get('duration')
    media_seconds = float(raw_duration) if raw_duration and raw_duration != 'N/A' else None
    if media_seconds is not None and media_seconds > 0 and start >= media_seconds:
        raise ValueError(f'Start {start:g} s is at or after the recording end ({media_seconds:g} s). '
                         'Start is an offset from the beginning. Use start=0 or omit it for the first window.')
    channel_count = audio['channels']
    if channel is not None and (type(channel) is not int or not 1 <= channel <= channel_count):
        raise ValueError(f'Choose an integer channel from 1 to {channel_count}, or omit it for the mono mix.')
    source_rate = int(audio['sample_rate'])
    analysis_rate = 16000
    channel_rate = min(48000, source_rate)
    channel_limit = max(1, round(duration * channel_rate))
    # Trim the original samples before the resampler can blend in audio beyond the window.
    source_trim = f'atrim=end_sample={max(1, round(duration * source_rate))}'
    with TemporaryDirectory(prefix='pi-audio-') as folder:
        folder = Path(folder)
        excerpt = folder / 'speech.wav'
        stereo = folder / 'stereo.wav'
        include_stereo = channel is None and channel_count == 2
        limit = round(duration * analysis_rate)
        analysis_filter = f'{source_trim},aresample={analysis_rate},atrim=end_sample={limit}'
        if channel is not None:
            analysis_filter = f'pan=mono|c0=c{channel - 1},{analysis_filter}'
        decode = [
            '-v', 'error', '-nostdin', '-ss', f'{start:.4f}', *input_flags(path), '-i', path,
            '-map', '0:a:0', '-vn', '-af', analysis_filter,
            '-ac', '1', '-c:a', 'pcm_s16le', excerpt,
            '-map', '0:a:0', '-vn', '-af', f'{source_trim},aresample={channel_rate},atrim=end_sample={channel_limit}',
            '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1']
        if include_stereo:
            decode.extend(['-map', '0:a:0', '-vn', '-af', analysis_filter, '-c:a', 'pcm_s16le', stereo])
        channel_pcm = ff('ffmpeg', decode)
        if not channel_pcm:
            raise ValueError(f'No audio was decoded at start {start:g} s. Try an earlier offset or omit start.')
        if len(channel_pcm) > channel_limit * channel_count * 4 or len(channel_pcm) % (channel_count * 4):
            raise ValueError('Unexpected decoded channel sample count.')
        decoded = np.frombuffer(channel_pcm, dtype='<f4').reshape(-1, channel_count)
        channel_levels = np.abs(decoded)
        if not np.isfinite(channel_levels).all():
            raise ValueError('The decoded audio includes non-finite channel levels.')
        channel_peaks = channel_levels.max(axis=0)
        nonzero = channel_levels != 0
        first_nonzero = nonzero.argmax(axis=0)
        nonzero_end = len(decoded) - nonzero[::-1].argmax(axis=0)
        channel_dbfs = [dbfs(level) for level in channel_peaks]
        channel_rms = np.sqrt(np.mean(channel_levels ** 2, axis=0))
        loudest_peak = float(channel_peaks.max())
        loudest_rms = float(channel_rms.max())
        full_scale = np.count_nonzero(channel_levels >= 32767/32768, axis=0)
        with wave.open(str(excerpt), 'rb') as wav:
            if wav.getnframes() <= 0 or wav.getnframes() > limit:
                raise ValueError('There are no decoded audio samples in the requested interval.')
            mono_pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
        samples = mono_pcm.astype(np.float32) / 32768
        peak = float(np.max(np.abs(samples)))
        end = start + len(samples) / analysis_rate
        result = {'start_seconds': start, 'end_seconds': end, 'samples': len(samples), 'sample_rate': analysis_rate,
                  'source_sample_rate_hz': source_rate, 'analysis_sample_rate_hz': analysis_rate,
                  'rms_dbfs': dbfs(np.sqrt(np.mean(samples ** 2))), 'peak_dbfs': dbfs(peak),
                  'recording_setup_status': 'unknown_from_audio_analysis',
                  'recording_setup_scope': ('The measurements describe the decoded file. '
                                            'Channel levels at capture and any later processing remain unknown.'),
                  'peak_reference_channels': [int(i) + 1 for i in np.flatnonzero(channel_peaks == loudest_peak)]
                  if loudest_peak else [],
                  'rms_reference_channels': [int(i) + 1 for i in np.flatnonzero(channel_rms == loudest_rms)]
                  if loudest_rms else [],
                  'digital_silence': not bool(channel_peaks.any()),
                  'channel_sample_rate': channel_rate, 'samples_per_channel': len(channel_levels),
                  'decoded_nonzero_spans_seconds_from_excerpt_start': [
                      [round(int(first_nonzero[i]) / channel_rate, 6), round(int(nonzero_end[i]) / channel_rate, 6)]
                      if channel_peaks[i] else None for i in range(channel_count)],
                  'channels': [{'channel': i+1, 'peak_dbfs': channel_dbfs[i], 'rms_dbfs': dbfs(channel_rms[i]),
                                'peak_relative_to_loudest_channel_db': dbfs(channel_peaks[i] / loudest_peak) if loudest_peak else None,
                                'rms_relative_to_loudest_channel_db': dbfs(channel_rms[i] / loudest_rms) if loudest_rms else None,
                                'digital_silence': channel_dbfs[i] is None,
                                'gain_headroom_db': max(0.0, -channel_dbfs[i]) if channel_dbfs[i] is not None else None,
                                'samples_at_full_scale': int(full_scale[i])} for i in range(channel_count)],
                  'sound_event_hints': []}
        separate = None
        if channel_count == 2:
            difference = np.abs(decoded[:, 0] - decoded[:, 1])
            difference_peak = float(difference.max())
            result['decoded_stereo_channels_identical'] = difference_peak == 0
            result['decoded_stereo_difference_peak_dbfs'] = dbfs(difference_peak)
            result['stereo_difference_peak_relative_to_loudest_channel_db'] = dbfs(difference_peak / loudest_peak) if loudest_peak else None
            if include_stereo and difference_peak:
                separate = stereo_signal(stereo, analysis_rate, limit)
        if peak or separate is not None:
            result.update(sound_events(samples, start, analysis_rate, separate))
        if channel is None:
            result['mono_peak_change_from_loudest_channel_db'] = dbfs(peak / loudest_peak) if peak and loudest_peak else None
            result['mono_analysis_silence'] = peak == 0
            analysis_scope = ('Main speech and event hints use the mono mix. Separate channel estimates, when present, '
                              'use the individual decoded channels. A negative mono peak change is measured '
                              'attenuation versus the loudest original channel, including when caused by averaging. '
                              'A silent mix has no finite peak change. ')
        else:
            result['analysis_channel'] = channel
            result['analysis_channel_silence'] = peak == 0
            analysis_scope = (f'Speech, event hints and excerpt levels use only channel {channel}. '
                              'The channel measurements still cover every original channel. '
                              'Channel separation does not identify speakers or separate voices mixed into one channel. ')
        if transcribe:
            result['transcription_status'] = 'analysis_signal_digital_silence' if not peak else 'no_words_returned'
        else:
            result['transcription_status'] = 'not_requested'
        if transcribe and peak:
            result.update(speech_estimate(excerpt, folder / 'transcript', mono_pcm, analysis_rate))
        if transcribe and separate is not None:
            result['channel_transcripts'] = stereo_speech_estimates(separate, folder, analysis_rate)
        if media_seconds is not None:
            result['next_start_seconds'] = end if end < media_seconds - .002 else None
        result['scope'] = (analysis_scope +
                           'The source sample rate is the codec stream rate. The analysis rate belongs to the resampled model input. '
                           'A channel marked digitally silent has decoded zero samples throughout the window. '
                           'Each nonzero span is a decoded channel envelope relative to the excerpt start. '
                           'Its exclusive end is one sample after the last nonzero sample. Add start_seconds '
                           'for recording time. A span can contain silent intervals and does not measure speech. '
                           'Word times estimate speech timing. If materially outside decoded activity, Pi rechecks the '
                           'timing in the active window and retains it only when the recognized text still matches. '
                           'An inconsistent word-time result does not support timing or overlap. '
                           'Peak, RMS and stereo-difference values in dBFS are relative to digital full scale. '
                           'Use the relative-to-loudest-channel dB fields when comparing peaks or RMS. '
                           'Peak and RMS have separate references. Null means there is no finite level or reference. '
                           'Similar channel peaks or RMS do not establish identical waveforms. Use the separate stereo '
                           'estimates when present, or select a channel and window for closer inspection. '
                           'Estimated word spans enclose recognized words, including gaps, and do not establish exact overlap. '
                           'Shorter sound windows can report additional whole-window candidates absent from the broader halves. '
                           'Describe sound labels as candidates. Classifier scores do not verify an event or identify '
                           'its source or establish that two events do not overlap. Channel measurements and '
                           'classifier labels do not establish microphone placement, rooms or recording conditions. '
                           'Report the recording setup as unknown when this is the only evidence. '
                           'Gain headroom estimates how much uniform '
                           'gain a decoded channel can take before reaching full scale. It excludes intersample peaks. '
                           'Full-scale counts include either polarity at the magnitude threshold 32767/32768 and '
                           'indicate possible saturation. An empty transcript alone does not establish absence of '
                           'speech. Speech confidence is a model estimate. Speaker identity, exact timing and '
                           'perceived quality require separate evidence.')
        return result


def document(path, offset=0, count=6, sheet=None, render=False, char_offset=0, readable_html=False):
    suffix = path.suffix.lower()
    if readable_html:
        if suffix not in ('.htm', '.html', '.xhtml') or render or sheet is not None or char_offset:
            raise ValueError('Readable HTML requires an HTML file and uses a single character offset.')
        with path.open('rb') as file:
            data = file.read(2_000_001)
        soup = parsed_html(data[:2_000_000])
        for block in soup(['p', 'div', 'section', 'article', 'li', 'br', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            block.insert_before('\n')
            block.append('\n')
        lines = [' '.join(line.split()) for line in soup.get_text().splitlines()]
        text = '\n'.join(line for line in lines if line)
        if not 0 <= offset <= len(text):
            raise ValueError('Character offset is outside the readable HTML text.')
        end = offset + 12000
        return {'text': text[offset:end], 'offset': offset,
                'next_offset': end if end < len(text) else None, 'input_truncated': len(data) > 2_000_000}
    pages = []
    if suffix == '.pdf':
        import fitz
        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError('This PDF has an opening password.')
            total = len(pdf)
            if offset >= total:
                raise ValueError('Page offset is outside the PDF.')
            if render:
                pixmap = pdf[offset].get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
                with Image.open(BytesIO(pixmap.tobytes('png'))) as image:
                    return {'page': offset + 1, 'page_count': total, 'images': [image_content(image)]}
            pages = [pdf[index].get_text() for index in range(offset, min(total, offset + count))]
    elif suffix == '.docx':
        from docx import Document
        doc = Document(path)
        paragraphs = [paragraph.text for paragraph in doc.paragraphs]
        paragraphs.extend(' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows)
        total = len(paragraphs)
        pages = paragraphs[offset:offset + count]
    elif suffix in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is None:
                return {'sheets': workbook.sheetnames, 'scope': 'Select a sheet and a row offset to read values.'}
            view = workbook[sheet]
            total = view.max_row
            end = min(total, offset + count) if total is not None else offset + count
            pages = [list(row) for row in view.iter_rows(min_row=offset + 1, max_row=end, values_only=True)] if end > offset else []
        finally:
            workbook.close()
    elif suffix == '.pptx':
        from pptx import Presentation
        slides = Presentation(path).slides
        total = len(slides)
        pages = ['\n'.join(shape.text for shape in slides[index].shapes if shape.has_text_frame)
                 for index in range(offset, min(total, offset + count))]
    elif suffix == '.zip':
        with ZipFile(path) as archive:
            entries = archive.infolist()
            total = len(entries)
            pages = [{'path': item.filename, 'bytes': item.file_size} for item in entries[offset:offset + count]]
    else:
        with path.open('rb') as file:
            header = file.read(4)
            file.seek(offset)
            block = file.read(12000)
        if b'\x00' in block[:1024] and not header.startswith((b'\xff\xfe', b'\xfe\xff')):
            raise ValueError('This file appears to be binary. Choose a decoder for its format.')
        encoding = 'utf-16-le' if header[:2] == b'\xff\xfe' else 'utf-16-be' if header[:2] == b'\xfe\xff' else 'utf-8-sig'
        import codecs
        decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
        text = decoder.decode(block, final=offset + len(block) >= path.stat().st_size)
        consumed = len(block) - len(decoder.getstate()[0])
        return {'text': text, 'byte_offset': offset, 'next_byte_offset':
                offset + consumed if offset + consumed < path.stat().st_size else None, 'encoding': encoding}
    result = []
    budget = 12000
    continuation = None
    for index, item in enumerate(pages):
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, default=str)
        start = char_offset if index == 0 else 0
        chunk = text[start:start + budget]
        result.append({'offset': offset + index, 'char_offset': start, 'text': chunk})
        budget -= len(chunk)
        if start + len(chunk) < len(text):
            continuation = {'offset': offset + index, 'char_offset': start + len(chunk)}
            break
        if budget <= 0:
            continuation = {'offset': offset + index + 1, 'char_offset': 0}
            break
    next_page = offset + len(pages)
    if continuation is None and pages and ((total is not None and next_page < total) or
                                           (total is None and len(pages) == count)):
        continuation = {'offset': next_page, 'char_offset': 0}
    if continuation and total is not None and continuation['offset'] >= total:
        continuation = None
    return {'offset': offset, 'total': total, 'results': result, 'continuation': continuation}


def inspect(path):
    if path.is_dir():
        with os.scandir(path) as directory:
            items = [{'name': item.name, 'directory': item.is_dir()} for item in islice(directory, 100)]
        return {'path': str(path), 'directory': True, 'entries': items,
                'scope': 'First 100 entries. Use the workspace find and grep tools to inspect deeply.'}
    result = {'path': str(path), 'bytes': path.stat().st_size, 'extension': path.suffix.lower()}
    if path.suffix.lower() in AV_EXT:
        result['media'] = media_info(path)
    elif path.suffix.lower() in IMAGE_EXT:
        with Image.open(path) as image:
            result.update(format=image.format, size=image.size, frames=getattr(image, 'n_frames', 1))
    return result


def public_address(address):
    parsed = urlsplit(address)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Skill research uses public HTTPS sources.')
    targets = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not targets or any(not ipaddress.ip_address(row[4][0]).is_global for row in targets):
        raise ValueError('Skill research cannot reach private network addresses.')


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_address(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parsed_html(html):
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(html, 'html.parser')
    for element in parsed(['script', 'style', 'template', 'noscript']):
        element.decompose()
    return parsed


def webpage(url, offset=0, public_only=False, specification=False):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a plain HTTP or HTTPS address without embedded credentials.')
    request = Request(url, headers={'User-Agent': 'Pi-Local-Reader/1.0', 'Accept': 'text/html,text/plain'})
    if public_only:
        public_address(url)
    opener = build_opener(PublicRedirect()).open if public_only else urlopen
    with opener(request, timeout=12 if public_only else 18) as response:
        media_type = response.headers.get_content_type()
        encoding = response.headers.get_content_charset() or 'utf-8'
        final_url = response.url
        data = response.read(2_000_001)
    if media_type not in ('text/html', 'application/xhtml+xml', 'text/plain'):
        raise ValueError(f'The response is {media_type}. Download an authorized local file for its decoder.')
    html = data[:2_000_000].decode(encoding, errors='replace')
    fragment = unquote(urlsplit(final_url).fragment or parsed.fragment)
    title = ''
    fragment_found = None
    if media_type != 'text/plain':
        parsed = parsed_html(html)
        title = parsed.title.get_text(' ', strip=True) if parsed.title else ''
        anchor = parsed.find(id=fragment) if fragment else None
        if fragment:
            fragment_found = anchor is not None
        if anchor is not None:
            section = anchor if anchor.name in ('section', 'article', 'emu-clause') else (
                anchor.find_parent(['section', 'article', 'emu-clause']) or anchor)
            if section is anchor and anchor.name in ('h2', 'h3', 'h4', 'h5', 'h6'):
                parts = [anchor.get_text(' ', strip=True)]
                for element in anchor.next_siblings:
                    if getattr(element, 'name', None) in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                        if element.name <= anchor.name:
                            break
                    if hasattr(element, 'get_text'):
                        parts.append(element.get_text(' ', strip=True))
                html = '\n'.join(filter(None, parts))
            else:
                html = '\n'.join(section.stripped_strings)
        elif specification:
            body, examples, background = [], [], []
            for section in parsed.select('section[id]'):
                key = section.get('id').removeprefix('section-')
                if not (key == 'abstract' or key[:1].isdigit() or key.startswith('appendix.')):
                    continue
                heading = section.find(['h2', 'h3', 'h4', 'h5', 'h6'], recursive=False)
                if heading is None:
                    continue
                title_text = heading.get_text(' ', strip=True).rstrip('¶').strip()
                if any(term in title_text.lower() for term in ('references', 'iana considerations')):
                    continue
                if key.startswith('appendix.') and not any(term in title_text.lower() for term in ('test', 'sample', 'example')):
                    continue
                parts = []
                for node in section.find_all(['p', 'pre', 'li', 'dt', 'dd', 'tr']):
                    if node.find_parent('section') is not section or node.find_parent(['li', 'tr']):
                        continue
                    value = (' | '.join(cell.get_text(' ', strip=True) for cell in node.find_all(['td', 'th']))
                             if node.name == 'tr' else node.get_text().strip() if node.name == 'pre'
                             else ' '.join(node.get_text().split()))
                    if value:
                        parts.append(value)
                if parts:
                    section_text = title_text + '\n' + '\n'.join(parts)
                    if key.startswith('appendix.'):
                        examples.append(section_text)
                    elif key == 'abstract' or any(term in title_text.lower() for term in
                                                  ('introduction', 'terminology', 'security considerations')):
                        background.append(section_text)
                    else:
                        body.append(section_text)
            html = '\n\n'.join(body + examples + background) if body else '\n'.join(parsed.stripped_strings)
        else:
            html = '\n'.join(parsed.stripped_strings)
    page_size = 15000 if specification else 12000
    block = html[offset:offset + page_size]
    return {'url': final_url, 'title': title, 'text': block, 'offset': offset,
            'next_offset': offset + len(block) if offset + len(block) < len(html) else None,
            'response_prefix_only': len(data) > 2_000_000,
            **({'fragment_found': fragment_found, 'fragment': fragment} if fragment else {}),
            'scope': 'Reads server-rendered text. Authenticated or browser-rendered interactions need browser controls.'}


def search_sources(query, category='web'):
    if not 1 <= len(query.strip()) <= 180:
        raise ValueError('Use a short public search query.')

    def fetch(endpoint, params, limit=1_000_000):
        request = Request(endpoint + '?' + urlencode(params),
                          headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Pi-Local-Research/1.0',
                                   'Accept-Language': 'en-US,en;q=0.8'})
        with urlopen(request, timeout=9) as response:
            return response.read(limit)

    def row(link, title, snippet=''):
        return {'url': link, 'title': (title or '')[:200], 'snippet': (snippet or '')[:450]}

    if category == 'repos':
        data = json.loads(fetch('https://api.github.com/search/repositories', {'q': query, 'per_page': 8}))
        results = [row(item['html_url'], item['full_name'], item.get('description')) for item in data['items']]
        return {'provider': 'GitHub repository search', 'results': results}

    if category == 'social':
        data = json.loads(fetch('https://hn.algolia.com/api/v1/search',
                                {'query': query, 'hitsPerPage': 8, 'tags': 'story'}))
        results = [row('https://news.ycombinator.com/item?id=' + item['objectID'], item.get('title'), item.get('url'))
                   for item in data['hits']]
        return {'provider': 'Hacker News search', 'results': results}

    if category == 'video':
        from re import search
        data = fetch('https://www.youtube.com/results', {'search_query': query}, 3_000_000).decode('utf-8', 'replace')
        match = search(r'(?:var ytInitialData|window\["ytInitialData"\])\s*=\s*', data)
        if not match:
            raise ValueError('YouTube did not expose its public result list.')
        tree, _ = json.JSONDecoder().raw_decode(data[match.end():])
        queue, results, seen = [tree], [], set()
        while queue and len(results) < 8:
            item = queue.pop()
            if isinstance(item, list):
                queue.extend(reversed(item))
            elif isinstance(item, dict):
                video = item.get('videoRenderer')
                video_id = video.get('videoId') if isinstance(video, dict) else None
                if video_id and video_id not in seen:
                    title = ''.join(part.get('text', '') for part in video.get('title', {}).get('runs', []))
                    results.append(row('https://www.youtube.com/watch?v=' + video_id, title))
                    seen.add(video_id)
                queue.extend(reversed(list(item.values())))
        return {'provider': 'YouTube public search', 'results': results}

    if category != 'web':
        raise ValueError('Choose web, repos, social or video.')
    data = fetch('https://news.google.com/rss/search', {'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    if b'<!doctype' in data.lower():
        raise ValueError('The search response could not be processed safely.')
    results = []
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise ValueError('Public article search did not return a results feed.') from error
    for entry in root.findall('./channel/item')[:8]:
        link = entry.findtext('link', '')
        publisher = entry.find('source')
        if urlsplit(link).scheme == 'https':
            results.append(row(link, entry.findtext('title'), publisher.get('url') if publisher is not None else None))
    return {'provider': 'Google News article index', 'results': results}


def main():
    options = json.load(sys.stdin)
    function = dict(info=inspect, image=picture, video=video_frames, audio=audio_excerpt,
                    document=document, webpage=webpage, search_sources=search_sources)[sys.argv[1]]
    if 'path' in options:
        options['path'] = Path(options['path']).resolve(strict=True)
    try:
        result = function(**options)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {'error': str(exc)}
    print(json.dumps(result, ensure_ascii=True, default=str))


if __name__ == '__main__':
    main()
