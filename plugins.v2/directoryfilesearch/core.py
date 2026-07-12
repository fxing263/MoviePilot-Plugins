"""目录文件搜索删除插件的纯文件系统引擎。"""

import hashlib
import stat
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from threading import Event
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_MAX_RESULTS = 1000
MAX_QUERY_LENGTH = 256
DELETE_VERIFY_DELAYS = (0.0, 0.2, 0.6)


@dataclass(frozen=True)
class DirectorySearchConfig:
    """目录文件搜索配置。"""

    enabled: bool = False
    root_dir: Optional[Path] = None
    max_results: int = DEFAULT_MAX_RESULTS


@dataclass(frozen=True)
class FileSearchItem:
    """一次搜索命中的普通文件快照。"""

    item_id: str
    relative_path: str
    absolute_path: str
    name: str
    parent: str
    suffix: str
    size: int
    mtime_ns: int
    modified_at: str
    device: int
    inode: int


@dataclass
class FileSearchReport:
    """目录文件搜索报告。"""

    query: str
    items: List[FileSearchItem] = field(default_factory=list)
    scanned_files: int = 0
    matched_files: int = 0
    failed_entries: int = 0
    truncated: bool = False
    cancelled: bool = False
    generated_at: str = ""
    message: str = ""


@dataclass(frozen=True)
class FileDeletePlan:
    """单个普通文件的删除预览。"""

    item_id: str
    relative_path: str
    absolute_path: str
    size: int
    modified_at: str
    confirm_token: str
    blocked_reasons: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FileDeleteResult:
    """单个普通文件的删除及复核结果。"""

    item_id: str
    relative_path: str
    absolute_path: str
    deleted: bool
    verified: bool
    message: str


