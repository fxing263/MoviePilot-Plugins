"""整理完成后尝试 115 秒传；复用延迟暂存插件的事件、调度与联邦页面接线。"""

import copy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import threading
import time
from typing import Optional

from fastapi import Body, Depends, HTTPException

from app.schemas.response import Response
from app.schemas.token import TokenPayload
from app.schemas.types import EventType
from app.sdk.events import Event, eventmanager
from app.sdk.logging import logger
from app.sdk.plugin.base import _PluginBase
from app.sdk.security import verify_token

from .bdmv import BdmvWorker
from .client import RapidClient, RemoteConflictError, RetryLaterError, calculate_hashes, open_source
from .queue import FileChangedError, UploadQueue
from .normal import upload
from .progress import UploadProgress
from .torrents import reconcile
from .rules import DEFAULTS, validate_config
from .directories import local_library_roots, validate_library_roots


def _new_tag_hook(**config):
    """仅启用 qB 接管时加载宿主挂钩，普通上传不依赖下载器模块。"""
    from .tag_hook import TagMonitorHook

    return TagMonitorHook(**config)


def _admin(principal: TokenPayload = Depends(verify_token)) -> None:
    if principal.super_user is not True:
        raise HTTPException(status_code=403, detail="仅管理员可以管理115秒传任务")


def _payload(value: object) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else {}


