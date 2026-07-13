"""媒体元数据双目录同步 MoviePilot 插件入口。"""

import time
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.chain.storage import StorageChain
from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Response

from .core import (
    DEFAULT_SYNC_EXTENSIONS,
    DirectoryReadiness,
    MetadataSyncConfig,
    MetadataSyncEngine,
    MissingDeletePlan,
    MissingMetadataItem,
    config_from_dict,
    object_to_dict,
    validate_config,
)


MAX_LOG_LINES = 500
MAX_VISIBLE_NOT_READY = 200
SUPPRESSION_SECONDS = 10
MONITOR_TICK_SECONDS = 0.5


class _SourceChangeHandler:
    def __init__(self, plugin: "MediaMetadataSync") -> None:
        self.plugin = plugin

    def on_created(self, event: Any) -> None:
        """处理源目录新增事件。"""
        self._queue(event.src_path, event.is_directory)

    def on_modified(self, event: Any) -> None:
        """处理源目录文件修改事件。"""
        if not event.is_directory:
            self._queue(event.src_path, False)

    def on_moved(self, event: Any) -> None:
        """处理源目录移动完成事件。"""
        self._queue(event.dest_path, event.is_directory)

    def _queue(self, path: str, is_directory: bool) -> None:
        self.plugin.queue_source_event(Path(path), is_directory)


class _TargetJsonChangeHandler:
    def __init__(self, plugin: "MediaMetadataSync") -> None:
        self.plugin = plugin

    def on_created(self, event: Any) -> None:
        """处理目标目录 JSON 新增事件。"""
        if not event.is_directory:
            self.plugin.queue_target_event(Path(event.src_path))

    def on_modified(self, event: Any) -> None:
        """处理目标目录 JSON 修改事件。"""
        if not event.is_directory:
            self.plugin.queue_target_event(Path(event.src_path))

    def on_moved(self, event: Any) -> None:
        """处理目标目录 JSON 移动完成事件。"""
        if not event.is_directory:
            self.plugin.queue_target_event(Path(event.dest_path))


