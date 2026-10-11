"""复用MP本地监控器，只将稳定文件事件适配为115队列任务。"""

import time
from pathlib import Path
from threading import Event
from typing import Any, Optional

from watchfiles import Change

from app.monitor.syslimits import decide_monitor_mode
from app.monitor.watcher import LocalDirectoryWatcher
from app.sdk.logging import logger

from .queue import FileChangedError, UploadQueue


class _InitialDirectoryWatcher(LocalDirectoryWatcher):
    """在监控线程内复用目录展开，启动和内部重启时补录已有文件。"""

    def _run_watch(self, force_polling: Optional[bool]) -> None:
        self._dispatch_changes(
            self._expand_added_directories({(Change.added, str(self.watch_path))}),
            defer_unstable=True,
        )
        super()._run_watch(force_polling)


class DirectoryMonitor:
    """持有宿主watcher的生命周期；不创建第二套扫描或稳定性判定机制。"""

    def __init__(self) -> None:
        self._watchers: dict[str, LocalDirectoryWatcher] = {}
        self._mappings: list[dict] = []
        self._queue: Optional[UploadQueue] = None
        self._stop: Optional[Event] = None

    def scan(self, mappings: list[dict], queue: UploadQueue, stop: Event) -> None:
        """调度只启动缺失监控器；事件、稳定检查及重扫由宿主watcher处理。"""
        self._mappings, self._queue, self._stop = mappings, queue, stop
        for mapping in mappings:
            if stop.is_set():
                return
            root = Path(mapping["library_root"])
            current = self._watchers.get(str(root))
            if current and current.is_alive():
                continue
            if root.resolve() != root:
                raise ValueError("监控根不能经过符号链接")
            polling, reason, _, _ = decide_monitor_mode(root, "fast")
            watcher = _InitialDirectoryWatcher(root, self, force_polling=polling)
            self._watchers[str(root)] = watcher
            logger.info(f"115目录监控：{root}，{reason}")
            watcher.start()

    def event_handler(self, event: Any, text: str, event_path: str,
                      file_size: Optional[float] = None) -> None:
        """宿主完成写入稳定检查后，按路径组件匹配映射并登记任务。"""
        if not self._stop or self._stop.is_set() or event.is_directory:
            return
        path = Path(event_path)
        mapping = next((item for item in self._mappings
                        if path.is_relative_to(item["library_root"])), None)
        if mapping is None:
            return
        relative = path.relative_to(mapping["library_root"])
        if any(part.startswith(".") for part in relative.parts):
            return
        if path.name.lower().endswith((".part", ".tmp", ".!qb", ".aria2", ".crdownload")):
            return
        try:
            self._queue.enqueue({"mappings": [mapping]}, str(path), str(path), origin="watch")
        except (OSError, FileChangedError) as error:
            logger.warning(f"115监控文件暂不可登记：{path}：{error}")

    def stop(self) -> None:
        """先封口再限时等待；未退出时保留句柄并阻止重建第二代监控器。"""
        if self._stop:
            self._stop.set()
        for watcher in self._watchers.values():
            watcher.stop()
        deadline = time.monotonic() + 10
        for watcher in self._watchers.values():
            watcher.join(timeout=max(0, deadline - time.monotonic()))
        if any(watcher.is_alive() for watcher in self._watchers.values()):
            raise RuntimeError("115目录监控尚未停止，保留句柄等待重试")
        self._watchers.clear()
