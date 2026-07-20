import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PLUGIN_REPO = Path(__file__).resolve().parents[3]
PLUGIN_DIR = PLUGIN_REPO / "plugins.v2" / "saferemovelink"
PLUGIN_INIT_FILE = PLUGIN_DIR / "__init__.py"
PACKAGE_FILE = PLUGIN_REPO / "package.v2.json"


class FakeClock:
    """提供可控的墙上时钟和单调时钟。"""

    def __init__(self) -> None:
        """从固定时间初始化测试时钟。"""
        self.value = 1_700_000_000.0

    def time(self) -> float:
        """返回当前墙上时间。"""
        return self.value

    def monotonic(self) -> float:
        """返回当前单调时间。"""
        return self.value

    def advance(self, seconds: float) -> None:
        """推进测试时钟。"""
        self.value += seconds

    def wait(self, event, timeout: float) -> bool:
        """推进等待时长并返回停止事件状态。"""
        self.advance(timeout)
        return event.is_set()


@pytest.fixture
def deletion_module():
    """从权威本地插件源加载并隔离删除队列模块。"""
    module_name = "safe_remove_link_deletion_for_tests"
    module_path = PLUGIN_DIR / "deletion.py"
    assert module_path.exists(), "SafeRemoveLink 删除队列模块尚未实现"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)


@pytest.fixture
def plugin_module():
    """从权威本地插件源加载并隔离插件入口模块。"""
    module_name = "safe_remove_link_plugin_for_tests"
    assert PLUGIN_INIT_FILE.exists(), "SafeRemoveLink 插件入口尚未实现"
    sys.modules.pop(module_name, None)
    sys.modules.pop(f"{module_name}.deletion", None)
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_INIT_FILE,
        submodule_search_locations=[PLUGIN_DIR.as_posix()],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop(f"{module_name}.deletion", None)


def _task_payload(status: str = "pending") -> dict:
    """构造一项可持久化的删除任务。"""
    return {
        "task_id": "u115:/media/a",
        "strm_path": "/strm/a.strm",
        "storage_type": "u115",
        "storage_path": "/media/a",
        "status": status,
        "attempts": 1,
        "next_run_at": 0,
        "created_at": 1,
        "updated_at": 1,
        "last_error": "",
    }


def _fail_current_task(queue, clock: FakeClock) -> None:
    """让当前任务完成首次执行及三次退避重试。"""
    assert queue.run_once() is True
    for delay in (30, 60, 120):
        clock.advance(delay)
        assert queue.run_once() is True


def _collect_text_values(value) -> list[str]:
    """递归收集 Vuetify JSON 中可见文本。"""
    texts = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "title", "label"}:
                texts.append(str(item))
            texts.extend(_collect_text_values(item))
    elif isinstance(value, list):
        for item in value:
            texts.extend(_collect_text_values(item))
    return texts


def test_deletion_module_exists() -> None:
    """本地插件源应提供独立的 115 删除队列模块。"""
    assert (PLUGIN_DIR / "deletion.py").exists()


def test_plugin_source_is_standalone_and_named_consistently() -> None:
    """新插件应拥有独立源码且不导入已安装 RemoveLink。"""
    assert PLUGIN_INIT_FILE.exists()
    source = PLUGIN_INIT_FILE.read_text(encoding="utf-8")
    assert "class SafeRemoveLink(_PluginBase):" in source
    assert "app.plugins.removelink" not in source
    assert "class RemoveLink(" not in source
    assert "def update_state(" in source
    assert "def updateState(" not in source