class MediaMetadataSync(_PluginBase):
    """媒体元数据双目录同步插件。"""

    plugin_name = "媒体元数据双目录同步"
    plugin_desc = (
        "在9kg与番号系列目录间同步媒体元数据，支持缺失元数据巡检和三端安全删除。"
    )
    plugin_icon = "sync_file.png"
    plugin_version = "1.1.2"
    plugin_label = "元数据同步"
    plugin_author = "zhaojg"
    plugin_config_prefix = "mediametadatasync_"
    plugin_order = 46
    auth_level = 2
    _DELETE_VERIFY_DELAYS = (0.0, 0.4, 1.0)

    def __init__(self) -> None:
        """初始化插件运行状态。"""
        super().__init__()
        self._state_lock = RLock()
        self._sync_lock = RLock()
        self._observer_lock = RLock()
        self._generation = 0
        self._enabled = False
        self._config: Dict[str, Any] = self._default_config()
        self._sync_config = config_from_dict(self._config)
        self._lifecycle_stop_event = Event()
        self._monitor_stop_event = Event()
        self._engine = self._create_engine()
        self._task_future: Optional[Future] = None
        self._monitor_future: Optional[Future] = None
        self._source_observer = None
        self._target_observer = None
        self._pending_source: Dict[str, float] = {}
        self._pending_json: Dict[str, float] = {}
        self._suppressed_paths: Dict[str, float] = {}
        self._activated_directories: Set[str] = set()
        self._not_ready: Dict[str, Dict[str, Any]] = {}
        self._logs: List[str] = []
        self._stats: Dict[str, int] = {}
        self._last_report: Dict[str, Any] = {}
        self._missing_metadata_report: Dict[str, Any] = {}
        self._monitoring = False
        self._task_status = "idle"
        self._task_kind = ""
        self._task_message = ""
        self._task_started_at = ""
        self._task_finished_at = ""
        self._last_error = ""

    def init_plugin(self, config: dict = None) -> None:
        """加载配置，并在启用后提交启动全量同步任务。"""
        self.stop_service()
        self._lifecycle_stop_event = Event()
        self._monitor_stop_event = Event()
        self._config = self._merge_defaults(config or {})
        self._sync_config = config_from_dict(self._config)
        validation_errors = validate_config(self._sync_config)
        self._enabled = self._sync_config.enabled and not validation_errors
        self._logs = list(self.get_data("logs") or [])[-MAX_LOG_LINES:]
        self._stats = dict(self.get_data("stats") or {})
        self._last_report = dict(self.get_data("latest_report") or {})
        self._missing_metadata_report = dict(
            self.get_data("missing_metadata_report") or {}
        )
        activation_source_dir = str(self.get_data("activation_source_dir") or "")
        if activation_source_dir == self._sync_config.source_dir.as_posix():
            self._activated_directories = set(
                self.get_data("activated_directories") or []
            )
        else:
            self._activated_directories = set()
        stored_not_ready = self.get_data("not_ready") or {}
        self._not_ready = (
            dict(stored_not_ready) if isinstance(stored_not_ready, dict) else {}
        )
        self._pending_source = {}
        self._pending_json = {}
        self._suppressed_paths = {}
        self._task_future = None
        self._monitor_future = None
        self._task_status = "idle"
        self._task_kind = ""
        self._task_message = ""
        self._task_started_at = ""
        self._task_finished_at = ""
        self._last_error = ""
        self._engine = self._create_engine()
        if validation_errors:
            self._task_status = "failed"
            self._last_error = validation_errors[0]
            self._task_message = "配置校验失败"
            for error in validation_errors:
                self._append_log(f"配置错误：{error}")
            self._persist_runtime_state()
            return
        if self._enabled:
            self._submit_task(
                kind="startup_sync",
                label="启动双向全量同步",
                task=self._run_combined_sync,
                start_monitor_after=self._sync_config.monitor_enabled,
            )

    def get_state(self) -> bool:
        """返回插件是否处于启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件管理页使用的相对 API 路径。"""
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取媒体元数据同步状态",
                "description": "返回任务、监控、待就绪目录、分类统计和最近日志。",
            },
            {
                "path": "/sync/all",
                "endpoint": self.api_sync_all,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交双向全量同步",
                "description": "后台执行正向全量同步和全量JSON回写。",
            },
            {
                "path": "/sync/forward",
                "endpoint": self.api_sync_forward,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交正向全量同步",
                "description": "后台扫描9kg并同步全部受支持的元数据文件。",
            },
            {
                "path": "/sync/reverse",
                "endpoint": self.api_sync_reverse,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交全量JSON回写",
                "description": "后台扫描番号系列并将JSON回写到全部同名源目录。",
            },
            {
                "path": "/monitor/start",
                "endpoint": self.api_start_monitor,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "全量同步后启动监控",
                "description": "先后台执行双向全量同步，成功后再启动双向实时监控。",
            },
            {
                "path": "/monitor/stop",
                "endpoint": self.api_stop_monitor,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "停止实时监控",
                "description": "立即停止接收新事件，并在后台回收文件系统观察器。",
            },
            {
                "path": "/missing/scan",
                "endpoint": self.api_scan_missing_metadata,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "扫描缺失元数据",
                "description": "后台扫描缺少同名NFO或MediaInfo的STRM。",
            },
            {
                "path": "/missing/items",
                "endpoint": self.api_missing_metadata_items,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取缺失元数据记录",
                "description": "分页返回最近一次缺失元数据扫描结果。",
            },
            {
                "path": "/missing/delete-preview",
                "endpoint": self.api_missing_delete_preview,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "预览缺失元数据删除目标",
                "description": "只读生成9kg、番号系列和网盘源文件删除清单。",
            },
            {
                "path": "/missing/delete",
                "endpoint": self.api_delete_missing_metadata,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交缺失元数据三端删除",
                "description": "后台按网盘、番号系列、9kg顺序删除并逐步复核。",
            },
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回 Vue 配置组件使用的默认配置。"""
        return None, self._default_config()

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """返回 Vue 联邦组件渲染模式。"""
        return "vue", "dist/assets-1.1.2"

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式下不生成后端页面结构。"""
        return None

    def get_service(self) -> List[Dict[str, Any]]:
        """返回空的公共服务列表。"""
        return []

    def stop_service(self) -> None:
        """停止后台同步和实时监控资源。"""
        self._generation += 1
        if hasattr(self, "_lifecycle_stop_event"):
            self._lifecycle_stop_event.set()
        if hasattr(self, "_monitor_stop_event"):
            self._monitor_stop_event.set()
        self._monitoring = False
        self._stop_observers(wait=True)
        if hasattr(self, "_state_lock"):
            with self._state_lock:
                self._pending_source.clear()
                self._pending_json.clear()

    def api_status(self) -> Response:
        """返回页面轮询所需的完整运行状态。"""
        return Response(success=True, message="", data=self._status_data())

    def api_sync_all(self) -> Response:
        """提交双向全量同步后台任务。"""
        return self._submit_enabled_task(
            kind="sync_all",
            label="双向全量同步",
            task=self._run_combined_sync,
        )

    def api_sync_forward(self) -> Response:
        """提交正向全量同步后台任务。"""
        return self._submit_enabled_task(
            kind="sync_forward",
            label="正向全量同步",
            task=self._run_forward_sync,
        )

    def api_sync_reverse(self) -> Response:
        """提交全量 JSON 回写后台任务。"""
        return self._submit_enabled_task(
            kind="sync_reverse",
            label="JSON 全量回写",
            task=self._run_reverse_sync,
        )

    def api_start_monitor(self) -> Response:
        """提交全量同步并在成功后启动实时监控。"""
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        if self._monitoring:
            return Response(
                success=True,
                message="实时监控已在运行",
                data=self._status_data(),
            )
        self._monitor_stop_event = Event()
        return self._submit_task(
            kind="monitor_start",
            label="全量同步后启动监控",
            task=self._run_combined_sync,
            start_monitor_after=True,
        )

    def api_stop_monitor(self) -> Response:
        """停止接收新事件并后台回收实时观察器。"""
        self._monitor_stop_event.set()
        self._monitoring = False
        try:
            ThreadHelper().submit(self._stop_observers, True)
        except Exception as err:
            logger.error(f"【{self.plugin_name}】提交监控停止任务失败：{str(err)}")
            return Response(success=False, message=f"停止监控失败：{str(err)}")
        self._append_log("实时监控停止中")
        return Response(
            success=True,
            message="实时监控停止中",
            data=self._status_data(),
        )

    def api_scan_missing_metadata(self) -> Response:
        """提交缺失 NFO 或 MediaInfo 的 STRM 扫描任务。"""
        return self._submit_enabled_task(
            kind="missing_scan",
            label="缺失元数据扫描",
            task=self._run_missing_metadata_scan,
        )

    def api_missing_metadata_items(
        self,
        page: int = 1,
        page_size: int = 30,
        query: str = "",
    ) -> Response:
        """分页返回最近一次缺失元数据扫描记录。"""
        return Response(
            success=True,
            message="",
            data=self._missing_items_data(page, page_size, query),
        )

    def api_missing_delete_preview(self, item_id: str) -> Response:
        """生成单条缺失记录的三端删除清单和确认令牌。"""
        item = self._find_missing_item(item_id)
        if not item:
            return Response(success=False, message="该记录不在当前扫描结果中")
        plan = self._engine.build_missing_delete_plan(item)
        message = (
            "删除预览存在阻止项"
            if plan.blocked_reasons
            else "删除预览已生成"
        )
        return Response(
            success=True,
            message=message,
            data=object_to_dict(plan),
        )

    def api_delete_missing_metadata(
        self,
        item_id: str,
        confirmed: bool = False,
        confirm_token: str = "",
    ) -> Response:
        """校验预览令牌后提交单条三端删除后台任务。"""
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        if not confirmed or not str(confirm_token or "").strip():
            return Response(success=False, message="请先预览并确认删除目标")
        item = self._find_missing_item(item_id)
        if not item:
            return Response(success=False, message="该记录不在当前扫描结果中")
        plan = self._engine.build_missing_delete_plan(item)
        if plan.blocked_reasons:
            return Response(
                success=False,
                message=plan.blocked_reasons[0],
                data=object_to_dict(plan),
            )
        if confirm_token != plan.confirm_token:
            return Response(
                success=False,
                message="文件状态已变化，请重新预览后再确认",
            )
        return self._submit_task(
            kind="missing_delete",
            label=f"删除 {item.number}/{item.file_name}",
            task=lambda: self._run_missing_metadata_delete(
                item_id=item.item_id,
                confirm_token=confirm_token,
            ),
        )

    def _submit_enabled_task(
        self,
        kind: str,
        label: str,
        task: Callable[[], Dict[str, Any]],
    ) -> Response:
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        return self._submit_task(kind=kind, label=label, task=task)

    def _submit_task(
        self,
        kind: str,
        label: str,
        task: Callable[[], Dict[str, Any]],
        start_monitor_after: bool = False,
    ) -> Response:
        with self._state_lock:
            if self._task_future and not self._task_future.done():
                return Response(
                    success=False,
                    message=self._task_message or "已有后台任务正在执行",
                    data={"status": self._task_status},
                )
            generation = self._generation
            self._task_status = "queued"
            self._task_kind = kind
            self._task_message = f"{label}已排队"
            self._task_started_at = ""
            self._task_finished_at = ""
            self._last_error = ""
            try:
                self._task_future = ThreadHelper().submit(
                    self._run_task,
                    generation,
                    label,
                    task,
                    start_monitor_after,
                )
            except Exception as err:
                self._task_status = "failed"
                self._task_finished_at = self._now()
                self._last_error = str(err)
                self._task_message = f"{label}提交失败"
                return Response(
                    success=False,
                    message=f"后台任务提交失败：{str(err)}",
                )
        self._append_log(f"{label}已排队")
        return Response(
            success=True,
            message=f"{label}已排队",
            data={"status": "queued", "kind": kind},
        )

    def _run_task(
        self,
        generation: int,
        label: str,
        task: Callable[[], Dict[str, Any]],
        start_monitor_after: bool,
    ) -> None:
        if generation != self._generation:
            return
        with self._state_lock:
            self._task_status = "running"
            self._task_started_at = self._now()
            self._task_message = f"{label}正在执行"
        self._append_log(f"{label}开始")
        try:
            result = task()
            if generation != self._generation:
                return
            if (
                start_monitor_after
                and not self._lifecycle_stop_event.is_set()
                and not self._monitor_stop_event.is_set()
            ):
                self._start_monitoring(generation)
            task_succeeded = result.get("success") is not False
            result_message = str(result.get("message") or f"{label}完成")
            with self._state_lock:
                self._last_report = result
                self._task_status = "succeeded" if task_succeeded else "failed"
                self._task_finished_at = self._now()
                self._task_message = result_message
                self._last_error = "" if task_succeeded else result_message
            self._append_log(self._task_message)
            self._persist_runtime_state()
        except Exception as err:
            if generation != self._generation:
                return
            with self._state_lock:
                self._task_status = "failed"
                self._task_finished_at = self._now()
                self._task_message = f"{label}失败"
                self._last_error = str(err)
            logger.error(
                f"【{self.plugin_name}】{label}失败：{str(err)}",
                exc_info=True,
            )
            self._append_log(f"{label}失败：{str(err)}")
            self._persist_runtime_state()

    def _run_combined_sync(self) -> Dict[str, Any]:
        with self._sync_lock:
            self._prepare_directories()
            forward_report = self._engine.full_forward_sync()
            if self._lifecycle_stop_event.is_set():
                raise RuntimeError("同步任务已停止")
            self._refresh_readiness_state()
            reverse_report = self._engine.full_reverse_sync()
            self._stats = self._engine.get_stats()
            message = (
                f"双向全量完成：正向复制 {forward_report.copied_files}，"
                f"JSON回写 {reverse_report.copied_files}，"
                f"失败 {forward_report.failed_files + reverse_report.failed_files}"
            )
            return {
                "kind": "sync_all",
                "message": message,
                "forward": object_to_dict(forward_report),
                "reverse": object_to_dict(reverse_report),
            }

    def _run_forward_sync(self) -> Dict[str, Any]:
        with self._sync_lock:
            self._prepare_directories()
            report = self._engine.full_forward_sync()
            self._refresh_readiness_state()
            self._stats = self._engine.get_stats()
            data = object_to_dict(report)
            data["message"] = report.message
            return data

    def _run_reverse_sync(self) -> Dict[str, Any]:
        with self._sync_lock:
            self._prepare_directories()
            report = self._engine.full_reverse_sync()
            self._stats = self._engine.get_stats()
            data = object_to_dict(report)
            data["message"] = report.message
            return data

    def _run_missing_metadata_scan(self) -> Dict[str, Any]:
        with self._sync_lock:
            self._prepare_directories()
            report = self._engine.scan_missing_metadata()
            data = object_to_dict(report)
            data["success"] = True
            self._missing_metadata_report = data
            self.save_data("missing_metadata_report", data)
            return data

    def _run_missing_metadata_delete(
        self,
        item_id: str,
        confirm_token: str,
    ) -> Dict[str, Any]:
        with self._sync_lock:
            item = self._find_missing_item(item_id)
            if not item:
                return {
                    "kind": "missing_delete",
                    "success": False,
                    "message": "该记录已不在当前扫描结果中",
                    "item_id": item_id,
                }
            plan = self._engine.build_missing_delete_plan(item)
            report: Dict[str, Any] = {
                "kind": "missing_delete",
                "success": False,
                "verified": False,
                "message": "删除未执行",
                "item_id": item_id,
                "number": item.number,
                "file_name": item.file_name,
                "plan": object_to_dict(plan),
                "cloud_results": [],
                "target_results": [],
                "source_results": [],
            }
            if plan.blocked_reasons:
                report["message"] = plan.blocked_reasons[0]
                return report
            if confirm_token != plan.confirm_token:
                report["message"] = "文件状态已变化，请重新预览后再确认"
                return report

            storage_chain = StorageChain()
            cloud_results = self._delete_paths_and_verify(
                [Path(path) for path in plan.cloud_files],
                storage_chain,
                verify_absent_parent=True,
            )
            report["cloud_results"] = cloud_results
            if not self._delete_results_verified(cloud_results):
                message = "网盘源文件未全部通过删除复核，番号系列和 9kg 未处理"
                report["target_results"] = self._skipped_delete_results(
                    plan.target_files,
                    message,
                )
                report["source_results"] = self._skipped_delete_results(
                    plan.source_files,
                    message,
                )
                report["message"] = message
                return report

            target_results = self._delete_paths_and_verify(
                [Path(path) for path in plan.target_files],
                storage_chain,
            )
            report["target_results"] = target_results
            if not self._delete_results_verified(target_results):
                message = "番号系列文件未全部通过删除复核，9kg 未处理"
                report["source_results"] = self._skipped_delete_results(
                    plan.source_files,
                    message,
                )
                report["message"] = message
                return report

            source_results = self._delete_paths_and_verify(
                [Path(path) for path in plan.source_files],
                storage_chain,
            )
            report["source_results"] = source_results
            if not self._delete_results_verified(source_results):
                report["message"] = "9kg 文件未全部通过删除复核"
                return report

            self._remove_missing_item(item_id)
            report["success"] = True
            report["verified"] = True
            report["message"] = (
                f"三端删除并复核完成：{item.number}/{item.file_name}"
            )
            return report

    def _prepare_directories(self) -> None:
        validation_errors = validate_config(self._sync_config)
        if validation_errors:
            raise ValueError(validation_errors[0])
        if not self._sync_config.source_dir.is_dir():
            raise OSError(f"源目录不存在：{self._sync_config.source_dir}")
        if self._sync_config.source_dir.is_symlink():
            raise OSError("源目录不能是符号链接")
        if self._sync_config.target_dir.is_symlink():
            raise OSError("目标目录不能是符号链接")
        self._sync_config.target_dir.mkdir(parents=True, exist_ok=True)

    def _refresh_readiness_state(self) -> None:
        existing_paths: Set[str] = set()
        for directory in self._engine.iter_source_directories():
            relative_path = self._relative_source_directory(directory)
            existing_paths.add(relative_path)
            readiness = self._engine.analyze_readiness(directory)
            if readiness.ready:
                self._activated_directories.add(relative_path)
                self._not_ready.pop(relative_path, None)
                continue
            self._not_ready[relative_path] = self._readiness_data(
                readiness,
                activated=relative_path in self._activated_directories,
            )
        self._activated_directories.intersection_update(existing_paths)
        self._not_ready = {
            path: data
            for path, data in self._not_ready.items()
            if path in existing_paths
        }

    def _start_monitoring(self, generation: int) -> None:
        if self._monitoring:
            return
        if generation != self._generation:
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as err:
            raise RuntimeError(f"watchdog 依赖不可用：{str(err)}") from err
        with self._observer_lock:
            if (
                generation != self._generation
                or self._lifecycle_stop_event.is_set()
                or self._monitor_stop_event.is_set()
            ):
                return
            self._prepare_directories()
            source_handler = type(
                "SourceChangeHandler",
                (_SourceChangeHandler, FileSystemEventHandler),
                {},
            )(self)
            target_handler = type(
                "TargetJsonChangeHandler",
                (_TargetJsonChangeHandler, FileSystemEventHandler),
                {},
            )(self)
            try:
                self._source_observer = Observer()
                self._source_observer.schedule(
                    source_handler,
                    self._sync_config.source_dir.as_posix(),
                    recursive=True,
                )
                self._source_observer.start()
                if self._sync_config.reverse_sync_enabled:
                    self._target_observer = Observer()
                    self._target_observer.schedule(
                        target_handler,
                        self._sync_config.target_dir.as_posix(),
                        recursive=True,
                    )
                    self._target_observer.start()
                monitor_stop_event = self._monitor_stop_event
                self._monitoring = True
                self._monitor_future = ThreadHelper().submit(
                    self._monitor_worker,
                    generation,
                    monitor_stop_event,
                )
                monitor_mode = (
                    "双向" if self._sync_config.reverse_sync_enabled else "正向"
                )
                self._append_log(f"{monitor_mode}实时监控已启动")
            except Exception:
                self._monitoring = False
                self._stop_observers(wait=True)
                raise

    def _monitor_worker(self, generation: int, stop_event: Event) -> None:
        while (
            generation == self._generation
            and not self._lifecycle_stop_event.is_set()
            and not stop_event.wait(MONITOR_TICK_SECONDS)
        ):
            changed = self._process_pending_source(generation)
            changed = self._process_pending_json(generation) or changed
            if changed:
                self._stats = self._engine.get_stats()
                self._persist_runtime_state()
        if generation == self._generation:
            self._monitoring = False
            self._append_log("实时监控处理线程已停止")

    def _process_pending_source(self, generation: int) -> bool:
        now = time.monotonic()
        with self._state_lock:
            pending_items = [
                (path, updated_at)
                for path, updated_at in self._pending_source.items()
                if now - updated_at >= self._sync_config.settle_seconds
            ]
        changed = False
        for path_text, updated_at in pending_items:
            if generation != self._generation:
                return changed
            directory = Path(path_text)
            if not directory.is_dir() or directory.is_symlink():
                self._complete_pending(self._pending_source, path_text, updated_at)
                continue
            relative_path = self._relative_source_directory(directory)
            is_activated = relative_path in self._activated_directories
            with self._sync_lock:
                readiness = self._engine.analyze_readiness(directory)
                if not is_activated and not readiness.ready:
                    self._not_ready[relative_path] = self._readiness_data(
                        readiness,
                        activated=False,
                    )
                    self._append_log(f"未就绪目录：{directory}，{readiness.reason}")
                    self._complete_pending(
                        self._pending_source,
                        path_text,
                        updated_at,
                    )
                    changed = True
                    continue
                if readiness.ready and not is_activated:
                    self._activated_directories.add(relative_path)
                    self._not_ready.pop(relative_path, None)
                    self._append_log(f"目录已满足同名 STRM+NFO：{directory}")
                elif not readiness.ready:
                    self._not_ready[relative_path] = self._readiness_data(
                        readiness,
                        activated=True,
                    )
                report = self._engine.forward_sync_directory(directory)
                self._last_report = object_to_dict(report)
            self._complete_pending(self._pending_source, path_text, updated_at)
            changed = True
        return changed

    def _process_pending_json(self, generation: int) -> bool:
        now = time.monotonic()
        with self._state_lock:
            pending_items = [
                (path, updated_at)
                for path, updated_at in self._pending_json.items()
                if now - updated_at >= self._sync_config.settle_seconds
            ]
        changed = False
        for path_text, updated_at in pending_items:
            if generation != self._generation:
                return changed
            json_file = Path(path_text)
            if json_file.is_file() and not json_file.is_symlink():
                with self._sync_lock:
                    report = self._engine.reverse_sync_file(json_file)
                if report:
                    self._last_report = object_to_dict(report)
                    changed = True
            self._complete_pending(self._pending_json, path_text, updated_at)
        return changed

    def queue_source_event(self, event_path: Path, is_directory: bool) -> None:
        """将源目录文件系统事件加入防抖处理队列。"""
        if not is_directory and self._is_suppressed(event_path):
            return
        if not is_directory and not self._engine.is_sync_extension(event_path):
            return
        directory = self._engine.source_event_directory(event_path)
        if not directory:
            return
        relative_path = self._relative_source_directory(directory)
        if (
            not is_directory
            and relative_path not in self._activated_directories
            and event_path.suffix.lower() not in {".strm", ".nfo"}
        ):
            return
        with self._state_lock:
            self._pending_source[directory.as_posix()] = time.monotonic()

    def queue_target_event(self, event_path: Path) -> None:
        """将目标 JSON 文件事件加入防抖回写队列。"""
        if self._is_suppressed(event_path):
            return
        if not self._engine.is_target_json_file(event_path):
            return
        with self._state_lock:
            self._pending_json[event_path.as_posix()] = time.monotonic()

    def _mark_suppressed(self, file_path: Path) -> None:
        with self._state_lock:
            self._cleanup_suppressed_paths()
            self._suppressed_paths[file_path.resolve(strict=False).as_posix()] = (
                time.monotonic() + SUPPRESSION_SECONDS
            )

    def _is_suppressed(self, file_path: Path) -> bool:
        path_text = file_path.resolve(strict=False).as_posix()
        with self._state_lock:
            self._cleanup_suppressed_paths()
            return self._suppressed_paths.get(path_text, 0) > time.monotonic()

    def _cleanup_suppressed_paths(self) -> None:
        now = time.monotonic()
        self._suppressed_paths = {
            path: expires_at
            for path, expires_at in self._suppressed_paths.items()
            if expires_at > now
        }

    def _stop_observers(self, wait: bool) -> None:
        with self._observer_lock:
            observers = [self._source_observer, self._target_observer]
            self._source_observer = None
            self._target_observer = None
            for observer in observers:
                if not observer:
                    continue
                try:
                    observer.stop()
                except Exception as err:
                    logger.error(f"【{self.plugin_name}】停止观察器失败：{str(err)}")
            if not wait:
                return
            for observer in observers:
                if not observer:
                    continue
                try:
                    observer.join(timeout=5)
                except Exception as err:
                    logger.error(
                        f"【{self.plugin_name}】等待观察器退出失败：{str(err)}"
                    )

    def _create_engine(self) -> MetadataSyncEngine:
        lifecycle_stop_event = self._lifecycle_stop_event
        return MetadataSyncEngine(
            config=self._sync_config,
            log_callback=self._append_log,
            write_callback=self._mark_suppressed,
            stop_callback=lifecycle_stop_event.is_set,
        )

    def _missing_items_data(
        self,
        page: int,
        page_size: int,
        query: str,
    ) -> Dict[str, Any]:
        with self._state_lock:
            report = dict(self._missing_metadata_report)
            items = [dict(item) for item in report.get("items") or []]
        clean_query = str(query or "").strip().casefold()
        if clean_query:
            items = [
                item
                for item in items
                if clean_query
                in " ".join(
                    [
                        str(item.get("number") or ""),
                        str(item.get("file_name") or ""),
                        *[str(value) for value in item.get("owner_names") or []],
                        *[str(value) for value in item.get("source_paths") or []],
                    ]
                ).casefold()
            ]
        normalized_page_size = min(max(int(page_size or 30), 1), 100)
        total = len(items)
        page_count = max(1, (total + normalized_page_size - 1) // normalized_page_size)
        normalized_page = min(max(int(page or 1), 1), page_count)
        start = (normalized_page - 1) * normalized_page_size
        summary = {
            key: value
            for key, value in report.items()
            if key != "items"
        }
        return {
            "items": items[start : start + normalized_page_size],
            "total": total,
            "page": normalized_page,
            "page_count": page_count,
            "page_size": normalized_page_size,
            "summary": summary,
        }

    def _find_missing_item(self, item_id: str) -> Optional[MissingMetadataItem]:
        clean_item_id = str(item_id or "").strip()
        with self._state_lock:
            items = list(self._missing_metadata_report.get("items") or [])
        for item_data in items:
            if str(item_data.get("item_id") or "") == clean_item_id:
                return MissingMetadataItem.from_dict(item_data)
        return None

    def _remove_missing_item(self, item_id: str) -> None:
        with self._state_lock:
            report = dict(self._missing_metadata_report)
            items = [
                dict(item)
                for item in report.get("items") or []
                if str(item.get("item_id") or "") != item_id
            ]
            report["items"] = items
            report["missing_items"] = len(items)
            report["missing_nfo"] = sum(
                1 for item in items if "NFO" in item.get("missing_types", [])
            )
            report["missing_mediainfo"] = sum(
                1
                for item in items
                if "MediaInfo" in item.get("missing_types", [])
            )
            report["message"] = f"当前剩余 {len(items)} 条缺失元数据记录"
            self._missing_metadata_report = report
        self.save_data("missing_metadata_report", report)

    def _delete_paths_and_verify(
        self,
        paths: List[Path],
        storage_chain: StorageChain,
        verify_absent_parent: bool = False,
    ) -> List[Dict[str, Any]]:
        unique_paths = list(dict.fromkeys(paths))
        completed: Dict[Path, Dict[str, Any]] = {}
        pending: Dict[Path, bool] = {}
        originally_absent: Set[Path] = set()
        for path in unique_paths:
            try:
                file_item = storage_chain.get_file_item(storage="local", path=path)
                if not file_item:
                    if verify_absent_parent:
                        pending[path] = True
                        originally_absent.add(path)
                    else:
                        completed[path] = {
                            "path": path.as_posix(),
                            "name": path.name,
                            "status": "absent",
                            "verified": True,
                            "message": "文件原本已不存在",
                        }
                    continue
                if file_item.type != "file":
                    completed[path] = {
                        "path": path.as_posix(),
                        "name": path.name,
                        "status": "failed",
                        "verified": False,
                        "message": "目标不是普通文件，已拒绝删除",
                    }
                    continue
                pending[path] = bool(storage_chain.delete_file(file_item))
            except Exception as err:
                completed[path] = {
                    "path": path.as_posix(),
                    "name": path.name,
                    "status": "failed",
                    "verified": False,
                    "message": f"删除调用异常：{str(err)}",
                }

        remaining = set(pending)
        for delay in self._DELETE_VERIFY_DELAYS:
            if not remaining:
                break
            if delay:
                time.sleep(delay)
            paths_by_parent: Dict[Path, List[Path]] = {}
            for path in remaining:
                paths_by_parent.setdefault(path.parent, []).append(path)
            verified_paths: Set[Path] = set()
            for parent, parent_paths in paths_by_parent.items():
                try:
                    parent_item = storage_chain.get_file_item(
                        storage="local",
                        path=parent,
                    )
                    if not parent_item:
                        verified_paths.update(
                            path
                            for path in parent_paths
                            if path not in originally_absent
                        )
                        continue
                    children = storage_chain.list_files(parent_item)
                    if children is None:
                        continue
                    existing_names = {
                        Path(item.path or "").name
                        for item in children
                    }
                    verified_paths.update(
                        path
                        for path in parent_paths
                        if path.name not in existing_names
                    )
                except Exception as err:
                    logger.warning(
                        f"【{self.plugin_name}】删除后目录复核失败："
                        f"{parent}，{str(err)}"
                    )
            remaining.difference_update(verified_paths)

        for path, delete_result in pending.items():
            verified = path not in remaining
            completed[path] = {
                "path": path.as_posix(),
                "name": path.name,
                "status": "deleted" if verified else "failed",
                "verified": verified,
                "message": (
                    (
                        "文件原本已不存在，已通过父目录复核"
                        if path in originally_absent
                        else "已删除并通过父目录复核"
                    )
                    if verified
                    else (
                        "删除调用失败，文件仍存在"
                        if not delete_result
                        else "删除后文件仍存在"
                    )
                ),
            }
        return [completed[path] for path in unique_paths]

    @staticmethod
    def _delete_results_verified(results: List[Dict[str, Any]]) -> bool:
        return all(bool(result.get("verified")) for result in results)

    @staticmethod
    def _skipped_delete_results(
        paths: List[str],
        message: str,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "path": path,
                "name": Path(path).name,
                "status": "skipped",
                "verified": False,
                "message": message,
            }
            for path in paths
        ]

    def _append_log(self, message: str) -> None:
        clean_message = str(message or "").strip()
        if not clean_message:
            return
        logger.info(f"【{self.plugin_name}】{clean_message}")
        log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {clean_message}"
        with self._state_lock:
            self._logs.append(log_line)
            self._logs = self._logs[-MAX_LOG_LINES:]

    def _persist_runtime_state(self) -> None:
        self.save_data("logs", list(self._logs[-MAX_LOG_LINES:]))
        self.save_data(
            "activated_directories",
            sorted(self._activated_directories),
        )
        self.save_data(
            "activation_source_dir",
            self._sync_config.source_dir.as_posix(),
        )
        self.save_data("not_ready", dict(self._not_ready))
        self.save_data("stats", dict(self._stats))
        self.save_data("latest_report", dict(self._last_report))
        self.save_data(
            "missing_metadata_report",
            dict(self._missing_metadata_report),
        )

    def _status_data(self) -> Dict[str, Any]:
        with self._state_lock:
            not_ready = sorted(
                self._not_ready.values(),
                key=lambda item: str(item.get("path") or "").casefold(),
            )[:MAX_VISIBLE_NOT_READY]
            missing_summary = {
                key: value
                for key, value in self._missing_metadata_report.items()
                if key != "items"
            }
            return {
                "enabled": self._enabled,
                "monitor_enabled": self._sync_config.monitor_enabled,
                "reverse_sync_enabled": self._sync_config.reverse_sync_enabled,
                "monitoring": self._monitoring,
                "task_status": self._task_status,
                "task_kind": self._task_kind,
                "task_message": self._task_message,
                "task_started_at": self._task_started_at,
                "task_finished_at": self._task_finished_at,
                "last_error": self._last_error,
                "pending_source_count": len(self._pending_source),
                "pending_json_count": len(self._pending_json),
                "activated_count": len(self._activated_directories),
                "not_ready": not_ready,
                "stats": dict(self._stats),
                "logs": list(self._logs[-200:]),
                "last_report": dict(self._last_report),
                "missing_metadata": missing_summary,
                "config": {
                    "source_dir": self._sync_config.source_dir.as_posix(),
                    "target_dir": self._sync_config.target_dir.as_posix(),
                    "other_category": self._sync_config.other_category,
                    "settle_seconds": self._sync_config.settle_seconds,
                    "sync_extensions": list(self._sync_config.sync_extensions),
                    "cloud_mount_paths": [
                        path.as_posix()
                        for path in self._sync_config.cloud_mount_paths
                    ],
                    "max_delete_files": self._sync_config.max_delete_files,
                },
            }

    def _relative_source_directory(self, directory: Path) -> str:
        try:
            return directory.relative_to(self._sync_config.source_dir).as_posix()
        except ValueError:
            return directory.name

    @staticmethod
    def _readiness_data(
        readiness: DirectoryReadiness,
        activated: bool,
    ) -> Dict[str, Any]:
        return {
            "path": readiness.path,
            "reason": readiness.reason,
            "matched_stems": list(readiness.matched_stems),
            "activated": activated,
        }

    def _complete_pending(
        self,
        pending: Dict[str, float],
        path_text: str,
        processed_at: float,
    ) -> None:
        with self._state_lock:
            if pending.get(path_text, 0) <= processed_at:
                pending.pop(path_text, None)

    @classmethod
    def _merge_defaults(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        sync_config = config_from_dict({**cls._default_config(), **config})
        return {
            "enabled": sync_config.enabled,
            "monitor_enabled": sync_config.monitor_enabled,
            "reverse_sync_enabled": sync_config.reverse_sync_enabled,
            "source_dir": sync_config.source_dir.as_posix(),
            "target_dir": sync_config.target_dir.as_posix(),
            "other_category": sync_config.other_category,
            "settle_seconds": sync_config.settle_seconds,
            "sync_extensions": list(sync_config.sync_extensions),
            "cloud_mount_paths": [
                path.as_posix() for path in sync_config.cloud_mount_paths
            ],
            "max_delete_files": sync_config.max_delete_files,
        }

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "enabled": False,
            "monitor_enabled": True,
            "reverse_sync_enabled": True,
            "source_dir": "/media/9kg",
            "target_dir": "/media/番号系列",
            "other_category": "其他",
            "settle_seconds": 2,
            "sync_extensions": list(DEFAULT_SYNC_EXTENSIONS),
            "cloud_mount_paths": ["/CloudNAS/CloudDrive"],
            "max_delete_files": 100,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