class DirectoryFileEngine:
    """在受控根目录内搜索和删除普通文件。"""

    def __init__(self, config: DirectorySearchConfig) -> None:
        """保存目录搜索配置。"""
        self.config = config

    def validate_root(self) -> Path:
        """校验并返回解析后的搜索根目录。"""
        root_dir = self.config.root_dir
        if root_dir is None:
            raise ValueError("请先配置搜索目录")
        if not root_dir.is_absolute():
            raise ValueError("搜索目录必须是绝对路径")
        if root_dir.is_symlink():
            raise ValueError("搜索目录不能是符号链接")
        try:
            resolved_root = root_dir.resolve(strict=True)
        except OSError as err:
            raise ValueError(f"搜索目录不存在或不可访问：{root_dir}") from err
        if not resolved_root.is_dir():
            raise ValueError(f"搜索目录不是文件夹：{resolved_root}")
        if resolved_root.parent == resolved_root:
            raise ValueError("不允许将文件系统根目录作为搜索目录")
        return resolved_root

    def search_files(
        self,
        query: str,
        stop_event: Optional[Event] = None,
    ) -> FileSearchReport:
        """递归搜索文件名或相对路径包含关键词的普通文件。"""
        normalized_query = normalize_query(query)
        root_dir = self.validate_root()
        query_key = normalized_query.casefold()
        report = FileSearchReport(query=normalized_query)
        directories = [root_dir]

        while directories:
            if stop_event and stop_event.is_set():
                report.cancelled = True
                break
            current_dir = directories.pop()
            try:
                entries = sorted(
                    current_dir.iterdir(),
                    key=lambda path: path.name.casefold(),
                    reverse=True,
                )
            except OSError:
                report.failed_entries += 1
                continue

            for entry in entries:
                if stop_event and stop_event.is_set():
                    report.cancelled = True
                    break
                try:
                    entry_stat = entry.lstat()
                except OSError:
                    report.failed_entries += 1
                    continue
                if stat.S_ISLNK(entry_stat.st_mode):
                    continue
                if stat.S_ISDIR(entry_stat.st_mode):
                    directories.append(entry)
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    continue

                report.scanned_files += 1
                relative_path = entry.relative_to(root_dir).as_posix()
                if query_key not in relative_path.casefold():
                    continue
                report.matched_files += 1
                if len(report.items) < self.config.max_results:
                    report.items.append(
                        self._build_item(entry, relative_path, entry_stat)
                    )
            if report.cancelled:
                break

        report.items.sort(key=lambda item: item.relative_path.casefold())
        report.truncated = report.matched_files > len(report.items)
        report.generated_at = _now()
        if report.cancelled:
            report.message = "搜索任务已停止"
        elif report.truncated:
            report.message = (
                f"搜索完成，共匹配 {report.matched_files} 个文件，"
                f"仅保留前 {len(report.items)} 条"
            )
        else:
            report.message = f"搜索完成，共匹配 {report.matched_files} 个文件"
        return report

    def build_delete_plan(
        self,
        item: FileSearchItem,
        confirm_token: str,
    ) -> FileDeletePlan:
        """根据当前文件状态生成删除预览。"""
        blocked_reasons: List[str] = []
        try:
            self._resolve_snapshot(item)
        except (OSError, ValueError) as err:
            blocked_reasons.append(str(err))
        return FileDeletePlan(
            item_id=item.item_id,
            relative_path=item.relative_path,
            absolute_path=item.absolute_path,
            size=item.size,
            modified_at=item.modified_at,
            confirm_token=confirm_token if not blocked_reasons else "",
            blocked_reasons=tuple(blocked_reasons),
        )

    def delete_file(self, item: FileSearchItem) -> FileDeleteResult:
        """删除快照对应的普通文件，并重新枚举父目录复核。"""
        try:
            candidate, _ = self._resolve_snapshot(item)
        except (OSError, ValueError) as err:
            return FileDeleteResult(
                item_id=item.item_id,
                relative_path=item.relative_path,
                absolute_path=item.absolute_path,
                deleted=False,
                verified=False,
                message=str(err),
            )

        try:
            candidate.unlink()
        except OSError as err:
            return FileDeleteResult(
                item_id=item.item_id,
                relative_path=item.relative_path,
                absolute_path=item.absolute_path,
                deleted=False,
                verified=False,
                message=f"删除失败：{str(err)}",
            )

        verified = self._verify_deleted(candidate)
        return FileDeleteResult(
            item_id=item.item_id,
            relative_path=item.relative_path,
            absolute_path=item.absolute_path,
            deleted=True,
            verified=verified,
            message="文件已删除并通过复核" if verified else "文件已删除，但父目录复核失败",
        )

    def _build_item(
        self,
        path: Path,
        relative_path: str,
        path_stat: Any,
    ) -> FileSearchItem:
        item_id = hashlib.sha256(
            (
                f"{relative_path}\0{path_stat.st_dev}\0{path_stat.st_ino}\0"
                f"{path_stat.st_size}\0{path_stat.st_mtime_ns}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        return FileSearchItem(
            item_id=item_id,
            relative_path=relative_path,
            absolute_path=path.as_posix(),
            name=path.name,
            parent=PurePosixPath(relative_path).parent.as_posix(),
            suffix=path.suffix.lower(),
            size=path_stat.st_size,
            mtime_ns=path_stat.st_mtime_ns,
            modified_at=datetime.fromtimestamp(path_stat.st_mtime).astimezone().isoformat(
                timespec="seconds"
            ),
            device=path_stat.st_dev,
            inode=path_stat.st_ino,
        )

    def _resolve_snapshot(self, item: FileSearchItem) -> Tuple[Path, Any]:
        root_dir = self.validate_root()
        relative_path = _validate_relative_path(item.relative_path)
        candidate = root_dir.joinpath(*relative_path.parts)
        try:
            candidate_stat = candidate.lstat()
        except OSError as err:
            raise ValueError("文件已不存在，请重新搜索") from err
        if stat.S_ISLNK(candidate_stat.st_mode):
            raise ValueError("不允许删除符号链接")
        if not stat.S_ISREG(candidate_stat.st_mode):
            raise ValueError("只允许删除普通文件")
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except OSError as err:
            raise ValueError("文件路径无法解析，请重新搜索") from err
        if resolved_candidate != candidate or not resolved_candidate.is_relative_to(root_dir):
            raise ValueError("文件路径超出配置的搜索目录")
        current_snapshot = (
            candidate_stat.st_dev,
            candidate_stat.st_ino,
            candidate_stat.st_size,
            candidate_stat.st_mtime_ns,
        )
        expected_snapshot = (
            item.device,
            item.inode,
            item.size,
            item.mtime_ns,
        )
        if current_snapshot != expected_snapshot:
            raise ValueError("文件状态已变化，请重新搜索后再删除")
        return candidate, candidate_stat

    @staticmethod
    def _verify_deleted(path: Path) -> bool:
        for delay in DELETE_VERIFY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                if all(entry.name != path.name for entry in path.parent.iterdir()):
                    return True
            except OSError:
                continue
        return False


def config_from_dict(config: Optional[Dict[str, Any]]) -> DirectorySearchConfig:
    """将插件配置字典转换为强类型目录搜索配置。"""
    values = config or {}
    root_text = str(values.get("root_dir") or "").strip()
    return DirectorySearchConfig(
        enabled=_as_bool(values.get("enabled"), False),
        root_dir=Path(root_text).expanduser() if root_text else None,
        max_results=DEFAULT_MAX_RESULTS,
    )


def normalize_query(query: str) -> str:
    """规范化搜索关键词并拒绝空查询或超长输入。"""
    normalized = str(query or "").strip()
    if not normalized:
        raise ValueError("请输入搜索关键词")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ValueError(f"搜索关键词不能超过 {MAX_QUERY_LENGTH} 个字符")
    return normalized


def _validate_relative_path(path_text: str) -> PurePosixPath:
    path = PurePosixPath(str(path_text or ""))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("搜索结果路径无效")
    return path


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return default


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