def test_all_new_functions_and_public_classes_have_chinese_docstrings() -> None:
    """插件新增函数、方法和公开类必须具备中文 docstring。"""
    assert PLUGIN_INIT_FILE.exists()
    for path in (PLUGIN_INIT_FILE, PLUGIN_DIR / "deletion.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            if isinstance(node, ast.ClassDef) and node.name.startswith("_"):
                continue
            docstring = ast.get_docstring(node)
            assert docstring, f"{path.name}:{node.lineno} {node.name} 缺少 docstring"
            assert any(
                "\u4e00" <= char <= "\u9fff" for char in docstring
            ), f"{path.name}:{node.lineno} {node.name} 缺少中文 docstring"


def test_all_new_public_functions_have_type_annotations() -> None:
    """插件新增公开函数和方法必须完整标注参数及返回类型。"""
    assert PLUGIN_INIT_FILE.exists()
    for path in (PLUGIN_INIT_FILE, PLUGIN_DIR / "deletion.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            for argument in (*node.args.posonlyargs, *node.args.args):
                if argument.arg in {"self", "cls"}:
                    continue
                assert argument.annotation is not None, (
                    f"{path.name}:{node.lineno} {node.name} 参数 "
                    f"{argument.arg} 缺少类型标注"
                )
            assert node.returns is not None, (
                f"{path.name}:{node.lineno} {node.name} 缺少返回类型"
            )


@pytest.mark.parametrize("storage_type", ["u115", "U115", "115网盘Plus"])
def test_u115_strm_event_only_enqueues_without_storage_delete(
    plugin_module,
    storage_type: str,
) -> None:
    """115 STRM 删除事件应只入队并启动单消费者。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    calls = []
    plugin._u115_queue = SimpleNamespace(
        enqueue=lambda *args: calls.append(("enqueue", *args)) or True
    )
    plugin._ensure_u115_worker = lambda: calls.append(("worker",))
    plugin._get_storage_path_from_strm = lambda _path: (
        storage_type,
        "/media/a",
    )
    plugin._execute_strm_deletion = lambda *_args: calls.append(("delete",))

    plugin.handle_strm_deleted(Path("/strm/a.strm"))

    assert calls == [
        ("enqueue", "/strm/a.strm", storage_type, "/media/a"),
        ("worker",),
    ]


def test_non_u115_strm_event_uses_original_delete_flow(plugin_module) -> None:
    """非 115 STRM 删除事件应继续执行原同步清理流程。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    calls = []
    plugin._get_storage_path_from_strm = lambda _path: (
        "alist",
        "/media/a",
    )
    plugin._execute_strm_deletion = (
        lambda *args: calls.append(args) or (True, "ok")
    )

    plugin.handle_strm_deleted(Path("/strm/a.strm"))

    assert calls == [(Path("/strm/a.strm"), "alist", "/media/a")]


def test_duplicate_u115_event_does_not_restart_worker(plugin_module) -> None:
    """重复的 115 删除事件不应反复唤起工作者。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    calls = []
    plugin._u115_queue = SimpleNamespace(enqueue=lambda *_args: False)
    plugin._ensure_u115_worker = lambda: calls.append("worker")
    plugin._get_storage_path_from_strm = lambda _path: (
        "u115",
        "/media/a",
    )

    plugin.handle_strm_deleted(Path("/strm/a.strm"))

    assert calls == []


def test_init_restores_queue_before_starting_worker(
    plugin_module,
    monkeypatch,
) -> None:
    """插件启用时应先恢复执行中任务，再启动单消费者。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    persisted = {"tasks": [_task_payload(status="processing")]}
    calls = []
    plugin.get_data = lambda key: persisted if key == "u115_deletion_queue" else None
    plugin.save_data = lambda key, value: calls.append(("save", key, value))
    plugin._ensure_u115_worker = lambda: calls.append(("worker",))
    plugin.update_config = lambda _config: True
    monkeypatch.setattr(
        plugin_module,
        "TransferHistoryOper",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        plugin_module,
        "StorageChain",
        lambda: SimpleNamespace(),
    )

    plugin.init_plugin(
        {
            "enabled": True,
            "notify": False,
            "monitor_dirs": "",
            "monitor_strm_deletion": False,
            "u115_queue_interval": 30,
        }
    )

    state = plugin._u115_queue.snapshot()
    assert state["tasks"][0]["status"] == "pending"
    assert calls[-1] == ("worker",)


def test_delete_storage_item_routes_u115_through_delete_slot(plugin_module) -> None:
    """115 主文件和附属文件删除都应通过同一个删除槽。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    calls = []
    plugin._storagechain = SimpleNamespace(
        delete_file=lambda item: calls.append(("delete", item.path)) or True
    )
    plugin._u115_queue = SimpleNamespace(
        execute_delete=lambda operation: calls.append(("slot",)) or operation()
    )
    file_item = SimpleNamespace(storage="u115", path="/media/a.mkv")

    assert plugin._delete_storage_item(file_item) is True
    assert calls == [("slot",), ("delete", "/media/a.mkv")]


def test_sidecar_failure_does_not_replay_successful_main_delete(
    plugin_module,
) -> None:
    """主媒体删除成功后附属清理异常不得把任务改判为失败。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    delete_calls = []
    plugin._find_storage_media_file = lambda *_args: SimpleNamespace(
        storage="u115",
        path="/media/a.mkv",
    )
    plugin._delete_storage_item = (
        lambda item: delete_calls.append(item.path) or True
    )
    plugin._delete_scrap_infos = True
    plugin.delete_scrap_infos = lambda _path: None
    plugin._delete_storage_scrap_files = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("sidecar failed")
    )
    plugin._delete_storage_empty_folders = lambda *_args: 0
    plugin._delete_history = False
    plugin._notify = False

    result = plugin._execute_strm_deletion(
        Path("/strm/a.strm"),
        "u115",
        "/media/a",
    )

    assert result[0] is True
    assert delete_calls == ["/media/a.mkv"]


def test_stop_service_stops_u115_queue_without_draining_pending_tasks(
    plugin_module,
) -> None:
    """停止插件时应停止消费者且不执行尚未开始的 115 任务。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    calls = []
    plugin._observer = []
    plugin._deletion_timer = None
    plugin.deletion_queue = []
    plugin._u115_worker_future = None
    plugin._u115_queue = SimpleNamespace(stop=lambda: calls.append("stop"))
    plugin._stopping = False

    plugin.stop_service()

    assert calls == ["stop"]
    assert plugin._stopping is True


def test_ensure_worker_submits_only_one_consumer(
    plugin_module,
    monkeypatch,
) -> None:
    """重复唤醒队列时只能提交一个后台消费者。"""
    calls = []

    class FakeFuture:
        """模拟仍在运行的工作者 Future。"""

        @staticmethod
        def done() -> bool:
            """返回工作者仍未完成。"""
            return False

    class FakeThreadHelper:
        """记录线程池提交次数。"""

        @staticmethod
        def submit(func):
            """记录提交函数并返回运行中 Future。"""
            calls.append(func)
            return FakeFuture()

    queue = SimpleNamespace(
        has_pending=lambda: True,
        activate=lambda: calls.append("activate"),
        run=lambda: None,
    )
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    plugin._enabled = True
    plugin._u115_queue = queue
    plugin._u115_worker_future = None
    plugin._u115_worker_lock = plugin_module.threading.Lock()
    monkeypatch.setattr(plugin_module, "ThreadHelper", lambda: FakeThreadHelper())

    plugin._ensure_u115_worker()
    plugin._ensure_u115_worker()

    assert calls == ["activate", queue.run]


def test_form_preserves_original_fields_and_adds_queue_controls(
    plugin_module,
) -> None:
    """配置表单应保留原功能并增加 115 队列控制项。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)

    form, defaults = plugin.get_form()
    texts = _collect_text_values(form)

    assert defaults["monitor_strm_deletion"] is False
    assert defaults["strm_path_mappings"] == ""
    assert defaults["u115_queue_interval"] == 30
    assert defaults["resume_u115_queue"] is False
    assert "115删除间隔（秒）" in texts
    assert "恢复暂停的115删除队列" in texts


