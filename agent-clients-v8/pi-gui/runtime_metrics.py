"""Read local GPU, system memory and llama.cpp slot measurements."""
import csv
import json
from pathlib import Path
import re
import subprocess
import time

import psutil

EVAL_RATE = re.compile(rb"\|\s+eval time\s*=\s*[\d.]+\s*ms /.*?([\d.]+)\s+tokens per second\)")


class PostToolLatency:
    """Time local model, tool, and rendering events without saving message content."""

    def __init__(self, path):
        self.path = path
        self.tool = None
        self.active_tools = {}
        self.turn = None
        self.stream = None
        self.compaction = None
        self.pending = []
        self.origin = time.time_ns(), time.perf_counter_ns()
        with path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps({'type': 'clock', 'unix_ns': self.origin[0], 'monotonic_ns': self.origin[1]}) + '\n')

    def observe(self, event):
        received = event['_received_ns']
        kind = event.get('type')
        if kind in ('agent_start', 'agent_settled', 'local_exit'):
            self.tool = None
            self.active_tools.clear()
            self.turn = self.stream = self.compaction = None
        elif kind == 'turn_start':
            self.turn = received
            self.stream = None
        elif kind == 'compaction_start':
            self.compaction = received
        elif kind == 'compaction_end' and self.compaction is not None:
            if event.get('aborted'):
                outcome = 'aborted'
            elif event.get('errorMessage'):
                outcome = 'failed'
            else:
                outcome = 'saved' if event.get('result') is not None else 'unsaved'
            self.pending.append({'type': 'compaction_interval', 'start_ns': self.compaction,
                                 'end_ns': received, 'outcome': outcome})
            self.compaction = None
        elif kind == 'tool_execution_start' and event.get('toolCallId'):
            self.active_tools[event['toolCallId']] = received
        elif kind == 'tool_execution_end':
            self.tool = received, event.get('toolName')
            call = event.get('toolCallId')
            started = self.active_tools.pop(call, None)
            if started is not None:
                self.pending.append({'type': 'tool_interval', 'call': call, 'tool': event.get('toolName'),
                                     'start_ns': started, 'end_ns': received, 'ok': not event.get('isError')})
        elif kind == 'message_update':
            delta = event.get('assistantMessageEvent') or {}
            if delta.get('type') in ('thinking_delta', 'text_delta', 'toolcall_delta') and delta.get('delta'):
                self.stream = (received if self.stream is None else self.stream[0], received)
            if (self.tool is not None and delta.get('type') in ('thinking_delta', 'text_delta')
                    and delta.get('delta')):
                finished, name = self.tool
                self.pending.append({'type': 'post_tool', 'tool': name, 'first_output': delta['type'],
                                     'tool_end_ns': finished, 'first_output_ns': received,
                                     'tool_result_to_output_ms': (received - finished) / 1_000_000})
                self.tool = None
        elif kind == 'message_end' and event.get('message', {}).get('role') == 'assistant':
            message = event['message']
            usage = message.get('usage') or {}
            if self.turn is not None and self.stream is not None and usage.get('output', 0) > 0:
                self.pending.append({'type': 'model_interval', 'turn_start_ns': self.turn,
                                     'first_token_ns': self.stream[0], 'last_token_ns': self.stream[1],
                                     'end_ns': received, 'input_tokens': usage.get('input', 0)
                                     + usage.get('cacheRead', 0) + usage.get('cacheWrite', 0),
                                     'output_tokens': usage['output'], 'stop_reason': message.get('stopReason')})
            self.turn = self.stream = None

    def sample(self, at, data):
        self.pending.append({'type': 'host_sample', 'at_ns': at, 'cpu_percent': data['cpu'],
                             'ram_percent': 100 * data['ram_used'] / data['ram_total'],
                             'slot': data['slot'], 'context_tokens': data.get('context_used'),
                             'max_context_tokens': data.get('context_max')})

    def flush(self):
        if not self.pending:
            return
        rendered = time.perf_counter_ns()
        with self.path.open('a', encoding='utf-8') as stream:
            for row in self.pending:
                if row['type'] == 'post_tool':
                    row['transport_to_tk_ms'] = (rendered - row['first_output_ns']) / 1_000_000
                stream.write(json.dumps(row) + '\n')
        self.pending.clear()


class Metrics:
    def __init__(self, server):
        self.server = server
        self.previous = None

    def read(self):
        ram = psutil.virtual_memory()
        result = {
            'ram_used': ram.total - ram.available,
            'ram_total': ram.total,
            'cpu': psutil.cpu_percent(interval=0.08),
            'slot': 'Unavailable',
            'gpus': [],
        }
        try:
            gpu = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.used,memory.total,memory.free,temperature.gpu,utilization.gpu',
                 '--format=csv,noheader,nounits'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            for row in csv.reader(gpu.stdout.splitlines(), skipinitialspace=True):
                if len(row) != 6:
                    continue
                values = [int(value) if value.strip().isdigit() else None for value in row[1:]]
                result['gpus'].append(dict(zip(('name', 'used', 'total', 'free', 'temperature', 'load'), [row[0], *values])))
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            slot, = self.server.request('/slots')
            active = bool(slot.get('is_processing'))
            decoded = (slot.get('next_token') or [{}])[0].get('n_decoded') or 0
            task = slot.get('id_task')
            now = time.monotonic()
            prompt = slot.get('n_prompt_tokens')
            result.update(slot='Busy' if active else 'Idle', context_max=slot.get('n_ctx'),
                          context_used=prompt + decoded if isinstance(prompt, int) else None)
            if active and self.previous:
                previous_task, previous_count, previous_time = self.previous
                if task == previous_task and decoded > previous_count > 0:
                    result['live_rate'] = (decoded - previous_count) / (now - previous_time)
            self.previous = (task, decoded, now) if active else None
        except (OSError, ValueError, RuntimeError):
            self.previous = None
        log = getattr(self.server, 'log_path', None)
        if log:
            try:
                with Path(log).open('rb') as file:
                    file.seek(max(0, file.seek(0, 2) - 65536))
                    rates = EVAL_RATE.findall(file.read())
                if rates:
                    result['last_rate'] = float(rates[-1])
            except OSError:
                pass
        return result
