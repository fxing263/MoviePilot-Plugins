"""115 延迟暂存队列：持久化意图、硬链接及经明确确认后的清理。"""

import copy
import errno
import fcntl
import hashlib
import json
import math
import os
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

from app.sdk.logging import logger

GB = 1_000_000_000
DELETION_CONFIRM_SECONDS = 30
TERMINAL = {"done", "cancelled"}
DEFAULTS = {
    "enabled": False, "library_root": "", "staging_root": "",
    "rules": [], "cleanup_organized": True, "cleanup_empty_dirs": True,
    "confirmation_mode": "manual", "scan_once": False, "history_days": 7,
}


def _absolute(value: str) -> Path:
    path = Path(value)
    if not value or not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise ValueError("根目录必须是非 / 的绝对路径，且不能包含 ..")
    if path.resolve() != path:
        raise ValueError(f"路径不能经过符号链接：{path}")
    return path


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("大小和延迟必须是数字")
    try:
        numeric = float(value)
    except OverflowError as error:
        raise ValueError("大小或延迟超出可表示范围") from error
    if not math.isfinite(numeric) or numeric < 0 or not math.isfinite(numeric * 60):
        raise ValueError("大小和延迟必须为有限非负数，且分钟转换不能溢出")
    return numeric


def _validate_single_config(config: dict, allow_root_rule: bool = False) -> dict:
    result = copy.deepcopy(DEFAULTS)
    result.update(config)
    for key in ("enabled", "cleanup_organized", "cleanup_empty_dirs", "scan_once"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} 必须为布尔值")
    days = result["history_days"]
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        raise ValueError("任务保留天数必须为 1 到 3650 的整数")
    if result["confirmation_mode"] not in ("manual", "staging_deleted"):
        raise ValueError("上传确认方式必须为 manual 或 staging_deleted")
    if not result["enabled"] and not result["library_root"] and not result["staging_root"] and not result["rules"]:
        return result
    library = _absolute(result["library_root"])
    staging = _absolute(result["staging_root"])
    if library.is_relative_to(staging) or staging.is_relative_to(library):
        raise ValueError("媒体库根目录与暂存根目录不能相同或互相包含")
    if not isinstance(result["rules"], list):
        raise ValueError("规则必须是列表")
    directories = []
    for rule in result["rules"]:
        if not isinstance(rule, dict) or not isinstance(rule.get("directory"), str):
            raise ValueError("每条规则必须有目录")
        raw_directory = rule["directory"].strip()
        relative = Path(raw_directory.lstrip("/"))
        root_rule = allow_root_rule and raw_directory in {"/", "."}
        if (relative == Path(".") and not root_rule) or ".." in relative.parts:
            if allow_root_rule:
                raise ValueError("规则目录不能为空或包含 ..；整个整理根请填写 /")
            raise ValueError("规则目录不能为空、/ 或包含 ..")
        directory = library / relative
        _absolute(str(directory))
        if any(directory.is_relative_to(old) or old.is_relative_to(directory) for old in directories):
            raise ValueError(f"规则目录重复或存在父子冲突：{rule['directory']}")
        directories.append(directory)
        rule["directory"] = relative.as_posix()
        if "tiers" in rule:
            if "delay_minutes" in rule:
                raise ValueError("同一规则不能同时设置固定延迟和大小分档")
            tiers = rule["tiers"]
            if not isinstance(tiers, list) or not tiers:
                raise ValueError("大小规则至少需要一档，最后一档上限必须为空")
            previous = 0
            for index, tier in enumerate(tiers):
                if not isinstance(tier, dict):
                    raise ValueError("大小分档必须是对象")
                _number(tier.get("delay_minutes"))
                upper = tier.get("below_gb")
                tier["below_gb"] = upper
                if upper is None:
                    if index != len(tiers) - 1:
                        raise ValueError("无上限分档只能放在最后")
                else:
                    upper = _number(upper)
                    if upper <= previous or index == len(tiers) - 1:
                        raise ValueError("分档上限必须递增，最后一档上限必须为空")
                    previous = upper
        else:
            _number(rule.get("delay_minutes"))
    result["library_root"], result["staging_root"] = str(library), str(staging)
    return result