class Rapid115Upload(_PluginBase):
    """只消费成功的本地文件整理，队列与本地媒体互不修改。"""

    plugin_name = "媒体整理增强"
    plugin_desc = "接入MP整理，秒传重试后普通上传，整种子上传后回写qB标签。"
    plugin_icon = "mdi-cloud-upload-outline"
    plugin_version = "1.2.2"
    plugin_author = "MoviePilot local"
    author_url = "https://github.com/jxxghp/MoviePilot"
    plugin_config_prefix = "rapid115upload_"
    plugin_order = 31
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.RLock()
        self._execution = threading.Lock()
        self._stop = threading.Event()
        self._config = copy.deepcopy(DEFAULTS)
        self._queue = None
        self._progress = UploadProgress()
        self._enabled = False
        self._error = ""
        self._hook = None
        self._bdmv = None

    def init_plugin(self, config: Optional[dict] = None) -> None:
        """停止旧消费者后加载配置；错误时保持关闭并保留队列原件。"""
        self.stop_service()
        with self._execution, self._guard:
            self._queue = UploadQueue(self.get_data_path())
            try:
                self._config = validate_config(config or {})
                self._queue.tasks()
                self._bdmv = BdmvWorker(self.get_data_path(), self._config["bdmv"], self._stop)
                self._bdmv.queue.snapshot()
            except (OSError, ValueError, TypeError) as error:
                self._error = str(error)
                logger.error(f"115仅秒传未启用：{error}")
                return
            self._error = ""
            self._hook = None
            if self._config["enabled"] and self._config["qb_enabled"]:
                try:
                    self._hook = _new_tag_hook(
                        downloaders=tuple(self._config["downloaders"]),
                        include_tags=tuple(self._config["include_tags"]),
                        exclude_tags=tuple(self._config["exclude_tags"]),
                    )
                    self._hook.install()
                except (RuntimeError, ValueError) as error:
                    self._error = str(error)
                    self._hook = None
                    return
            self._stop.clear()
            self._enabled = self._config["enabled"]

    def get_state(self) -> bool:
        """返回通过配置与队列校验后的启用状态。"""
        return self._enabled

    @staticmethod
    def get_render_mode() -> tuple[str, str]:
        """复用标准联邦插件页面协议。"""
        return "vue", "dist/assets"

    def get_form(self) -> tuple[list, dict]:
        """表单默认值由插件提供，保存使用宿主标准入口。"""
        return [], copy.deepcopy(self._config)

    def get_page(self) -> list:
        """三行路径由联邦页面渲染。"""
        return []

    @staticmethod
    def get_sidebar_nav() -> list[dict]:
        """在整理分组提供只读历史和上传队列入口，不改写宿主整理历史。"""
        return [{"nav_key": "main", "title": "115秒传", "icon": "mdi-cloud-upload-outline",
                 "section": "organize", "permission": "admin", "order": 36},
                {"nav_key": "history", "title": "媒体整理记录", "icon": "mdi-history",
                 "section": "organize", "permission": "admin", "order": 35}]

    def get_service(self) -> list[dict]:
        """宿主每15秒调度队列，重试等待通过持久化时间表达。"""
        if not self._enabled:
            return []
        services = [{"id": "Rapid115UploadTick", "name": "115仅秒传队列", "trigger": "interval",
                 "func": self.process_tasks, "kwargs": {"seconds": 15}}]
        if self._bdmv and self._config["bdmv"]["enabled"]:
            minute, hour, day, month, weekday = self._config["bdmv"]["cron"].split()
            services.extend([
                {"id": "Rapid115BdmvScan", "name": "BDMV 定时目录上传发现", "trigger": "cron",
                 "func": self._bdmv.scan, "kwargs": {"minute": minute, "hour": hour, "day": day,
                                                       "month": month, "day_of_week": weekday}},
                {"id": "Rapid115BdmvTick", "name": "BDMV 上传状态核对", "trigger": "interval",
                 "func": self._bdmv.tick, "kwargs": {"seconds": 60}},
            ])
        return services

    def stop_service(self) -> None:
        """先取消哈希和后续请求，再等待当前有超时的请求退出；不释放在用资源。"""
        self._stop.set()
        with self._guard:
            self._enabled = False
        if self._bdmv is not None:
            self._bdmv.close()
        with self._execution:
            if self._hook is not None:
                self._hook.stop()
                self._hook = None

    @eventmanager.register(EventType.TransferFailed)
    def on_transfer_failed(self, event: Event) -> None:
        """失败文件不上传，仅保留种子来源，供后续手动补整理恢复关联。"""
        with self._guard:
            if not self._enabled or not event:
                return
            payload = event.event_data or {}
            info = _payload(payload.get("transferinfo"))
            item = _payload(info.get("fileitem") or payload.get("fileitem"))
            if item.get("storage") != "local":
                return
            for source in info.get("file_list") or [item.get("path")]:
                try:
                    self._queue.source_context(str(source or ""), payload.get("downloader") or "",
                                               payload.get("download_hash") or "", remember=True)
                except (OSError, ValueError, TypeError):
                    logger.warning("保存失败整理的下载关联失败，后续不自动猜测种子")

    @eventmanager.register(EventType.TransferComplete)
    def on_transfer_complete(self, event: Event) -> None:
        """事件只登记，不读整部影片或请求115，避免阻塞本地整理。"""
        with self._guard:
            if not self._enabled or not event:
                return
            payload = event.event_data or {}
            info = _payload(payload.get("transferinfo"))
            target = _payload(info.get("target_item"))
            if info.get("success") is not True or target.get("storage") != "local":
                return
            source_item = _payload(info.get("fileitem") or payload.get("fileitem"))
            targets = info.get("file_list_new") or [target.get("path")]
            sources = info.get("file_list") or []
            # 目录设置变化后只停止失效映射的新登记，不改动已入队任务。
            try:
                roots = local_library_roots()
            except Exception:
                self._error = "读取MP目录管理失败，本次整理暂未登记上传"
                logger.error(self._error)
                return
            current_config = {**self._config, "mappings": [
                item for item in self._config["mappings"] if item["library_root"] in roots
            ]}
            if len(current_config["mappings"]) != len(self._config["mappings"]):
                self._error = "部分整理目录已从MP目录管理移除，请在插件配置中重新选择"
            for index, path in enumerate(targets):
                if not path:
                    continue
                source = sources[index] if len(sources) == len(targets) else source_item.get("path", "")
                try:
                    downloader, torrent_hash = payload.get("downloader") or "", payload.get("download_hash") or ""
                    if source_item.get("storage") == "local":
                        downloader, torrent_hash = self._queue.source_context(
                            str(source), downloader, torrent_hash)
                    self._queue.enqueue(
                        current_config, str(path), str(source), payload.get("transfer_history_id"),
                        downloader=downloader, download_hash=torrent_hash,
                    )
                except (OSError, ValueError, TypeError) as error:
                    self._error = f"秒传登记失败：{path}：{error}"
                    logger.error(self._error)

    def process_tasks(self) -> None:
        """按并发上限消费到期任务；停止时等待在途工作退出。"""
        if not self._execution.acquire(blocking=False):
            return
        try:
            if not self._enabled or self._stop.is_set():
                return
            with self._queue.worker() as acquired:
                if not acquired:
                    return
                with ThreadPoolExecutor(max_workers=self._config["concurrency"],
                                        thread_name_prefix="rapid115") as executor:
                    active = set()
                    while not self._stop.is_set():
                        while len(active) < self._config["concurrency"]:
                            task = self._queue.claim()
                            if task is None:
                                break
                            active.add(executor.submit(self._run_task, task))
                        if not active:
                            break
                        done, active = wait(active, return_when=FIRST_COMPLETED)
                        for future in done:
                            future.result()
                if not self._stop.is_set():
                    reconcile(self._queue, self._stop)
        except Exception as error:
            # 不输出异常原文，网络库异常可能携带授权请求信息。
            self._error = f"秒传队列执行失败（{type(error).__name__}），请检查插件数据目录和日志"
            logger.error(self._error)
        finally:
            self._execution.release()

    def _run_task(self, task: dict) -> None:
        client = None
        report = lambda stage, completed=0, total=0: self._progress.update(task["id"], stage, completed, total)
        report("hashing")
        try:
            with open_source(task) as stream:
                hashes = calculate_hashes(stream, task, self._stop)
                self._queue.update(task["id"], hashes=hashes)
                report("checking")
                client = RapidClient(self._stop)
                result = client.attempt(task, stream, hashes)
                if result is None:
                    misses = task.get("instant_misses", 0) + 1
                    task = self._queue.update(task["id"], instant_misses=misses)
                    if task.get("upload_mode") == "normal" or misses >= task.get("max_attempts", 3):
                        task = self._queue.update(task["id"], upload_mode="normal")
                        result = upload(client, task, stream, hashes, client.initialized, report)
            if result is None:
                self._queue.defer(task, "未命中秒传，已停止本次尝试，等待下次重试")
            else:
                self._queue.update(task["id"], state="uploaded", receipt=result,
                                   uploaded_at=time.time(), ready_at=None, error="")
                self._remove_uploaded_file(task)
                logger.info(f"115上传成功：{task['organized_path']} → {task['remote_path']}")
            self._error = ""
        except (FileNotFoundError, FileChangedError, RemoteConflictError) as error:
            self._queue.update(task["id"], state="blocked", error=str(error))
        except InterruptedError:
            self._queue.defer(task, "插件已停止，重新启用后继续")
        except RetryLaterError as error:
            self._queue.defer(task, str(error), error.delay)
        except OSError:
            self._queue.defer(task, "本地文件或队列暂不可读写，等待重试")
        except Exception as error:
            self._queue.defer(task, f"秒传尝试异常（{type(error).__name__}），等待重试")
        finally:
            self._progress.remove(task["id"])
            if client is not None:
                client.close()

    def _remove_uploaded_file(self, task: dict) -> None:
        """仅在成功状态落盘后按当前配置删除整理目标，失败不回滚上传或保存删除记录。"""
        if not self._config.get("delete_after_upload", False):
            return
        try:
            path = Path(task["organized_path"])
            path.unlink(missing_ok=True)
            if self._config.get("remove_empty_parents", False):
                self._remove_empty_parents(path)
        except OSError as error:
            logger.warning(f"115上传已成功，本地整理文件删除失败（{type(error).__name__}）："
                           f"{task['organized_path']}")

    def _remove_empty_parents(self, path: Path) -> None:
        """只逐层移除映射范围内的空目录；保留根目录，非空或不可删除时停止。"""
        roots = [Path(item["library_root"]) for item in self._config["mappings"]
                 if path.is_relative_to(Path(item["library_root"]))]
        if not roots:
            return
        root = max(roots, key=lambda item: len(item.parts))
        parent = path.parent
        while parent != root and parent.is_relative_to(root):
            try:
                parent.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                break
            parent = parent.parent

    def get_api(self) -> list[dict]:
        """沿用延迟暂存的管理员鉴权与标准响应，不提供匿名执行入口。"""
        from .reorganize import reorganize

        return [{"path": path, "endpoint": endpoint, "methods": methods, "auth": "bear",
                 "dependencies": [Depends(_admin)], "summary": summary}
                for path, endpoint, methods, summary in [
                    ("/validate", self.validate_settings, ["POST"], "验证115仅秒传配置"),
                    ("/reorganize", reorganize, ["POST"], "按预览编辑目标路径重新整理"),
                    ("/tasks", self.task_list, ["GET"], "读取115秒传记录"),
                    ("/task", self.task_action, ["POST"], "重试或取消115秒传任务"),
                ]]

    def validate_settings(self, config: dict = Body(...)) -> Response:
        """只验证配置，不保存或访问115。"""
        try:
            checked = validate_config(config)
            validate_library_roots(checked, local_library_roots())
            return Response(success=True, data=checked)
        except (ValueError, OSError, TypeError) as error:
            return Response(success=False, message=str(error))

    def task_list(self) -> Response:
        """即使停用也可查询已保存记录，查询不触发秒传。"""
        try:
            tasks = self._queue.tasks() if self._queue else []
            for task in tasks:
                if task["state"] == "running":
                    task["progress"] = self._progress.snapshot(task["id"])
            return Response(success=True, data={"tasks": tasks,
                                                "bdmv": self._bdmv.queue.snapshot() if self._bdmv else {"tasks": [], "error": ""},
                                                "enabled": self._enabled, "error": self._error,
                                                "mappings": [{"library_root": item["library_root"],
                                                              "remote_root": item["remote_root"]}
                                                             for item in self._config["mappings"]],
                                                "concurrency": self._config["concurrency"],
                                                "tag_monitor_active": bool(self._hook and self._hook.installed),
                                                "torrents": self._queue.torrent_states() if self._queue else {}})
        except (OSError, ValueError, TypeError):
            return Response(success=False, message="读取秒传记录失败，原队列已保留")

    def task_action(self, payload: dict = Body(...)) -> Response:
        """重试仅重新排队，恢复缺失文件后可继续；取消不删除本地或远端文件。"""
        try:
            if self._queue is None or not isinstance(payload.get("task_id"), str):
                raise ValueError("任务不存在")
            self._queue.action(payload["task_id"], payload.get("action"))
            return Response(success=True)
        except (OSError, ValueError, TypeError) as error:
            return Response(success=False, message=str(error))
