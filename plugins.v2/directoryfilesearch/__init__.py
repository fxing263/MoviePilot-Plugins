"""目录文件搜索删除 MoviePilot 插件入口。"""

import secrets
import time
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from threading import Event, RLock
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Response

from .core import (
    DirectoryFileEngine,
    FileDeletePlan,
    FileDeleteResult,
    FileSearchItem,
    FileSearchReport,
    config_from_dict,
    normalize_query,
)


MAX_LOG_LINES = 200
MAX_PAGE_SIZE = 100
MAX_BATCH_DELETE_ITEMS = 1000
MAX_BATCH_PREVIEW_ITEMS = 50
DELETE_TOKEN_TTL_SECONDS = 300


class DeleteBatchPreviewRequest(BaseModel):
    """描述需要生成删除预览的搜索结果选择。"""

    item_ids: List[str] = Field(default_factory=list)
    excluded_item_ids: List[str] = Field(default_factory=list)
    select_all: bool = False


class DeleteBatchExecuteRequest(BaseModel):
    """描述消费批量删除确认令牌的请求。"""

    confirmed: bool = False
    confirm_token: str = ""


@dataclass(frozen=True)
class _DeleteTicket:
    items: Tuple[FileSearchItem, ...]
    expires_at: float


class DirectoryFileSearch(_PluginBase):
    """在配置目录内搜索并安全删除普通文件。"""

    plugin_name = "目录文件搜索删除"
    plugin_desc = "递归搜索配置目录内的普通文件，并提供单条或批量源文件删除与复核。"
    plugin_icon = "delete.png"
    plugin_version = "1.1.1"
    plugin_label = "文件管理"
    plugin_author = "zhaojg"
    plugin_config_prefix = "directoryfilesearch_"
    plugin_order = 47
    auth_level = 2

    def __init__(self) -> None:
        """初始化插件运行状态。"""
        super().__init__()
        self._state_lock = RLock()
        self._generation = 0
        self._enabled = False
        self._config: Dict[str, Any] = self._default_config()
        self._search_config = config_from_dict(self._config)
        self._engine = DirectoryFileEngine(self._search_config)
        self._stop_event = Event()
        self._task_future: Optional[Future] = None
        self._task_status = "idle"
        self._task_kind = ""
        self._task_message = ""
        self._task_started_at = ""
        self._task_finished_at = ""
        self._last_error = ""
        self._search_report: Optional[FileSearchReport] = None
        self._last_report: Dict[str, Any] = {}
        self._delete_tickets: Dict[str, _DeleteTicket] = {}
        self._logs: List[str] = []

    def init_plugin(self, config: dict = None) -> None:
        """加载插件配置并重置搜索会话。"""
        self.stop_service()
        self._stop_event = Event()
        self._config = self._merge_defaults(config or {})
        self._search_config = config_from_dict(self._config)
        self._engine = DirectoryFileEngine(self._search_config)
        self._enabled = self._search_config.enabled
        with self._state_lock:
            self._task_future = None
            self._task_status = "idle"
            self._task_kind = ""
            self._task_message = ""
            self._task_started_at = ""
            self._task_finished_at = ""
            self._last_error = ""
            self._search_report = None
            self._last_report = {}
            self._delete_tickets.clear()
        if self._enabled:
            try:
                self._engine.validate_root()
            except ValueError as err:
                self._last_error = str(err)
                self._task_message = "等待有效目录配置"
                self._append_log(f"配置提示：{str(err)}")

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回空的远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回管理页使用的插件相对 API。"""
        return [
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取目录文件搜索状态",
                "description": "返回后台任务、搜索摘要、配置和最近操作。",
            },
            {
                "path": "/search",
                "endpoint": self.api_search,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交目录文件搜索",
                "description": "后台递归搜索文件名或相对路径包含关键词的普通文件。",
            },
            {
                "path": "/results",
                "endpoint": self.api_results,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取目录文件搜索结果",
                "description": "分页返回最近一次后台搜索结果。",
            },
            {
                "path": "/delete-preview",
                "endpoint": self.api_delete_preview,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "预览文件删除",
                "description": "校验当前文件快照并生成一次性确认令牌。",
            },
            {
                "path": "/delete-batch-preview",
                "endpoint": self.api_delete_batch_preview,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "预览批量源文件删除",
                "description": "校验所选文件快照并生成绑定整批目标的一次性确认令牌。",
            },
            {
                "path": "/delete",
                "endpoint": self.api_delete,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交文件删除",
                "description": "后台删除普通文件并重新枚举父目录复核。",
            },
            {
                "path": "/delete-batch",
                "endpoint": self.api_delete_batch,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "提交批量源文件删除",
                "description": "后台逐项删除确认令牌绑定的源文件并复核每个结果。",
            },
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回 Vue 配置组件使用的默认配置。"""
        return None, self._default_config()

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """返回 Vue 联邦组件渲染模式。"""
        return "vue", "dist/assets-1.1.1"

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式下不生成后端页面结构。"""
        return None

    def get_service(self) -> List[Dict[str, Any]]:
        """返回空的公共服务列表。"""
        return []

    def stop_service(self) -> None:
        """通知正在运行的搜索任务停止。"""
        self._generation += 1
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        if hasattr(self, "_state_lock"):
            with self._state_lock:
                self._delete_tickets.clear()

    def api_status(self) -> Response:
        """返回页面轮询所需的完整运行状态。"""
        return Response(success=True, message="", data=self._status_data())

    def api_search(self, query: str = "") -> Response:
        """校验关键词并提交后台搜索任务。"""
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        try:
            normalized_query = normalize_query(query)
            self._engine.validate_root()
        except ValueError as err:
            return Response(success=False, message=str(err))

        with self._state_lock:
            if self._task_running_locked():
                return self._busy_response()
            self._search_report = None
            self._delete_tickets.clear()
            return self._queue_task_locked(
                kind="search",
                label=f"搜索“{normalized_query}”",
                task=lambda: self._run_search(normalized_query),
            )

    def api_results(self, page: int = 1, page_size: int = 50) -> Response:
        """分页返回最近一次搜索结果。"""
        safe_page = max(1, int(page or 1))
        safe_page_size = min(MAX_PAGE_SIZE, max(1, int(page_size or 50)))
        return Response(
            success=True,
            message="",
            data=self._results_data(safe_page, safe_page_size),
        )

    def api_delete_preview(self, item_id: str) -> Response:
        """校验搜索结果并生成一次性删除确认令牌。"""
        item = self._find_item(item_id)
        if not item:
            return Response(success=False, message="该文件不在当前搜索结果中")
        confirm_token = secrets.token_urlsafe(24)
        plan = self._engine.build_delete_plan(item, confirm_token)
        if plan.blocked_reasons:
            return Response(
                success=True,
                message="删除预览存在阻止项",
                data=self._delete_plan_data(plan),
            )
        with self._state_lock:
            self._prune_delete_tickets_locked()
            self._delete_tickets[confirm_token] = _DeleteTicket(
                items=(item,),
                expires_at=time.monotonic() + DELETE_TOKEN_TTL_SECONDS,
            )
        return Response(
            success=True,
            message="删除预览已生成",
            data=self._delete_plan_data(plan),
        )

    def api_delete(
        self,
        item_id: str,
        confirmed: bool = False,
        confirm_token: str = "",
    ) -> Response:
        """消费确认令牌并提交后台删除及复核任务。"""
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        if not confirmed or not str(confirm_token or "").strip():
            return Response(success=False, message="请先预览并确认删除目标")
        with self._state_lock:
            if self._task_running_locked():
                return self._busy_response()
            self._prune_delete_tickets_locked()
            ticket = self._delete_tickets.get(confirm_token)
            if (
                not ticket
                or len(ticket.items) != 1
                or ticket.items[0].item_id != item_id
            ):
                return Response(success=False, message="确认令牌无效或已过期，请重新预览")
            ticket_item = ticket.items[0]
            current_item = self._find_item_locked(item_id)
            if current_item != ticket_item:
                self._delete_tickets.pop(confirm_token, None)
                return Response(success=False, message="搜索结果已变化，请重新预览")
            plan = self._engine.build_delete_plan(ticket_item, confirm_token)
            if plan.blocked_reasons:
                self._delete_tickets.pop(confirm_token, None)
                return Response(
                    success=False,
                    message=plan.blocked_reasons[0],
                    data=self._delete_plan_data(plan),
                )
            self._delete_tickets.pop(confirm_token, None)
            return self._queue_task_locked(
                kind="delete",
                label=f"删除源文件 {ticket_item.name}",
                task=lambda: self._run_delete(ticket_item),
            )

    def api_delete_batch_preview(
        self,
        request: DeleteBatchPreviewRequest,
    ) -> Response:
        """校验选中的搜索结果并生成绑定整批文件的确认令牌。"""
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        with self._state_lock:
            if self._task_running_locked():
                return self._busy_response()
            selected_items, error = self._select_delete_items_locked(request)
        if error:
            return Response(success=False, message=error)

        confirm_token = secrets.token_urlsafe(24)
        plans = [
            self._engine.build_delete_plan(item, confirm_token)
            for item in selected_items
        ]
        blocked = any(plan.blocked_reasons for plan in plans)
        preview_data = self._batch_delete_plan_data(
            plans,
            confirm_token="" if blocked else confirm_token,
        )
        if blocked:
            return Response(
                success=True,
                message="批量删除预览存在阻止项，请重新搜索后再选择",
                data=preview_data,
            )

        with self._state_lock:
            if self._task_running_locked():
                return self._busy_response()
            if not self._items_match_report_locked(selected_items):
                return Response(success=False, message="搜索结果已变化，请重新选择")
            self._prune_delete_tickets_locked()
            self._delete_tickets[confirm_token] = _DeleteTicket(
                items=selected_items,
                expires_at=time.monotonic() + DELETE_TOKEN_TTL_SECONDS,
            )
        return Response(
            success=True,
            message=f"已生成 {len(selected_items)} 个源文件的删除预览",
            data=preview_data,
        )

    def api_delete_batch(
        self,
        request: DeleteBatchExecuteRequest,
    ) -> Response:
        """消费整批确认令牌并提交后台源文件删除任务。"""
        confirm_token = str(request.confirm_token or "").strip()
        if not self._enabled:
            return Response(success=False, message="插件未启用")
        if not request.confirmed or not confirm_token:
            return Response(success=False, message="请先预览并确认批量删除目标")
        with self._state_lock:
            if self._task_running_locked():
                return self._busy_response()
            self._prune_delete_tickets_locked()
            ticket = self._delete_tickets.get(confirm_token)
            if not ticket:
                return Response(success=False, message="确认令牌无效或已过期，请重新预览")
            if not self._items_match_report_locked(ticket.items):
                self._delete_tickets.pop(confirm_token, None)
                return Response(success=False, message="搜索结果已变化，请重新预览")
            selected_items = ticket.items
            self._delete_tickets.pop(confirm_token, None)
            return self._queue_task_locked(
                kind="delete_batch",
                label=f"删除 {len(selected_items)} 个源文件",
                task=lambda: self._run_delete_batch(selected_items),
            )

    def _run_search(self, query: str) -> Dict[str, Any]:
        report = self._engine.search_files(query, self._stop_event)
        with self._state_lock:
            self._search_report = report
        return {
            "kind": "search",
            "success": not report.cancelled,
            "message": report.message,
            "query": report.query,
            "scanned_files": report.scanned_files,
            "matched_files": report.matched_files,
            "failed_entries": report.failed_entries,
            "truncated": report.truncated,
            "generated_at": report.generated_at,
        }

    def _run_delete(self, item: FileSearchItem) -> Dict[str, Any]:
        result = self._engine.delete_file(item)
        self._remove_verified_results((result,))
        return {
            "kind": "delete",
            "success": result.verified,
            "verified": result.verified,
            "message": result.message,
            "result": self._delete_result_data(result),
        }

    def _run_delete_batch(
        self,
        items: Tuple[FileSearchItem, ...],
    ) -> Dict[str, Any]:
        preflight_plans = [
            self._engine.build_delete_plan(item, "")
            for item in items
        ]
        blocked_plans = [
            plan for plan in preflight_plans if plan.blocked_reasons
        ]
        if blocked_plans:
            blocked_reasons = [
                f"{plan.relative_path}：{reason}"
                for plan in blocked_plans
                for reason in plan.blocked_reasons
            ]
            message = (
                f"批量删除已取消，{len(blocked_plans)} 个源文件状态发生变化，"
                "本批次未删除任何文件"
            )
            return {
                "kind": "delete_batch",
                "success": False,
                "verified": False,
                "message": message,
                "requested_count": len(items),
                "processed_count": 0,
                "deleted_count": 0,
                "verified_count": 0,
                "failed_count": len(items),
                "verified_item_ids": [],
                "blocked_reasons": blocked_reasons[:MAX_BATCH_PREVIEW_ITEMS],
                "results": [],
                "results_truncated": False,
            }

        results: List[FileDeleteResult] = []
        for item in items:
            if self._stop_event.is_set():
                break
            result = self._engine.delete_file(item)
            results.append(result)
            self._append_log(f"源文件 {item.relative_path}：{result.message}")

        self._remove_verified_results(tuple(results))
        verified_count = sum(1 for result in results if result.verified)
        deleted_count = sum(1 for result in results if result.deleted)
        processed_count = len(results)
        requested_count = len(items)
        failed_count = requested_count - verified_count
        succeeded = processed_count == requested_count and verified_count == requested_count
        if succeeded:
            message = f"批量删除完成，{verified_count} 个源文件均已删除并通过复核"
        elif processed_count < requested_count:
            message = (
                f"批量删除已停止，已处理 {processed_count}/{requested_count} 个源文件，"
                f"复核通过 {verified_count} 个"
            )
        else:
            message = (
                f"批量删除部分完成，已删除 {deleted_count} 个，"
                f"复核通过 {verified_count}/{requested_count} 个"
            )
        return {
            "kind": "delete_batch",
            "success": succeeded,
            "verified": succeeded,
            "message": message,
            "requested_count": requested_count,
            "processed_count": processed_count,
            "deleted_count": deleted_count,
            "verified_count": verified_count,
            "failed_count": failed_count,
            "verified_item_ids": [
                result.item_id for result in results if result.verified
            ],
            "results": [
                self._delete_result_data(result)
                for result in results[:MAX_BATCH_PREVIEW_ITEMS]
            ],
            "results_truncated": len(results) > MAX_BATCH_PREVIEW_ITEMS,
        }

    def _remove_verified_results(
        self,
        results: Tuple[FileDeleteResult, ...],
    ) -> None:
        verified_ids = {
            result.item_id
            for result in results
            if result.verified
        }
        if not verified_ids:
            return
        with self._state_lock:
            if self._search_report:
                self._search_report.items = [
                    candidate
                    for candidate in self._search_report.items
                    if candidate.item_id not in verified_ids
                ]
                self._search_report.matched_files = max(
                    0,
                    self._search_report.matched_files - len(verified_ids),
                )
            stale_tokens = [
                token
                for token, ticket in self._delete_tickets.items()
                if any(item.item_id in verified_ids for item in ticket.items)
            ]
            for token in stale_tokens:
                self._delete_tickets.pop(token, None)

    def _queue_task_locked(
        self,
        kind: str,
        label: str,
        task: Callable[[], Dict[str, Any]],
    ) -> Response:
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
            )
        except Exception as err:
            self._task_status = "failed"
            self._task_finished_at = self._now()
            self._task_message = f"{label}提交失败"
            self._last_error = str(err)
            return Response(success=False, message=f"后台任务提交失败：{str(err)}")
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
            succeeded = result.get("success") is not False
            message = str(result.get("message") or f"{label}完成")
            with self._state_lock:
                self._last_report = dict(result)
                self._task_status = "succeeded" if succeeded else "failed"
                self._task_finished_at = self._now()
                self._task_message = message
                self._last_error = "" if succeeded else message
            self._append_log(message)
        except Exception as err:
            if generation != self._generation:
                return
            with self._state_lock:
                self._task_status = "failed"
                self._task_finished_at = self._now()
                self._task_message = f"{label}失败"
                self._last_error = str(err)
            logger.error(f"【{self.plugin_name}】{label}失败：{str(err)}", exc_info=True)
            self._append_log(f"{label}失败：{str(err)}")

    def _status_data(self) -> Dict[str, Any]:
        with self._state_lock:
            search_summary = self._search_summary_locked()
            return {
                "enabled": self._enabled,
                "task_status": self._task_status,
                "task_kind": self._task_kind,
                "task_message": self._task_message,
                "task_started_at": self._task_started_at,
                "task_finished_at": self._task_finished_at,
                "last_error": self._last_error,
                "search": search_summary,
                "last_report": dict(self._last_report),
                "logs": list(self._logs[-100:]),
                "config": {
                    "root_dir": (
                        self._search_config.root_dir.as_posix()
                        if self._search_config.root_dir
                        else ""
                    )
                },
            }

    def _results_data(self, page: int, page_size: int) -> Dict[str, Any]:
        with self._state_lock:
            report = self._search_report
            items = list(report.items) if report else []
            total = len(items)
            page_count = max(1, (total + page_size - 1) // page_size)
            safe_page = min(page, page_count)
            start = (safe_page - 1) * page_size
            return {
                "items": [
                    self._item_data(item)
                    for item in items[start:start + page_size]
                ],
                "total": total,
                "page": safe_page,
                "page_size": page_size,
                "page_count": page_count,
                "summary": self._search_summary_locked(),
            }

    def _search_summary_locked(self) -> Dict[str, Any]:
        report = self._search_report
        if not report:
            return {
                "query": "",
                "scanned_files": 0,
                "matched_files": 0,
                "visible_files": 0,
                "failed_entries": 0,
                "truncated": False,
                "generated_at": "",
                "message": "尚未搜索",
            }
        return {
            "query": report.query,
            "scanned_files": report.scanned_files,
            "matched_files": report.matched_files,
            "visible_files": len(report.items),
            "failed_entries": report.failed_entries,
            "truncated": report.truncated,
            "generated_at": report.generated_at,
            "message": report.message,
        }

    def _find_item(self, item_id: str) -> Optional[FileSearchItem]:
        with self._state_lock:
            return self._find_item_locked(item_id)

    def _find_item_locked(self, item_id: str) -> Optional[FileSearchItem]:
        if not self._search_report:
            return None
        return next(
            (
                item
                for item in self._search_report.items
                if item.item_id == item_id
            ),
            None,
        )

    def _select_delete_items_locked(
        self,
        request: DeleteBatchPreviewRequest,
    ) -> Tuple[Tuple[FileSearchItem, ...], str]:
        if not self._search_report:
            return (), "当前没有可删除的搜索结果"
        report_items = tuple(self._search_report.items)
        item_map = {item.item_id: item for item in report_items}
        item_ids = list(
            dict.fromkeys(
                str(item_id or "").strip()
                for item_id in request.item_ids
                if str(item_id or "").strip()
            )
        )
        excluded_ids = list(
            dict.fromkeys(
                str(item_id or "").strip()
                for item_id in request.excluded_item_ids
                if str(item_id or "").strip()
            )
        )
        if request.select_all:
            if any(item_id not in item_map for item_id in excluded_ids):
                return (), "排除项已不在当前搜索结果中，请重新选择"
            excluded_set = set(excluded_ids)
            selected_items = tuple(
                item for item in report_items if item.item_id not in excluded_set
            )
        else:
            if excluded_ids:
                return (), "仅在全选模式下允许设置排除项"
            if any(item_id not in item_map for item_id in item_ids):
                return (), "所选文件已不在当前搜索结果中，请重新选择"
            selected_items = tuple(item_map[item_id] for item_id in item_ids)
        if not selected_items:
            return (), "请至少选择一个源文件"
        if len(selected_items) > MAX_BATCH_DELETE_ITEMS:
            return (), f"单次最多删除 {MAX_BATCH_DELETE_ITEMS} 个源文件"
        return selected_items, ""

    def _items_match_report_locked(
        self,
        items: Tuple[FileSearchItem, ...],
    ) -> bool:
        return all(
            self._find_item_locked(item.item_id) == item
            for item in items
        )

    def _prune_delete_tickets_locked(self) -> None:
        current_time = time.monotonic()
        expired_tokens = [
            token
            for token, ticket in self._delete_tickets.items()
            if ticket.expires_at <= current_time
        ]
        for token in expired_tokens:
            self._delete_tickets.pop(token, None)

    def _task_running_locked(self) -> bool:
        return bool(self._task_future and not self._task_future.done())

    def _busy_response(self) -> Response:
        return Response(
            success=False,
            message=self._task_message or "已有后台任务正在执行",
            data={"status": self._task_status},
        )

    def _append_log(self, message: str) -> None:
        log_line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        with self._state_lock:
            self._logs.append(log_line)
            self._logs = self._logs[-MAX_LOG_LINES:]
        logger.info(f"【{self.plugin_name}】{message}")

    @staticmethod
    def _item_data(item: FileSearchItem) -> Dict[str, Any]:
        return {
            "item_id": item.item_id,
            "relative_path": item.relative_path,
            "absolute_path": item.absolute_path,
            "name": item.name,
            "parent": item.parent,
            "suffix": item.suffix,
            "size": item.size,
            "modified_at": item.modified_at,
        }

    @staticmethod
    def _delete_plan_data(plan: FileDeletePlan) -> Dict[str, Any]:
        return {
            "item_id": plan.item_id,
            "relative_path": plan.relative_path,
            "absolute_path": plan.absolute_path,
            "size": plan.size,
            "modified_at": plan.modified_at,
            "confirm_token": plan.confirm_token,
            "blocked_reasons": list(plan.blocked_reasons),
        }

    @classmethod
    def _batch_delete_plan_data(
        cls,
        plans: List[FileDeletePlan],
        confirm_token: str,
    ) -> Dict[str, Any]:
        blocked_plans = [plan for plan in plans if plan.blocked_reasons]
        blocked_reasons = [
            f"{plan.relative_path}：{reason}"
            for plan in blocked_plans
            for reason in plan.blocked_reasons
        ]
        preview_items = []
        for plan in plans[:MAX_BATCH_PREVIEW_ITEMS]:
            item_data = cls._delete_plan_data(plan)
            item_data.pop("confirm_token", None)
            preview_items.append(item_data)
        return {
            "selected_count": len(plans),
            "ready_count": len(plans) - len(blocked_plans),
            "blocked_count": len(blocked_plans),
            "total_size": sum(plan.size for plan in plans),
            "confirm_token": confirm_token if not blocked_plans else "",
            "blocked_reasons": blocked_reasons[:MAX_BATCH_PREVIEW_ITEMS],
            "items": preview_items,
            "preview_truncated": len(plans) > MAX_BATCH_PREVIEW_ITEMS,
            "permanent": True,
        }

    @staticmethod
    def _delete_result_data(result: FileDeleteResult) -> Dict[str, Any]:
        return {
            "item_id": result.item_id,
            "relative_path": result.relative_path,
            "absolute_path": result.absolute_path,
            "deleted": result.deleted,
            "verified": result.verified,
            "message": result.message,
        }

    @classmethod
    def _merge_defaults(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        search_config = config_from_dict({**cls._default_config(), **config})
        return {
            "enabled": search_config.enabled,
            "root_dir": (
                search_config.root_dir.as_posix()
                if search_config.root_dir
                else ""
            ),
        }

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "enabled": False,
            "root_dir": "",
        }

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
