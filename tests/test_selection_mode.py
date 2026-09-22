import os
import unittest
from unittest.mock import patch

from core import tasks
from utils import config as config_module


class _Page:
    def wait_for_timeout(self, _ms):
        pass


class _Context:
    def __init__(self):
        self.page = _Page()

    def set_default_navigation_timeout(self, _timeout):
        pass

    def set_default_timeout(self, _timeout):
        pass

    def new_page(self):
        return self.page

    def add_cookies(self, _cookies):
        pass

    def close(self):
        pass


class _Browser:
    def new_context(self):
        return _Context()


class _IM:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.last_scan = {"stopped": "caller-break", "select_failed": []}
        self.detached = False
        self.__class__.instances.append(self)

    def wait_ready(self):
        return {"status": tasks.STATUS_READY, "user_id": "account"}

    def iter_find_and_select(self, targets):
        for target in targets:
            yield {"display": target, "conv_id": f"conv:{target}"}

    def fold_groups(self):
        return {}

    def prepare_native_sticker(self, name):
        return {"name": name, "resource_key": "sticker-key"}

    def detach(self):
        self.detached = True


class SelectionModeTests(unittest.TestCase):
    def test_selection_only_never_reads_state_or_sends(self):
        _IM.instances.clear()
        with patch.object(tasks, "DouyinIM", _IM), patch.object(
            tasks.delivery_state,
            "get",
            side_effect=AssertionError("selection-only must not read send state"),
        ), patch.object(
            tasks,
            "build_message",
            side_effect=AssertionError("selection-only must not build a message"),
        ):
            tasks.do_user_task(
                _Browser(), "account", [], ["Rick", "Ken"], selection_only=True
            )

        self.assertTrue(_IM.instances[0].detached)

    def test_sticker_probe_never_reads_state_or_sends(self):
        _IM.instances.clear()
        with patch.object(tasks, "DouyinIM", _IM), patch.object(
            tasks.delivery_state,
            "get",
            side_effect=AssertionError("sticker probe must not read send state"),
        ), patch.object(
            tasks,
            "build_message",
            side_effect=AssertionError("sticker probe must not build a message"),
        ):
            tasks.do_user_task(
                _Browser(), "account", [], ["Rick", "Ken"], sticker_probe=True
            )

        self.assertTrue(_IM.instances[0].detached)

    def test_normal_mode_empty_targets_fails_loudly(self):
        """正式模式下没有配置目标好友也必须明确失败，不能被当成"无事可做"悄悄跳过成功。"""
        _IM.instances.clear()
        with patch.object(tasks, "DouyinIM", _IM):
            with self.assertRaises(RuntimeError):
                tasks.do_user_task(_Browser(), "account", [], [])

        self.assertTrue(_IM.instances[0].detached)

    def test_main_dispatches_selection_only(self):
        import main
        with patch("sys.argv", ["main.py", "--selection-only"]), patch("core.tasks.runTasks") as mock_run:
            main.main()
            mock_run.assert_called_once_with(selection_only=True)

        with patch("sys.argv", ["main.py", "task", "--selection-only"]), patch("core.tasks.runTasks") as mock_run:
            main.main()
            mock_run.assert_called_once_with(selection_only=True)

    def test_main_rejects_unrecognized_argv_instead_of_running_task(self):
        """拼写错误的子命令必须报错退出，绝不能悄悄落到正式发送模式。"""
        import main
        with patch("sys.argv", ["main.py", "selction-only"]), patch.dict(
            os.environ
        ), patch("core.tasks.runTasks") as mock_run:
            os.environ.pop("RUN_MODE", None)
            with self.assertRaises(SystemExit) as ctx:
                main.main()
            self.assertEqual(ctx.exception.code, 2)
            mock_run.assert_not_called()

    def test_main_rejects_unrecognized_run_mode_when_no_argv(self):
        import main
        with patch("sys.argv", ["main.py"]), patch.dict(
            os.environ, {"RUN_MODE": "banana"}
        ), patch("core.tasks.runTasks") as mock_run:
            with self.assertRaises(SystemExit) as ctx:
                main.main()
            self.assertEqual(ctx.exception.code, 2)
            mock_run.assert_not_called()


class ConfigUnitTests(unittest.TestCase):
    def tearDown(self):
        config_module.config = None

    def test_friend_wait_uses_seconds_and_warns_on_old_millisecond_scale(self):
        with patch.dict(os.environ, {"FRIEND_LIST_WAIT_TIME": "2"}, clear=False):
            config_module.config = None
            self.assertEqual(config_module.get_config()["friendListSettleMs"], 2000)

        with patch.dict(os.environ, {"FRIEND_LIST_WAIT_TIME": "2000"}, clear=False), patch.object(
            config_module.logger, "warning"
        ) as warning:
            config_module.config = None
            self.assertEqual(
                config_module.get_config()["friendListSettleMs"], 2_000_000
            )
            warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