def validate_config(config: dict) -> dict:
    """校验多组独立根目录；旧单根配置仍可读取，新组内 / 规则覆盖整个整理根。

    整理根之间、暂存根之间及任意整理根与暂存根之间均不得重叠，避免重复接收、
    覆盖其他组暂存文件或清理另一个组的根目录。规则冲突按组内实际目录判断。
    """
    if "mappings" not in config:
        return _validate_single_config(config)
    mappings = config["mappings"]
    if not isinstance(mappings, list):
        raise ValueError("目录映射必须是列表")
    result = _validate_single_config({key: config.get(key, DEFAULTS[key]) for key in
                                      ("cleanup_organized", "cleanup_empty_dirs", "confirmation_mode", "scan_once", "history_days")})
    enabled = config.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须为布尔值")
    if enabled and not mappings:
        raise ValueError("启用前至少需要一组整理目录与暂存目录映射")
    result = {key: value for key, value in result.items() if key not in {"library_root", "staging_root", "rules"}}
    result.update(enabled=enabled, mappings=[])
    libraries, stagings = [], []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("每组目录映射必须是对象")
        group = _validate_single_config({"enabled": True,
                                        "library_root": mapping.get("library_root", ""),
                                        "staging_root": mapping.get("staging_root", ""),
                                        "rules": mapping.get("rules", [])}, allow_root_rule=True)
        library, staging = Path(group["library_root"]), Path(group["staging_root"])
        if any(library.is_relative_to(old) or old.is_relative_to(library) for old in libraries):
            raise ValueError(f"整理根目录重复或存在父子冲突：{library}")
        if any(staging.is_relative_to(old) or old.is_relative_to(staging) for old in stagings):
            raise ValueError(f"暂存根目录重复或存在父子冲突：{staging}")
        if (any(library.is_relative_to(old) or old.is_relative_to(library) for old in stagings)
                or any(staging.is_relative_to(old) or old.is_relative_to(staging) for old in libraries)):
            raise ValueError("不同组的整理根目录与暂存根目录不能相同或互相包含")
        libraries.append(library)
        stagings.append(staging)
        result["mappings"].append({key: group[key] for key in ("library_root", "staging_root", "rules")})
    return result


def select_mapping(config: dict, source: Path) -> Optional[dict]:
    """用已校验的源根目录选择唯一映射，并继承全局清理选项；兼容旧单根配置。"""
    if not source.is_absolute() or ".." in source.parts:
        return None
    for mapping in config.get("mappings", [config]):
        if source.is_relative_to(Path(mapping["library_root"])):
            return {**config, **mapping}
    return None


def match_rule(config: dict, relative: Path, size: int) -> Optional[tuple[dict, float]]:
    """按路径组件唯一匹配规则；大小档为左闭右开，GB 使用十进制字节。"""
    for rule in config["rules"]:
        if relative.is_relative_to(Path(rule["directory"])):
            if "tiers" not in rule:
                return rule, float(rule["delay_minutes"])
            for tier in rule["tiers"]:
                if tier["below_gb"] is None or size < tier["below_gb"] * GB:
                    return rule, float(tier["delay_minutes"])
    return None


@contextmanager
def _directory(path: Path, create: bool = False) -> Iterator[int]:
    """逐段打开目录并拒绝符号链接；文件操作始终相对于已打开的父目录。"""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("文件路径必须为绝对路径且不含 ..")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(info: os.stat_result) -> list[int]:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("仅处理普通文件，拒绝目录及符号链接")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _file_identity(path: Path) -> list[int]:
    with _directory(path.parent) as parent:
        return _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))


