"""Native Windows interface for the pinned local Pi agent."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import msvcrt
import os
from pathlib import Path
from queue import Empty, SimpleQueue
from subprocess import SubprocessError
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
import webbrowser

import psutil
from markdown_it import MarkdownIt
from pywintypes import com_error
from win32com.client import Dispatch

import pi_backend as backend
from job_recovery import Jobs, TERMINAL
from inspect_input import AV_EXT, IMAGE_EXT, audio_excerpt, picture
from runtime_metrics import Metrics, PostToolLatency
from prompt_clarification import ClarificationCard, PREFIX as CLARIFICATION_PREFIX, has_saved_clarification, save_answer, save_request
import context_switch

ASSETS = Path(__file__).resolve().parent
APP_USER_MODEL_ID = 'LocalPi.Windows'
WINDOW_ICON = ASSETS / 'pi-icon.ico'
BG = '#ffffff'
PANEL = '#f6f8fb'
FIELD = '#eef2f7'
LINE = '#dce3ed'
TEXT = '#202735'
MUTED = '#586678'
ACCENT = '#2459b8'
ERROR = '#a62b30'
SELECTED = '#dfeafa'
SUCCESS = '#26704d'
ACCENT_HOVER = '#17499a'
DISABLED = '#687689'
ON_ACCENT = '#fffffe'
DARK = {
    BG: '#101419', PANEL: '#171d25', FIELD: '#222b36', LINE: '#2e3947',
    TEXT: '#e4eaf3', MUTED: '#a9b8ca', ACCENT: '#92baff', ERROR: '#ff9095',
    SELECTED: '#2c405e', SUCCESS: '#8bd5ad', ACCENT_HOVER: '#aecbff',
    DISABLED: '#8999ad', ON_ACCENT: '#111b2c',
}
HERMES = {
    BG: '#fdfdfd', PANEL: '#f8f9fb', FIELD: '#f3f5f8', LINE: '#dce1e8',
    TEXT: '#22252c', MUTED: '#606976', ACCENT: '#1954d1', ERROR: '#a52d38',
    SELECTED: '#e4ecff', SUCCESS: '#266744', ACCENT_HOVER: '#1247b4',
    DISABLED: '#687282', ON_ACCENT: '#fffffe',
}
THEMES = {'light': {color: color for color in DARK}, 'dark': DARK, 'hermes': HERMES}
THEME_OPTIONS = ('background', 'foreground', 'insertbackground', 'selectbackground',
                 'selectforeground', 'highlightbackground', 'highlightcolor',
                 'activebackground', 'activeforeground', 'disabledforeground')
MARKDOWN = MarkdownIt('commonmark', {'html': False}).enable('table').enable('strikethrough')
SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
REVIEWING_INITIAL_PLAN = 'Reviewing the initial plan'
LIVE_MARKDOWN_LIMIT = 4096
TOOL_LABELS = {'powershell': 'PowerShell command', 'bash': 'Shell command', 'read': 'Read file',
               'write': 'Write file', 'edit': 'Edit file', 'grep': 'Search files', 'find': 'Find files',
               'update_plan': 'Update plan', 'review_initial_plan': 'Review initial plan',
               'find_skills': 'Search skills', 'use_skill': 'Load skill',
               'save_skill': 'Draft skill', 'publish_skill': 'Publish checked skill', 'prepare_prompt': 'Prepare brief',
               'run_script': 'Run script'}
BODY = ('Segoe UI', 11)
SMALL = ('Segoe UI', 10)
MONO = ('Cascadia Mono', 10)


def format_audio_evidence(filename, result):
    def level(value, relative=False):
        if value is None:
            return '—' if relative else 'digital silence'
        return f'{value:+.2f} dB' if relative else f'{value:.2f} dBFS'

    def reference(channels):
        return ', '.join(f'channel {channel}' for channel in channels) or 'none (digital silence)'

    def time_label(value):
        return f'{value:.6f}'.rstrip('0').rstrip('.')

    def transcript(estimate):
        text = (estimate.get('speech_text') or '').strip()
        if text:
            return text
        return {'analysis_signal_digital_silence': 'No words returned. The selected signal is digitally silent.',
                'not_requested': 'Transcription was not requested.'}.get(
                    estimate.get('transcription_status'), 'No words returned. Speech and overlap remain unverified.')

    start = result['start_seconds']
    source = f"channel {result['analysis_channel']}" if 'analysis_channel' in result else 'the mono mix'
    lines = [filename, f"{time_label(start)}–{time_label(result['end_seconds'])} s  ·  Sound candidates use {source}."]
    source_rate = result.get('source_sample_rate_hz')
    analysis_rate = result.get('analysis_sample_rate_hz')
    if source_rate and analysis_rate:
        lines.append(f'Source sample rate {source_rate:,} Hz  ·  Model input {analysis_rate:,} Hz')
    lines.extend(('', 'Decoded channel measurements', f"Peak reference: {reference(result['peak_reference_channels'])}",
                  f"RMS reference: {reference(result['rms_reference_channels'])}"))
    for channel, span in zip(result['channels'], result['decoded_nonzero_spans_seconds_from_excerpt_start'], strict=True):
        peak, rms = (level(channel[f'{kind}_dbfs']) for kind in ('peak', 'rms'))
        peak_delta, rms_delta = (level(channel[f'{kind}_relative_to_loudest_channel_db'], relative=True)
                                 for kind in ('peak', 'rms'))
        lines.append(f"Channel {channel['channel']}  Peak {peak} ({peak_delta})  ·  RMS {rms} ({rms_delta})")
        if span:
            first, end = (time_label(start + offset) for offset in span)
            lines.append(f'    Decoded nonzero envelope {first}–{end} s (exclusive end)')
    if 'decoded_stereo_channels_identical' in result:
        difference = 'identical' if result['decoded_stereo_channels_identical'] else 'different'
        lines.append(f'Decoded stereo waveforms are {difference} in this window.')
    lines.extend(('', 'Recording setup: unknown from the audio.', '',
                  'Sound candidates (peak classifier scores)'))
    for signal in (result, *result.get('channel_sound_events', ())):
        if signal is not result:
            lines.extend(('', f"Sound candidates for channel {signal['channel']}"))
        lines.extend(f"{hint['label']}  {hint['score']:.4f}" for hint in signal['sound_event_hints'])
        if not signal['sound_event_hints']:
            lines.append('No candidates returned.')
        for window in signal.get('sound_event_time_windows', ()):
            first, end = map(time_label, window['window_seconds'])
            hints = ', '.join(f"{hint['label']} {hint['score']:.4f}" for hint in window['hints'])
            lines.append(f'{first}–{end} s  ·  {hints or "No candidates returned."}')
    def add_transcript(heading, estimate):
        lines.extend(('', heading, transcript(estimate)))
        span = estimate.get('estimated_word_span_seconds_from_excerpt_start')
        if span:
            first, end = (time_label(start + offset) for offset in span)
            lines.append(f'    Estimated first-to-last word range {first}–{end} s. Gaps may occur within it.')
        status = estimate.get('word_timing_status')
        if status == 'reestimated_on_decoded_activity':
            lines.append('    Timing re-estimated within the decoded activity window.')
        elif status == 'inconsistent_with_decoded_activity':
            lines.append('    Word timing remains unresolved after comparison with decoded activity.')
        if estimate.get('word_recognition_disagreement'):
            lines.append('    The full and activity-window passes disagree on some words.')

    for estimate in result.get('channel_transcripts', ()):
        add_transcript(f"Estimated transcript for channel {estimate['channel']}", estimate)
    add_transcript(f'Estimated transcript using {source}', result)
    return '\n'.join(lines)


class App:
    def __init__(self, root, server, workspace, state, watch=None, browser_only=False, evidence=None,
                 recover_jobs=False, allow_wide_context=False, latency_trace=None, exit_after_job=False):
        self.root = root
        self.server = server
        self.workspace = workspace
        self.state = state
        self.watch = watch
        self.external_watch = watch
        self.browser_only = browser_only
        self.evidence = evidence
        self.latency = PostToolLatency(latency_trace) if latency_trace is not None else None
        self.exit_after_job = exit_after_job
        self.jobs = Jobs(state) if recover_jobs else None
        self.allow_wide_context = allow_wide_context
        self.job = None
        self.starting_backend = False
        self.queued_payload = None
        self.resume_payload = None
        self.recovery_wait = False
        self.rpc = None
        self.rpc_marker = None
        self.pending = None
        self.clarification = None
        self.pending_prompt = None
        self.active = bool(watch and watch.active())
        self.clock = (watch.started
                      if watch else None)
        self.elapsed = None
        self.tasks = {}
        self.tool_cards = {}
        self.tool_updates = set()
        self.running_tools = set()
        self.compactions = 0
        self.plan_steps = []
        self.plan_reason = ''
        self.plan_review_pending = False
        self.attachments = []
        self.audio_report_window = None
        self.history = []
        self.visible_chats = []
        self.history_rows = {}
        self.last_answer = ''
        self.settings_path = state / 'gui-settings.json'
        self.preferences = {}
        self.pinned_chats = set()
        try:
            settings = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(settings, dict):
                self.preferences = settings
        except (OSError, ValueError):
            pass
        level = self.preferences.get('thinking')
        self.thinking = level if level in ('off', 'low', 'medium', 'high') else 'medium'
        theme = self.preferences.get('theme')
        self.theme = 'light'
        self.theme_choice = tk.StringVar(value=theme if isinstance(theme, str) and theme in THEMES else self.theme)
        self.show_reasoning = tk.BooleanVar(value=self.preferences.get('show_reasoning', True) is not False)
        self.settings_window = None
        self.reasoning_choices = []
        try:
            pinned = json.loads((state / 'pinned-chats.json').read_text(encoding='utf-8'))
            if isinstance(pinned, list):
                self.pinned_chats = {item for item in pinned if isinstance(item, str)}
        except (OSError, ValueError):
            pass
        self.metrics = Metrics(server)
        self.streamed = False
        self.stream_thoughts = {}
        self.stream_thought_chunks = {}
        self.stream_preview = ''
        self.stream_preview_dirty = False
        self.stream_preview_limit = False
        self.thought_cards = {}
        self.reply_links = []
        self.reply_actions = {}
        self.voice = None
        self.chat_following = True
        self.last_usage = None
        self.queue = SimpleQueue()
        self.slot_text = tk.StringVar(value='Checking model slot…')
        self.activity_indicator = tk.StringVar()
        self.status = tk.StringVar(value='Watching image test' if watch else 'Ready')
        self.info = tk.StringVar()
        self.attachment_label = tk.StringVar()
        self.chat_title = tk.StringVar(value='New chat')
        self.workspace_title = tk.StringVar(value=workspace.name or str(workspace))
        self.thinking_label = tk.StringVar(value=self.thinking.title())
        self.root.bind('<Map>', self._map_caption, add='+')
        self._build()
        self._apply_theme(self.theme_choice.get())
        self._controls()
        self._refresh_history()
        self.root.after(30, self._poll)
        self.root.after(100, self._read_slot)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if self.jobs:
            self.root.after(150, self._recover_job)

    def _style(self, palette):
        bg, panel, field, line, text, muted, accent, selected, disabled, hover, on_accent = (
            palette[color] for color in (BG, PANEL, FIELD, LINE, TEXT, MUTED, ACCENT, SELECTED,
                                         DISABLED, ACCENT_HOVER, ON_ACCENT))
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Pi.TButton', background=field, foreground=text, bordercolor=line,
                        lightcolor=field, darkcolor=field, focuscolor=accent, padding=(12, 7), font=SMALL)
        style.map('Pi.TButton', background=[('active', selected)], foreground=[('disabled', disabled)])
        style.configure('Send.TButton', background=accent, foreground=on_accent, bordercolor=accent,
                        lightcolor=accent, darkcolor=accent, focuscolor=on_accent, padding=(15, 8),
                        font=('Segoe UI Semibold', 11))
        style.map('Send.TButton', background=[('disabled', field), ('active', hover)],
                  foreground=[('disabled', disabled)])
        style.configure('Pi.TRadiobutton', background=panel, foreground=text, bordercolor=line,
                        indicatorbackground=field, indicatorforeground=accent, focuscolor=accent,
                        padding=(5, 4), font=SMALL)
        style.map('Pi.TRadiobutton', background=[('active', selected)], foreground=[('disabled', disabled)],
                  indicatorbackground=[('selected', accent)], indicatorforeground=[('selected', on_accent)])
        style.configure('Clarification.TFrame', background=panel, bordercolor=line, relief='solid', borderwidth=1)
        style.configure('Clarification.TLabel', background=panel, foreground=text, font=SMALL)
        style.configure('Clarification.TEntry', fieldbackground=bg, foreground=text, bordercolor=line,
                        lightcolor=line, darkcolor=line, insertcolor=text, padding=(7, 5))
        style.configure('ClarificationChoice.TButton', background=field, foreground=text, bordercolor=line,
                        lightcolor=field, darkcolor=field, focuscolor=accent, anchor='w', padding=(8, 5), font=SMALL)
        style.map('ClarificationChoice.TButton', background=[('active', selected)])
        style.configure('Pi.TCheckbutton', background=panel, foreground=text, indicatorbackground=field,
                        indicatorforeground=accent, focuscolor=accent, padding=(5, 4), font=SMALL)
        style.map('Pi.TCheckbutton', background=[('active', selected)],
                  indicatorbackground=[('selected', accent)], indicatorforeground=[('selected', on_accent)])
        style.configure('Pi.Treeview', background=panel, fieldbackground=panel, foreground=text,
                        bordercolor=line, rowheight=29, font=SMALL)
        style.configure('Pi.Treeview.Heading', background=field, foreground=muted,
                        bordercolor=line, lightcolor=field, darkcolor=field, font=('Segoe UI Semibold', 9))
        style.map('Pi.Treeview', background=[('selected', selected)], foreground=[('selected', text)])
        style.configure('Pi.TNotebook', background=panel, bordercolor=line, lightcolor=panel,
                        darkcolor=panel, borderwidth=0)
        style.configure('Pi.TNotebook.Tab', background=panel, foreground=muted, bordercolor=line,
                        lightcolor=panel, darkcolor=panel, padding=(13, 10), font=SMALL)
        style.map('Pi.TNotebook.Tab', background=[('selected', field), ('active', selected)],
                  foreground=[('selected', accent)], lightcolor=[('selected', line), ('!selected', line)])
        style.configure('Runtime.Horizontal.TProgressbar', background=accent, troughcolor=field,
                        lightcolor=accent, darkcolor=accent, bordercolor=panel, thickness=5)
        style.configure('Pi.Vertical.TScrollbar', background=field, troughcolor=bg, bordercolor=bg,
                        lightcolor=field, darkcolor=field, arrowcolor=muted, width=11)
        style.map('Pi.Vertical.TScrollbar', background=[('disabled', field), ('active', selected)],
                  arrowcolor=[('disabled', disabled), ('!disabled', muted)])

    def _apply_theme(self, theme):
        previous, palette = THEMES[self.theme], THEMES[theme]
        recolor = {previous[color]: palette[color] for color in palette}
        self.theme = theme
        self._style(palette)
        widgets = [self.root]
        while widgets:
            widget = widgets.pop()
            widgets.extend(widget.winfo_children())
            options = set(widget.keys()).intersection(THEME_OPTIONS)
            changes = {option: recolor[value] for option in options
                       if (value := str(widget.cget(option))) in recolor and recolor[value] != value}
            if changes:
                widget.configure(**changes)
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                widget.after_idle(lambda window=widget: self._color_caption(window))
        for widget in (self.chat, self.plan):
            for tag in widget.tag_names():
                for option in ('foreground', 'background'):
                    value = str(widget.tag_cget(tag, option))
                    if value in recolor and recolor[value] != value:
                        widget.tag_configure(tag, **{option: recolor[value]})
        self.chat.tag_configure('user', justify='left' if theme == 'hermes' else 'right')
        self.chat.tag_configure('user_message', justify='left' if theme == 'hermes' else 'right',
                                lmargin1=13 if theme == 'hermes' else 40,
                                lmargin2=13 if theme == 'hermes' else 40)
        self.activity.tag_configure('failed', foreground=palette[ERROR])
        self.activity.tag_configure('working', foreground=palette[ACCENT])
        for row in range(self.chat_list.size()):
            if row not in self.history_rows:
                self.chat_list.itemconfigure(row, foreground=palette[MUTED])

    def _map_caption(self, event):
        if event.widget is self.root:
            self.root.after_idle(lambda: self._color_caption(self.root))

    def _color_caption(self, window):
        if not window.winfo_exists():
            return
        # DWM caption and text colors follow the Pi preference independently of the OS theme.
        palette = THEMES[self.theme]
        hwnd = ctypes.c_void_p(int(window.wm_frame(), 0))
        for attribute, color in ((35, palette[PANEL]), (36, palette[TEXT])):
            value = int.from_bytes(bytes.fromhex(color[1:]), 'little') if self.theme == 'dark' else 0xffffffff
            color_ref = ctypes.c_uint32(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(color_ref), ctypes.sizeof(color_ref))

    def _build(self):
        self.root.title('Pi · Local Qwen')
        screen_width, screen_height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(1400, round(screen_width * .94))
        height = min(865, round(screen_height * .88))
        self.root.geometry(f'{width}x{height}+{(screen_width - width) // 2}+20')
        self.root.minsize(min(1030, width), min(660, height))
        self.root.configure(bg=BG)

        self.panes = panes = tk.PanedWindow(self.root, orient='horizontal', bg=LINE, bd=0, sashwidth=3)
        panes.pack(fill='both', expand=True)
        sidebar = tk.Frame(panes, width=240, bg=PANEL)
        center = tk.Frame(panes, bg=BG)
        inspector = tk.Frame(panes, width=335, bg=PANEL)
        self.sidebar, self.center, self.inspector = sidebar, center, inspector
        panes.add(sidebar, minsize=180, width=225, stretch='never')
        panes.add(center, minsize=470, stretch='always')
        panes.add(inspector, minsize=280, width=340, stretch='never')

        logo = tk.PhotoImage(file=ASSETS / 'pi-icon.png')
        self.brand_icon = logo.subsample(6)
        self.root.iconbitmap(default=str(WINDOW_ICON))
        self.root.iconbitmap(str(WINDOW_ICON))
        tk.Label(sidebar, text='Pi', image=self.brand_icon, compound='left', bg=PANEL, fg=TEXT,
                 font=('Segoe UI Semibold', 25), padx=16, pady=13, anchor='w').pack(fill='x')
        self._button(sidebar, '+   New chat', self.new_chat).pack(fill='x', padx=14, pady=(0, 10))
        self.root.bind('<Control-n>', lambda _: self.new_chat())
        self.search = tk.StringVar()
        search_box = tk.Entry(sidebar, textvariable=self.search, bg=FIELD, fg=TEXT, insertbackground=ACCENT,
                              selectbackground=SELECTED, selectforeground=TEXT,
                              relief='flat', font=SMALL)
        tk.Label(sidebar, text='Search chats', bg=PANEL, fg=MUTED, font=SMALL, padx=15).pack(anchor='w')
        search_box.pack(fill='x', padx=14, ipady=8, pady=(4, 12))
        self.search.trace_add('write', lambda *_: self._show_history())
        self.root.bind('<Control-k>', lambda _: search_box.focus_set())
        self.change_folder = self._button(sidebar, 'Workspace', self.choose_folder)
        self.change_folder.pack(fill='x', padx=14, pady=(0, 12))
        tk.Frame(sidebar, bg=LINE, height=1).pack(fill='x', padx=14)
        history = tk.Frame(sidebar, bg=PANEL)
        history.pack(fill='both', expand=True, padx=9, pady=(7, 0))
        self.chat_list = tk.Listbox(history, bg=PANEL, fg=TEXT, font=SMALL, relief='flat',
                                    highlightthickness=0, selectbackground=SELECTED, selectforeground=TEXT, activestyle='none')
        chat_scroll = ttk.Scrollbar(history, orient='vertical', command=self.chat_list.yview,
                                    style='Pi.Vertical.TScrollbar')
        self.chat_list.configure(yscrollcommand=chat_scroll.set)
        chat_scroll.pack(side='right', fill='y')
        self.chat_list.pack(fill='both', expand=True)
        self.chat_list.bind('<Double-Button-1>', self.resume_chat)
        self.chat_list.bind('<Return>', self.resume_chat)
        self.chat_list.bind('<Button-3>', self._history_menu)
        self.chat_list.bind('<Shift-F10>', self._history_menu)
        rail = tk.Frame(sidebar, bg=PANEL, padx=14, pady=13)
        rail.pack(fill='x')
        self._button(rail, 'Settings', self.settings).pack(fill='x')

        header = tk.Frame(center, bg=BG, padx=18, pady=10)
        header.pack(fill='x')
        self._button(header, 'Chats', self.toggle_sidebar).pack(side='left')
        self._button(header, 'Inspector', self.toggle_inspector).pack(side='right')
        self.branch_button = self._button(header, 'Branch…', self._choose_branch)
        self.branch_button.pack(side='right', padx=(0, 8))
        self._button(header, 'Files', self.show_files).pack(side='right', padx=6)
        title = tk.Frame(header, bg=BG)
        title.pack(side='left', padx=12, fill='x', expand=True)
        tk.Label(title, textvariable=self.chat_title, bg=BG, fg=TEXT, anchor='w',
                 font=('Segoe UI Semibold', 11)).pack(fill='x')
        tk.Label(title, textvariable=self.workspace_title, bg=BG, fg=MUTED, font=SMALL, anchor='w').pack(fill='x')
        tk.Frame(center, bg=LINE, height=1).pack(fill='x')
        self.chat = self._scrolled_text(center, BODY, 10, surface=BG, on_scroll=self._chat_scrolled)
        for key in ('<MouseWheel>', '<Prior>', '<Next>', '<Control-Home>', '<Control-End>'):
            self.chat.bind(key, lambda _event: self.root.after_idle(self._chat_scrolled))
        self.chat.tag_configure('user', foreground=ACCENT, font=('Segoe UI Semibold', 10), spacing1=16,
                                justify='right', rmargin=19)
        self.chat.tag_configure('user_message', foreground=TEXT, background=FIELD, justify='right',
                                lmargin1=40, lmargin2=40, rmargin=19, spacing1=7, spacing3=9)
        self.chat.tag_configure('assistant', foreground=MUTED, font=('Segoe UI Semibold', 10), spacing1=9, lmargin1=13)
        self.chat.tag_configure('answer', foreground=TEXT, lmargin1=13, lmargin2=13, rmargin=15, spacing2=4)
        self.chat.tag_configure('code', foreground=TEXT, background=PANEL, font=MONO,
                                lmargin1=24, lmargin2=24, rmargin=15, spacing2=2)
        self.chat.tag_configure('heading', foreground=TEXT, font=('Segoe UI Semibold', 13), lmargin1=13, spacing1=7)
        self.chat.tag_configure('inline_code', font=MONO, background=FIELD)
        self.chat.tag_configure('strong', font=('Segoe UI Semibold', 11))
        self.chat.tag_configure('em', font=('Segoe UI', 11, 'italic'))
        self.chat.tag_configure('strike', overstrike=True)
        self.chat.tag_configure('link', foreground=ACCENT, underline=True)
        self.chat.tag_configure('reply_action', foreground=ACCENT, font=SMALL, spacing1=5, spacing3=3, lmargin1=13)
        self.chat.tag_configure('quote', foreground=MUTED, lmargin1=28, lmargin2=28)
        self.chat.tag_configure('table', background=PANEL, font=MONO, lmargin1=16, lmargin2=16)
        self.chat.tag_configure('thought_label', foreground=ACCENT, font=SMALL, lmargin1=13, spacing1=6)
        self.chat.tag_configure('thought_text', foreground=MUTED, background=PANEL,
                                lmargin1=27, lmargin2=27, rmargin=15, spacing2=2)
        self.chat.tag_configure('event', foreground=MUTED, font=SMALL, lmargin1=13, spacing1=8)
        for state, color in [('running', ACCENT), ('done', MUTED), ('failed', ERROR)]:
            self.chat.tag_configure('tool_' + state, foreground=color, font=SMALL, lmargin1=14, spacing1=4)
        self.chat.tag_configure('tool_body', foreground=TEXT, background=PANEL, font=MONO,
                                lmargin1=28, lmargin2=28, rmargin=18, spacing2=2)
        self.chat.bind('<Return>', self._toggle_focused_tool)
        self.chat.tag_configure('error', foreground=ERROR, font=SMALL, lmargin1=13, spacing1=8)

        self.composer = compose = tk.Frame(center, bg=BG, padx=11, pady=8, highlightbackground=LINE,
                                           highlightcolor=ACCENT, highlightthickness=1)
        compose.pack(fill='x', padx=20, pady=(4, 8))
        self.prompt = tk.Text(compose, height=3, bg=BG, fg=TEXT, insertbackground=ACCENT,
                             selectbackground=SELECTED, selectforeground=TEXT,
                             wrap='word', bd=0, padx=5, pady=6, font=BODY, undo=True)
        self.prompt.pack(fill='x', pady=(0, 4))
        self.prompt.bind('<Control-Return>', lambda _: (self.send(), 'break')[1])
        self.prompt_hint = tk.Label(self.prompt, text='Ask Pi to work in this workspace', bg=BG, fg=MUTED, font=BODY)
        self.prompt_hint.place(x=4, y=4)
        self.prompt_hint.bind('<Button-1>', lambda _: self.prompt.focus_set())
        self.prompt.bind('<FocusIn>', self._composer_hint)
        self.prompt.bind('<FocusOut>', self._composer_hint)
        actions = tk.Frame(compose, bg=BG)
        actions.pack(fill='x')
        self.send_button = self._button(actions, 'Send  ↑', self.send, 'Send.TButton')
        self.send_button.pack(side='right')
        self.stop_button = self._button(actions, 'Stop', self.stop)
        self.stop_button.pack(side='right', padx=7)
        self.thinking_button = ttk.Button(actions, textvariable=self.thinking_label, style='Pi.TButton',
                                          command=self.settings)
        self.thinking_button.pack(side='right', padx=(3, 0))
        self.attach_button = self._button(actions, '+ Attach', self.attach)
        self.attach_button.pack(side='left')
        self.clear_button = self._button(actions, 'Clear', self.clear_attachments)
        self.clear_button.pack(side='left', padx=5)
        if not (self.browser_only or self.evidence or self.watch):
            self._button(actions, 'Audio report', self.open_audio_report).pack(side='left')
        self.chat_activity = tk.Label(actions, textvariable=self.activity_indicator, bg=BG, fg=ACCENT,
                                      anchor='w', width=1, font=SMALL)
        self.chat_activity.pack(side='left', fill='x', expand=True, padx=4)
        self.attached_files = tk.Label(compose, textvariable=self.attachment_label, bg=BG, fg=MUTED,
                                      font=SMALL, anchor='w')
        footer = tk.Frame(center, bg=BG, padx=20, pady=1)
        footer.pack(fill='x', side='bottom', padx=0, pady=(0, 8))
        tk.Label(footer, text='Qwen3.8-27B-Uncensored', bg=BG, fg=TEXT, font=SMALL).pack(side='left')
        tk.Label(footer, textvariable=self.slot_text, bg=BG, fg=ACCENT, font=SMALL).pack(side='left', padx=8)
        self._button(footer, 'Copy reply', self.copy_reply).pack(side='right')
        self._button(footer, 'Latest ↓', self._show_latest).pack(side='right', padx=6)

        self.book = book = ttk.Notebook(inspector, style='Pi.TNotebook')
        book.pack(fill='both', expand=True, padx=5)
        overview = tk.Frame(book, bg=PANEL)
        log = tk.Frame(book, bg=PANEL)
        skill_page = tk.Frame(book, bg=PANEL)
        book.add(overview, text='Plan & Runtime')
        book.add(log, text='Activity')
        book.add(skill_page, text='Skills')
        self.files_page = tk.Frame(book, bg=PANEL)
        book.add(self.files_page, text='Files')
        self._build_files()
        self._section(skill_page, 'Active skill')
        self.active_skill = tk.StringVar(value='Awaiting task')
        tk.Label(skill_page, textvariable=self.active_skill, bg=PANEL, fg=ACCENT,
                 font=BODY, anchor='w', padx=14, pady=5).pack(fill='x')
        self._button(skill_page, 'Open skill library', self.open_skill_library).pack(anchor='w', padx=14, pady=6)
        self.skill_log = self._scrolled_text(skill_page, BODY, 10, expand=True)
        self._section(overview, 'Plan')
        self.plan = self._scrolled_text(overview, BODY, 9, expand=True)
        self.plan.tag_configure('completed', foreground=SUCCESS, spacing1=5)
        self.plan.tag_configure('in_progress', foreground=ACCENT, font=('Segoe UI Semibold', 11), spacing1=5)
        self.plan.tag_configure('pending', foreground=MUTED, spacing1=5)
        self.plan.tag_configure('reason', foreground=MUTED, font=SMALL, spacing1=9)
        self._write(self.plan, 'Pi will post a plan when work starts.', 'pending')
        self._section(overview, 'Runtime')
        self.runtime_status = tk.StringVar(value='Waiting for local metrics')
        tk.Label(overview, textvariable=self.runtime_status, fg=MUTED, bg=PANEL,
                 font=SMALL, anchor='w', padx=14, pady=5).pack(fill='x')
        self.metrics_rows = {}
        for key, title in [('vram', 'GPU memory'), ('gpu', 'GPU temperature / load'),
                           ('cpu', 'CPU utilization'), ('ram', 'System RAM'),
                           ('context', 'Context window'), ('speed', 'Shared model speed')]:
            row = tk.Frame(overview, bg=PANEL, padx=14, pady=4)
            row.pack(fill='x')
            top = tk.Frame(row, bg=PANEL)
            top.pack(fill='x')
            tk.Label(top, text=title, bg=PANEL, fg=TEXT, font=SMALL, anchor='w').pack(side='left')
            value = tk.StringVar(value='—')
            tk.Label(top, textvariable=value, bg=PANEL, fg=MUTED, font=SMALL, anchor='e').pack(side='right')
            meter = ttk.Progressbar(row, maximum=100, style='Runtime.Horizontal.TProgressbar')
            if key != 'speed':
                meter.pack(fill='x', pady=(4, 0))
            self.metrics_rows[key] = value, meter

        summary = tk.Frame(log, bg=PANEL, padx=14, pady=11)
        summary.pack(fill='x')
        tk.Label(summary, textvariable=self.status, bg=PANEL, fg=ACCENT, font=('Segoe UI Semibold', 13)).pack(anchor='w')
        tk.Label(summary, textvariable=self.info, bg=PANEL, fg=MUTED, font=SMALL,
                 justify='left').pack(anchor='w', pady=(3, 3))
        table = tk.Frame(log, bg=PANEL)
        table.pack(fill='both', expand=True, padx=12, pady=(3, 9))
        self.activity = ttk.Treeview(table, columns=('tool', 'status', 'time'), show='headings', style='Pi.Treeview')
        for col, title, width, stretch in [('tool', 'Tool', 143, True), ('status', 'State', 61, False), ('time', 'Time', 62, False)]:
            self.activity.heading(col, text=title, anchor='w')
            self.activity.column(col, width=width, minwidth=50, stretch=stretch)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.activity.yview, style='Pi.Vertical.TScrollbar')
        self.activity.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.activity.pack(fill='both', expand=True)
        self.activity.bind('<<TreeviewSelect>>', self._selected)
        self.activity.tag_configure('failed', foreground=ERROR)
        self.activity.tag_configure('working', foreground=ACCENT)
        self._section(log, 'Tool details')
        self.details = self._scrolled_text(log, MONO, 7, expand=False)

    def _button(self, frame, name, command, style='Pi.TButton'):
        return ttk.Button(frame, text=name, style=style, command=command)

    def _section(self, frame, title):
        tk.Label(frame, text=title, bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 12),
                 padx=14, pady=10, anchor='w').pack(fill='x')
        tk.Frame(frame, bg=LINE, height=1).pack(fill='x')

    def _scrolled_text(self, frame, font, height, expand=True, surface=PANEL, on_scroll=None):
        wrap = tk.Frame(frame, bg=surface)
        wrap.pack(fill='both', expand=expand, padx=12, pady=8)
        widget = tk.Text(wrap, bg=surface, fg=TEXT, font=font, height=height, wrap='word',
                         bd=0, state='disabled', padx=3, pady=3, selectbackground=SELECTED, selectforeground=TEXT)
        def scroll_to(*args):
            widget.yview(*args)
            if on_scroll:
                on_scroll()
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=scroll_to, style='Pi.Vertical.TScrollbar')
        widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        widget.pack(fill='both', expand=True)
        return widget

    def _write(self, widget, text, tag=(), replace=False):
        chat = widget is self.chat
        near_end = self.chat_following if chat else widget.yview()[1] > 0.96
        widget.configure(state='normal')
        if replace:
            widget.delete('1.0', 'end')
        widget.insert('end', text, tag)
        if near_end and not replace:
            if chat:
                widget.yview('end')
            else:
                widget.see('end')
        widget.configure(state='disabled')

    def _chat_scrolled(self):
        self.chat_following = self.chat.yview()[1] >= 0.99

    def _show_latest(self):
        self.chat_following = True
        self.chat.see('end')

    def _controls(self):
        editing = not (self.active or self.pending or self.watch or self.recovery_wait or self.starting_backend)
        self.send_button.configure(state='normal' if editing else 'disabled')
        self.change_folder.configure(state='normal' if editing and not self.evidence else 'disabled')
        self.branch_button.configure(state='normal' if editing and self.rpc and not self.evidence else 'disabled')
        self.stop_button.configure(state='normal' if self.active and self.rpc or self.recovery_wait else 'disabled')
        self.attach_button.configure(state='normal' if editing and not self.evidence else 'disabled')
        self.clear_button.configure(state='normal' if editing and self.attachments else 'disabled')
        self.thinking_button.configure(state='normal' if editing else 'disabled')
        if self.settings_window and self.settings_window.winfo_exists():
            for button in self.reasoning_choices:
                button.configure(state='normal' if editing else 'disabled')
            self.unload_button.configure(state='normal' if editing and not self.evidence else 'disabled')

    def _composer_hint(self, event):
        if event.type == tk.EventType.FocusOut and not self.prompt.get('1.0', 'end-1c'):
            self.prompt_hint.place(x=4, y=4)
        else:
            self.prompt_hint.place_forget()

    def _read_slot(self):
        def check():
            data = self.metrics.read()
            self.queue.put({'type': 'local_metrics', 'data': data, 'sampled_ns': time.perf_counter_ns()})
        threading.Thread(target=check, daemon=True).start()
        self.root.after(3500, self._read_slot)

    def _poll(self):
        if self.watch:
            for event in self.watch.read():
                self._event(event, replay=True)
        deadline = time.perf_counter() + 0.012
        for _ in range(450):
            try:
                self._event(self.queue.get_nowait())
            except Empty:
                break
            if time.perf_counter() >= deadline:
                break
        self._render_stream_thoughts()
        self._render_stream_preview()
        if self.latency:
            try:
                self.latency.flush()
            except OSError as error:
                self.latency = None
                self._write(self.chat, f'\nLatency trace stopped: {error}\n', 'error')
        if self.tool_updates:
            for key in self.tool_updates:
                self._render_tool(key)
            selection = self.activity.selection()
            if selection and selection[0] in self.tool_updates:
                self._selected()
            self.tool_updates.clear()
        duration = self.elapsed if self.elapsed is not None else (time.time() - self.clock if self.clock else 0)
        mins, secs = divmod(max(0, int(duration)), 60)
        details = f'{mins:02d}:{secs:02d} elapsed  ·  {len(self.tasks)} tool calls'
        if self.watch:
            details += '\nImage test · read-only'
        if self.compactions:
            details += f'\n{self.compactions} compaction(s)'
        if self.last_usage:
            details += f'\n{self.last_usage:,} tokens in latest model call'
        self.info.set(details)
        self.runtime_status.set(f'{self.status.get()}  ·  {mins:02d}:{secs:02d}  ·  {len(self.tasks)} tools')
        phase = self.status.get()
        animation = f'{SPINNER[int(time.monotonic() * 8) % len(SPINNER)]}  {phase}' if self.active else ''
        if self.activity_indicator.get() != animation:
            self.activity_indicator.set(animation)
        self._controls()
        self.root.after(1 if not self.queue.empty() else 65, self._poll)

    def _event(self, e, replay=False):
        if '_transport' in e and e['_transport'] is not self.rpc_marker:
            return
        if self.latency and '_received_ns' in e:
            self.latency.observe(e)
        if self.evidence and '_transport' in e:
            event = {key: value for key, value in e.items() if key != '_transport'}
            with (self.evidence / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n')
        kind = e.get('type')
        if kind == 'extension_ui_request' and str(e.get('title', '')).startswith(CLARIFICATION_PREFIX):
            self._show_clarification(e)
        elif kind == 'local_metrics':
            self._runtime(e['data'])
            if self.latency and self.active and 'sampled_ns' in e:
                self.latency.sample(e['sampled_ns'], e['data'])
        elif kind == 'local_history':
            self.history = e['data']
            self._show_history()
        elif kind == 'local_warning' and e.get('text'):
            self._write(self.chat, '\n' + e['text'] + '\n', 'error')
        elif (kind == 'extension_error' and self.job and self.recovery_wait
              and e.get('extensionPath') == 'command:local-pi-recover'):
            self._pause_recovery(e.get('error') or 'Pi refused the recovery command.')
        elif kind == 'native_backend':
            self.starting_backend = False
            retry = e['retry']
            if e.get('server') is not None:
                self.server = self.metrics.server = e['server']
            if retry is not None:
                self.prompt.configure(state='normal')
                self.status.set('Ready')
                if e.get('error'):
                    self._write(self.chat, '\n' + e['error'] + '\n', 'error')
                else:
                    retry()
            elif e.get('error'):
                self._pause_recovery(e['error'])
            else:
                self._recover_job()
        elif kind == 'native_unloaded':
            self.starting_backend = False
            if e.get('error'):
                self.status.set(e['previous_status'])
                self._write(self.chat, '\n' + e['error'] + '\n', 'error')
            else:
                self.server = self.metrics.server = e['server']
                self.status.set('Local model unloaded')
        elif kind == 'context_profile':
            self.starting_backend = False
            if e.get('server') is not None:
                self.server = self.metrics.server = e['server']
            if e.get('error'):
                self._pause_recovery(e['error'])
            elif e['restore']:
                if e.get('server') is None:
                    self.status.set(e['status'])
                    self.root.after(2000, self._recover_job)
                else:
                    self.recovery_wait = False
                    self.status.set(e['status'])
            else:
                note = 'Pi switched to 128k context and is opening the same chat.'
                if e.get('fallback'):
                    note = 'Pi restored 64k after the 128k launch failed. ' + e['fallback']
                self._write(self.chat, '\n' + note + '\n', 'event')
                self._recover_job()
        elif kind == 'local_exit':
            if not self.job:
                self._restore_pending_prompt()
                self.queued_payload = None
            self.pending = self.rpc = None
            self.rpc_marker = None
            if self.active or e['code']:
                self._finish('Pi exited')
                self._write(self.chat, f'\nPi process exited with code {e["code"]}.\n', 'error')
            if self.job:
                self.queued_payload = self.resume_payload = self.pending_prompt = None
                self.recovery_wait = True
                self.root.after(200, self._recover_job)
        elif kind == 'watch_end':
            if self.active:
                self._finish('Image test exited')
            if self.jobs:
                self.root.after(100, self._recover_job)
        elif kind == 'response':
            if e.get('id') == self.pending:
                self.pending = None
                if not e.get('success'):
                    self._restore_pending_prompt()
                self.pending_prompt = None
                if self.jobs and self._recovery_response(e):
                    return
                if e.get('success') and e.get('command') == 'get_fork_messages':
                    self._show_branch_messages((e.get('data') or {}).get('messages') or [])
                if e.get('success') and e.get('command') == 'fork':
                    data = e.get('data') or {}
                    if not data.get('cancelled'):
                        self._reset()
                        self.prompt.delete('1.0', 'end')
                        self.prompt.insert('1.0', data.get('text') or '')
                        self.pending = self.rpc.send('get_messages')
                        self.status.set('Opening branch')
                        self._refresh_history()
                if e.get('success') and e.get('command') == 'switch_session':
                    if (e.get('data') or {}).get('cancelled'):
                        self.status.set('Session switch canceled')
                    else:
                        self.pending = self.rpc.send('get_messages')
                        self.status.set('Loading chat')
                if e.get('success') and e.get('command') == 'get_messages':
                    for message in (e.get('data') or {}).get('messages', []):
                        self.streamed = False
                        if message.get('role') == 'toolResult':
                            self._chat_tool_result(message.get('toolCallId', ''), message.get('toolName', 'Tool'),
                                                   message, bool(message.get('isError')))
                            if not message.get('isError'):
                                details = message.get('details') or {}
                                if message.get('toolName') in ('update_plan', 'review_initial_plan'):
                                    self._apply_plan(details)
                                elif details.get('skillEvent'):
                                    self._apply_skill(details)
                                    answers = details.get('answers')
                                    if details['skillEvent'] == 'brief' and isinstance(answers, list):
                                        for answer in answers:
                                            if isinstance(answer, dict) and all(isinstance(answer.get(key), str)
                                                                               for key in ('question', 'answer')):
                                                self._show_clarified_answer(answer['question'], answer['answer'])
                        else:
                            self._message(message)
                            for item in message.get('content') or []:
                                if isinstance(item, dict) and item.get('type') == 'toolCall':
                                    self._chat_tool_call(item.get('id', ''), item.get('name', 'Tool'),
                                                         item.get('arguments', {}))
                    if self.resume_payload is not None:
                        if self.resume_payload['message'] == f"/local-pi-recover {self.job['id']}":
                            self.pending = self.rpc.send('get_commands')
                        else:
                            self._send_resumed()
                    else:
                        self.status.set('Ready')
            if not e.get('success'):
                self._write(self.chat, '\n' + e.get('error', 'Pi rejected the command.') + '\n', 'error')
                if not self.active:
                    self.status.set('Ready')
        elif kind == 'agent_start':
            self.active = True
            self.recovery_wait = False
            if not replay:
                self.clock = (datetime.fromisoformat(self.job['created_at']).timestamp()
                              if self.job else time.time())
            self.elapsed = None
            self.status.set('Preparing response')
        elif kind == 'turn_start' and self.active:
            if self.plan_review_pending:
                self.status.set(REVIEWING_INITIAL_PLAN)
            elif self.status.get() != 'Processing tool results':
                self.status.set('Preparing response')
        elif kind == 'agent_settled':
            phase = self._settle_job() if self.job else None
            self._finish({'failed': 'Failed', 'needs_review': 'Needs review', 'stopped': 'Stopped'}.get(
                phase, 'Stopped' if e.get('aborted') else 'Finished'))
            if self.exit_after_job and phase in TERMINAL and not self.recovery_wait:
                self.root.after_idle(self.close)
        elif kind == 'compaction_start':
            self.status.set('Compacting context')
        elif kind == 'compaction_end':
            self.status.set('Preparing response')
            if e.get('aborted'):
                self._write(self.chat, '\nContext compaction cancelled.\n', 'event')
            elif e.get('errorMessage'):
                self._write(self.chat, '\n' + e['errorMessage'] + '\n', 'error')
            elif e.get('result') is not None:
                self.compactions += 1
                self._write(self.chat, '\nContext checkpoint saved.\n', 'event')
            else:
                self._write(self.chat, '\nContext compaction ended without a saved checkpoint.\n', 'event')
        elif kind == 'message_start':
            if e.get('message', {}).get('role') == 'assistant':
                self.streamed = False
                self.stream_thoughts.clear()
                self.stream_thought_chunks.clear()
                self._reset_stream_preview()
        elif kind == 'message_update':
            self._stream_assistant(e.get('assistantMessageEvent') or {})
        elif kind == 'message_end':
            message = e.get('message', {})
            self._message(message)
            if not replay and message.get('role') == 'user':
                self._refresh_history()
        elif kind in ('tool_execution_start', 'tool_execution_update', 'tool_execution_end'):
            self._tool(e)

    def _message(self, message):
        role = message.get('role')
        if role not in ('user', 'assistant'):
            return
        content = message.get('content') or []
        text = content if isinstance(content, str) else '\n'.join(
            part.get('text', '') for part in content if part.get('type') == 'text')
        if role == 'user' and text:
            if self.chat_title.get() == 'New chat':
                title = ' '.join(text.split())
                self.chat_title.set(title[:66] + ('…' if len(title) > 66 else ''))
            self._write(self.chat, '\nYou\n', 'user')
            self._write(self.chat, text + '\n', 'user_message')
        elif role == 'assistant':
            if text:
                self.last_answer = text
            parts = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
            visible = any((part['type'] == 'text' and part.get('text')) or
                          (part['type'] == 'thinking' and part.get('thinking')) for part in parts)
            expanded = {}
            if self.streamed and (visible or not message.get('errorMessage')):
                for index, key in self.stream_thoughts.items():
                    card = self.thought_cards.pop(key)
                    expanded[index] = card['manual']
                    self.chat.tag_delete(*card['tags'])
                self.chat.configure(state='normal')
                self.chat.delete('stream_start', 'stream_limit')
                self.chat.configure(state='disabled')
            if visible:
                self._write(self.chat, '\nPi\n', 'assistant')
                for index, part in enumerate(parts):
                    if part['type'] == 'thinking' and part.get('thinking'):
                        self._add_thought(part['thinking'], False, expanded.get(index))
                    elif part['type'] == 'text' and part.get('text'):
                        self._format_reply(part['text'])
                if text:
                    self._add_reply_actions(text)
            if not visible and message.get('errorMessage'):
                self._settle_stream_thoughts()
            self.streamed = False
            self.stream_thoughts.clear()
            self.stream_thought_chunks.clear()
            self._reset_stream_preview()
            usage = message.get('usage', {})
            self.last_usage = usage.get('totalTokens', self.last_usage)
            if message.get('errorMessage'):
                self._write(self.chat, '\n' + message['errorMessage'] + '\n', 'error')

    def _stream_assistant(self, event):
        kind, text = event.get('type'), event.get('delta')
        if kind != 'thinking_delta' and kind != 'toolcall_delta':
            self._render_stream_thoughts()
        if kind in ('thinking_start', 'text_start', 'toolcall_start') and self.active:
            phase = {'thinking_start': 'Thinking', 'text_start': 'Writing reply',
                     'toolcall_start': 'Preparing tool'}[kind]
            if kind == 'thinking_start' and self.plan_review_pending:
                phase = REVIEWING_INITIAL_PLAN
            elif kind == 'toolcall_start' and event.get('toolName'):
                phase += ' · ' + self._tool_label(event['toolName'])
            self.status.set(phase)
        # Some providers emit thinking_end after the whole message, including its tool arguments.
        if kind in ('text_start', 'toolcall_start'):
            for key in self.stream_thoughts.values():
                self._close_live_thought(key)
        if kind == 'thinking_end':
            self._close_live_thought(self.stream_thoughts.get(event.get('contentIndex', 0)))
        if kind == 'text_end':
            self._render_stream_preview()
            self._reset_stream_preview()
        if kind not in ('thinking_delta', 'text_delta') or not isinstance(text, str) or not text:
            return
        if not self.streamed:
            self.streamed = True
            self.chat.mark_set('stream_start', 'end-1c')
            self.chat.mark_gravity('stream_start', 'left')
            self._write(self.chat, '\nPi\n', 'assistant')
            self._mark_stream_end()
        if kind == 'thinking_delta':
            index = event.get('contentIndex', 0)
            self.stream_thought_chunks.setdefault(index, []).append(text)
        else:
            tags = self.chat.tag_names('end-2c')
            if 'thought_text' in tags and self.chat.get('end-2c', 'end-1c') != '\n':
                self._write(self.chat, '\n', tags)
            for key in self.stream_thoughts.values():
                self._close_live_thought(key)
            self._preview_text(text)
            self._mark_stream_end()

    def _render_stream_thoughts(self):
        if not self.stream_thought_chunks:
            return
        for index, chunks in self.stream_thought_chunks.items():
            key = self.stream_thoughts.get(index)
            if key is None:
                key = self._add_thought('', True)
                self.stream_thoughts[index] = key
            self._write(self.chat, ''.join(chunks), ('thought_text', self.thought_cards[key]['tags'][1]))
        self.stream_thought_chunks.clear()
        self._mark_stream_end()

    def _mark_stream_end(self):
        self.chat.mark_set('stream_limit', 'end-1c')
        self.chat.mark_gravity('stream_limit', 'left')

    def _preview_text(self, text):
        if self.stream_preview_limit:
            self._write(self.chat, text, 'answer')
            return
        if not self.stream_preview:
            self.chat.mark_set('stream_preview', 'end-1c')
            self.chat.mark_gravity('stream_preview', 'left')
            self._mark_stream_end()
        self.stream_preview += text
        self.stream_preview_dirty = True
        # shortcut: long blocks stream their remaining text directly until the final Markdown render.
        if len(self.stream_preview) > LIVE_MARKDOWN_LIMIT:
            self._render_stream_preview(raw=True)
            self._reset_stream_preview()
            self.stream_preview_limit = True

    def _render_stream_preview(self, raw=False):
        if not self.stream_preview_dirty:
            return
        self.stream_preview_dirty = False
        self.chat.configure(state='normal')
        self.chat.delete('stream_preview', 'stream_limit')
        self.chat.configure(state='disabled')
        if raw:
            self._write(self.chat, self.stream_preview, 'answer')
        else:
            self._format_reply(self.stream_preview, links=False)
        self._mark_stream_end()

    def _reset_stream_preview(self):
        self.stream_preview = ''
        self.stream_preview_dirty = self.stream_preview_limit = False
        self.chat.mark_unset('stream_preview')

    def _add_thought(self, text, live, manual=None):
        if self.chat.get('end-2c', 'end-1c') != '\n':
            self._write(self.chat, '\n', self.chat.tag_names('end-2c'))
        key = f'thought_{len(self.thought_cards)}_{self.chat.index("end-1c").replace(".", "_")}'
        header, body = key + '_heading', key + '_body'
        expanded = live if manual is None else manual
        self.thought_cards[key] = {'tags': (header, body), 'expanded': expanded, 'manual': manual, 'live': live}
        self.chat.tag_bind(header, '<Button-1>', lambda _event: self._toggle_thought(key))
        self._write(self.chat, self._thought_label(self.thought_cards[key]) + '\n', ('thought_label', header))
        if text:
            self._write(self.chat, text.rstrip('\n') + '\n', ('thought_text', body))
        self._show_thought(self.thought_cards[key])
        return key

    def _show_thought(self, card):
        header, body = card['tags']
        show = self.show_reasoning.get()
        self.chat.tag_configure(header, elide=not show)
        self.chat.tag_configure(body, elide=not (show and card['expanded']))

    def _toggle_thought(self, key):
        card = self.thought_cards[key]
        card['manual'] = card['expanded'] = not card['expanded']
        self.chat_following = False
        position = self._refresh_thought_label(card)
        self._show_thought(card)
        self.chat.mark_set('insert', position)
        self.chat.focus_set()
        return 'break'

    def _thought_label(self, card):
        return ('▾' if card['expanded'] else '▸') + ('  Thinking' if card['live'] else '  Thought')

    def _refresh_thought_label(self, card):
        header = card['tags'][0]
        start, end = self.chat.tag_ranges(header)
        self.chat.configure(state='normal')
        self.chat.replace(start, end, self._thought_label(card) + '\n', ('thought_label', header))
        self.chat.configure(state='disabled')
        return start

    def _format_reply(self, text, links=True):
        style = []
        lists = []
        table = None
        runs = []

        def add(value, tags):
            runs.extend((value, tags))

        for token in MARKDOWN.parse(text):
            kind = token.type
            if kind in ('fence', 'code_block'):
                add(token.content + ('\n' if not token.content.endswith('\n') else ''), 'code')
            elif kind in ('heading_open', 'blockquote_open'):
                style.append('heading' if kind == 'heading_open' else 'quote')
            elif kind in ('heading_close', 'blockquote_close'):
                if kind == 'heading_close':
                    add('\n', 'heading')
                style.pop()
            elif kind in ('bullet_list_open', 'ordered_list_open'):
                lists.append(None if kind == 'bullet_list_open' else int(token.attrGet('start') or 1))
            elif kind in ('bullet_list_close', 'ordered_list_close'):
                lists.pop()
            elif kind == 'list_item_open':
                number = lists[-1]
                add('  ' * (len(lists) - 1) + ('• ' if number is None else f'{number}. '), 'answer')
                if number is not None:
                    lists[-1] += 1
            elif kind == 'table_open':
                table = []
            elif kind == 'tr_open':
                table.append([])
            elif kind == 'table_close':
                widths = [max(map(len, column)) for column in zip(*table)]
                for index, row in enumerate(table):
                    add(' │ '.join(cell.ljust(width) for cell, width in zip(row, widths)) + '\n', 'table')
                    if index == 0:
                        add('─┼─'.join('─' * width for width in widths) + '\n', 'table')
                table = None
            elif kind == 'inline':
                if table is not None:
                    table[-1].append(''.join(c.content for c in token.children if c.type in ('text', 'code_inline', 'image')))
                else:
                    self._format_inline(token.children, tuple(style) or ('answer',), links, add)
            elif kind in ('paragraph_close', 'hr'):
                add('\n', tuple(style) or ('answer',))
        if runs:
            self.chat.configure(state='normal')
            try:
                self.chat.insert('end', *runs)
                if self.chat_following:
                    self.chat.yview('end')
            finally:
                self.chat.configure(state='disabled')

    def _format_inline(self, pieces, tags, links, add):
        inline = {'strong_open': 'strong', 'em_open': 'em', 's_open': 'strike'}
        active = []
        link = ()
        for part in pieces:
            if part.type in inline:
                active.append(inline[part.type])
            elif part.type in ('strong_close', 'em_close', 's_close'):
                active.pop()
            elif part.type == 'link_open' and links:
                url = part.attrGet('href')
                try:
                    parsed = urlsplit(url)
                except ValueError:
                    continue
                if parsed.scheme in ('http', 'https') and parsed.hostname and parsed.username is None:
                    tag = f'reply_link_{len(self.reply_links)}'
                    self.reply_links.append((tag, url))
                    self.chat.tag_bind(tag, '<Button-1>', lambda _event, target=url: webbrowser.open(target))
                    link = ('link', tag)
            elif part.type == 'link_close':
                link = ()
            elif part.type in ('text', 'code_inline', 'image', 'softbreak', 'hardbreak'):
                value = {'softbreak': ' ', 'hardbreak': '\n'}.get(part.type, part.content)
                decoration = ('inline_code',) if part.type == 'code_inline' else ()
                add(value, (*tags, *active, *decoration, *link))

    def _add_reply_actions(self, text):
        for label, action in (('Copy reply', self._copy_text), ('Read aloud', self._toggle_read_aloud)):
            tag = f'reply_action_{len(self.reply_actions)}'
            self.reply_actions[tag] = (action, text)
            self.chat.tag_bind(tag, '<Button-1>', lambda _event, key=tag: self._reply_action(key))
            self._write(self.chat, label + '    ', ('reply_action', tag))
        self._write(self.chat, '\n', 'reply_action')

    def _reply_action(self, tag):
        action, text = self.reply_actions[tag]
        action(text)
        return 'break'

    def _tool_label(self, name):
        name = name.removeprefix('mcp__windows__').removeprefix('mcp__chrome__')
        return TOOL_LABELS.get(name, name.replace('_', ' ').capitalize())

    def _chat_tool_call(self, key, name, args):
        if key in self.tool_cards:
            return
        label = self._tool_label(name)
        target = args.get('path') or args.get('name') or args.get('query') or args.get('command')
        if isinstance(target, str) and target.strip():
            target = ' '.join(target.split())
            label += ' · ' + (target[:80] + '…' if len(target) > 80 else target)
        ordinal = len(self.tool_cards)
        start, limit, heading, body = (f'card_{ordinal}_{part}' for part in ('start', 'limit', 'heading', 'body'))
        if self.chat.get('end-2c', 'end-1c') != '\n':
            self._write(self.chat, '\n')
        position = self.chat.index('end-1c')
        self._write(self.chat, '\n\n')
        self.chat.mark_set(start, position)
        self.chat.mark_gravity(start, 'left')
        self.chat.mark_set(limit, f'{position}+1c')
        self.chat.mark_gravity(limit, 'right')
        request = '\n'.join(f'{field}\n{value}' if isinstance(value, str) else
                            f'{field}\n{json.dumps(value, ensure_ascii=False, indent=2)}'
                            for field, value in args.items())
        self.tool_cards[key] = {'marks': (start, limit, heading, body), 'label': label, 'request': request,
                                'output': '', 'state': 'running', 'expanded': False, 'manual': False}
        self.chat.tag_bind(heading, '<Button-1>', lambda _event: self._toggle_tool(key))
        self._render_tool(key)

    def _toggle_tool(self, key):
        card = self.tool_cards[key]
        card['expanded'] = not card['expanded']
        card['manual'] = True
        self.chat_following = False
        self._render_tool(key)
        self.chat.mark_set('insert', card['marks'][0])
        self.chat.see(card['marks'][0])
        self.chat.focus_set()
        return 'break'

    def _toggle_focused_tool(self, _event):
        tags = self.chat.tag_names('insert')
        for key, card in self.tool_cards.items():
            if card['marks'][2] in tags:
                return self._toggle_tool(key)
        for key, card in self.thought_cards.items():
            if self.show_reasoning.get() and card['tags'][0] in tags:
                return self._toggle_thought(key)
        for tag, url in self.reply_links:
            if tag in tags:
                webbrowser.open(url)
                return 'break'
        for tag in tags:
            if tag in self.reply_actions:
                return self._reply_action(tag)

    def _render_tool(self, key):
        card = self.tool_cards[key]
        start, limit, heading, body = card['marks']
        state, expanded = card['state'], card['expanded']
        status = {'running': 'Running', 'done': 'Done', 'failed': 'Failed'}[state]
        title = f"{'▾' if expanded else '▸'}  {card['label']}   ·   {status}"
        output = '\n\n'.join(part for part in (card['request'], card['output']) if part)
        self.chat.configure(state='normal')
        self.chat.delete(start, limit)
        self.chat.insert(limit, title, (heading, 'tool_' + state))
        self.chat.insert(limit, '\n' + (output[:32000] or 'No additional details.') +
                         ('\n[Preview truncated. See the saved session for the rest.]' if len(output) > 32000 else ''),
                         ('tool_body', body))
        self.chat.tag_configure(body, elide=not expanded)
        self.chat.configure(state='disabled')
        if self.chat_following:
            self.chat.see('end')

    def _chat_tool_result(self, key, name, result, error=False, running=False):
        if key not in self.tool_cards:
            self._chat_tool_call(key, name, {})
        content = '\n'.join(p.get('text', '') for p in result.get('content', []) if p.get('type') == 'text')
        images = sum(p.get('type') == 'image' for p in result.get('content', []))
        if images:
            content += f'\n[{images} image result(s)]'
        card = self.tool_cards[key]
        card.update(output=content, state='failed' if error else 'running' if running else 'done')
        if running:
            # RPC partial results are snapshots. Draw the newest one once per poll.
            self.tool_updates.add(key)
            return
        self.tool_updates.discard(key)
        if not card['manual']:
            card['expanded'] = False
        self._render_tool(key)

    def _show_running_tool(self, key, card):
        if (self.tool_cards.get(key) is card and card['state'] == 'running'
                and not card['manual'] and (card['request'] or card['output'])):
            card['expanded'] = True
            self._render_tool(key)

    def _tool(self, e):
        key = e.get('toolCallId')
        if not key:
            return
        name = e.get('toolName', 'Tool').removeprefix('mcp__windows__').removeprefix('mcp__chrome__')
        if e['type'] == 'tool_execution_start':
            args = e.get('args') or {}
            self.running_tools.add(key)
            self._chat_tool_call(key, name, args)
            self.root.after(400, self._show_running_tool, key, self.tool_cards[key])
            title = args.get('command') or args.get('path') or ', '.join(
                f'{k}={v}' for k, v in args.items() if k in ('pid', 'window_id', 'query', 'delivery_mode'))
            selection = self.activity.selection()
            follow_latest = not selection or selection == self.activity.get_children()[-1:]
            self.tasks[key] = (time.monotonic(), str(title)[:1000], '')
            self.activity.insert('', 'end', iid=key, values=(name, 'Running', '…'), tags=('working',))
            self.activity.see(key)
            if follow_latest:
                self.activity.selection_set(key)
            self.status.set('Running tool · ' + self._tool_label(name))
        elif e['type'] == 'tool_execution_update' and key in self.tasks:
            part = e.get('partialResult') or {}
            if part.get('content'):
                started, title, _ = self.tasks[key]
                result = '\n'.join(p.get('text', '') for p in part['content'] if p.get('type') == 'text')
                self.tasks[key] = started, title, result[-4000:]
                self._chat_tool_result(key, name, part, running=True)
        elif key in self.tasks:
            self.running_tools.discard(key)
            started, title, _ = self.tasks[key]
            result = e.get('result') or {}
            if name in ('update_plan', 'review_initial_plan') and not e.get('isError'):
                self._apply_plan(result.get('details') or {})
            elif not e.get('isError') and (result.get('details') or {}).get('skillEvent'):
                self._apply_skill(result['details'])
            excerpt = '\n'.join(p.get('text', '') for p in result.get('content', []) if p.get('type') == 'text')
            self.tasks[key] = started, title, excerpt[:4000]
            error = bool(e.get('isError'))
            self._chat_tool_result(key, name, result, error)
            elapsed = '—' if self.watch else f'{time.monotonic() - started:.1f}s'
            self.activity.item(key, values=(name, 'Error' if error else 'Done', elapsed),
                               tags=('failed',) if error else ())
            if self.activity.selection() == (key,):
                self._selected()
            if self.active and not self.running_tools:
                self.status.set(REVIEWING_INITIAL_PLAN if self.plan_review_pending else 'Processing tool results')

    def _selected(self, _=None):
        current = self.activity.selection()
        if current and current[0] in self.tasks:
            _, title, result = self.tasks[current[0]]
            self._write(self.details, '\n\n'.join(part for part in (title, result) if part), replace=True)

    def _finish(self, status):
        self._clear_clarification()
        self.active = False
        self.plan_review_pending = False
        self.running_tools.clear()
        self._settle_stream_thoughts()
        self.refresh_files()
        self.elapsed = time.time() - self.clock if self.clock else None
        if self.watch:
            receipt = self.watch.receipt
            if receipt.is_file():
                try:
                    self.elapsed = json.loads(receipt.read_text(encoding='utf-8')).get('elapsed_seconds', self.elapsed)
                except (OSError, ValueError):
                    pass
        self.status.set(status)
        if self.rpc:
            self._refresh_history()
        if self.evidence and not self.watch:
            receipt = {'ended_utc': datetime.now(timezone.utc).isoformat(), 'status': status, 'elapsed_seconds': self.elapsed}
            (self.evidence / 'gui-settled.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')

    def _show_clarification(self, event):
        identity = event.get('id')
        if not isinstance(identity, str) or not self.rpc:
            return
        try:
            if self.exit_after_job or self.clarification:
                raise ValueError('Open this task in visible Pi to answer the clarification.')
            path, record, question = save_request(event, self.jobs, self.job)
        except (OSError, ValueError) as error:
            self._write(self.chat, '\n' + str(error) + '\n', 'error')
            self.rpc.send('extension_ui_response', id=identity, cancelled=True)
            return

        def submit(answer):
            if not self.clarification or self.clarification[0] != identity or answer is None:
                return
            try:
                save_answer(path, record, answer)
            except (OSError, ValueError) as error:
                self._write(self.chat, '\nCould not save the clarification. ' + str(error) + '\n', 'error')
                return
            self._clear_clarification()
            written = answer['text'] if 'text' in answer else question['choices'][answer['choice']]
            self._show_clarified_answer(question['question'], written)
            self.status.set('Continuing')
            try:
                self.rpc.send('extension_ui_response', id=identity, value='saved')
            except OSError:
                self._write(self.chat, '\nYour answer is saved and will be used when Pi reconnects.\n', 'error')

        for key in self.running_tools:
            tool = self.tool_cards.get(key)
            if tool and tool['label'] == self._tool_label('prepare_prompt'):
                tool['expanded'], tool['manual'] = False, True
                self._render_tool(key)
        card = ClarificationCard(self.chat, question, submit, max(270, min(620, self.chat.winfo_width() - 50)))
        self.clarification = identity, card
        state = self.chat.cget('state')
        self.chat.configure(state='normal')
        try:
            self.chat.insert('end-1c', '\n')
            self.chat.window_create('end-1c', window=card, align='top')
            self.chat.insert('end-1c', '\n')
        finally:
            self.chat.configure(state=state)
        self.root.after_idle(lambda: self.chat.yview_moveto(1.0) if self.clarification and
                             self.clarification[0] == identity else None)
        self.status.set('Waiting for your answer')
        card.entry.focus_set()

    def _show_clarified_answer(self, question, answer):
        self._write(self.chat, '\n' + question + '\n')
        self._write(self.chat, 'You: ' + answer + '\n', 'user')

    def _clear_clarification(self):
        if self.clarification:
            identity, card = self.clarification
            self.clarification = None
            card.destroy()
            return identity

    def _settle_stream_thoughts(self):
        self._render_stream_thoughts()
        self._render_stream_preview()
        self._reset_stream_preview()
        for key in self.stream_thoughts.values():
            self._close_live_thought(key)
        self.stream_thoughts.clear()
        self.stream_thought_chunks.clear()
        self.streamed = False

    def _close_live_thought(self, key):
        card = self.thought_cards.get(key)
        if card and card['live']:
            card['live'] = False
            card['expanded'] = bool(card['manual'])
            self._refresh_thought_label(card)
            self._show_thought(card)

    def _apply_plan(self, plan):
        self.plan_steps = plan.get('steps', [])
        reviewing = plan.get('reviewPending') is True
        self.plan_review_pending = reviewing
        self.plan_reason = 'Reviewing the initial plan before starting work.' if reviewing else plan.get('reason') or ''
        if plan.get('awaitingSkill'):
            self.active_skill.set('Choosing a skill')
            self._write(self.skill_log, 'Stage needs a skill\n' + plan['awaitingSkill'] + '\n\n')
        symbols = {'completed': '✓', 'in_progress': '▸', 'pending': '○'}
        self._write(self.plan, '', replace=True)
        for index, step in enumerate(self.plan_steps, 1):
            state = 'pending' if reviewing else step['status']
            self._write(self.plan, f"{symbols.get(state, '○')}  {index}. {step['title']}\n", state)
        if self.plan_reason:
            self._write(self.plan, '\n' + self.plan_reason + '\n', 'reason')

    def _apply_skill(self, details):
        event = details['skillEvent']
        if event == 'brief':
            self.active_skill.set('Choosing a skill')
            text = 'Prepared brief\n' + details['brief']
            if details.get('checks'):
                text += '\n' + '\n'.join('• ' + check for check in details['checks'])
        elif event == 'search':
            matches = ', '.join(details.get('matches', [])) or 'No local match'
            text = f"Local search · {details['query']}\n{matches}"
        elif event == 'active':
            self.active_skill.set(details['skill'])
            text = f"Loaded {details['skill']} · {details['source']}\n{details['reason']}"
        elif event == 'draft':
            self.active_skill.set('Draft ready to load')
            text = f"Drafted {details['skill']}\n{details['reason']}"
        elif event == 'saved':
            text = f"Saved {details['skill']}\n{details.get('reason', details.get('proof', ''))}\n{details['path']}"
        elif event == 'discarded':
            text = f"Discarded draft {details['skill']}"
        elif event == 'research':
            text = 'Research · ' + (details.get('url') or details.get('query') or '')
        else:
            return
        self._write(self.skill_log, text + '\n\n')

    def _runtime(self, data):
        self.slot_text.set(f"●  Local · {data['slot'].lower()}")

        def set_meter(key, text, used=None, total=None):
            label, meter = self.metrics_rows[key]
            label.set(text)
            meter['value'] = min(100, 100 * used / total) if used is not None and total else 0

        gib = 1024 ** 3
        ram = data['ram_used']
        capacity = data['ram_total']
        set_meter('ram', f'{ram / gib:.1f} / {capacity / gib:.1f} GiB · {(capacity - ram) / gib:.1f} available', ram, capacity)
        set_meter('cpu', f"{data['cpu']:.0f}%", data['cpu'], 100)
        gpus = data.get('gpus', [])
        if gpus:
            used_values = [gpu['used'] for gpu in gpus]
            total_values = [gpu['total'] for gpu in gpus]
            known = None not in used_values and None not in total_values
            used = sum(used_values) if known else None
            total = sum(total_values) if known else None
            free = [gpu.get('free') for gpu in gpus]
            measured = f'{used / 1024:.1f} / {total / 1024:.1f} GiB' if known else '—'
            if None not in free:
                measured += f' · {sum(free):,} MiB free'
            set_meter('vram', measured, used, total)
            temperatures = [gpu['temperature'] for gpu in gpus if gpu['temperature'] is not None]
            loads = [gpu['load'] for gpu in gpus if gpu['load'] is not None]
            temp = f'{max(temperatures)} °C' if temperatures else '—'
            load = max(loads) if loads else None
            set_meter('gpu', f'{temp} / {str(load) + "%" if load is not None else "—"}', load, 100)
        else:
            set_meter('vram', 'Unavailable')
            set_meter('gpu', 'Unavailable')
        used = data.get('context_used')
        limit = data.get('context_max')
        set_meter('context', f'{used:,} / {limit:,}' if used is not None and limit else '—', used, limit)
        live, last = data.get('live_rate'), data.get('last_rate')
        if data['slot'] == 'Busy':
            speed = f'{live:.1f} tok/s live' if live is not None else 'Waiting for sample'
        else:
            speed = f'{last:.1f} tok/s last' if last is not None else '—'
        set_meter('speed', speed)

    def _refresh_history(self):
        def scan():
            self.queue.put({'type': 'local_history', 'data': backend.saved_chats(self.state)})
        threading.Thread(target=scan, daemon=True).start()

    def _show_history(self):
        if not hasattr(self, 'chat_list'):
            return
        muted = THEMES[self.theme][MUTED]
        query = self.search.get().casefold().strip()
        self.visible_chats = [entry for entry in self.history
                              if query in entry[1].casefold() or query in entry[3].name.casefold()]
        selected = self.chat_list.curselection()
        previous = self.history_rows.get(selected[0]) if selected else None
        self.history_rows.clear()
        self.chat_list.delete(0, 'end')
        groups = {}
        for entry in self.visible_chats:
            _, _, path, workspace = entry
            group = None if str(path) in self.pinned_chats else workspace
            groups.setdefault(group, []).append(entry)
        if not groups:
            self.chat_list.insert('end', '  No matching chats' if query else '  No saved chats')
            self.chat_list.itemconfigure('end', foreground=muted)
        workspace_labels = [item.name for item in groups if item is not None]
        for group in sorted(groups, key=lambda item: (item is not None, -groups[item][0][0])):
            label = 'Pinned' if group is None else group.name or str(group)
            if group is not None and workspace_labels.count(group.name) > 1:
                label = f'{group.parent.name} › {label}'
            self.chat_list.insert('end', '  ' + label)
            self.chat_list.itemconfigure('end', foreground=muted)
            for entry in groups[group]:
                _, title, path, _ = entry
                row = self.chat_list.size()
                self.history_rows[row] = entry
                self.chat_list.insert('end', '    ' + title)
                if previous and previous[2] == path:
                    self.chat_list.selection_set(row)

    def _history_menu(self, event):
        chosen = self.chat_list.curselection()
        row = self.chat_list.nearest(event.y) if event.num == 3 else (chosen[0] if chosen else -1)
        if row not in self.history_rows:
            return
        path = str(self.history_rows[row][2])
        palette = THEMES[self.theme]
        menu = tk.Menu(self.root, tearoff=False, bg=palette[PANEL], fg=palette[TEXT],
                       activebackground=palette[SELECTED], activeforeground=palette[TEXT])
        menu.add_command(label='Unpin chat' if path in self.pinned_chats else 'Pin chat',
                         command=lambda: self._pin_chat(path))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _pin_chat(self, path):
        pinned = self.pinned_chats ^ {path}
        destination = self.state / 'pinned-chats.json'
        try:
            staged = destination.with_suffix('.tmp')
            staged.write_text(json.dumps(sorted(pinned)), encoding='utf-8')
            staged.replace(destination)
        except OSError as exc:
            self._write(self.chat, '\n' + str(exc) + '\n', 'error')
            return
        self.pinned_chats = pinned
        self._show_history()

    def resume_chat(self, _=None):
        active = self.chat_list.curselection()
        if not active or self.active or self.pending or self.browser_only or self.recovery_wait or self.starting_backend:
            return
        chat = self.history_rows.get(active[0])
        if chat is not None:
            self._open_chat(chat)

    def _open_chat(self, chat, *, start_model=True):
        _, title, path, workspace = chat
        try:
            if not workspace.is_dir():
                raise RuntimeError('This chat’s workspace folder is unavailable.')
            retry = (lambda: self._open_chat(chat, start_model=False)) if start_model else None
            if not self._native_available(retry):
                return
            if self.rpc and workspace.resolve() != self.workspace.resolve():
                self.rpc.close()
                self.rpc = self.rpc_marker = None
            self.watch = None
            self.workspace = workspace
            self._reset()
            self.chat_title.set(title[:66] + ('…' if len(title) > 66 else ''))
            self._start_rpc()
            self.pending = self.rpc.send('switch_session', sessionPath=str(path))
            self.status.set('Opening chat')
        except (OSError, RuntimeError, ValueError) as exc:
            self._write(self.chat, '\n' + str(exc) + '\n', 'error')

    def _choose_branch(self):
        if not self.rpc or self.pending or self.active or self.evidence:
            return
        if self.prompt.get('1.0', 'end-1c').strip() or self.attachments:
            messagebox.showinfo('Branch chat', 'Send or save your current draft before opening a branch.', parent=self.root)
            return
        self.pending = self.rpc.send('get_fork_messages')

    def _show_branch_messages(self, messages):
        if not messages:
            messagebox.showinfo('Branch chat', 'This chat has no saved prompts yet.', parent=self.root)
            return
        palette = THEMES[self.theme]
        dialog = tk.Toplevel(self.root, bg=palette[PANEL])
        dialog.title('Branch from a prompt')
        dialog.transient(self.root)
        dialog.grab_set()
        label = 'Pi opens a new branch and puts the selected prompt in the composer for review.'
        tk.Label(dialog, text=label, bg=palette[PANEL], fg=palette[TEXT], padx=15, pady=10, font=SMALL).pack(anchor='w')
        rows = tk.Frame(dialog, bg=palette[PANEL], padx=15)
        rows.pack(fill='both', expand=True)
        prompts = tk.Listbox(rows, width=72, height=min(12, len(messages)), font=SMALL,
                             bg=palette[BG], fg=palette[TEXT], selectbackground=palette[ACCENT],
                             selectforeground=palette[ON_ACCENT])
        scroll = ttk.Scrollbar(rows, command=prompts.yview, style='Pi.Vertical.TScrollbar')
        scroll.pack(side='right', fill='y')
        prompts.configure(yscrollcommand=scroll.set)
        prompts.pack(fill='both', expand=True)
        for message in messages:
            prompts.insert('end', ' '.join(message['text'].split())[:120])
        prompts.selection_set('end')
        prompts.see('end')

        def select(_event=None):
            chosen = prompts.curselection()
            if chosen:
                dialog.destroy()
                self._fork_at(messages[chosen[0]]['entryId'])

        prompts.bind('<Double-Button-1>', select)
        prompts.bind('<Return>', select)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        self._button(dialog, 'Open branch', select).pack(anchor='e', padx=15, pady=10)
        prompts.focus_set()

    def _fork_at(self, entry_id):
        self.pending = self.rpc.send('fork', entryId=entry_id)

    def settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        palette = THEMES[self.theme]
        dialog = self.settings_window = tk.Toplevel(self.root, bg=palette[PANEL])
        self.reasoning_choices.clear()
        dialog.withdraw()
        dialog.title('Settings')
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = tk.Frame(dialog, bg=palette[PANEL], padx=21, pady=17)
        panel.pack(fill='both', expand=True)
        for label, variable, values, apply in (
            ('Theme', self.theme_choice, ('hermes', 'light', 'dark'), self._set_theme),
            ('Reasoning level', self.thinking_label, ('off', 'low', 'medium', 'high'), self._set_reasoning),
        ):
            tk.Label(panel, text=label, bg=palette[PANEL], fg=palette[TEXT],
                     font=('Segoe UI Semibold', 11)).pack(anchor='w')
            row = tk.Frame(panel, bg=palette[PANEL])
            row.pack(fill='x', pady=(4, 13))
            for value in values:
                choice = value if label == 'Theme' else value.title()
                title = 'Hermes light' if value == 'hermes' else value.title()
                button = ttk.Radiobutton(row, text=title, variable=variable, value=choice,
                                         command=apply, style='Pi.TRadiobutton')
                if label == 'Reasoning level':
                    self.reasoning_choices.append(button)
                button.pack(side='left', padx=(0, 5))
        ttk.Checkbutton(panel, text='Show local Qwen reasoning', variable=self.show_reasoning,
                        style='Pi.TCheckbutton', command=self._set_show_reasoning).pack(anchor='w', pady=(0, 13))
        actions = tk.Frame(panel, bg=palette[PANEL])
        actions.pack(fill='x')
        self._button(actions, 'Open plugins and MCP folder', self.open_tools_profile).pack(side='left', padx=(0, 10))
        self.unload_button = self._button(actions, 'Unload local model', self._unload_native)
        self.unload_button.pack(side='left', padx=(0, 10))
        done = self._button(actions, 'Done', dialog.destroy)
        done.pack(side='right')
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_reqheight()) // 2
        dialog.geometry(f'+{x}+{y}')
        dialog.deiconify()
        dialog.after_idle(lambda: self._color_caption(dialog))
        dialog.grab_set()
        done.focus_set()
        self._controls()

    def _save_preferences(self, **updates):
        preferences = {**self.preferences, **updates}
        self.state.mkdir(parents=True, exist_ok=True)
        staged = self.settings_path.with_suffix('.tmp')
        staged.write_text(json.dumps(preferences), encoding='utf-8')
        staged.replace(self.settings_path)
        self.preferences = preferences

    def _set_theme(self):
        theme = self.theme_choice.get()
        if theme == self.theme:
            return
        try:
            self._save_preferences(theme=theme)
            self._apply_theme(theme)
        except OSError as exc:
            self.theme_choice.set(self.theme)
            messagebox.showerror('Settings', str(exc), parent=self.settings_window)

    def _set_show_reasoning(self):
        shown = self.show_reasoning.get()
        try:
            self._save_preferences(show_reasoning=shown)
        except OSError as exc:
            self.show_reasoning.set(not shown)
            messagebox.showerror('Settings', str(exc), parent=self.settings_window)
        for card in self.thought_cards.values():
            self._show_thought(card)
        if self.chat_following:
            self.chat.see('end')

    def _set_reasoning(self):
        level = self.thinking_label.get().lower()
        if self.active or self.pending:
            self.thinking_label.set(self.thinking.title())
            return
        if level == self.thinking:
            return
        try:
            if self.rpc:
                self.pending = self.rpc.send('set_thinking_level', level=level)
            self._save_preferences(thinking=level)
            self.thinking = level
        except OSError as exc:
            self.thinking_label.set(self.thinking.title())
            messagebox.showerror('Settings', str(exc), parent=self.settings_window)

    def open_audio_report(self):
        if self.audio_report_window and self.audio_report_window.winfo_exists():
            self.audio_report_window.lift()
            return
        filename = filedialog.askopenfilename(parent=self.root, title='Choose local audio or video',
                                              initialdir=self.workspace,
                                              filetypes=[('Audio and video', ' '.join('*' + ext for ext in sorted(AV_EXT)))])
        if not filename:
            return
        path = Path(filename)
        palette = THEMES[self.theme]
        dialog = self.audio_report_window = tk.Toplevel(self.root, bg=palette[PANEL])
        dialog.title('Pi Audio report')
        dialog.transient(self.root)
        dialog.geometry('740x560')
        dialog.minsize(540, 360)
        tk.Label(dialog, text=path.name, bg=palette[PANEL], fg=palette[TEXT], font=BODY).pack(pady=(12, 3))
        options = tk.Frame(dialog, bg=palette[PANEL])
        options.pack(pady=5)
        fields = {}
        for name, value in (('Start (s)', '0'), ('Length (s)', '30'), ('Channel (optional)', '')):
            tk.Label(options, text=name, bg=palette[PANEL], fg=palette[TEXT], font=SMALL).pack(side='left', padx=5)
            fields[name] = tk.StringVar(dialog, value)
            ttk.Entry(options, textvariable=fields[name], width=7).pack(side='left')
        output = self._scrolled_text(dialog, BODY, 18, surface=palette[PANEL])

        def analyze():
            try:
                start, duration = (float(fields[name].get()) for name in ('Start (s)', 'Length (s)'))
                channel = fields['Channel (optional)'].get().strip()
                channel = int(channel) if channel else None
            except ValueError:
                self._write(output, 'Enter seconds for start and length, and a whole channel number if needed.', replace=True)
                return
            button.state(['disabled'])
            self._write(output, 'Analyzing locally…', replace=True)
            result = SimpleQueue()

            def worker():
                try:
                    measurements = audio_excerpt(path.resolve(strict=True), start=start, duration=duration, channel=channel)
                    result.put(format_audio_evidence(path.name, measurements))
                except (ImportError, OSError, ValueError, KeyError, RuntimeError, SubprocessError) as error:
                    result.put(f'Audio analysis failed. {error}')

            def poll():
                if not dialog.winfo_exists():
                    return
                try:
                    text = result.get_nowait()
                except Empty:
                    self.root.after(100, poll)
                    return
                self._write(output, text, replace=True)
                output.yview_moveto(0)
                button.state(['!disabled'])

            threading.Thread(target=worker, daemon=True).start()
            self.root.after(100, poll)

        button = self._button(options, 'Analyze', analyze)
        button.pack(side='left', padx=8)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        analyze()

    def attach(self):
        names = filedialog.askopenfilenames(parent=self.root, title='Attach local files', initialdir=self.workspace,
            filetypes=[('All files', '*.*'), ('Images', '*.png *.jpg *.jpeg *.webp *.gif *.tiff *.avif'),
                       ('Video and audio', '*.mp4 *.mov *.mkv *.webm *.avi *.mp3 *.wav *.m4a *.ogg *.flac'),
                       ('Documents', '*.pdf *.docx *.xlsx *.pptx *.txt *.md *.csv *.json *.zip')])
        self.attachments = list(dict.fromkeys([*self.attachments, *(Path(name) for name in names)]))
        self.attachment_label.set(', '.join(path.name for path in self.attachments))
        if self.attachments:
            self.attached_files.pack(fill='x')
        self._controls()

    def clear_attachments(self):
        self.attachments.clear()
        self.attachment_label.set('')
        self.attached_files.pack_forget()
        self._controls()

    def copy_reply(self):
        if self.last_answer:
            self._copy_text(self.last_answer)

    def _copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _toggle_read_aloud(self, text):
        try:
            if self.voice is None:
                self.voice = Dispatch('SAPI.SpVoice')
            if self.voice.Status.RunningState == 2:
                self.voice.Speak('', 19)
                return
            parts = []
            for token in MARKDOWN.parse(text):
                if token.type == 'inline':
                    parts.append(''.join(' ' if part.type.endswith('break') else part.content for part in token.children))
                elif token.type in ('fence', 'code_block'):
                    parts.append(token.content)
            spoken = '\n'.join(parts)
            self.voice.Speak(spoken or text, 19)  # Asynchronous, purge previous audio, treat as plain text.
        except (OSError, com_error) as exc:
            messagebox.showerror('Read aloud', str(exc), parent=self.root)

    def _prompt_payload(self, prompt):
        if not self.attachments:
            return {'message': prompt}
        references = []
        small_texts = []
        images = []
        remaining_inline = 4096
        for selected in self.attachments:
            file = selected.resolve(strict=True)
            if not file.is_file():
                raise ValueError(f'Choose a file or use Workspace for a folder: {file.name}')
            suffix = file.suffix.lower()
            size = file.stat().st_size
            entry = {'path': str(file), 'name': file.name, 'bytes': size}
            if suffix in IMAGE_EXT and len(images) < 4:
                try:
                    preview = picture(file)['images'][0]
                    images.append(preview)
                    entry['inline_image'] = len(images)
                except (OSError, ValueError):
                    entry['inline_image'] = 'Preview failed; original is still linked.'
            elif suffix in ('.txt', '.md', '.csv', '.json', '.py') and size <= remaining_inline:
                try:
                    content = file.read_text(encoding='utf-8')
                except UnicodeError:
                    pass
                else:
                    remaining_inline -= size
                    small_texts.append(f'\n--- Attachment: {file.name} ---\n{content}\n--- End attachment ---')
            references.append(entry)
        context = '\n\nSelected local attachments. Inspect these originals with your local analysis tools:\n'
        return dict(message=prompt + context + json.dumps(references, ensure_ascii=False) + ''.join(small_texts),
                    **({'images': images} if images else {}))

    def _start_rpc(self, session=None, thinking=None):
        if self.rpc:
            return
        key = self.server.key()
        context_window = backend.model_slot(self.server).get('n_ctx') if self.jobs else None
        if self.jobs and context_window is None:
            raise RuntimeError('Qwen did not report the active context window.')
        env = backend.prepare(self.state, key, browser_only=self.browser_only, workspace=self.workspace,
                              calibration=self.evidence is not None, recover_jobs=self.jobs is not None,
                              context_window=context_window)
        if self.jobs:
            env['PI_GUI_RECOVERY_DIR'] = str(self.jobs.directory)
            env['PI_GUI_PLAN_REVIEW'] = '1'
            if not self.exit_after_job:
                env['PI_GUI_CLARIFICATION'] = '1'
            if context_switch.qualifies(self.server):
                env['PI_GUI_AUTO_CONTEXT'] = '1'
        marker = self.rpc_marker = object()
        command = backend.command(self.state, self.browser_only, thinking or self.thinking,
                                  calibration=self.evidence is not None)
        if session:
            command.extend(('--session', session))
        def received(event):
            if self.latency:
                event['_received_ns'] = time.perf_counter_ns()
            self.queue.put({**event, '_transport': marker})
        self.rpc = backend.Rpc(self.workspace, env, command, received)

    def _recovery_response(self, event):
        command, success = event.get('command'), event.get('success')
        if command == 'get_state' and self.queued_payload is not None:
            payload, self.queued_payload = self.queued_payload, None
            try:
                if not success:
                    raise RuntimeError(event.get('error', 'Pi did not identify its session.'))
                session = (event.get('data') or {}).get('sessionFile')
                if not session:
                    raise RuntimeError('Pi did not provide a durable session path.')
                backend.verify_available(self.server, self.external_watch)
                if not self.allow_wide_context and backend.model_slot(self.server).get('n_ctx') != context_switch.NARROW:
                    raise RuntimeError('New Pi jobs require the 64k profile.')
                self.job = self.jobs.admit(session, self.workspace, payload, self.thinking, self.rpc.process,
                                           allow_wide_context=self.allow_wide_context)
                self.pending = self.rpc.send('prompt', **payload)
            except (OSError, RuntimeError, ValueError, psutil.Error) as exc:
                if self.job:
                    self._pause_recovery(str(exc))
                else:
                    if not self.prompt.get('1.0', 'end-1c').strip():
                        self.prompt.insert('1.0', payload['message'])
                    self.status.set('Ready')
                    self._write(self.chat, '\n' + str(exc) + '\n', 'error')
            return True
        if command == 'get_commands' and self.resume_payload is not None:
            commands = (event.get('data') or {}).get('commands', [])
            if success and any(item.get('name') == 'local-pi-recover' for item in commands):
                self._send_resumed()
            else:
                self._pause_recovery('The pinned Pi recovery command is unavailable.')
            return True
        if self.job and command in ('get_messages', 'prompt') and not success:
            note = (self.jobs.checkpoint(self.job).get('note') if self.recovery_wait else None)
            self._pause_recovery(note or event.get('error') or 'Pi refused the job.')
            return True
        return False

    def _send_resumed(self):
        payload, self.resume_payload = self.resume_payload, None
        try:
            if self.jobs.status(self.job) == 'stopped':
                self._settle_job()
                self._finish('Stopped')
                return
            backend.verify_available(self.server, self.external_watch)
            self.pending = self.rpc.send('prompt', **payload)
            self.status.set('Resuming saved job')
        except (OSError, RuntimeError, ValueError) as exc:
            self._pause_recovery(str(exc))

    def _pause_recovery(self, note):
        self.resume_payload = None
        self.recovery_wait = True
        self.status.set('Needs review')
        if self.job and self.jobs.status(self.job) != 'needs_review':
            self.jobs.hold(self.job, note)
        self._write(self.chat, '\nPi paused recovery. ' + note + '\n', 'error')

    def _settle_job(self):
        phase = self.jobs.status(self.job)
        if phase == 'needs_review':
            self._pause_recovery(self.jobs.hold_note(self.job) or self.jobs.checkpoint(self.job).get('note')
                                 or 'An interrupted operation needs to be checked.')
        elif phase in TERMINAL:
            self.jobs.archive(self.job, phase)
            self.job = None
            self.recovery_wait = False
            if context_switch.lease_file(self.jobs.directory).is_file():
                self.recovery_wait = True
                self.root.after(100, self._recover_job)
        else:
            # A low-level abort without a Stop marker can be a transport failure.
            self.recovery_wait = True
            if self.rpc:
                self.rpc.close()
        return phase

    def _recover_job(self):
        if not self.jobs or self.pending or self.active or self.starting_backend:
            return
        try:
            job = self.jobs.current()
            if job is None:
                if context_switch.lease_file(self.jobs.directory).is_file():
                    self.recovery_wait = True
                    if self.rpc:
                        self.rpc.close()
                        self.rpc = self.rpc_marker = None
                    self._change_context(restore=True)
                return
            self.job = job
            phase = self.jobs.status(job)
            if phase in TERMINAL:
                self._settle_job()
                return
            self.recovery_wait = True
            if phase == 'needs_review':
                self._pause_recovery(self.jobs.hold_note(job) or self.jobs.checkpoint(job).get('note')
                                     or 'An interrupted operation needs to be checked.')
                return
            if self.watch and not self.watch.active():
                self.watch = None
            if self.watch or backend.hermes_active():
                self.status.set('Waiting to recover Pi job')
                self.root.after(3000, self._recover_job)
                return
            if self.jobs.owner_running(job):
                self.status.set('Waiting for the previous Pi process')
                self.root.after(1000, self._recover_job)
                return
            if self.exit_after_job and has_saved_clarification(self.jobs, job):
                self.root.destroy()
                return
            native_status = self.server.status().get('status')
            if native_status == 'stopped':
                self._start_native()
                return
            if native_status != 'ready' or backend.slot(self.server) != 'Idle':
                self.status.set('Waiting for the Qwen slot')
                self.root.after(3000, self._recover_job)
                return
            backend.verify_available(self.server, self.external_watch)
            if (context_switch.requested(self.jobs, job)
                    and backend.model_slot(self.server).get('n_ctx') != context_switch.WIDE):
                self._change_context(job=job)
                return
            workspace = Path(job['workspace']).resolve(strict=True)
            if not workspace.is_dir():
                raise ValueError('The original Pi workspace is unavailable.')
            resume = self.jobs.resume_prompt(job)
            if not self.jobs.retry(job):
                raise RuntimeError('Pi exhausted three automatic recovery attempts for this job.')
            self.workspace = workspace
            self._reset()
            self.chat_title.set(' '.join(job['payload']['message'].split())[:66] or 'Saved chat')
            plan = self.jobs.checkpoint(job).get('plan')
            if plan:
                self._apply_plan(plan)
            self._start_rpc(job['session'], job['thinking'])
            self.jobs.record_owner(job, self.rpc.process)
            self.resume_payload = resume
            self.pending = self.rpc.send('get_messages')
            self.status.set('Loading saved checkpoint')
        except (KeyError, OSError, RuntimeError, ValueError, psutil.Error) as exc:
            if self.job:
                self._pause_recovery(str(exc))
            else:
                self.status.set('Needs review')
                self._write(self.chat, '\n' + str(exc) + '\n', 'error')

    def _change_context(self, job=None, restore=False):
        self.starting_backend = True
        event = {'type': 'context_profile', 'restore': restore, 'status': self.status.get()}
        self.status.set('Restoring 64k context' if restore else 'Switching Qwen to 128k context')

        def change():
            try:
                if restore:
                    event['server'] = context_switch.restore_idle(self.server, self.jobs)
                else:
                    event['server'], event['fallback'] = context_switch.switch_for_job(self.server, self.jobs, job)
            except (OSError, RuntimeError, ValueError) as exc:
                event['error'] = str(exc)
            self.queue.put(event)

        threading.Thread(target=change, daemon=True).start()

    def _native_available(self, retry):
        try:
            backend.verify_available(self.server, self.external_watch)
        except backend.NativeStopped:
            if retry is None:
                raise
            self._start_native(retry)
            return False
        return True

    def _start_native(self, retry=None):
        self.starting_backend = True
        if retry is not None:
            self.prompt.configure(state='disabled')
        self.status.set('Starting local Qwen' if retry is not None else 'Starting Qwen for recovery')
        self._controls()

        def start():
            event = {'type': 'native_backend', 'retry': retry}
            try:
                with self.server.lock():
                    if backend.hermes_active():
                        if retry is not None:
                            raise RuntimeError('Qwen is reserved by another session.')
                    else:
                        server = backend.Launcher(self.server.directory)
                        server.start()
                        event['server'] = server
            except (OSError, RuntimeError, ValueError, psutil.Error) as exc:
                event['error'] = str(exc)
            self.queue.put(event)

        threading.Thread(target=start, daemon=True).start()

    def _unload_native(self):
        if self.active or self.pending or self.watch or self.recovery_wait or self.starting_backend or self.evidence:
            return
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.starting_backend = True
        previous_status = self.status.get()
        self.status.set('Unloading local Qwen')
        self._controls()

        def unload():
            event = {'type': 'native_unloaded', 'previous_status': previous_status}
            try:
                with self.server.lock():
                    server = backend.Launcher(self.server.directory)
                    if self.jobs and (self.jobs.current() or context_switch.lease_file(self.jobs.directory).exists()):
                        raise RuntimeError('A saved Pi job still needs the local model.')
                    try:
                        backend.verify_available(server, self.external_watch)
                    except backend.NativeStopped:
                        pass
                    else:
                        server.stop()
                    if server.port_owners():
                        raise RuntimeError('The local model port still has a listener. Its owner was left running.')
                    event['server'] = server
            except (OSError, RuntimeError, ValueError, psutil.Error) as exc:
                event['error'] = str(exc)
            self.queue.put(event)

        threading.Thread(target=unload, daemon=True).start()

    def send(self, *, start_model=True):
        if self.active or self.pending or self.watch or self.recovery_wait or self.starting_backend:
            return
        if self.evidence and (self.evidence / 'gui-admission.jsonl').exists():
            self._write(self.chat, '\nThis calibration folder has already recorded its one prompt.\n', 'error')
            return
        prompt = self.prompt.get('1.0', 'end-1c').strip()
        if not prompt:
            return
        try:
            retry = (lambda: self.send(start_model=False)) if start_model and not self.evidence else None
            if not self._native_available(retry):
                return
            payload = self._prompt_payload(prompt)
            self._start_rpc()
            if self.jobs:
                self.pending = self.rpc.send('get_state')
                self.queued_payload = payload
            else:
                self.pending = self.rpc.send('prompt', **payload)
            if self.evidence:
                from hashlib import sha256
                admission = {'submitted_utc': datetime.now(timezone.utc).isoformat(),
                             'pid': self.rpc.process.pid, 'prompt_sha256': sha256(prompt.encode()).hexdigest(),
                             'browser_only': self.browser_only, 'native_status': self.server.status()}
                with (self.evidence / 'gui-admission.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(admission) + '\n')
        except (OSError, RuntimeError, ValueError) as exc:
            self._write(self.chat, '\n' + str(exc) + '\n', 'error')
            return
        self.prompt.delete('1.0', 'end')
        self.pending_prompt = prompt
        self.clear_attachments()
        self.status.set('Starting Pi')
        self._controls()

    def stop(self):
        if self.job and (self.active or self.recovery_wait or self.clarification):
            try:
                self.jobs.stop(self.job)
                if not self.active and not self.pending and not self.clarification:
                    self._settle_job()
                    self._finish('Stopped')
                    return
            except (OSError, ValueError) as exc:
                self._write(self.chat, '\nCould not record Stop. ' + str(exc) + '\n', 'error')
                return
        if self.rpc and (self.active or self.clarification):
            try:
                if identity := self._clear_clarification():
                    self.rpc.send('extension_ui_response', id=identity, cancelled=True)
                self.rpc.send('abort')
                self.status.set('Stopping')
            except OSError as exc:
                self._write(self.chat, '\n' + str(exc) + '\n', 'error')

    def _restore_pending_prompt(self):
        if self.pending_prompt and not self.prompt.get('1.0', 'end-1c').strip():
            self.prompt.insert('1.0', self.pending_prompt)
        self.pending_prompt = None

    def close(self):
        if self.starting_backend:
            messagebox.showinfo('Qwen is busy', 'Wait for the local model operation to finish before closing Pi.')
            return
        if self.rpc and (self.active or self.pending):
            messagebox.showinfo('Pi is running', 'Use Stop and allow the run to settle before closing.')
            return
        if self.rpc:
            self.rpc.close()
        self.root.destroy()

    def new_chat(self):
        if (self.active or self.pending) and self.rpc or self.recovery_wait or self.starting_backend:
            return
        if self.rpc:
            try:
                self.pending = self.rpc.send('new_session')
            except OSError as exc:
                self._write(self.chat, '\n' + str(exc) + '\n', 'error')
                return
        self.watch = None
        self._reset()

    def _reset(self):
        self.active = False
        self.elapsed = self.clock = self.last_usage = None
        self.compactions = 0
        self.plan_steps = []
        self.plan_reason = ''
        self.plan_review_pending = False
        self.last_answer = ''
        self.tasks.clear()
        for card in self.tool_cards.values():
            start, limit, heading, body = card['marks']
            self.chat.mark_unset(start, limit)
            self.chat.tag_delete(heading, body)
        self.tool_cards.clear()
        self.tool_updates.clear()
        self.running_tools.clear()
        for card in self.thought_cards.values():
            self.chat.tag_delete(*card['tags'])
        for tag, _url in self.reply_links:
            self.chat.tag_delete(tag)
        if self.reply_actions:
            self.chat.tag_delete(*self.reply_actions)
        self.thought_cards.clear()
        self.reply_links.clear()
        self.reply_actions.clear()
        self.stream_thoughts.clear()
        self.stream_thought_chunks.clear()
        self._reset_stream_preview()
        self.chat.mark_unset('stream_start', 'stream_limit')
        self.streamed = False
        self.chat_following = True
        self.chat_title.set('New chat')
        self.workspace_title.set(self.workspace.name or str(self.workspace))
        for item in self.activity.get_children():
            self.activity.delete(item)
        for widget in (self.chat, self.details, self.skill_log):
            self._write(widget, '', replace=True)
        self.active_skill.set('Awaiting task')
        self._write(self.plan, 'Pi will post a plan when work starts.', 'pending', replace=True)
        self.clear_attachments()
        self.status.set('Ready')
        self.refresh_files()
        self._controls()

    def open_watch(self):
        if (self.active and self.rpc or self.pending or self.starting_backend
                or not (backend.DEFAULT_WATCH / 'gui-admission.jsonl').is_file()):
            return
        self._reset()
        self.watch = backend.Watch(backend.DEFAULT_WATCH)
        self.external_watch = self.watch
        self.clock = self.watch.started
        self.active = self.watch.active()
        self.status.set('Watching image test')
        self.workspace_title.set(self.watch.directory.parent.name)
        self._controls()

    def choose_folder(self):
        if self.starting_backend:
            return
        folder = filedialog.askdirectory(parent=self.root, title='Choose the Pi workspace', initialdir=self.workspace)
        if folder and Path(folder) != self.workspace:
            if self.rpc:
                self.rpc.close()
                self.rpc = None
                self.rpc_marker = None
            self.workspace = Path(folder)
            self._reset()

    def _build_files(self):
        self._section(self.files_page, 'Workspace files')
        self.files_location = tk.StringVar()
        tk.Label(self.files_page, textvariable=self.files_location, bg=PANEL, fg=MUTED,
                 font=SMALL, anchor='w', justify='left', wraplength=310, padx=13, pady=5).pack(fill='x')
        bar = tk.Frame(self.files_page, bg=PANEL, padx=9, pady=5)
        bar.pack(fill='x')
        self._button(bar, 'Refresh', self.refresh_files).pack(side='left')
        self._button(bar, 'Open workspace', self.open_folder).pack(side='right')
        panel = tk.Frame(self.files_page, bg=PANEL, padx=9, pady=8)
        panel.pack(fill='both', expand=True)
        self.file_tree = ttk.Treeview(panel, columns=('type',), show='tree headings', style='Pi.Treeview')
        self.file_tree.heading('#0', text='Name', anchor='w')
        self.file_tree.heading('type', text='Type', anchor='w')
        self.file_tree.column('#0', minwidth=130, width=205)
        self.file_tree.column('type', width=70, minwidth=55, stretch=False)
        scroll = ttk.Scrollbar(panel, orient='vertical', command=self.file_tree.yview, style='Pi.Vertical.TScrollbar')
        scroll.pack(side='right', fill='y')
        self.file_tree.configure(yscrollcommand=scroll.set)
        self.file_tree.pack(fill='both', expand=True)
        self.file_tree.bind('<<TreeviewOpen>>', self._expand_folder)
        self.file_tree.bind('<Double-Button-1>', self._open_workspace_file)
        self.file_tree.bind('<Return>', self._open_workspace_file)
        self.file_rows = {}
        self.refresh_files()

    def _list_workspace(self, row, folder):
        try:
            root = self.workspace.resolve(strict=True)
            if not folder.resolve(strict=True).is_relative_to(root):
                return
            entries = [(entry, entry.is_dir()) for entry in folder.iterdir()]
            for entry, directory in sorted(entries, key=lambda item: (not item[1], item[0].name.casefold())):
                item = self.file_tree.insert(row, 'end', text=entry.name,
                                             values=('Folder' if directory else entry.suffix.lower().lstrip('.') or 'File',))
                self.file_rows[item] = (entry, directory)
                if directory:
                    self.file_tree.insert(item, 'end', text='Loading…')
        except OSError as error:
            self.files_location.set(str(error))

    def refresh_files(self):
        self.files_location.set(str(self.workspace))
        self.file_tree.delete(*self.file_tree.get_children())
        self.file_rows.clear()
        self._list_workspace('', self.workspace)

    def _expand_folder(self, _event=None):
        row = self.file_tree.focus()
        children = self.file_tree.get_children(row)
        if row in self.file_rows and len(children) == 1 and children[0] not in self.file_rows:
            self.file_tree.delete(children[0])
            self._list_workspace(row, self.file_rows[row][0])

    def _open_workspace_file(self, _event=None):
        row = self.file_tree.focus()
        if row not in self.file_rows:
            return
        path, directory = self.file_rows[row]
        if directory:
            self.file_tree.item(row, open=True)
            self._expand_folder()
            return
        try:
            if path.resolve(strict=True).is_relative_to(self.workspace.resolve(strict=True)):
                os.startfile(path)
        except OSError as error:
            self.files_location.set(str(error))

    def show_files(self):
        if str(self.inspector) not in map(str, self.panes.panes()):
            self.toggle_inspector()
        self.refresh_files()
        self.book.select(self.files_page)

    def toggle_sidebar(self):
        if str(self.sidebar) in map(str, self.panes.panes()):
            self.panes.forget(self.sidebar)
        else:
            self.panes.add(self.sidebar, before=self.center, minsize=180, width=225, stretch='never')

    def toggle_inspector(self):
        if str(self.inspector) in map(str, self.panes.panes()):
            self.panes.forget(self.inspector)
        else:
            self.panes.add(self.inspector, minsize=280, width=340, stretch='never')

    def open_folder(self):
        folder = self.watch.directory.parent / 'public' if self.watch else self.workspace
        try:
            os.startfile(folder)
        except OSError as error:
            self.files_location.set(str(error))

    def open_skill_library(self):
        library = self.state / 'profile/skills'
        library.mkdir(parents=True, exist_ok=True)
        os.startfile(library)

    def open_tools_profile(self):
        directory = self.state / 'profile'
        try:
            directory.mkdir(exist_ok=True)
            os.startfile(directory)
        except OSError as error:
            messagebox.showerror('Plugins and MCP', str(error), parent=self.settings_window)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-image', action='store_true')
    parser.add_argument('--workspace', type=Path, default=backend.ROOT)
    parser.add_argument('--state-dir', type=Path, help='Use an isolated directory for local chats and job state.')
    parser.add_argument('--prompt-file', type=Path, help='Submit one UTF-8 prompt when opening Pi.')
    parser.add_argument('--background-job', action='store_true',
                        help='Start or recover a job in a hidden window, then close after its terminal outcome is saved.')
    parser.add_argument('--browser-session', action='store_true')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--latency-trace', type=Path, help='Save local model, tool and rendering times without chat content.')
    parser.add_argument('--recover-only', action='store_true', help='Reopen Pi only when a saved job exists.')
    parser.add_argument('--allow-wide-context', action='store_true', help='Allow new jobs to use the qualified 128k fallback.')
    options = parser.parse_args()
    if options.background_job and (not (options.prompt_file or options.recover_only)
                                   or options.browser_session or options.evidence or options.watch_image):
        parser.error('--background-job requires --prompt-file or --recover-only with normal Pi tools.')
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_USER_MODEL_ID))
    state = options.state_dir.resolve() if options.state_dir else Path(os.environ['LOCALAPPDATA']) / 'LocalPiGUI'
    pending_recovery = (state / 'recovery/active-job.json').is_file() or context_switch.lease_file(state / 'recovery').is_file()
    startup_prompt = None
    if options.prompt_file:
        if pending_recovery or options.recover_only or options.watch_image:
            parser.error('--prompt-file requires a new Pi job with no saved job to recover.')
        try:
            startup_prompt = options.prompt_file.read_text(encoding='utf-8-sig').strip()
        except (OSError, UnicodeError) as error:
            parser.error(f'Cannot read --prompt-file: {error}')
        if not startup_prompt:
            parser.error('--prompt-file is empty.')
    if options.recover_only and not pending_recovery:
        raise SystemExit(0)
    state.mkdir(parents=True, exist_ok=True)
    instance = (state / 'instance.lock').open('a+b')
    instance.seek(0)
    try:
        msvcrt.locking(instance.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        instance.close()
        if startup_prompt:
            parser.error('Pi is already open. Close the existing window before launching with --prompt-file.')
        if not options.recover_only:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo('Pi is already open', 'Switch to the existing Pi window.')
            root.destroy()
        raise SystemExit(0) from None
    root = tk.Tk()
    if options.background_job:
        root.withdraw()
    if options.evidence:
        options.evidence.mkdir(parents=True, exist_ok=True)
    if options.latency_trace and (options.latency_trace.exists() or not options.latency_trace.parent.is_dir()):
        parser.error('--latency-trace requires a new file in an existing directory.')
    application = App(root, backend.Launcher(backend.ROOT / 'native-qwen'), options.workspace.resolve(),
                      state, browser_only=options.browser_session, evidence=options.evidence,
                      recover_jobs=not (options.browser_session or options.evidence or options.watch_image),
                      allow_wide_context=options.allow_wide_context, latency_trace=options.latency_trace,
                      exit_after_job=options.background_job)
    if (backend.DEFAULT_WATCH / 'gui-admission.jsonl').is_file():
        application.external_watch = backend.Watch(backend.DEFAULT_WATCH)
        if options.watch_image or application.external_watch.active():
            application.open_watch()
    if startup_prompt:
        application.prompt.insert('1.0', startup_prompt)
        root.after_idle(application.send)
    try:
        root.mainloop()
    finally:
        instance.close()
