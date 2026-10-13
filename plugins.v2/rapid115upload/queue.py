"""复用延迟暂存的持久化意图模式，仅保存秒传状态，不操作媒体文件。"""

import copy
import fcntl
import hashlib
import json
import os
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Optional


class FileChangedError(ValueError):
    """本地整理文件的身份变化，需人工检查后重新登记。"""


def file_identity(path: Path) -> list[int]:
    """拒绝目录和符号链接；身份包含 inode、大小和纳秒修改时间。"""
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise FileChangedError("整理文件不能经过符号链接或越界路径")
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise FileChangedError("只支持普通整理文件")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


class UploadQueue:
    """原子 JSON 快照与文件锁；远端调用前落盘意图，重启后先核对远端。"""

    def __init__(self, directory: Path, clock: Callable[[], float] = time.time) -> None:
        self.directory = directory
        self.path = directory / "queue.json"
        self.clock = clock
        self._guard = threading.RLock()

    @contextmanager
    def _locked(self) -> Iterator[dict]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._guard, (self.directory / "queue.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            snapshot = {"version": 1, "tasks": {}}
            if self.path.exists():
                snapshot = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(snapshot, dict) or snapshot.get("version") != 1
                        or not isinstance(snapshot.get("tasks"), dict)):
                    raise ValueError("秒传队列损坏或版本不兼容，保留原文件")
                for key, task in snapshot["tasks"].items():
                    if (not isinstance(task, dict) or task.get("id") != key
                            or task.get("state") not in {"waiting", "running", "uploaded", "blocked", "cancelled"}
                            or not all(field in task for field in (
                                "organized_path", "remote_path", "identity", "attempts", "ready_at", "retry_minutes"))):
                        raise ValueError("秒传队列记录不完整，保留原文件")
            yield snapshot

    def _save(self, snapshot: dict) -> None:
        temporary = self.directory / "queue.json.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def tasks(self) -> list[dict]:
        """返回独立快照，页面读取不会推进上传。"""
        with self._locked() as snapshot:
            return sorted(copy.deepcopy(list(snapshot["tasks"].values())),
                          key=lambda item: item["created_at"], reverse=True)

    def source_context(self, source: str, downloader: str = "", download_hash: str = "",
                       remember: bool = False) -> tuple[str, str]:
        """仅失败事件请求保存来源；成功事件只恢复同路径同身份的唯一种子。"""
        if not source:
            return downloader, download_hash
        try:
            identity = file_identity(Path(source))
        except (OSError, ValueError):
            return downloader, download_hash
        with self._locked() as snapshot:
            records = snapshot.setdefault("source_contexts", {})
            record = records.get(source, {})
            pairs = record.get("pairs", []) if record.get("identity") == identity else []
            if downloader and download_hash:
                pair = [downloader, download_hash.lower()]
                if remember and pair not in pairs:
                    records[source] = {"identity": identity, "pairs": pairs + [pair]}
                    self._save(snapshot)
                return downloader, download_hash.lower()
            if len(pairs) == 1:
                name, torrent_hash = pairs[0]
                if (not downloader or downloader == name) and (
                        not download_hash or download_hash.lower() == torrent_hash):
                    return name, torrent_hash
        return downloader, download_hash

    def enqueue(self, config: dict, organized: str, source: str = "",
                history_id: Optional[int] = None, origin: str = "transfer",
                downloader: str = "", download_hash: str = "") -> Optional[str]:
        """成功整理事件按根目录映射入队；重复事件不重置重试或完成状态。"""
        path = Path(organized)
        mapping = next((item for item in config["mappings"]
                        if path.is_relative_to(Path(item["library_root"]))), None)
        if mapping is None:
            return None
        identity = file_identity(path)
        relative = path.relative_to(mapping["library_root"])
        remote = str(PurePosixPath(mapping["remote_root"]) / relative.as_posix())
        key = hashlib.sha256(json.dumps([str(path), remote, identity]).encode()).hexdigest()
        with self._locked() as snapshot:
            changed = key not in snapshot["tasks"]
            if changed:
                snapshot["tasks"][key] = {
                    "id": key, "source_path": source, "organized_path": str(path), "origin": origin,
                    "relative_path": relative.as_posix(), "remote_path": remote,
                    "history_id": history_id, "identity": identity,
                    "retry_minutes": list(mapping["retry_minutes"]),
                    "created_at": self.clock(),
                    "ready_at": self.clock() + mapping.get("initial_delay_minutes", 0) * 60,
                    "state": "waiting", "attempts": 0, "error": "", "hashes": {},
                    "max_attempts": mapping.get("max_attempts", config.get("max_attempts", 3)), "instant_misses": 0,
                    "upload_mode": "instant", "links": [],
                }
            task = snapshot["tasks"][key]
            link = {"downloader": downloader, "download_hash": download_hash.lower(),
                    "source_path": source, "history_id": history_id}
            if link not in task.setdefault("links", []):
                task["links"].append(link)
                changed = True
            if changed:
                self._save(snapshot)
        return key

    def update(self, task_id: str, **changes: object) -> dict:
        """锁内合并单条记录，网络执行期间的新整理事件不会丢失。"""
        with self._locked() as snapshot:
            task = snapshot["tasks"][task_id]
            task.update(changes)
            self._save(snapshot)
            return copy.deepcopy(task)

    def action(self, task_id: str, action: str, options: Optional[dict] = None) -> None:
        """冲突操作锁内落盘；覆盖仅授权当前已确认的文件，运行中及成功任务不可修改。"""
        options = options or {}
        with self._locked() as snapshot:
            task = snapshot["tasks"].get(task_id)
            if not task or action not in {"retry", "cancel", "rename", "overwrite"}:
                raise ValueError("任务不存在或操作不支持")
            if task["state"] in {"running", "uploaded"}:
                raise ValueError("正在执行或已经上传的任务不能操作")
            intent = {}
            if action in {"rename", "overwrite"}:
                diagnostic = task.get("verification", {})
                if task["state"] != "blocked" or diagnostic.get("reason") not in {"size_mismatch", "directory"}:
                    raise ValueError("请先重新校验，确认同名冲突后再处理")
                if options.get("verification") != diagnostic:
                    raise ValueError("冲突信息已变化，请刷新任务详情")
                remote = PurePosixPath(task["remote_path"])
                if action == "rename":
                    name = options.get("filename")
                    if (not isinstance(name, str) or not name.strip() or name in {".", "..", remote.name}
                            or any(char in name for char in '/\\') or any(ord(char) < 32 for char in name)):
                        raise ValueError("请输入不同的文件名，不能包含目录或控制字符")
                    target = str(remote.with_name(name))
                else:
                    if (options.get("confirmed") is not True or diagnostic.get("reason") != "size_mismatch"
                            or not str(diagnostic.get("file_id", "")).isascii()
                            or not str(diagnostic.get("file_id", "")).isdigit()):
                        raise ValueError("覆盖必须确认具体的同名文件，不支持删除目录")
                    target = str(remote)
                    intent = {"state": "authorized", "remote_path": target, **diagnostic}
                if any(other["id"] != task_id and other["remote_path"] == target
                       and other["state"] != "cancelled" for other in snapshot["tasks"].values()):
                    raise ValueError("目标路径已被其他上传任务使用")
                task["remote_path"] = target
            # 普通重试不继承旧的删除授权；超时结果需重新校验后由用户重新确认。
            task.update(state="cancelled" if action == "cancel" else "waiting", overwrite=intent,
                        ready_at=self.clock(), error="", metadata_failures=0, verification={})
            self._save(snapshot)

    @contextmanager
    def worker(self) -> Iterator[bool]:
        """同一实例数据目录最多一个消费者；进程退出自动释放执行锁。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "worker.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            # 只有拿到进程级消费者锁，才能恢复上次进程中断的任务。
            with self._locked() as snapshot:
                interrupted = [task for task in snapshot["tasks"].values() if task["state"] == "running"]
                for task in interrupted:
                    task.update(state="waiting", ready_at=self.clock())
                if interrupted:
                    self._save(snapshot)
            yield True

    def claim(self) -> Optional[dict]:
        """持有 worker 锁后调用；只领取到期等待任务，在途任务由其他线程拥有。"""
        with self._locked() as snapshot:
            if snapshot.get("cooldown_until", 0) > self.clock():
                return None
            running_paths = {task["remote_path"] for task in snapshot["tasks"].values()
                             if task["state"] == "running"}
            due = [task for task in snapshot["tasks"].values()
                   if task["state"] == "waiting" and task["ready_at"] <= self.clock()
                   and task["remote_path"] not in running_paths]
            if not due:
                return None
            task = min(due, key=lambda item: item["ready_at"])
            task.update(state="running", attempts=task["attempts"] + 1, error="")
            self._save(snapshot)
            return copy.deepcopy(task)

    def defer(self, task: dict, message: str, minimum_seconds: float = 0) -> None:
        """失败按任务登记时的规则等待，末档无限重复，不使用睡眠线程。"""
        intervals = task["retry_minutes"]
        minutes = intervals[min(task["attempts"] - 1, len(intervals) - 1)]
        with self._locked() as snapshot:
            snapshot["tasks"][task["id"]].update(
                state="waiting", error=message,
                ready_at=self.clock() + max(minutes * 60, minimum_seconds),
            )
            if minimum_seconds:
                snapshot["cooldown_until"] = max(snapshot.get("cooldown_until", 0),
                                                  self.clock() + minimum_seconds)
            self._save(snapshot)

    def torrent_status(self, key: str) -> dict:
        """标签回写独立于文件上传重试，进程重启后继续核对。"""
        with self._locked() as snapshot:
            return copy.deepcopy(snapshot.get("torrents", {}).get(key, {}))

    def update_torrent(self, key: str, **changes: object) -> None:
        """标签确认成功与唯一失败关联清理原子落盘；回写失败时保留关联。"""
        with self._locked() as snapshot:
            snapshot.setdefault("torrents", {}).setdefault(key, {}).update(changes)
            if changes.get("tagged") is True:
                pair = json.loads(key)
                records = snapshot.get("source_contexts", {})
                for source in list(records):
                    if records[source].get("pairs") == [pair]:
                        del records[source]
            self._save(snapshot)

    def torrent_states(self) -> dict:
        """返回标签回写诊断快照，界面查询不连接下载器。"""
        with self._locked() as snapshot:
            return copy.deepcopy(snapshot.get("torrents", {}))