def _directory_identity(descriptor: int) -> list[int]:
    info = os.fstat(descriptor)
    return [info.st_dev, info.st_ino]


def _valid_staging_evidence(evidence: object) -> bool:
    if not isinstance(evidence, dict):
        return False
    for key in ("root_identity", "parent_identity"):
        identity = evidence.get(key)
        if not isinstance(identity, list) or len(identity) != 2 or any(type(value) is not int for value in identity):
            return False
    linked_at = evidence.get("linked_at")
    return isinstance(linked_at, (int, float)) and math.isfinite(linked_at)


def _has_confirmation(task: dict) -> bool:
    receipt = task.get("upload_result")
    if not isinstance(receipt, dict):
        return False
    if receipt.get("method") == "staging_deleted":
        evidence = task.get("staging_evidence")
        return (receipt.get("confirmed") is True and receipt.get("remote_verified") is False
                and receipt.get("staging_path") == task["staging_path"]
                and task.get("confirmation_mode") == "staging_deleted"
                and _valid_staging_evidence(evidence)
                and isinstance(receipt.get("first_seen_deleted_at"), (int, float))
                and isinstance(receipt.get("confirmed_at"), (int, float))
                and receipt["confirmed_at"] - receipt["first_seen_deleted_at"] >= DELETION_CONFIRM_SECONDS)
    return receipt.get("verified") is True and bool(receipt.get("remote_reference"))


