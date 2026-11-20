"""Exercise the Chrome page proof without a desktop or a model."""
from copy import deepcopy

from chrome_attachment import ChromeAttachment, active_page

ORIGIN = 'https://chatgpt.com'


def node(index, role, label, value=None, parent=None, web=False):
    return {'element_index': index, 'role': role, 'label': label, 'value': value,
            'parent_index': parent, 'in_web_content': web,
            'frame': {'x': 150, 'y': 250, 'w': 80, 'h': 40}, 'element_token': f's00000001:{index}'}


def refuses(fn, message):
    try:
        fn()
    except ValueError as error:
        assert message in str(error), error
    else:
        raise AssertionError('Unsafe Chrome target was accepted.')


class FixtureDriver:
    def __init__(self):
        self.actions = []
        self.state = {'app_name': 'chrome.exe', 'pid': 123, 'window_id': 456,
                      'window_bounds': {'x': 0, 'y': 0, 'width': 500, 'height': 500},
                      'elements': [
                          node(1, 'Document', 'stale', 'https://example.org/'),
                          node(2, 'Button', 'Foreign page action', parent=1, web=True),
                          node(3, 'Edit', 'Address and search bar', 'chatgpt.com'),
                          node(4, 'Document', 'ChatGPT', ORIGIN + '/'),
                          node(5, 'Button', 'Open profile menu', parent=4, web=True),
                          node(6, 'Edit', 'Ask ChatGPT', parent=4, web=True),
                      ]}

    def call(self, method, **kwargs):
        if method == 'list_windows':
            return {'structuredContent': {'windows': [{'pid': 123, 'window_id': 456, 'app_name': 'chrome.exe'}]}}
        if method == 'get_window_state':
            return {'structuredContent': deepcopy(self.state), 'content': []}
        self.actions.append((method, kwargs))
        return {'content': [{'type': 'text', 'text': 'fixture dispatched'}]}


if __name__ == '__main__':
    driver = FixtureDriver()
    chrome = ChromeAttachment(driver, ORIGIN, 456)
    refuses(lambda: chrome.read(target_window=789), 'approved Chrome window')
    text = chrome.read()['content'][0]['text']
    assert 'Ask ChatGPT' in text and 'Foreign page action' not in text
    refuses(lambda: chrome.action(3, 'type', text='location bar'), 'control changed')
    chrome.read(query='Ask ChatGPT')
    refuses(lambda: chrome.action(5, 'click'), 'control changed')
    driver.state['elements'][2]['value'] = 'chatgpt.com.evil.test'
    refuses(lambda: chrome.action(6, 'type', text='incorrect origin'), 'approved website')
    driver.state['elements'][2]['value'] = 'chatgpt.com'
    driver.state['elements'].append(node(7, 'Document', 'Duplicate', ORIGIN + '/'))
    refuses(lambda: active_page(driver.state, ORIGIN), 'one page document')
    driver.state['elements'].pop()
    assert driver.actions == []
    chrome.read()
    chrome.action(6, 'type', text='valid')
    assert driver.actions == [('type_text', {'pid': 123, 'window_id': 456, 'text': 'valid',
                                            'element_token': 's00000001:6', 'delivery_mode': 'foreground'})]
    refuses(lambda: chrome.action(6, 'type', text='duplicate'), 'Read the active')
    local = 'http://127.0.0.1:10218'
    state = {'app_name': 'chrome.exe', 'elements': [
        node(1, 'Edit', 'Address and search bar', '127.0.0.1:10218/review?cut=1#handoff'),
        node(2, 'Document', 'Review', local + '/review?cut=1#handoff'),
    ]}
    assert active_page(state, None)[0] == (local, '/review', 'cut=1', 'handoff')
    assert active_page(state, local)[1]['element_index'] == 2
    https = 'https://127.0.0.1:10218'
    refuses(lambda: active_page(state, https), 'approved website')
    state['elements'].append(node(3, 'Document', 'Stale HTTPS root', https + '/review?cut=1#handoff'))
    refuses(lambda: active_page(state, local), 'one page document')
    state['elements'].pop()
    state['elements'][0]['value'] = https + '/review?cut=1#handoff'
    refuses(lambda: active_page(state, None), 'one page document')
    state['elements'][0]['value'] = '127.0.0.1:10218/review?cut=2#handoff'
    refuses(lambda: active_page(state, None), 'one page document')
    state['elements'][0]['value'] = '127.0.0.1:10219/review?cut=1#handoff'
    refuses(lambda: active_page(state, None), 'one page document')
    state['elements'][0]['value'] = '127.0.0.1:10218/review?cut=1#other'
    refuses(lambda: active_page(state, None), 'one page document')
    print('Passed active document, pinned window, foreign origin, filtered controls, duplicate roots and one-action snapshot checks.')
