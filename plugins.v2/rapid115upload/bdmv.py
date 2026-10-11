"""BDMV 每日发现、CD2 复制收据核对与可恢复的 qB 标签回写。"""

import copy
import fcntl
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Optional

from .bdmv_cd2 import BdmvCd2ConflictError, BdmvCd2Error
from .bdmv_rules import mapped_paths, torrent_identity
from .torrents import _qb_module


def _adapter(plugin_id: str, stop: threading.Event) -> object:
    from .bdmv_cd2 import BdmvCd2Adapter
    return BdmvCd2Adapter(plugin_id=plugin_id, stop=stop)


def _tags(row: dict) -> set[str]:
    return {tag.strip() for tag in row.get("tags", "").split(",")}


class BdmvQueue:
    """持久化提交意图；文件锁防止同一数据目录的重复复制。"""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / "bdmv.json"
        self._guard = threading.RLock()

    @contextmanager
    def locked(self) -> Iterator[dict]:
        """跨线程和进程串行访问；损坏快照不会被覆盖。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._guard, (self.directory / "bdmv.lock").open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield self._read()

    def _read(self) -> dict:
        data = {"version": 1, "tasks": {}, "error": ""}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("tasks"), dict):
                raise ValueError("BDMV 队列损坏，原文件已保留")
            for key, task in data["tasks"].items():
                if not isinstance(task, dict) or task.get("id") != key or not all(name in task for name in ("state", "source", "target", "fingerprint", "manifest", "downloader", "download_hash")):
                    raise ValueError("BDMV 队列记录不完整，原文件已保留")
        return data

    def save(self, data: dict) -> None:
        """调用方持锁时原子替换快照并同步目录，先落盘再执行外部副作用。"""
        temporary = self.path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def snapshot(self) -> dict:
        """仅返回页面需要的状态和进度，不暴露连接或授权信息。"""
        # 写入使用原子替换，页面只读完整旧/新快照，不等待远程 RPC 持有的执行锁。
        data = self._read()
        fields = ("id", "downloader", "download_hash", "name", "source", "target", "state", "error", "created_at", "updated_at", "progress")
        return {"error": data.get("error", ""), "tasks": [{key: copy.deepcopy(task[key]) for key in fields if key in task} for task in data["tasks"].values()]}



class BdmvWorker:
    """每日扫描只发现新任务；一分钟核对已提交任务，不重复提交未知结果。"""

    def __init__(self, directory: Path, config: dict, stop: threading.Event,
                 module_factory: Callable = _qb_module, adapter_factory: Optional[Callable] = None,
                 clock: Callable = time.time) -> None:
        self.queue = BdmvQueue(directory)
        self.config = copy.deepcopy(config)
        self.stop = stop
        self.module_factory = module_factory
        self.adapter_factory = adapter_factory or (lambda plugin_id: _adapter(plugin_id, stop))
        self.clock = clock
        self._execution = threading.Lock()

    def close(self) -> None:
        """宿主先设置 stop；等待有界 RPC 完成，防止新旧实例重叠执行。"""
        with self._execution:
            pass

    def scan(self) -> None:
        """仅按 BDMV 标签下推拉取选定下载器，精确筛选未整理和全部文件完成。"""
        self._run(discover=True)

    def tick(self) -> None:
        """只核对持久化任务，不扫描所有种子。"""
        self._run(discover=False)

    def _run(self, discover: bool) -> None:
        if self.stop.is_set() or not self.config["enabled"] or not self._execution.acquire(blocking=False):
            return
        try:
            with self.queue.locked() as data:
                try:
                    active = any(task["state"] not in {"done", "blocked"} for task in data["tasks"].values())
                    if not discover and not active:
                        return
                    module = self.module_factory()
                    if discover:
                        self._discover(data, module)
                    if any(task["state"] not in {"done", "blocked"} for task in data["tasks"].values()) and not self.stop.is_set():
                        adapter = self.adapter_factory(self.config["cd2_plugin_id"])
                        tasks = adapter.tasks()
                        for task in data["tasks"].values():
                            if self.stop.is_set():
                                break
                            if task["state"] not in {"done", "blocked"}:
                                self._advance(data, task, module, adapter, tasks)
                    data["error"] = ""
                except BdmvCd2Error as error:
                    data["error"] = str(error)
                except Exception as error:
                    data["error"] = f"BDMV 处理暂不可用（{type(error).__name__}），任务已保留"
                self.queue.save(data)
        finally:
            self._execution.release()

    def _discover(self, data: dict, module: object) -> None:
        for downloader in self.config["downloaders"]:
            if self.stop.is_set():
                return
            client = module.get_instance(downloader)
            if client is None or client.qbc is None:
                raise ValueError("BDMV 下载器不可用")
            for row in client.qbc.torrents_info(tag="BDMV") or []:
                if self.stop.is_set():
                    return
                if not {"BDMV", "未整理"}.issubset(_tags(row)) or "已上传" in _tags(row):
                    continue
                try:
                    identity = torrent_identity(module, downloader, row, client.qbc.torrents_files(torrent_hash=row["hash"]))
                    source, target = mapped_paths(identity, self.config["mappings"])
                except (ValueError, TypeError, KeyError):
                    continue
                key = hashlib.sha256(json.dumps([downloader, identity["download_hash"], source, target]).encode()).hexdigest()
                if key not in data["tasks"]:
                    data["tasks"][key] = {**identity, "id": key, "downloader": downloader,
                                          "name": str(row.get("name", "")), "source": source, "target": target,
                                          "cd2_plugin_id": self.config["cd2_plugin_id"], "state": "waiting", "error": "",
                                          "created_at": self.clock(), "updated_at": self.clock()}
                    self.queue.save(data)

    def _current(self, task: dict, module: object) -> tuple[object, dict]:
        client = module.get_instance(task["downloader"])
        if client is None or client.qbc is None:
            raise RuntimeError("下载器暂不可用")
        rows = client.qbc.torrents_info(torrent_hashes=task["download_hash"])
        matches = [row for row in rows or [] if str(row.get("hash", "")).lower() == task["download_hash"]]
        if len(matches) != 1:
            raise ValueError("种子已删除或身份无法唯一确认")
        row = matches[0]
        identity = torrent_identity(module, task["downloader"], row, client.qbc.torrents_files(torrent_hash=task["download_hash"]))
        if identity["fingerprint"] != task["fingerprint"] or "BDMV" not in _tags(row):
            raise ValueError("种子文件清单、路径或标签发生变化，停止自动回写")
        if module.get_instance(task["downloader"]) is not client:
            raise RuntimeError("下载器实例已变化")
        return client.qbc, row

    def _advance(self, data: dict, task: dict, module: object, adapter: object, tasks: list) -> None:
        try:
            if task.get("cd2_plugin_id") != self.config["cd2_plugin_id"]:
                raise ValueError("CD2 配置实例已变化，保留原任务")
            qbc, row = self._current(task, module)
            if task["state"] == "tagging":
                self._tag(task, module, qbc, row)
            elif task["state"] == "waiting":
                active = sum(item.get("status") not in {3, 4} for item in tasks)
                uncertain = sum(item["state"] in {"submitting", "unknown"} for item in data["tasks"].values())
                if active + uncertain >= 2:
                    task["error"] = "等待 CD2 复制任务空位（最多 2 个）"
                    return
                if "未整理" not in _tags(row) or "已上传" in _tags(row):
                    raise ValueError("种子不再符合未整理条件")
                def before_submit() -> None:
                    if self.stop.is_set():
                        raise InterruptedError("插件已停止")
                    task.update(state="submitting", submitted_at=self.clock(), updated_at=self.clock(),
                                previous_starts=[item.get("start") for item in tasks
                                                 if item.get("source") == task["source"] and item.get("dest") in
                                                 {task["target"], str(PurePosixPath(task["target"]).parent)}])
                    self.queue.save(data)
                # 前置目录校验失败没有副作用；只有 CopyFile 前落盘意图后才进入未知结果。
                try:
                    adapter.submit(task["source"], str(PurePosixPath(task["target"]).parent),
                                   manifest=task["manifest"], before_submit=before_submit)
                finally:
                    if task["state"] == "submitting":
                        task.update(state="unknown", error="等待 CD2 复制任务确认")
                        self.queue.save(data)

            else:
                self._receipt(task, tasks)
        except (ValueError, BdmvCd2ConflictError) as error:
            task.update(state="blocked", error=str(error))
        except BdmvCd2Error as error:
            task["error"] = str(error)
        except Exception as error:
            task["error"] = f"BDMV 状态暂无法确认（{type(error).__name__}），稍后重试"
        task["updated_at"] = self.clock()
        self.queue.save(data)

    def _receipt(self, task: dict, tasks: list) -> None:
        from .bdmv_cd2 import is_completed
        candidates = [item for item in tasks if item.get("source") == task["source"] and item.get("dest") in {task["target"], str(PurePosixPath(task["target"]).parent)}]
        if task.get("copy_start"):
            candidates = [item for item in candidates if item.get("start") == task["copy_start"]]
        else:
            candidates = [item for item in candidates if item.get("start") not in task.get("previous_starts", [])
                          and float(item.get("start", 0)) >= task.get("submitted_at", 0) - 5]
        if len(candidates) != 1:
            task.update(state="unknown", error="CD2 任务缺失或存在多个匹配，禁止重新上传及回写标签")
            return
        receipt = candidates[0]
        task["copy_start"] = receipt["start"]
        task["progress"] = {key: receipt.get(key, 0) for key in ("total", "uploaded", "total_bytes", "uploaded_bytes")}
        if is_completed(receipt) and receipt["total"] == len(task["manifest"]):
            task.update(state="tagging", error="上传已完成，等待确认 qB 标签")
        elif receipt.get("status") in {3, 4} or any(receipt.get(key, 0) for key in ("failed", "failed_folders", "skipped", "cancelled")):
            task.update(state="blocked", error="CD2 复制存在失败、跳过或取消，保留未整理标签")
        else:
            task.update(state="copying", error="")

    def _tag(self, task: dict, module: object, qbc: object, row: dict) -> None:
        if self.stop.is_set():
            return
        if "已上传" not in _tags(row):
            qbc.torrents_add_tags(torrent_hashes=task["download_hash"], tags="已上传")
        qbc, row = self._current(task, module)
        if "已上传" not in _tags(row):
            raise RuntimeError("等待已上传标签确认")
        if "未整理" in _tags(row) and not self.stop.is_set():
            qbc.torrents_remove_tags(torrent_hashes=task["download_hash"], tags="未整理")
        _, row = self._current(task, module)
        if "未整理" in _tags(row) or "已上传" not in _tags(row):
            raise RuntimeError("等待未整理标签移除确认")
        task.update(state="done", error="")