class StagingQueue:
    """单实例队列；文件锁串行化进程间操作，原子日志先于外部文件副作用落盘。"""

    def __init__(self, directory: Path, clock: Callable[[], float] = time.time) -> None:
        self.directory = directory
        self.clock = clock
        self._lock = threading.RLock()

    @contextmanager
    def _locked(self) -> Iterator[dict]:
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "queue.lock").open("a+b") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    path = self.directory / "queue.json"
                    data = json.loads(path.read_text("utf-8")) if path.exists() else {"version": 1, "tasks": {}}
                    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("tasks"), dict):
                        raise ValueError("队列格式不兼容；请保留日志并人工检查")
                    for task in data["tasks"].values():
                        self._validate_task(task)
                    yield data
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _validate_task(task: dict) -> None:
        required = {"id", "source_path", "relative_path", "staging_path", "library_root", "staging_root",
                    "rule", "delay_minutes", "created_at", "ready_at", "identity", "state", "error",
                    "attempts", "cleanup_organized", "cleanup_empty_dirs",
                    "upload_result", "cleanup_result"}
        if not isinstance(task, dict) or not required.issubset(task):
            raise ValueError("任务记录不完整；请保留日志并人工检查")
        if task["state"] not in {"waiting", "linking", "staged", "failed", "confirmed", "cleanup_failed", *TERMINAL}:
            raise ValueError("任务状态不兼容；请保留日志并人工检查")
        relative = Path(task["relative_path"])
        if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
            raise ValueError("任务相对路径无效")
        if (Path(task["library_root"]) / relative != Path(task["source_path"])
                or Path(task["staging_root"]) / relative != Path(task["staging_path"])):
            raise ValueError("任务路径与记录的根目录不一致")
        if not isinstance(task["cleanup_result"], dict):
            raise ValueError("任务清理结果格式错误")
        if task["state"] in {"confirmed", "cleanup_failed", "done"}:
            if not _has_confirmation(task):
                raise ValueError("任务缺少可靠上传确认，停止队列")

    def _save(self, data: dict) -> None:
        temporary = self.directory / "queue.json.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.directory / "queue.json")
        with _directory(self.directory) as descriptor:
            os.fsync(descriptor)

    def tasks(self) -> list[dict]:
        """读取持久化任务快照；损坏日志不会被空队列覆盖。"""
        with self._locked() as data:
            return sorted(data["tasks"].values(), key=lambda task: task["created_at"], reverse=True)

    def enqueue(self, config: dict, source: str, *, immediate: bool = False) -> Optional[str]:
        """记录整理后的本地文件；重复事件不延长等待，同路径新版本采用独立身份。"""
        path = Path(source)
        config = select_mapping(config, path)
        if config is None:
            return None
        library = Path(config["library_root"])
        identity = _file_identity(path)
        relative = path.relative_to(library)
        matched = match_rule(config, relative, identity[2])
        if matched is None:
            return None
        rule, delay = matched
        if immediate:
            delay = 0
        task_id = hashlib.sha256(json.dumps([str(path), identity]).encode()).hexdigest()[:24]
        with self._locked() as data:
            if task_id in data["tasks"]:
                return task_id
            destination = Path(config["staging_root"]) / relative
            if any(task["staging_path"] == str(destination) and task["state"] not in TERMINAL
                   for task in data["tasks"].values()):
                raise ValueError(f"同一暂存路径仍有未结束任务：{destination}")
            data["tasks"][task_id] = {
                "id": task_id, "source_path": str(path), "relative_path": str(relative),
                "staging_path": str(destination), "library_root": str(library),
                "staging_root": config["staging_root"], "rule": copy.deepcopy(rule),
                "delay_minutes": delay, "created_at": self.clock(), "ready_at": self.clock() + delay * 60,
                "identity": identity, "state": "waiting", "error": "", "attempts": 0,
                "cleanup_organized": config["cleanup_organized"],
                "cleanup_empty_dirs": config["cleanup_empty_dirs"],
                "confirmation_mode": config.get("confirmation_mode", "manual"),
                "upload_result": None, "cleanup_result": {},
            }
            self._save(data)
        return task_id

    def scan_once(self, config: dict) -> int:
        """手动补扫匹配规则的普通文件，新任务立即到期；重扫复用持久化任务避免重复投递。"""
        count = 0
        mappings = config.get("mappings", [config])
        def walk_error(error):
            raise error
        for mapping in mappings:
            root = _absolute(mapping["library_root"])
            if not root.is_dir():
                raise ValueError(f"整理目录不可访问：{root}")
            for directory, directories, files in os.walk(root, onerror=walk_error, followlinks=False):
                directories[:] = [name for name in directories
                                  if not (Path(directory) / name).is_symlink()
                                  and not name.startswith(".delayed115-cleanup-")]
                for name in files:
                    path = Path(directory) / name
                    if not stat.S_ISREG(path.lstat().st_mode):
                        continue
                    if self.enqueue(config, str(path), immediate=True) is not None:
                        count += 1
        return count

    def purge_history(self, days: int) -> None:
        """每天删除超过保留期的已完成记录；旧记录从首次维护起计时，不删除任何文件。"""
        with self._locked() as data:
            now = self.clock()
            if now - data.get("history_checked_at", -86400) < 86400:
                return
            for task_id, task in list(data["tasks"].items()):
                if task["state"] != "done":
                    continue
                completed = task.setdefault("completed_at", now)
                if now - completed >= days * 86400:
                    del data["tasks"][task_id]
            data["history_checked_at"] = now
            self._save(data)

    def tick(self, cleanup_organized: bool = False, confirmation_mode: str = "manual") -> None:
        """处理到期任务和已确认任务；崩溃遗留的链接意图仅核对，不盲目重复投递。"""
        with self._locked() as data:
            for task in data["tasks"].values():
                if task["state"] == "linking":
                    self._recover(task)
                    self._save(data)
                if task["state"] == "waiting" and task["ready_at"] <= self.clock():
                    self._stage(data, task)
                if task["state"] == "staged":
                    previous = copy.deepcopy(task)
                    if confirmation_mode == "staging_deleted" and task.get("confirmation_mode") == "staging_deleted":
                        self._observe_staging_deletion(task)
                    else:
                        task.pop("deletion_seen_at", None)
                    if task.get("error") and task.get("error") != previous.get("error"):
                        logger.warning(f"自动确认暂停：{task['staging_path']}；{task['error']}")
                    if task != previous:
                        # 确认依据必须先落盘，再进入下面的清理步骤。
                        self._save(data)
                        if task["state"] == "confirmed":
                            logger.info(f"暂存文件删除已确认（按上传器约定）：{task['staging_path']}")
                if task["state"] == "confirmed":
                    self._cleanup(data, task, cleanup_organized)

    def _observe_staging_deletion(self, task: dict) -> None:
        """按用户声明的上传器成功删除约定确认；目录异常和文件替换不构成成功。

        只接受本插件已持久化链接成功证据的新任务。相隔至少 30 秒的两次检查中，
        暂存根目录身份保持一致，且暂存文件或下级目录不存在，才记录推定确认。
        整理文件按映射路径清理，确认阶段不读取其文件身份。
        此结果不冒充对 115 的远端查询；人为删除在该模式下同样会被视为成功。
        """
        evidence = task.get("staging_evidence")
        if not _valid_staging_evidence(evidence):
            task["error"] = "缺少链接成功时的目录证据，请人工核验上传结果"
            return
        if task.get("deletion_confirmation_blocked"):
            return
        path = Path(task["staging_path"])
        try:
            with _directory(Path(task["staging_root"])) as root:
                if _directory_identity(root) != evidence["root_identity"]:
                    raise ValueError("暂存根目录身份变化")
                try:
                    with _directory(path.parent) as parent:
                        if _directory_identity(parent) != evidence["parent_identity"]:
                            raise ValueError("暂存父目录身份变化")
                        current_stat = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    # 根目录已单独核验；其下级目录被删除与文件被删除采用同一确认约定。
                    current = None
                else:
                    try:
                        current = _identity(current_stat)
                    except ValueError:
                        task["deletion_confirmation_blocked"] = True
                        raise
                if current is not None:
                    task.pop("deletion_seen_at", None)
                    if current != task["identity"]:
                        task["deletion_confirmation_blocked"] = True
                        raise ValueError("暂存文件已替换，请人工核验")
                    task["error"] = ""
                    return
                # 打开的目录句柄可能仍指向刚被移走的目录，缺失观测后重新核对路径绑定。
                with _directory(Path(task["staging_root"])) as current_root:
                    if _directory_identity(current_root) != evidence["root_identity"]:
                        raise ValueError("缺失检查期间暂存根目录发生变化")
                try:
                    with _directory(path.parent) as current_parent:
                        if _directory_identity(current_parent) != evidence["parent_identity"]:
                            raise ValueError("缺失检查期间暂存父目录发生变化")
                except FileNotFoundError:
                    pass
        except (OSError, ValueError) as error:
            task.pop("deletion_seen_at", None)
            task["error"] = f"自动确认暂停：{error}"
            return
        task["error"] = ""
        now = self.clock()
        if "deletion_seen_at" not in task:
            task["deletion_seen_at"] = now
            return
        if now - task["deletion_seen_at"] < DELETION_CONFIRM_SECONDS:
            return
        task["upload_result"] = {
            "method": "staging_deleted", "confirmed": True, "remote_verified": False,
            "staging_path": task["staging_path"], "first_seen_deleted_at": task["deletion_seen_at"],
            "confirmed_at": now,
        }
        task["state"] = "confirmed"

    @staticmethod
    def _recover(task: dict) -> None:
        try:
            if _file_identity(Path(task["staging_path"])) != task["identity"]:
                raise ValueError("暂存文件身份已改变")
            task["state"] = "staged"
        except (OSError, ValueError) as error:
            task["state"] = "failed"
            task["error"] = f"暂存中断，无法确定是否已投递；核对上传器后重试：{error}"

    def _stage(self, data: dict, task: dict) -> None:
        source, destination = Path(task["source_path"]), Path(task["staging_path"])
        task["state"] = "linking"
        task["attempts"] += 1
        self._save(data)
        try:
            with _directory(source.parent) as source_parent, _directory(destination.parent, create=True) as target_parent:
                identity = _identity(os.stat(source.name, dir_fd=source_parent, follow_symlinks=False))
                if identity != task["identity"]:
                    raise ValueError("源文件在等待期间已改变，拒绝投递")
                with _directory(Path(task["staging_root"])) as root:
                    evidence = {"root_identity": _directory_identity(root),
                                "parent_identity": _directory_identity(target_parent)}
                # os.link 不覆盖目标，也不回退复制；上传器可以在返回后立即取走暂存文件。
                os.link(source.name, destination.name, src_dir_fd=source_parent,
                        dst_dir_fd=target_parent, follow_symlinks=False)
                logger.info(f"硬链接创建成功：{source} → {destination}")
                os.fsync(target_parent)
                try:
                    linked = _identity(os.stat(destination.name, dir_fd=target_parent, follow_symlinks=False))
                except FileNotFoundError:
                    linked = identity
                if linked != identity:
                    raise ValueError("链接期间文件发生变化，须人工核对暂存文件")
                task["staging_evidence"] = {**evidence, "linked_at": self.clock()}
            task["state"], task["error"] = "staged", ""
        except (OSError, ValueError) as error:
            task["state"], task["error"] = "failed", str(error)
            logger.error(f"硬链接暂存失败：{source} → {destination}；{error}")
        self._save(data)

    def action(self, task_id: str, action: str, remote_reference: str = "", verified: bool = False) -> None:
        """重试不跳过原到期时间；取消不删文件；确认需调用方已核验该任务的远端结果。"""
        with self._locked() as data:
            task = data["tasks"].get(task_id)
            if task is None:
                raise ValueError("任务不存在")
            if action == "confirm":
                if not verified or not remote_reference.strip():
                    raise ValueError("必须先核验远端上传成功，并填写远端文件 ID 或路径")
                if task["state"] in {"confirmed", "done", "cleanup_failed"}:
                    return
                if task["state"] != "staged":
                    raise ValueError("只有已暂存任务可以确认上传成功")
                task["upload_result"] = {"verified": True, "remote_reference": remote_reference.strip(),
                                         "confirmed_at": self.clock()}
                task["state"] = "confirmed"
            elif action == "retry":
                if task["state"] == "cleanup_failed":
                    task["state"] = "confirmed"
                elif task["state"] == "failed":
                    task["state"] = "waiting"
                else:
                    raise ValueError("只有失败任务可以重试")
                task["error"] = ""
            elif action == "cancel":
                if task["state"] in {"confirmed", "done", "cleanup_failed"}:
                    raise ValueError("已确认上传的任务不能取消，请检查清理结果")
                task["state"] = "cancelled"
            else:
                raise ValueError("未知操作")
            self._save(data)

    @staticmethod
    def _remove(path: Path, identity: list[int], token: str) -> str:
        # 原子隔离后再复核，避免 stat 与 unlink 之间同名文件被替换而误删。
        hold_name = f".delayed115-cleanup-{token}"
        try:
            with _directory(path.parent) as parent:
                try:
                    os.mkdir(hold_name, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                hold = os.open(hold_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    try:
                        os.stat("payload", dir_fd=hold, follow_symlinks=False)
                    except FileNotFoundError:
                        try:
                            actual = _identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
                        except FileNotFoundError:
                            return "already_absent"
                        if actual != identity:
                            raise ValueError(f"文件身份已变化，保留文件：{path}")
                        os.rename(path.name, "payload", src_dir_fd=parent, dst_dir_fd=hold)
                        os.fsync(hold)
                        os.fsync(parent)
                    try:
                        actual = _identity(os.stat("payload", dir_fd=hold, follow_symlinks=False))
                        if actual != identity:
                            raise ValueError("身份不匹配")
                    except ValueError as error:
                        # 恢复时使用不覆盖的硬链接，若原位置已出现新文件则保留隔离物供人工处理。
                        try:
                            os.link("payload", path.name, src_dir_fd=hold,
                                    dst_dir_fd=parent, follow_symlinks=False)
                        except OSError as restore_error:
                            raise ValueError(f"并发替换文件已保留在 {path.parent / hold_name / 'payload'}："
                                             f"{restore_error}") from error
                        os.unlink("payload", dir_fd=hold)
                        os.fsync(parent)
                        raise ValueError(f"检测到并发替换，文件已恢复并保留：{path}") from error
                    os.unlink("payload", dir_fd=hold)
                    os.fsync(hold)
                    return "removed"
                finally:
                    os.close(hold)
                    try:
                        os.rmdir(hold_name, dir_fd=parent)
                        os.fsync(parent)
                    except OSError as error:
                        if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                            raise
        except FileNotFoundError:
            return "already_absent"

    @staticmethod
    def _remove_organized(path: Path) -> str:
        """按目录映射直接删除整理路径；不比较文件身份、不隔离、不追踪其他硬链接。"""
        try:
            with _directory(path.parent) as parent:
                os.unlink(path.name, dir_fd=parent)
                logger.info(f"整理文件删除成功：{path}")
                os.fsync(parent)
            return "removed"
        except FileNotFoundError:
            return "already_absent"

    @staticmethod
    def _prune(path: Path, root: Path, protected: tuple[Path, ...] = ()) -> None:
        current = path.parent
        while current != root and current.is_relative_to(root):
            if current in protected:
                return
            try:
                with _directory(current.parent) as parent:
                    os.rmdir(current.name, dir_fd=parent)
                    logger.info(f"空目录删除成功：{current}")
            except FileNotFoundError:
                pass
            except OSError as error:
                if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                    return
                raise
            current = current.parent

    def _cleanup(self, data: dict, task: dict, cleanup_organized: bool) -> None:
        if not _has_confirmation(task):
            raise ValueError("缺少已持久化的上传成功确认，拒绝清理")
        try:
            paths = [("staging", Path(task["staging_path"]), Path(task["staging_root"]))]
            if task["cleanup_organized"] and cleanup_organized:
                source = Path(task["library_root"]) / task["relative_path"]
                if task["cleanup_result"].get("organized") == "retained":
                    task["cleanup_result"].pop("organized")
                paths.append(("organized", source, Path(task["library_root"])))
            else:
                task["cleanup_result"]["organized"] = "retained"
            for key, path, root in paths:
                if not path.is_relative_to(root) or path == root:
                    raise ValueError("清理路径超出任务记录的根目录")
                if key not in task["cleanup_result"]:
                    if key == "organized":
                        task["cleanup_result"][key] = self._remove_organized(path)
                    else:
                        task["cleanup_result"][key] = self._remove(path, task["identity"], f"{task['id']}-{key}")
                    self._save(data)
                    result = task["cleanup_result"][key]
                    if key == "staging" and result == "removed":
                        logger.info(f"暂存硬链接删除成功：{path}")
                    elif result == "already_absent":
                        logger.info(f"清理目标已不存在：{path}")
                if task["cleanup_empty_dirs"]:
                    # 同目录还有待自动确认的任务时，保留其目录身份作为观测证据。
                    protected = tuple(Path(other["staging_path"]).parent for other in data["tasks"].values()
                                      if other["id"] != task["id"] and other["state"] == "staged"
                                      and other.get("confirmation_mode") == "staging_deleted")
                    self._prune(path, root, protected)
            task["state"], task["error"] = "done", ""
            task["completed_at"] = self.clock()
            logger.info(f"暂存任务完成：{task['relative_path']}；整理文件{'保留' if task['cleanup_result'].get('organized') == 'retained' else '已清理'}")
        except (OSError, ValueError) as error:
            task["state"], task["error"] = "cleanup_failed", str(error)
            logger.error(f"文件清理失败：{task['source_path']}；{error}")
        self._save(data)