def test_page_reports_queue_counts_pause_and_recent_error(plugin_module) -> None:
    """插件详情页应展示队列数量、暂停原因和最近错误。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    plugin._enabled = True
    plugin._u115_queue = SimpleNamespace(
        snapshot=lambda: {
            "tasks": [
                {"status": "pending"},
                {"status": "pending"},
                {"status": "processing"},
                {"status": "failed"},
            ],
            "paused": True,
            "pause_reason": "连续 3 个 115 删除任务失败",
            "cooldown_until": 0,
            "consecutive_failures": 3,
            "last_success_at": 1_700_000_000,
            "last_error": "访问上限",
        }
    )

    page = plugin.get_page()
    text = "\n".join(_collect_text_values(page))

    assert "已暂停" in text
    assert "连续 3 个 115 删除任务失败" in text
    assert "待处理：2" in text
    assert "处理中：1" in text
    assert "失败：1" in text
    assert "连续失败：3" in text
    assert "访问上限" in text


def test_resume_switch_resumes_queue_and_resets_config(
    plugin_module,
    monkeypatch,
) -> None:
    """保存恢复开关时应解除暂停并把瞬时开关回写为关闭。"""
    plugin = plugin_module.SafeRemoveLink.__new__(plugin_module.SafeRemoveLink)
    saved_configs = []
    plugin.get_data = lambda _key: {
        "paused": True,
        "pause_reason": "连续失败",
        "consecutive_failures": 3,
        "tasks": [],
    }
    plugin.save_data = lambda *_args: None
    plugin.update_config = lambda config: saved_configs.append(config) or True
    monkeypatch.setattr(plugin_module, "TransferHistoryOper", lambda: SimpleNamespace())
    monkeypatch.setattr(plugin_module, "StorageChain", lambda: SimpleNamespace())

    plugin.init_plugin(
        {
            "enabled": False,
            "resume_u115_queue": True,
            "u115_queue_interval": 30,
        }
    )

    state = plugin._u115_queue.snapshot()
    assert state["paused"] is False
    assert state["consecutive_failures"] == 0
    assert saved_configs[-1]["resume_u115_queue"] is False


def test_package_metadata_matches_plugin_entrypoint(plugin_module) -> None:
    """本地包元数据应与插件入口类保持一致。"""
    package = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))
    metadata = package["SafeRemoveLink"]
    plugin_class = plugin_module.SafeRemoveLink

    assert PLUGIN_DIR.name == "SafeRemoveLink".lower()
    assert metadata["version"] == plugin_class.plugin_version
    assert metadata["name"] == plugin_class.plugin_name
    assert metadata["description"] == plugin_class.plugin_desc
    assert metadata["icon"] == plugin_class.plugin_icon
    assert metadata["author"] == plugin_class.plugin_author
    assert metadata["level"] == plugin_class.auth_level
    assert metadata["release"] is True
    assert "v1.0.0" in metadata["history"]


def test_readme_documents_conflict_and_restart_recovery() -> None:
    """README 应说明与原插件互斥及队列重启恢复行为。"""
    readme_path = PLUGIN_DIR / "README.md"
    assert readme_path.exists()
    text = readme_path.read_text(encoding="utf-8")
    assert "RemoveLink" in text
    assert "不能同时" in text
    assert "30 秒" in text
    assert "重启" in text
    assert "连续 3 个" in text


def test_queue_restores_processing_task_as_pending(deletion_module) -> None:
    """重启恢复时应把执行中的任务重新排队。"""
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok")
    )

    queue.restore({"tasks": [_task_payload(status="processing")]})

    task = queue.snapshot()["tasks"][0]
    assert task["status"] == "pending"
    assert task["attempts"] == 1


def test_queue_deduplicates_active_storage_path(deletion_module) -> None:
    """相同 115 路径存在活动任务时不应重复入队。"""
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok")
    )

    assert queue.enqueue("/strm/a.strm", "u115", "/media/a") is True
    assert queue.enqueue("/strm/a.strm", "U115", "/media/a") is False
    assert len(queue.snapshot()["tasks"]) == 1


def test_queue_processes_tasks_in_created_order(deletion_module) -> None:
    """单消费者应按任务创建顺序逐个处理。"""
    calls = []
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda task: (calls.append(task.storage_path) or True, "ok")
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")
    queue.enqueue("/strm/b.strm", "u115", "/media/b")

    assert queue.run_once() is True
    assert queue.run_once() is True

    assert calls == ["/media/a", "/media/b"]
    assert queue.snapshot()["tasks"] == []


def test_queue_persists_enqueue_and_completion(deletion_module) -> None:
    """入队和完成状态都应写入持久化回调。"""
    states = []
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok"),
        persist_state=lambda state: states.append(state),
    )

    queue.enqueue("/strm/a.strm", "u115", "/media/a")
    queue.run_once()

    assert states[0]["tasks"][0]["status"] == "pending"
    assert states[-1]["tasks"] == []
    assert states[-1]["recent"][0]["status"] == "completed"


def test_delete_slot_waits_for_configured_interval(deletion_module) -> None:
    """相邻两次 115 删除应满足配置的最小时间间隔。"""
    clock = FakeClock()
    calls = []
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok"),
        interval=30,
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )

    assert queue.execute_delete(lambda: calls.append(clock.monotonic()) or True)
    assert queue.execute_delete(lambda: calls.append(clock.monotonic()) or True)

    assert calls == [1_700_000_000.0, 1_700_000_030.0]


def test_failed_task_retries_after_30_60_120_seconds(deletion_module) -> None:
    """主删除失败后应按三段退避重试并最终标记失败。"""
    clock = FakeClock()
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (False, "访问上限"),
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")

    expected_delays = (30, 60, 120)
    for attempts, delay in enumerate(expected_delays, start=1):
        assert queue.run_once() is True
        task = queue.snapshot()["tasks"][0]
        assert task["attempts"] == attempts
        assert task["status"] == "pending"
        assert task["next_run_at"] == clock.time() + delay
        assert queue.run_once() is False
        clock.advance(delay)

    assert queue.run_once() is True

    task = queue.snapshot()["tasks"][0]
    assert task["attempts"] == 4
    assert task["status"] == "failed"
    assert queue.snapshot()["cooldown_until"] == clock.time() + 3600


def test_terminal_failure_cools_down_next_task_for_one_hour(deletion_module) -> None:
    """终态失败后下一任务应等待完整一小时冷却。"""
    clock = FakeClock()
    calls = []

    def execute(task):
        """让首个任务失败，后续任务成功。"""
        calls.append(task.storage_path)
        return (task.storage_path != "/media/a", "failed")

    queue = deletion_module.U115DeletionQueue(
        execute_task=execute,
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")
    queue.enqueue("/strm/b.strm", "u115", "/media/b")
    _fail_current_task(queue, clock)

    clock.advance(3599)
    assert queue.run_once() is False
    clock.advance(1)
    assert queue.run_once() is True

    assert calls == ["/media/a"] * 4 + ["/media/b"]


def test_worker_waits_for_remaining_cooldown_without_busy_loop(
    deletion_module,
) -> None:
    """冷却期间工作者应等待剩余时长而不是零秒忙轮询。"""
    clock = FakeClock()
    waits = []
    queue = None

    def wait(_event, timeout: float) -> bool:
        """记录工作者等待时长并停止测试循环。"""
        waits.append(timeout)
        queue.stop()
        return True

    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda task: (task.storage_path != "/media/a", "failed"),
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=wait,
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")
    queue.enqueue("/strm/b.strm", "u115", "/media/b")
    _fail_current_task(queue, clock)

    queue.run()

    assert waits == [3600]


def test_worker_does_not_lose_enqueue_wakeup_before_wait(
    deletion_module,
    monkeypatch,
) -> None:
    """任务在等待前入队时唤醒信号不得被随后清除。"""
    event_states = []
    queue = None

    def wait(event, _timeout) -> bool:
        """记录进入等待时的唤醒状态并停止工作者。"""
        event_states.append(event.is_set())
        queue.stop()
        return True

    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok"),
        wait_func=wait,
    )

    def enqueue_before_wait():
        """模拟任务在 run_once 与 wait 之间到达。"""
        queue.enqueue("/strm/a.strm", "u115", "/media/a")
        return None

    monkeypatch.setattr(queue, "_next_wait_seconds", enqueue_before_wait)

    queue.run()

    assert event_states == [True]


def test_three_terminal_failures_pause_queue(deletion_module) -> None:
    """连续三个任务最终失败后应暂停队列并只通知一次。"""
    clock = FakeClock()
    notifications = []
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (False, "访问上限"),
        notify_paused=lambda message: notifications.append(message),
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )
    for name in ("a", "b", "c", "d"):
        queue.enqueue(f"/strm/{name}.strm", "u115", f"/media/{name}")

    for index in range(3):
        _fail_current_task(queue, clock)
        if index < 2:
            clock.advance(3600)

    state = queue.snapshot()
    assert state["paused"] is True
    assert state["consecutive_failures"] == 3
    assert len(notifications) == 1
    assert queue.run_once() is False


def test_success_resets_consecutive_failure_count(deletion_module) -> None:
    """任一主任务成功后应清零连续失败次数。"""
    clock = FakeClock()

    def execute(task):
        """让首个任务失败，第二个任务成功。"""
        return (task.storage_path == "/media/b", "result")

    queue = deletion_module.U115DeletionQueue(
        execute_task=execute,
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")
    queue.enqueue("/strm/b.strm", "u115", "/media/b")
    _fail_current_task(queue, clock)
    clock.advance(3600)

    assert queue.run_once() is True
    assert queue.snapshot()["consecutive_failures"] == 0


def test_resume_clears_manual_pause_but_keeps_pending_tasks(deletion_module) -> None:
    """手动恢复应清除熔断状态且保留尚未处理的任务。"""
    clock = FakeClock()
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (False, "访问上限"),
        now_func=clock.time,
        monotonic_func=clock.monotonic,
        wait_func=clock.wait,
    )
    for name in ("a", "b", "c", "d"):
        queue.enqueue(f"/strm/{name}.strm", "u115", f"/media/{name}")
    for index in range(3):
        _fail_current_task(queue, clock)
        if index < 2:
            clock.advance(3600)

    queue.resume()

    state = queue.snapshot()
    assert state["paused"] is False
    assert state["pause_reason"] == ""
    assert state["consecutive_failures"] == 0
    assert any(task["status"] == "pending" for task in state["tasks"])


def test_stop_keeps_unstarted_tasks_pending(deletion_module) -> None:
    """停止队列时不得执行尚未开始的删除任务。"""
    calls = []
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda task: (calls.append(task.task_id) or True, "ok")
    )
    queue.enqueue("/strm/a.strm", "u115", "/media/a")

    queue.stop()

    assert queue.run_once() is False
    assert calls == []
    assert queue.snapshot()["tasks"][0]["status"] == "pending"


def test_corrupt_persisted_task_is_skipped(deletion_module) -> None:
    """损坏记录不应阻止其它合法任务恢复。"""
    queue = deletion_module.U115DeletionQueue(
        execute_task=lambda _task: (True, "ok")
    )
    queue.restore({"tasks": [{"task_id": "broken"}, _task_payload()]})

    state = queue.snapshot()
    assert len(state["tasks"]) == 1
    assert state["tasks"][0]["task_id"] == "u115:/media/a"
