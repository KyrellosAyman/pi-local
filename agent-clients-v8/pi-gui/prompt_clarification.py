"""Durable answers and the native chat card for a Pi clarification request."""
import json
import re
from textwrap import fill
import tkinter as tk
from tkinter import ttk

from job_recovery import atomic_json, read_json


PREFIX = 'PI_CLARIFICATION_V1\n'


def has_saved_clarification(jobs, job):
    return (jobs.directory / (job['id'] + '.clarification.json')).is_file()


def save_request(event, jobs, job):
    if event.get('method') != 'input' or not jobs or not job or jobs.current() != job:
        raise ValueError('Clarification does not belong to the active Pi task.')
    record = json.loads(event['title'][len(PREFIX):])
    if not isinstance(record, dict) or set(record) != {'job', 'session', 'brief', 'checks', 'questions', 'answers', 'index'}:
        raise ValueError('Invalid clarification request.')
    index = record.pop('index')
    questions, answers = record['questions'], record['answers']
    if (record['job'] != job['id'] or record['session'] != job['session'] or
            not isinstance(record['brief'], str) or not record['brief'].strip() or
            not isinstance(record['checks'], list) or not all(isinstance(item, str) for item in record['checks']) or
            not isinstance(questions, list) or not 1 <= len(questions) <= 2 or
            not isinstance(answers, list) or type(index) is not int or index != len(answers) or index >= len(questions)):
        raise ValueError('Invalid clarification questions or task identity.')
    for question in questions:
        options = question.get('choices') if isinstance(question, dict) else None
        if (not isinstance(question, dict) or not isinstance(question.get('question'), str) or
                not question['question'].strip() or len(question['question']) > 280 or
                not isinstance(options, list) or len(options) != 3 or
                not all(isinstance(item, str) and item.strip() and len(item) <= 180 for item in options) or
                len({item.strip().lower() for item in options}) != 3):
            raise ValueError('A clarification question must have three distinct choices.')
    path = jobs.directory / (job['id'] + '.clarification.json')
    previous = read_json(path)
    if previous is None:
        if answers:
            raise ValueError('No saved clarification answers exist for this task.')
        atomic_json(path, record)
    elif previous != record:
        raise ValueError('This clarification changed after Pi displayed it.')
    return path, record, questions[index]


def save_answer(path, record, answer):
    if read_json(path) != record:
        raise ValueError('The clarification has already changed.')
    if (not isinstance(answer, dict) or not (
            set(answer) == {'choice'} and type(answer['choice']) is int and 0 <= answer['choice'] < 3 or
            set(answer) == {'text'} and isinstance(answer['text'], str) and answer['text'].strip())):
        raise ValueError('Select a choice or type your answer.')
    atomic_json(path, {**record, 'answers': [*record['answers'], answer]})


class ClarificationCard(ttk.Frame):
    def __init__(self, parent, question, submit, width):
        super().__init__(parent, padding=(13, 10), style='Clarification.TFrame')
        self.answer = tk.StringVar(self)
        self.choices = []
        ttk.Label(self, text=question['question'], wraplength=width, style='Clarification.TLabel',
                  font=('Segoe UI Semibold', 11)).pack(anchor='w', pady=(0, 6))
        for index, value in enumerate(question['choices']):
            if index == 0:
                label = re.sub(r'\s*\((?:default recommendation|recommendation|recommended)\)\s*$', '', value, flags=re.I)
                value = (label or value) + ' (Recommended)'
            text = fill(value, width=max(26, width // 9))
            option = ttk.Button(self, text=text, style='ClarificationChoice.TButton',
                                command=lambda choice=index: submit({'choice': choice}))
            option.pack(anchor='w', fill='x', pady=2)
            self.choices.append(option)
        ttk.Label(self, text='Or write your answer', style='Clarification.TLabel').pack(anchor='w', pady=(8, 3))
        row = ttk.Frame(self, style='Clarification.TFrame')
        row.pack(anchor='w', fill='x')
        self.entry = ttk.Entry(row, textvariable=self.answer, width=max(22, width // 9 - 9), style='Clarification.TEntry')
        self.entry.pack(side='left', fill='x', expand=True)
        self.button = ttk.Button(row, text='Send', command=lambda: submit({'text': self.answer.get().strip()}), style='Send.TButton')
        self.button.pack(side='right', padx=(6, 0))
        self.button.state(['disabled'])
        self.answer.trace_add('write', self._ready)
        self.entry.bind('<Return>', lambda _event: self.button.invoke() or 'break')

    def _ready(self, *_):
        self.button.state(['!disabled'] if self.answer.get().strip() else ['disabled'])
