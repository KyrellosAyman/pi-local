"""Expose the active page of an existing Chrome window through the local Windows driver."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit


def url(value):
    value = (value or '').strip()
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return (f'{parsed.scheme}://{parsed.netloc.lower()}', parsed.path or '/', parsed.query, parsed.fragment)


def active_page(state, allowed_origin):
    if state.get('app_name', '').lower() != 'chrome.exe':
        raise ValueError('The attached window is no longer Google Chrome.')
    elements = state.get('elements', [])
    display = [(e.get('value') or '').strip() for e in elements if e.get('role') == 'Edit'
               and e.get('label') == 'Address and search bar' and not e.get('in_web_content')]
    address = url(display[0]) if len(display) == 1 else None
    if not address:
        raise ValueError('The active Chrome address does not match the approved website.')
    addresses = {address}
    # Chrome can omit the scheme in the address bar. Use the unique page document to resolve it.
    if '://' not in display[0]:
        addresses.add(url('http://' + display[0]))
    if allowed_origin and not any(address[0] == allowed_origin for address in addresses):
        raise ValueError('The active Chrome address does not match the approved website.')
    roots = []
    for element in elements:
        if element.get('role') == 'Document' and not element.get('in_web_content') and element.get('element_index') is not None:
            value = element.get('value') or ''
            if '://' in value:
                address = url(value)
                if address in addresses:
                    roots.append((element, address))
    if len(roots) != 1:
        raise ValueError('The active Chrome address does not identify one page document.')
    root, address = roots[0]
    if allowed_origin and address[0] != allowed_origin:
        raise ValueError('The active Chrome address does not match the approved website.')
    members = {root['element_index']: root}
    for element in elements:
        parent = element.get('parent_index')
        index = element.get('element_index')
        if index is not None and element.get('in_web_content') and parent in members:
            members[index] = element
    return address, root, members


class Driver:
    def __init__(self, executable):
        env = dict(os.environ, CUA_DRIVER_RS_TELEMETRY_ENABLED='0', PYTHONIOENCODING='utf-8')
        env.pop('PI_T03_API_KEY', None)
        self.process = subprocess.Popen([executable, 'mcp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         encoding='utf-8', env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        self.seq = 0
        self.request('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                    'clientInfo': {'name': 'Pi Chrome attachment', 'version': '1.0'}})

    def request(self, method, params):
        self.seq += 1
        request = {'jsonrpc': '2.0', 'id': self.seq, 'method': method, 'params': params}
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        for line in self.process.stdout:
            message = json.loads(line)
            if message.get('id') == self.seq:
                if 'error' in message:
                    raise RuntimeError(message['error']['message'])
                return message['result']
        raise RuntimeError('The local Windows driver exited.')

    def call(self, name, **args):
        result = self.request('tools/call', {'name': name, 'arguments': args})
        if result.get('isError'):
            error = next((c['text'] for c in result['content'] if c['type'] == 'text'), 'Driver action refused.')
            raise RuntimeError(error)
        return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)


def member_frame(element, root, bounds):
    frame = element.get('frame', {})
    if not frame.get('w') or not frame.get('h'):
        return None
    x, y = frame['x'] + frame['w'] / 2, frame['y'] + frame['h'] / 2
    return all(b.get('x', 0) <= x < b.get('x', 0) + b.get(w, 0)
               and b.get('y', 0) <= y < b.get('y', 0) + b.get(h, 0)
               for b, w, h in ((root.get('frame', {}), 'w', 'h'), (bounds, 'width', 'height')))


class ChromeAttachment:
    def __init__(self, driver, allowed_origin, allowed_window=None):
        self.driver = driver
        self.origin = allowed_origin
        self.allowed_window = allowed_window
        self.target = None
        self.snapshot = None

    def observe_window(self, target, screenshot=False):
        result = self.driver.call('get_window_state', **target, tree_format='elements',
                                  max_elements=1400, timeout_ms=3200, include_screenshot=screenshot,
                                  max_image_dimension=1440)
        state = result['structuredContent']
        if any(state.get(k) != v for k, v in target.items()):
            raise ValueError('The Windows driver returned a different window.')
        address, root, members = active_page(state, self.origin)
        return state, address, root, members, result['content']

    def read(self, target_window=None, query=None, screenshot=False, wait_seconds=0):
        if self.allowed_window is not None:
            if target_window is not None and target_window != self.allowed_window:
                raise ValueError('This task is scoped to its approved Chrome window.')
            target_window = self.allowed_window
        if not 0 <= wait_seconds <= 30:
            raise ValueError('Wait must be between 0 and 30 seconds.')
        if wait_seconds:
            time.sleep(wait_seconds)
        if self.target is None:
            windows = self.driver.call('list_windows', app='Chrome', on_screen_only=True)
            matches = []
            for window in windows['structuredContent']['windows']:
                if window.get('app_name', '').lower() != 'chrome.exe' or (
                        target_window is not None and window['window_id'] != target_window):
                    continue
                target = {key: window[key] for key in ('pid', 'window_id')}
                try:
                    view = self.observe_window(target, screenshot)
                except (ValueError, RuntimeError):
                    continue
                if self.origin == 'https://chatgpt.com' and not any(
                        e.get('label') == 'Open profile menu' and e.get('enabled') is not False
                        for e in view[3].values()):
                    continue
                matches.append((target, view))
            if len(matches) != 1:
                ids = [target['window_id'] for target, _ in matches]
                raise ValueError(f'Expected one matching signed-in Chrome window. Matching window IDs: {ids}.')
            self.target, view = matches[0]
            self.origin = view[1][0]
        else:
            if target_window is not None and self.target['window_id'] != target_window:
                raise ValueError('This chat is attached to a different Chrome window.')
            view = self.observe_window(self.target, screenshot)
        state, address, root, members, content = view
        exposed = {}
        lines = []
        for index, e in members.items():
            label = e.get('label', '')
            value = e.get('value', '') if e['role'] in ('Document', 'Edit') else ''
            description = ' '.join(f'{label} {value}'.split())[:800]
            if query and query.casefold() not in description.casefold():
                continue
            visible = member_frame(e, root, state['window_bounds'])
            if description and (visible or not e.get('actions')):
                exposed[index] = e
                lines.append(f"[{index}] {e['role']} {description}" +
                             (' (disabled)' if e.get('enabled') is False else ''))
        self.snapshot = address, exposed
        page = root['value']
        info = f"Attached to Chrome window {self.target['window_id']} at {page}.\n"
        if state.get('truncated'):
            info += 'The accessibility read was partial.\n'
        return text_result(info + '\n'.join(lines) + ('\nNo matching elements.' if not lines else ''), [
            part for part in content if screenshot and part['type'] == 'image'])

    def action(self, element, operation, text=None, key=None, direction=None, amount=3):
        if self.snapshot is None:
            raise ValueError('Read the active Chrome page first.')
        address, old_members = self.snapshot
        previous = old_members.get(element)
        state, current, root, members, _ = self.observe_window(self.target)
        e = members.get(element)
        fields = ('role', 'label', 'frame', 'parent_index')
        if (address != current or not previous or not e or
                any(previous.get(field) != e.get(field) for field in fields) or e.get('enabled') is False):
            raise ValueError('The Chrome page or control changed. Read it again before acting.')
        if not member_frame(e, root, state['window_bounds']):
            raise ValueError('That element is outside the current page viewport.')
        args = dict(self.target, delivery_mode='foreground', element_token=e['element_token'])
        self.snapshot = None
        if operation == 'click':
            result = self.driver.call('click', **args)
        elif operation == 'type' and e.get('role') == 'Edit' and isinstance(text, str) and 0 < len(text) <= 8000:
            result = self.driver.call('type_text', **args, text=text)
        elif operation == 'key' and key in {'Enter', 'Escape', 'Space', 'PageDown', 'PageUp', 'Backspace'}:
            result = self.driver.call('press_key', **args, key=key)
        elif operation == 'scroll' and direction in {'up', 'down'} and 1 <= amount <= 12:
            result = self.driver.call('scroll', **args, direction=direction, amount=amount)
        else:
            raise ValueError('Use a visible control and an operation matching its type.')
        return text_result(result['content'][0]['text'] + '\nRead the page again to confirm the effect.')


def text_result(text, extra=()):
    return {'content': [{'type': 'text', 'text': text}, *extra]}


def field(kind, description, **extra):
    return {'type': kind, 'description': description, **extra}


TOOLS = [
    {'name': 'get_chrome_state', 'description': 'Attach to and read the current website in existing signed-in Google Chrome. Returns live page controls and their element numbers. Use after each action, and query for a control if needed.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': {
         'target_window': field('integer', 'Chrome window ID, needed only if several match.'),
         'query': field('string', 'Optional text filter.'),
         'screenshot': field('boolean', 'Include a screenshot when visual inspection is needed.'),
         'wait_seconds': field('number', 'Optional wait before reading, up to 30 seconds.', minimum=0, maximum=30)}}},
    {'name': 'chrome_action', 'description': 'Act on one element from the last live Chrome page read. Click buttons, type in an Edit, press a named key on an element, or scroll its viewport. Read the page again after each action.',
     'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['element', 'operation'], 'properties': {
         'element': field('integer', 'Bracketed number from get_chrome_state.'),
         'operation': field('string', 'Kind of action.', enum=['click', 'type', 'key', 'scroll']),
         'text': field('string', 'Text to enter in an Edit for the type operation.'),
         'key': field('string', 'Key for the key operation.', enum=['Enter', 'Escape', 'Space', 'PageDown', 'PageUp', 'Backspace']),
         'direction': field('string', 'Scroll direction.', enum=['up', 'down']),
         'amount': field('integer', 'Number of scroll ticks.', minimum=1, maximum=12)}}},
]


def serve(executable, origin, window=None):
    driver = None
    chrome = None
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if 'id' not in request:
                continue
            response = {'jsonrpc': '2.0', 'id': request['id']}
            method = request['method']
            if method == 'initialize':
                response['result'] = {'protocolVersion': request['params']['protocolVersion'],
                                      'capabilities': {'tools': {}}, 'serverInfo': {'name': 'pi-chrome', 'version': '1.0'}}
            elif method == 'tools/list':
                response['result'] = {'tools': TOOLS}
            elif method == 'tools/call':
                try:
                    if chrome is None:
                        driver = Driver(executable)
                        chrome = ChromeAttachment(driver, origin, window)
                    name = request['params']['name']
                    handler = {'get_chrome_state': chrome.read, 'chrome_action': chrome.action}[name]
                    response['result'] = handler(**request['params'].get('arguments', {}))
                except (KeyError, TypeError, ValueError, RuntimeError, OSError) as error:
                    response['result'] = dict(text_result(str(error)), isError=True)
            else:
                response['error'] = {'code': -32601, 'message': 'Unsupported MCP method.'}
            print(json.dumps(response), flush=True)
    finally:
        if driver is not None:
            driver.close()


if __name__ == '__main__':
    window = os.environ.get('PI_CHROME_WINDOW')
    serve(Path(sys.argv[1]), os.environ.get('PI_CHROME_ORIGIN'), int(window) if window else None)
