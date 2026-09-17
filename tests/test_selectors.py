import unittest
from unittest.mock import patch

import core.tasks as tasks


class SelectorTests(unittest.TestCase):
    def test_conversation_item_selector_uses_class_selector_so_pinned_items_match(self):
        self.assertEqual(tasks.CONVERSATION_ITEM_SELECTOR, '.conversationConversationItemwrapper')
        self.assertEqual(tasks.CONVERSATION_TITLE_SELECTOR, '.conversationConversationItemtitle')
        self.assertEqual(tasks.CONVERSATION_LIST_SELECTOR, '.conversationConversationListwrapper')
        self.assertEqual(tasks.CHAT_EDITOR_SELECTOR, '.messageEditorimChatEditorContainer')
        self.assertEqual(tasks.SEND_BUTTON_SELECTOR, '.e2e-send-msg-btn')
        self.assertEqual(tasks.RIGHT_PANEL_TITLE_SELECTOR, '.RightPanelHeadertitle')
        self.assertEqual(tasks.TRUST_LOGIN_DIALOG_SELECTOR, '.trust-login-dialog-mask')

    def test_generator_activates_target_before_yielding(self):
        class FakeSpan:
            def inner_text(self):
                return 'Ken'

        class FakeElement:
            def locator(self, selector):
                return FakeSpan()

        class FakeItems:
            def __init__(self, element):
                self.element = element

            def all(self):
                return [self.element]

        class FakePage:
            def __init__(self, element):
                self.items = FakeItems(element)

            def locator(self, selector):
                return self.items

        element = FakeElement()
        page = FakePage(element)
        generator = tasks.scroll_and_select_user(page, 'account', ['Ken'])

        with patch.object(tasks, 'activate_conversation') as activate:
            self.assertEqual(next(generator), 'Ken')
            activate.assert_called_once_with(page, element, 'account', 'Ken')
            with self.assertRaises(StopIteration):
                next(generator)

    def test_activate_conversation_retries_until_right_panel_matches(self):
        class FakeElement:
            def __init__(self):
                self.dispatch_calls = []

            def dispatch_event(self, event, payload):
                self.dispatch_calls.append((event, payload))

        element = FakeElement()
        page = object()
        with patch.object(tasks, 'dismiss_trust_login_dialog', return_value=False), \
             patch.object(tasks, 'wait_for_active_conversation', side_effect=[False, True]), \
             patch.object(tasks, 'get_active_conversation_name', side_effect=['Peter', 'Peter']), \
             patch.object(tasks.time, 'sleep'):
            tasks.activate_conversation(page, element, 'account', 'Ken')

        self.assertEqual(
            element.dispatch_calls,
            [
                ('mousedown', {'button': 0, 'buttons': 1}),
                ('mousedown', {'button': 0, 'buttons': 1}),
            ],
        )

    def test_activate_conversation_fails_closed_when_target_not_confirmed(self):
        class FakeElement:
            def __init__(self):
                self.dispatch_calls = 0

            def dispatch_event(self, event, payload):
                self.dispatch_calls += 1

        element = FakeElement()
        retries = max(tasks.config['taskRetryTimes'], 1)
        with patch.object(tasks, 'dismiss_trust_login_dialog', return_value=False), \
             patch.object(tasks, 'wait_for_active_conversation', return_value=False), \
             patch.object(tasks, 'get_active_conversation_name', return_value='Ken'), \
             patch.object(tasks.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, '为避免误发已停止任务'):
                tasks.activate_conversation(object(), element, 'account', 'Rick')

        self.assertEqual(element.dispatch_calls, retries)

    def test_active_conversation_name_is_normalized(self):
        class FakeHeader:
            def count(self):
                return 1

            @property
            def first(self):
                return self

            def is_visible(self):
                return True

            def inner_text(self):
                return '今心（多伦多）'

        class FakePage:
            def locator(self, selector):
                self.selector = selector
                return FakeHeader()

        page = FakePage()
        self.assertEqual(tasks.get_active_conversation_name(page), '今心(多伦多)')
        self.assertEqual(page.selector, tasks.RIGHT_PANEL_TITLE_SELECTOR)

    def test_verification_text_removes_douyin_emoji_codes(self):
        message = (
            '[盖瑞]今日火花[加一]\\n'
            '—— [右边] 每日一言 [左边] ——\\n'
            '青枫江上秋帆远，白帝城边古木疏。 —— 高适'
        )
        self.assertEqual(
            tasks.verification_text_from_message(message),
            '今日火花 —— 每日一言 —— 青枫江上秋帆远,白帝城边古木疏。 —— 高适',
        )

    def test_record_verification_prefers_visible_bubble_text(self):
        record = {
            'message': '[盖瑞]今日火花[加一]',
            'verification_text': '今日火花',
            'effective_text': '盖瑞今日火花加一',
        }
        self.assertEqual(
            tasks.verification_text_from_record(record),
            '今日火花',
        )

    def test_type_message_uses_insert_text_to_preserve_emoji_shortcodes(self):
        class FakeKeyboard:
            def __init__(self):
                self.inserted = []
                self.pressed = []

            def insert_text(self, text):
                self.inserted.append(text)

            def press(self, key):
                self.pressed.append(key)

        class FakeInput:
            def __init__(self):
                self.focus_calls = 0
                self.reads = 0

            @property
            def first(self):
                return self

            def focus(self):
                self.focus_calls += 1

            def inner_text(self):
                self.reads += 1
                # The implementation checks emptiness twice before typing.
                # Final read mirrors what Slate exposes after preserving raw
                # emoji shortcodes.
                return '\u200b' if self.reads <= 2 else '[盖瑞]今日火花[加一]\n正文'

        class FakePage:
            def __init__(self):
                self.keyboard = FakeKeyboard()
                self.input = FakeInput()

            def wait_for_selector(self, *args, **kwargs):
                return None

            def locator(self, selector):
                self.selector = selector
                return self.input

        page = FakePage()
        _, effective = tasks.type_message_into_editor(
            page,
            'account',
            'Rick',
            '[盖瑞]今日火花[加一]\\n正文',
        )

        self.assertEqual(page.selector, tasks.CHAT_EDITABLE_SELECTOR)
        self.assertEqual(page.keyboard.inserted, ['[盖瑞]今日火花[加一]\n正文'])
        self.assertEqual(page.keyboard.pressed, [])
        self.assertEqual(effective, '[盖瑞]今日火花[加一] 正文')

    def test_send_button_uses_one_native_dom_click(self):
        class FakeButton:
            def __init__(self):
                self.events = []

            def count(self):
                return 1

            @property
            def first(self):
                return self

            def is_visible(self):
                return True

            def dispatch_event(self, event):
                self.events.append(event)

        class FakePage:
            def __init__(self):
                self.button = FakeButton()

            def locator(self, selector):
                self.selector = selector
                return self.button

        page = FakePage()
        tasks.click_send_button_once(page)
        self.assertEqual(page.selector, tasks.SEND_BUTTON_SELECTOR)
        self.assertEqual(page.button.events, ['click'])

    def test_send_button_dispatch_failure_is_explicitly_safe_to_retry(self):
        class FakeButton:
            def count(self):
                return 1

            @property
            def first(self):
                return self

            def is_visible(self):
                return True

            def dispatch_event(self, event):
                raise RuntimeError('not dispatched')

        class FakePage:
            def locator(self, selector):
                return FakeButton()

        with self.assertRaises(tasks.SendDispatchError):
            tasks.click_send_button_once(FakePage())

    def test_send_confirmation_never_retries_just_because_draft_remains(self):
        class FakeInput:
            def inner_text(self):
                return 'still here'

        page = object()
        with patch.object(tasks, 'get_active_conversation_name', return_value='Rick'), \
             patch.object(tasks, 'click_send_button_once') as click, \
             patch.object(tasks, 'wait_for_outgoing_message', return_value=False):
            ok = tasks.send_and_confirm_once(
                page,
                FakeInput(),
                'account',
                'Rick',
                'message',
                0,
                3,
            )

        self.assertFalse(ok)
        self.assertEqual(click.call_count, 1)

    def test_send_confirmation_never_retries_after_editor_is_consumed(self):
        class FakeInput:
            def inner_text(self):
                return '\u200b'

        page = object()
        with patch.object(tasks, 'get_active_conversation_name', return_value='Rick'), \
             patch.object(tasks, 'click_send_button_once') as click, \
             patch.object(tasks, 'wait_for_outgoing_message', side_effect=[False, False]):
            ok = tasks.send_and_confirm_once(
                page,
                FakeInput(),
                'account',
                'Rick',
                'message',
                0,
                3,
            )

        self.assertFalse(ok)
        self.assertEqual(click.call_count, 1)


if __name__ == '__main__':
    unittest.main()
