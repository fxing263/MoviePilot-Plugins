"""MoviePilot 115 延迟暂存插件；只投递硬链接，不实现上传、STRM 或媒体库刷新。"""

import copy
import threading
from typing import Optional

from fastapi import Body, Depends, HTTPException

from app.schemas.response import Response
from app.schemas.token import TokenPayload
from app.schemas.types import EventType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.plugin.base import _PluginBase
from app.sdk.security import verify_token

from .queue import DEFAULTS, StagingQueue, validate_config


def _admin(principal: TokenPayload = Depends(verify_token)) -> None:
    if principal.super_user is not True:
        raise HTTPException(status_code=403, detail="仅管理员可以管理延迟暂存任务")


class Delayed115Staging(_PluginBase):
    """整理结果事件入队，由宿主调度器执行到期投递，按配置取得成功确认后才清理。"""

    plugin_name = "115延迟暂存"
    plugin_desc = "整理完成后按目录或文件大小延迟硬链接到115监控目录，确认远端成功后安全清理。"
    plugin_icon = "mdi-clock-outline"
    plugin_version = "1.3.1"
    plugin_author = "MoviePilot local"
    author_url = "https://github.com/jxxghp/MoviePilot"
    plugin_config_prefix = "delayed115staging_"
    plugin_order = 30
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.RLock()
        self._enabled = False
        self._config = copy.deepcopy(DEFAULTS)
        self._queue = None
        self._error = ""

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """校验通过才启用；非法直写配置恢复上次有效值，且停止所有文件操作。"""
        with self._guard:
            self._enabled = False
            self._queue = StagingQueue(self.get_data_path())
            try:
                checked = validate_config(config or {})
                self._queue.tasks()
            except (OSError, ValueError, TypeError) as error:
                self._error = str(error)
                logger.error(f"115延迟暂存未启用：{error}")
                self.systemmessage.put(f"115延迟暂存配置或队列错误：{error}")
                previous = self.get_data("accepted_config")
                if previous is not None:
                    self.update_config(previous)
                return
            self._config = checked
            self.save_data("accepted_config", checked)
            self._enabled = checked["enabled"]
            self._error = ""

    def get_state(self) -> bool:
        """报告实际运行状态，校验失败与停止后均为关闭。"""
        return self._enabled

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        """使用带保存前校验与任务操作的标准联邦 Vue 插件界面。"""
        return "vue", "dist/assets"

    def get_form(self) -> tuple[list, dict]:
        """配置由联邦组件编辑，默认模型仍由插件提供。"""
        return [], copy.deepcopy(self._config)

    def get_page(self) -> list:
        """详情由联邦组件加载持久化任务快照。"""
        return []

    def get_service(self) -> list[dict]:
        """使用宿主定时服务每 15 秒检查到期任务，不创建睡眠线程。"""
        if not self._enabled:
            return []
        return [{"id": "Delayed115StagingTick", "name": "115延迟暂存队列",
                 "trigger": "interval", "func": self.process_tasks,
                 "kwargs": {"seconds": 15}}]

    def stop_service(self) -> None:
        """等当前短操作结束后关闭入口；队列日志保留供重启恢复。"""
        with self._guard:
            self._enabled = False

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event) -> None:
        """只登记成功整理事件中的本地目标文件，不递归扫描下载目录。"""
        with self._guard:
            if not self._enabled or not event:
                return
            payload = event.event_data or {}
            info = payload.get("transferinfo")
            if hasattr(info, "model_dump"):
                info = info.model_dump()
            if not info or info.get("success") is not True:
                return
            target = info.get("target_item") or {}
            if target.get("storage") != "local":
                return
            paths = info.get("file_list_new") or [target.get("path")]
            for path in dict.fromkeys(paths):
                if not path:
                    continue
                try:
                    self._queue.enqueue(self._config, str(path))
                except (OSError, ValueError) as error:
                    self._error = f"登记失败 {path}：{error}"
                    logger.error(f"115延迟暂存 {self._error}")

    def process_tasks(self) -> None:
        """推进队列；错误显示在状态页，持久化失败不继续执行副作用。"""
        with self._guard:
            if not self._enabled:
                return
            try:
                if self._config.get("scan_once"):
                    count = self._queue.scan_once(self._config)
                    updated = dict(self._config, scan_once=False)
                    self.update_config(updated)
                    self.save_data("accepted_config", updated)
                    self._config = updated
                    logger.info(f"115延迟暂存全量扫描完成，匹配 {count} 个文件")
                self._queue.purge_history(self._config.get("history_days", 7))
                self._queue.tick(cleanup_organized=self._config["cleanup_organized"],
                                 confirmation_mode=self._config.get("confirmation_mode", "manual"))
            except (OSError, ValueError) as error:
                self._error = str(error)
                logger.error(f"115延迟暂存队列失败：{error}")

    def get_api(self) -> list[dict]:
        """全部接口要求管理员身份；无匿名回调和外部上传请求。"""
        return [{"path": path, "endpoint": endpoint, "methods": methods,
                 "auth": "bear", "dependencies": [Depends(_admin)], "summary": summary}
                for path, endpoint, methods, summary in [
                    ("/validate", self.validate_settings, ["POST"], "验证115延迟暂存配置"),
                    ("/tasks", self.task_list, ["GET"], "读取115延迟暂存任务"),
                    ("/task", self.task_action, ["POST"], "操作115延迟暂存任务"),
                ]]

    def validate_settings(self, config: dict = Body(...)) -> Response:
        """配置组件提交前校验，不写配置、不创建目录、不修改任务。"""
        try:
            return Response(success=True, data=validate_config(config))
        except (OSError, ValueError, TypeError) as error:
            return Response(success=False, message=str(error))

    def task_list(self) -> Response:
        """停用时仍可查看任务；损坏日志显示错误而非重建队列。"""
        with self._guard:
            try:
                tasks = self._queue.tasks() if self._queue else []
                return Response(success=True, data={"tasks": tasks, "error": self._error,
                                                    "enabled": self._enabled,
                                                    "confirmation_mode": self._config.get("confirmation_mode", "manual")})
            except (OSError, ValueError) as error:
                return Response(success=False, message=str(error))

    def task_action(self, payload: dict = Body(...)) -> Response:
        """管理员提交指定任务操作；远端确认是可信调用方的核验声明，不是上传检测。"""
        with self._guard:
            if not self._enabled:
                return Response(success=False, message="插件未启用，请先修正配置并启用")
            try:
                task_id, action = payload.get("task_id"), payload.get("action")
                reference = payload.get("remote_reference", "")
                if not isinstance(task_id, str) or not isinstance(action, str) or not isinstance(reference, str):
                    raise ValueError("任务 ID、操作与远端引用必须为字符串")
                self._queue.action(task_id, action, reference, payload.get("verified") is True)
                return Response(success=True, message="操作已记录，定时服务将继续处理")
            except (OSError, ValueError) as error:
                return Response(success=False, message=str(error))
