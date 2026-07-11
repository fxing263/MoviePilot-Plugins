"""媒体元数据双目录同步的纯文件系统引擎。"""

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


DEFAULT_SOURCE_DIR = Path("/media/9kg")
DEFAULT_TARGET_DIR = Path("/media/番号系列")
DEFAULT_OTHER_CATEGORY = "其他"
DEFAULT_CLOUD_MOUNT_PATHS = (Path("/CloudNAS/CloudDrive"),)
DEFAULT_SYNC_EXTENSIONS = (
    ".strm",
    ".nfo",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".json",
)
MEDIAINFO_SUFFIX = "-mediainfo.json"
MAX_RECORDED_FILE_RESULTS = 200
TEMP_FILE_PATTERN = re.compile(r"^\..+\.tmp$")


class SyncDirection(str, Enum):
    """元数据文件同步方向。"""

    FORWARD = "forward"
    REVERSE = "reverse"


class SyncStatus(str, Enum):
    """单个元数据文件的同步结果。"""

    COPIED = "copied"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class MetadataSyncConfig:
    """媒体元数据双目录同步配置。"""

    enabled: bool = False
    monitor_enabled: bool = True
    reverse_sync_enabled: bool = True
    source_dir: Path = DEFAULT_SOURCE_DIR
    target_dir: Path = DEFAULT_TARGET_DIR
    other_category: str = DEFAULT_OTHER_CATEGORY
    settle_seconds: int = 2
    sync_extensions: Tuple[str, ...] = DEFAULT_SYNC_EXTENSIONS
    cloud_mount_paths: Tuple[Path, ...] = DEFAULT_CLOUD_MOUNT_PATHS
    max_delete_files: int = 100

    @classmethod
    def from_dict(
        cls,
        config: Optional[Dict[str, Any]],
    ) -> "MetadataSyncConfig":
        """从插件配置字典构造同步配置。"""
        raw = config or {}
        return cls(
            enabled=_parse_bool(raw.get("enabled"), False),
            monitor_enabled=_parse_bool(raw.get("monitor_enabled"), True),
            reverse_sync_enabled=_parse_bool(
                raw.get("reverse_sync_enabled"),
                True,
            ),
            source_dir=_parse_path(raw.get("source_dir"), DEFAULT_SOURCE_DIR),
            target_dir=_parse_path(raw.get("target_dir"), DEFAULT_TARGET_DIR),
            other_category=str(
                raw.get("other_category") or DEFAULT_OTHER_CATEGORY
            ).strip(),
            settle_seconds=max(1, _parse_int(raw.get("settle_seconds"), 2)),
            sync_extensions=_parse_extensions(raw.get("sync_extensions")),
            cloud_mount_paths=_parse_paths(
                raw.get("cloud_mount_paths"),
                DEFAULT_CLOUD_MOUNT_PATHS,
            ),
            max_delete_files=max(
                1,
                _parse_int(raw.get("max_delete_files"), 100),
            ),
        )


@dataclass
class DirectoryReadiness:
    """番号目录的实时同步就绪状态。"""

    path: str
    ready: bool
    matched_stems: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class FileSyncResult:
    """单个元数据文件的同步结果。"""

    direction: SyncDirection
    source_path: str
    target_path: str
    status: SyncStatus
    message: str


@dataclass
class SyncReport:
    """一次全量或增量同步的汇总报告。"""

    kind: str
    scanned_directories: int = 0
    ready_directories: int = 0
    copied_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    not_ready: List[DirectoryReadiness] = field(default_factory=list)
    missing_targets: List[str] = field(default_factory=list)
    files: List[FileSyncResult] = field(default_factory=list)
    message: str = ""

    def add_file_result(self, result: FileSyncResult) -> None:
        """记录单文件结果并累计汇总计数。"""
        if result.status == SyncStatus.COPIED:
            self.copied_files += 1
        elif result.status == SyncStatus.SKIPPED:
            self.skipped_files += 1
        else:
            self.failed_files += 1
        if len(self.files) < MAX_RECORDED_FILE_RESULTS:
            self.files.append(result)


@dataclass
class MissingMetadataItem:
    """一条按番号和 STRM 文件名聚合的缺失元数据记录。"""

    item_id: str
    number: str
    file_name: str
    source_paths: List[str] = field(default_factory=list)
    owner_names: List[str] = field(default_factory=list)
    missing_types: List[str] = field(default_factory=list)
    missing_by_source: Dict[str, List[str]] = field(default_factory=dict)
    target_directory: str = ""
    target_path: str = ""
    cloud_paths: List[str] = field(default_factory=list)
    cloud_ready: bool = False
    cloud_message: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MissingMetadataItem":
        """从持久化字典恢复缺失元数据记录。"""
        return cls(
            item_id=str(data.get("item_id") or ""),
            number=str(data.get("number") or ""),
            file_name=str(data.get("file_name") or ""),
            source_paths=[str(item) for item in data.get("source_paths") or []],
            owner_names=[str(item) for item in data.get("owner_names") or []],
            missing_types=[
                str(item) for item in data.get("missing_types") or []
            ],
            missing_by_source={
                str(path): [str(item) for item in values or []]
                for path, values in dict(
                    data.get("missing_by_source") or {}
                ).items()
            },
            target_directory=str(data.get("target_directory") or ""),
            target_path=str(data.get("target_path") or ""),
            cloud_paths=[str(item) for item in data.get("cloud_paths") or []],
            cloud_ready=bool(data.get("cloud_ready")),
            cloud_message=str(data.get("cloud_message") or ""),
        )


@dataclass
class MissingMetadataReport:
    """缺失元数据全量扫描报告。"""

    kind: str = "missing_metadata_scan"
    scanned_directories: int = 0
    scanned_strm_files: int = 0
    missing_items: int = 0
    missing_nfo: int = 0
    missing_mediainfo: int = 0
    generated_at: str = ""
    items: List[MissingMetadataItem] = field(default_factory=list)
    message: str = ""


@dataclass
class MissingDeletePlan:
    """缺失元数据条目的三端删除预览计划。"""

    item_id: str
    number: str
    file_name: str
    source_files: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    cloud_files: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    confirm_token: str = ""


def config_from_dict(
    config: Optional[Dict[str, Any]],
) -> MetadataSyncConfig:
    """解析媒体元数据同步插件配置。"""
    return MetadataSyncConfig.from_dict(config)


def object_to_dict(value: Any) -> Any:
    """将同步报告对象转换为可持久化的数据。"""
    if is_dataclass(value):
        return {
            item.name: object_to_dict(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return [object_to_dict(item) for item in value]
    if isinstance(value, list):
        return [object_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): object_to_dict(item) for key, item in value.items()}
    return value


def validate_config(config: MetadataSyncConfig) -> List[str]:
    """校验目录边界和可配置的元数据扩展名。"""
    errors: List[str] = []
    if not config.source_dir.is_absolute():
        errors.append("源目录必须使用绝对路径")
    if not config.target_dir.is_absolute():
        errors.append("目标目录必须使用绝对路径")
    source_dir = config.source_dir.resolve(strict=False)
    target_dir = config.target_dir.resolve(strict=False)
    if source_dir == target_dir:
        errors.append("源目录和目标目录不能相同")
    if _is_relative_to(source_dir, target_dir) or _is_relative_to(
        target_dir,
        source_dir,
    ):
        errors.append("源目录和目标目录不能互相包含")
    if (
        not config.other_category
        or config.other_category in {".", ".."}
        or "/" in config.other_category
        or "\\" in config.other_category
    ):
        errors.append("其他分类名称不能包含路径分隔符")
    if not config.sync_extensions:
        errors.append("至少需要配置一个正向同步扩展名")
    if ".json" not in config.sync_extensions:
        errors.append("同步扩展名必须包含 .json")
    for cloud_root in config.cloud_mount_paths:
        if not cloud_root.is_absolute() or ".." in cloud_root.parts:
            errors.append("网盘挂载根目录必须使用不含 .. 的绝对路径")
            continue
        resolved_cloud_root = cloud_root.resolve(strict=False)
        if (
            _is_relative_to(source_dir, resolved_cloud_root)
            or _is_relative_to(target_dir, resolved_cloud_root)
            or _is_relative_to(resolved_cloud_root, source_dir)
            or _is_relative_to(resolved_cloud_root, target_dir)
        ):
            errors.append("网盘挂载根目录不能与源目录或目标目录互相包含")
    if config.max_delete_files > 500:
        errors.append("单条最大删除文件数不能超过 500")
    return errors


class MetadataSyncEngine:
    """媒体元数据双目录同步引擎。"""

    def __init__(
        self,
        config: MetadataSyncConfig,
        log_callback: Optional[Callable[[str], None]] = None,
        write_callback: Optional[Callable[[Path], None]] = None,
        stop_callback: Optional[Callable[[], bool]] = None,
    ) -> None:
        """初始化同步配置以及日志和写入事件回调。"""
        self.config = config
        self._log_callback = log_callback
        self._write_callback = write_callback
        self._stop_callback = stop_callback

    def get_category_name(self, directory_name: str) -> str:
        """按番号目录名首字母返回 A-Z 或其他分类。"""
        clean_name = str(directory_name or "").strip()
        if clean_name:
            first_character = clean_name[0]
            if first_character.isascii() and first_character.isalpha():
                return first_character.upper()
        return self.config.other_category

    def get_target_directory(self, source_directory: Path) -> Path:
        """返回源番号目录对应的分类目标目录。"""
        return (
            self.config.target_dir
            / self.get_category_name(source_directory.name)
            / source_directory.name
        )

    def analyze_readiness(self, directory: Path) -> DirectoryReadiness:
        """检查目录中是否存在同名 STRM 与 NFO 文件。"""
        strm_stems: Dict[str, str] = {}
        nfo_stems: Set[str] = set()
        try:
            for file_path in self._iter_metadata_files(directory):
                normalized_stem = file_path.stem.casefold()
                if file_path.suffix.lower() == ".strm":
                    strm_stems[normalized_stem] = file_path.stem
                elif file_path.suffix.lower() == ".nfo":
                    nfo_stems.add(normalized_stem)
        except OSError as err:
            return DirectoryReadiness(
                path=directory.as_posix(),
                ready=False,
                reason=f"目录读取失败：{str(err)}",
            )
        matched_keys = sorted(set(strm_stems).intersection(nfo_stems))
        matched_stems = [strm_stems[key] for key in matched_keys]
        if matched_stems:
            return DirectoryReadiness(
                path=directory.as_posix(),
                ready=True,
                matched_stems=matched_stems,
            )
        return DirectoryReadiness(
            path=directory.as_posix(),
            ready=False,
            reason="未满足同名 .strm + .nfo 条件",
        )

    def iter_source_directories(self) -> List[Path]:
        """按“名字或合集/番号目录”结构列出所有源番号目录。"""
        directories: List[Path] = []
        try:
            owner_directories = sorted(
                (
                    item
                    for item in self.config.source_dir.iterdir()
                    if item.is_dir()
                    and not item.is_symlink()
                    and not item.name.startswith(".")
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return directories
        for owner_directory in owner_directories:
            try:
                directories.extend(
                    sorted(
                        (
                            item
                            for item in owner_directory.iterdir()
                            if item.is_dir()
                            and not item.is_symlink()
                            and not item.name.startswith(".")
                        ),
                        key=lambda item: item.name.casefold(),
                    )
                )
            except OSError as err:
                self._log(
                    f"跳过无法读取的名字或合集目录：{owner_directory}，{str(err)}"
                )
        return directories

    def build_source_index(self) -> Dict[str, List[Path]]:
        """按番号目录名建立源目录多位置索引。"""
        index: Dict[str, List[Path]] = {}
        for directory in self.iter_source_directories():
            index.setdefault(directory.name, []).append(directory)
        return index

    def find_source_directories(self, directory_name: str) -> List[Path]:
        """查找所有同名番号源目录。"""
        return self.build_source_index().get(directory_name, [])

    def scan_missing_metadata(self) -> MissingMetadataReport:
        """扫描所有 STRM，按番号和文件名聚合缺失的 NFO 与 MediaInfo。"""
        report = MissingMetadataReport(
            generated_at=datetime.now().isoformat(timespec="seconds")
        )
        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for source_directory in self.iter_source_directories():
            if self._should_stop():
                report.message = "缺失元数据扫描已停止"
                return report
            report.scanned_directories += 1
            try:
                strm_files = sorted(
                    (
                        item
                        for item in source_directory.iterdir()
                        if item.is_file()
                        and not item.is_symlink()
                        and item.suffix.casefold() == ".strm"
                    ),
                    key=lambda item: item.name.casefold(),
                )
            except OSError as err:
                self._log(
                    f"缺失元数据扫描跳过目录：{source_directory}，{str(err)}"
                )
                continue
            for strm_file in strm_files:
                report.scanned_strm_files += 1
                key = (
                    source_directory.name,
                    strm_file.name,
                )
                group = groups.setdefault(
                    key,
                    {
                        "number": source_directory.name,
                        "file_name": strm_file.name,
                        "source_paths": [],
                        "owner_names": [],
                        "missing_by_source": {},
                        "cloud_paths": [],
                        "cloud_errors": [],
                    },
                )
                source_path = strm_file.as_posix()
                group["source_paths"].append(source_path)
                group["owner_names"].append(source_directory.parent.name)
                missing_types: List[str] = []
                nfo_path = strm_file.with_suffix(".nfo")
                if not nfo_path.is_file() or nfo_path.is_symlink():
                    missing_types.append("NFO")
                mediainfo_path = strm_file.with_name(
                    f"{strm_file.stem}{MEDIAINFO_SUFFIX}"
                )
                if not mediainfo_path.is_file() or mediainfo_path.is_symlink():
                    missing_types.append("MediaInfo")
                if missing_types:
                    group["missing_by_source"][source_path] = missing_types
                cloud_path, cloud_error = self.resolve_cloud_path(strm_file)
                if cloud_error:
                    group["cloud_errors"].append(cloud_error)
                elif cloud_path:
                    group["cloud_paths"].append(cloud_path.as_posix())

        items: List[MissingMetadataItem] = []
        for group in groups.values():
            missing_by_source = dict(group["missing_by_source"])
            if not missing_by_source:
                continue
            missing_types = sorted(
                {
                    missing_type
                    for values in missing_by_source.values()
                    for missing_type in values
                }
            )
            number = str(group["number"])
            file_name = str(group["file_name"])
            item_id = hashlib.sha256(
                f"{number}\0{file_name}".encode("utf-8")
            ).hexdigest()[:16]
            target_directory = (
                self.config.target_dir
                / self.get_category_name(number)
                / number
            )
            cloud_errors = list(dict.fromkeys(group["cloud_errors"]))
            item = MissingMetadataItem(
                item_id=item_id,
                number=number,
                file_name=file_name,
                source_paths=sorted(set(group["source_paths"])),
                owner_names=sorted(set(group["owner_names"])),
                missing_types=missing_types,
                missing_by_source=missing_by_source,
                target_directory=target_directory.as_posix(),
                target_path=(target_directory / file_name).as_posix(),
                cloud_paths=sorted(set(group["cloud_paths"])),
                cloud_ready=not cloud_errors and bool(group["cloud_paths"]),
                cloud_message="；".join(cloud_errors),
            )
            items.append(item)
            report.missing_nfo += int("NFO" in missing_types)
            report.missing_mediainfo += int("MediaInfo" in missing_types)
        report.items = sorted(
            items,
            key=lambda item: (item.number.casefold(), item.file_name.casefold()),
        )
        report.missing_items = len(report.items)
        report.message = (
            f"缺失元数据扫描完成：检查 {report.scanned_strm_files} 个 STRM，"
            f"发现 {report.missing_items} 条缺失记录"
        )
        self._log(report.message)
        return report

    def build_missing_delete_plan(
        self,
        item: MissingMetadataItem,
    ) -> MissingDeletePlan:
        """为缺失元数据记录生成 9kg、番号系列和网盘删除预览。"""
        plan = MissingDeletePlan(
            item_id=item.item_id,
            number=item.number,
            file_name=item.file_name,
        )
        if (
            not item.number
            or Path(item.number).name != item.number
            or not item.file_name
            or Path(item.file_name).name != item.file_name
            or Path(item.file_name).suffix.casefold() != ".strm"
        ):
            plan.blocked_reasons.append("缺失记录中的番号或 STRM 文件名无效")
            return plan

        source_strm_files: List[Path] = []
        for source_directory in self.find_source_directories(item.number):
            try:
                source_strm_files.extend(
                    candidate.resolve()
                    for candidate in source_directory.iterdir()
                    if candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.name.casefold() == item.file_name.casefold()
                )
            except OSError as err:
                plan.blocked_reasons.append(
                    f"无法读取 9kg 番号目录：{source_directory}，{str(err)}"
                )
        source_strm_files = list(dict.fromkeys(source_strm_files))
        if not source_strm_files:
            plan.blocked_reasons.append("9kg 中已找不到该 STRM，请重新扫描")

        source_files: List[Path] = []
        cloud_files: List[Path] = []
        for strm_file in source_strm_files:
            try:
                source_files.extend(
                    self._owned_metadata_files(
                        strm_file.parent,
                        item.file_name,
                        self.config.source_dir,
                    )
                )
            except OSError as err:
                plan.blocked_reasons.append(str(err))
            cloud_path, cloud_error = self.resolve_cloud_path(
                strm_file,
                require_accessible=True,
            )
            if cloud_error:
                plan.blocked_reasons.append(cloud_error)
            elif cloud_path:
                cloud_files.append(cloud_path)

        target_directory = (
            self.config.target_dir
            / self.get_category_name(item.number)
            / item.number
        )
        target_files: List[Path] = []
        try:
            target_files = self._owned_metadata_files(
                target_directory,
                item.file_name,
                self.config.target_dir,
            )
        except OSError as err:
            plan.blocked_reasons.append(str(err))

        source_files = list(dict.fromkeys(source_files))
        target_files = list(dict.fromkeys(target_files))
        cloud_files = list(dict.fromkeys(cloud_files))
        total_files = len(source_files) + len(target_files) + len(cloud_files)
        if total_files > self.config.max_delete_files:
            plan.blocked_reasons.append(
                f"删除目标共 {total_files} 个，超过单条上限 "
                f"{self.config.max_delete_files}"
            )
        plan.source_files = [path.as_posix() for path in source_files]
        plan.target_files = [path.as_posix() for path in target_files]
        plan.cloud_files = [path.as_posix() for path in cloud_files]
        plan.blocked_reasons = list(dict.fromkeys(plan.blocked_reasons))
        plan.confirm_token = self._missing_delete_token(plan)
        return plan

    def resolve_cloud_path(
        self,
        strm_file: Path,
        require_accessible: bool = False,
    ) -> Tuple[Optional[Path], Optional[str]]:
        """读取 STRM 首行并校验其网盘挂载源文件路径。"""
        try:
            content = strm_file.read_text(encoding="utf-8", errors="ignore")
        except OSError as err:
            return None, f"读取 {strm_file.name} 失败：{str(err)}"
        first_line = next(
            (line.strip() for line in content.splitlines() if line.strip()),
            "",
        )
        if not first_line:
            return None, f"{strm_file.name} 内容为空"
        cloud_path = Path(first_line).expanduser()
        if not cloud_path.is_absolute() or ".." in cloud_path.parts:
            return None, f"{strm_file.name} 未指向有效的网盘绝对挂载路径"
        absolute_path = cloud_path.absolute()
        resolved_path = absolute_path.resolve(strict=False)
        matched_roots = [
            root
            for root in self.config.cloud_mount_paths
            if _is_relative_to(
                resolved_path,
                root.expanduser().resolve(strict=False),
            )
        ]
        if not matched_roots:
            return None, f"网盘路径超出允许挂载根目录：{absolute_path}"
        if require_accessible and not any(root.is_dir() for root in matched_roots):
            return None, "网盘挂载根目录当前不可访问，已停止删除"
        return resolved_path, None

    def _owned_metadata_files(
        self,
        directory: Path,
        strm_name: str,
        allowed_root: Path,
    ) -> List[Path]:
        if not directory.exists():
            return []
        if directory.is_symlink() or not directory.is_dir():
            raise OSError(f"删除目标目录不是普通目录：{directory}")
        resolved_directory = directory.resolve()
        if not _is_relative_to(
            resolved_directory,
            allowed_root.resolve(strict=False),
        ):
            raise OSError(f"删除目标目录超出允许范围：{directory}")
        try:
            metadata_files = sorted(
                (
                    candidate.resolve()
                    for candidate in directory.iterdir()
                    if candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.suffix.casefold()
                    in set(self.config.sync_extensions).union(
                        DEFAULT_SYNC_EXTENSIONS
                    )
                    and not self.is_temporary_file(candidate)
                ),
                key=lambda candidate: candidate.name.casefold(),
            )
        except OSError as err:
            raise OSError(f"读取删除目标目录失败：{directory}，{str(err)}") from err
        selected_name = strm_name.casefold()
        selected_stem = Path(strm_name).stem.casefold()
        strm_files = [
            candidate
            for candidate in metadata_files
            if candidate.suffix.casefold() == ".strm"
        ]
        selected_exists = any(
            candidate.name.casefold() == selected_name
            for candidate in strm_files
        )
        if selected_exists and len(strm_files) == 1:
            return metadata_files
        return [
            candidate
            for candidate in metadata_files
            if candidate.name.casefold() == selected_name
            or candidate.stem.casefold() == selected_stem
            or candidate.stem.casefold().startswith(f"{selected_stem}-")
        ]

    @staticmethod
    def _missing_delete_token(plan: MissingDeletePlan) -> str:
        snapshot_parts = [plan.item_id, plan.number, plan.file_name]
        for group_name, paths in (
            ("cloud", plan.cloud_files),
            ("target", plan.target_files),
            ("source", plan.source_files),
        ):
            for path_text in sorted(paths):
                path = Path(path_text)
                try:
                    stat = path.stat()
                    snapshot = f"{stat.st_size}:{stat.st_mtime_ns}"
                except OSError:
                    snapshot = "absent"
                snapshot_parts.append(f"{group_name}:{path_text}:{snapshot}")
        payload = "\n".join(snapshot_parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def source_event_directory(self, event_path: Path) -> Optional[Path]:
        """根据源目录文件系统事件定位所属番号目录。"""
        try:
            relative_path = event_path.resolve(strict=False).relative_to(
                self.config.source_dir.resolve(strict=False)
            )
        except ValueError:
            return None
        if len(relative_path.parts) < 2:
            return None
        owner_name, directory_name = relative_path.parts[:2]
        if owner_name.startswith(".") or directory_name.startswith("."):
            return None
        directory = self.config.source_dir / owner_name / directory_name
        if directory.is_symlink():
            return None
        return directory

    def forward_sync_directory(self, source_directory: Path) -> SyncReport:
        """将一个源番号目录内的元数据同步到分类目标目录。"""
        report = SyncReport(kind="forward_incremental", scanned_directories=1)
        readiness = self.analyze_readiness(source_directory)
        if readiness.ready:
            report.ready_directories = 1
        else:
            report.not_ready.append(readiness)
        target_directory = self.get_target_directory(source_directory)
        try:
            source_files = list(self._iter_metadata_files(source_directory))
        except OSError as err:
            report.failed_files += 1
            report.message = f"目录读取失败：{str(err)}"
            self._log(f"正向同步失败：{source_directory}，{str(err)}")
            return report
        for source_file in source_files:
            result = self._copy_if_needed(
                source_file=source_file,
                target_file=target_directory / source_file.name,
                direction=SyncDirection.FORWARD,
            )
            report.add_file_result(result)
            self._log_file_result(result)
        report.message = (
            f"正向同步 {source_directory.name} 完成：复制 {report.copied_files}，"
            f"跳过 {report.skipped_files}，失败 {report.failed_files}"
        )
        return report

    def full_forward_sync(self) -> SyncReport:
        """执行 9kg 到番号系列的全量元数据同步。"""
        report = SyncReport(kind="forward_full")
        if not self.config.source_dir.is_dir():
            report.failed_files = 1
            report.message = f"源目录不存在：{self.config.source_dir}"
            self._log(report.message)
            return report
        for source_directory in self.iter_source_directories():
            if self._should_stop():
                report.message = "正向全量已停止"
                self._log(report.message)
                return report
            directory_report = self.forward_sync_directory(source_directory)
            report.scanned_directories += 1
            report.ready_directories += directory_report.ready_directories
            report.not_ready.extend(directory_report.not_ready)
            self._merge_file_report(report, directory_report)
            if directory_report.not_ready:
                self._log(
                    f"未就绪目录：{source_directory}，"
                    f"{directory_report.not_ready[0].reason}"
                )
        report.message = (
            f"正向全量完成：扫描 {report.scanned_directories} 个目录，"
            f"复制 {report.copied_files}，跳过 {report.skipped_files}，"
            f"失败 {report.failed_files}，未就绪 {len(report.not_ready)}"
        )
        self._log(report.message)
        return report

    def reverse_sync_file(
        self,
        json_file: Path,
        source_index: Optional[Dict[str, List[Path]]] = None,
    ) -> Optional[SyncReport]:
        """将一个目标 JSON 回写到所有同名源番号目录。"""
        if not self.is_target_json_file(json_file):
            return None
        report = SyncReport(kind="reverse_incremental", scanned_directories=1)
        index = source_index if source_index is not None else self.build_source_index()
        source_directories = index.get(json_file.parent.name, [])
        if not source_directories:
            report.missing_targets.append(json_file.as_posix())
            report.message = f"找不到 9kg 回写目标：{json_file}"
            self._log(report.message)
            return report
        for source_directory in source_directories:
            result = self._copy_if_needed(
                source_file=json_file,
                target_file=source_directory / json_file.name,
                direction=SyncDirection.REVERSE,
            )
            report.add_file_result(result)
            self._log_file_result(result)
        report.message = (
            f"JSON 回写 {json_file.parent.name}/{json_file.name} 完成："
            f"复制 {report.copied_files}，跳过 {report.skipped_files}，"
            f"失败 {report.failed_files}"
        )
        return report

    def full_reverse_sync(self) -> SyncReport:
        """执行番号系列到 9kg 的全量 JSON 回写。"""
        report = SyncReport(kind="reverse_full")
        if not self.config.target_dir.is_dir():
            report.failed_files = 1
            report.message = f"目标目录不存在：{self.config.target_dir}"
            self._log(report.message)
            return report
        source_index = self.build_source_index()
        for target_directory in self._iter_target_directories():
            if self._should_stop():
                report.message = "JSON 全量回写已停止"
                self._log(report.message)
                return report
            report.scanned_directories += 1
            try:
                json_files = sorted(
                    (
                        item
                        for item in target_directory.iterdir()
                        if item.is_file()
                        and not item.is_symlink()
                        and item.suffix.lower() == ".json"
                        and not self.is_temporary_file(item)
                    ),
                    key=lambda item: item.name.casefold(),
                )
            except OSError as err:
                report.failed_files += 1
                self._log(f"跳过无法读取的目标番号目录：{target_directory}，{str(err)}")
                continue
            for json_file in json_files:
                file_report = self.reverse_sync_file(json_file, source_index)
                if not file_report:
                    continue
                report.missing_targets.extend(file_report.missing_targets)
                self._merge_file_report(report, file_report)
        report.message = (
            f"JSON 全量回写完成：扫描 {report.scanned_directories} 个目录，"
            f"复制 {report.copied_files}，跳过 {report.skipped_files}，"
            f"失败 {report.failed_files}，无回写目标 {len(report.missing_targets)}"
        )
        self._log(report.message)
        return report

    def is_target_json_file(self, file_path: Path) -> bool:
        """判断路径是否为目标目录三级结构中的 JSON 文件。"""
        if (
            file_path.suffix.lower() != ".json"
            or self.is_temporary_file(file_path)
            or file_path.is_dir()
            or file_path.is_symlink()
        ):
            return False
        try:
            relative_path = file_path.resolve(strict=False).relative_to(
                self.config.target_dir.resolve(strict=False)
            )
        except ValueError:
            return False
        return len(relative_path.parts) == 3

    def is_sync_extension(self, file_path: Path) -> bool:
        """判断文件是否属于正向同步扩展名。"""
        return (
            file_path.suffix.lower() in self.config.sync_extensions
            and not self.is_temporary_file(file_path)
        )

    @staticmethod
    def is_temporary_file(file_path: Path) -> bool:
        """判断文件是否为本插件原子复制使用的临时文件。"""
        return bool(TEMP_FILE_PATTERN.match(file_path.name))

    def get_stats(self) -> Dict[str, int]:
        """统计目标根目录各分类下的番号目录数量。"""
        stats: Dict[str, int] = {}
        if not self.config.target_dir.is_dir():
            return stats
        try:
            categories = sorted(
                (
                    item
                    for item in self.config.target_dir.iterdir()
                    if item.is_dir() and not item.is_symlink()
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return stats
        for category in categories:
            try:
                stats[category.name] = sum(
                    1
                    for item in category.iterdir()
                    if item.is_dir() and not item.is_symlink()
                )
            except OSError:
                stats[category.name] = 0
        return stats

    def _iter_metadata_files(self, directory: Path) -> Iterable[Path]:
        return sorted(
            (
                item
                for item in directory.iterdir()
                if item.is_file()
                and not item.is_symlink()
                and self.is_sync_extension(item)
            ),
            key=lambda item: item.name.casefold(),
        )

    def _iter_target_directories(self) -> List[Path]:
        directories: List[Path] = []
        try:
            categories = sorted(
                (
                    item
                    for item in self.config.target_dir.iterdir()
                    if item.is_dir()
                    and not item.is_symlink()
                    and not item.name.startswith(".")
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return directories
        for category in categories:
            try:
                directories.extend(
                    sorted(
                        (
                            item
                            for item in category.iterdir()
                            if item.is_dir()
                            and not item.is_symlink()
                            and not item.name.startswith(".")
                        ),
                        key=lambda item: item.name.casefold(),
                    )
                )
            except OSError as err:
                self._log(f"跳过无法读取的分类目录：{category}，{str(err)}")
        return directories

    def _copy_if_needed(
        self,
        source_file: Path,
        target_file: Path,
        direction: SyncDirection,
    ) -> FileSyncResult:
        try:
            self._ensure_within_allowed_roots(source_file, target_file, direction)
            source_stat = source_file.stat()
            if target_file.exists():
                if target_file.is_dir() or target_file.is_symlink():
                    raise OSError("目标路径不是普通文件")
                target_stat = target_file.stat()
                if (
                    source_stat.st_size == target_stat.st_size
                    and source_stat.st_mtime_ns == target_stat.st_mtime_ns
                ):
                    return self._file_result(
                        direction,
                        source_file,
                        target_file,
                        SyncStatus.SKIPPED,
                        "大小和修改时间未变化",
                    )
                if (
                    source_file.suffix.lower() == ".json"
                    and target_stat.st_mtime_ns > source_stat.st_mtime_ns
                ):
                    return self._file_result(
                        direction,
                        source_file,
                        target_file,
                        SyncStatus.SKIPPED,
                        "目标文件较新，保留现有版本",
                    )
            target_file.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_copy(source_file, target_file)
            return self._file_result(
                direction,
                source_file,
                target_file,
                SyncStatus.COPIED,
                "已原子复制",
            )
        except OSError as err:
            return self._file_result(
                direction,
                source_file,
                target_file,
                SyncStatus.FAILED,
                str(err),
            )

    def _atomic_copy(self, source_file: Path, target_file: Path) -> None:
        for attempt in range(2):
            source_stat_before = source_file.stat()
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target_file.name}.",
                suffix=".tmp",
                dir=target_file.parent,
            )
            os.close(file_descriptor)
            temporary_path = Path(temporary_name)
            try:
                shutil.copy2(source_file, temporary_path)
                source_stat_after = source_file.stat()
                source_changed = (
                    source_stat_before.st_size != source_stat_after.st_size
                    or source_stat_before.st_mtime_ns != source_stat_after.st_mtime_ns
                )
                if source_changed:
                    temporary_path.unlink(missing_ok=True)
                    if attempt == 0:
                        continue
                    raise OSError("源文件复制期间持续变化")
                if self._write_callback:
                    self._write_callback(target_file)
                os.replace(temporary_path, target_file)
                target_stat = target_file.stat()
                if target_stat.st_size != source_stat_after.st_size:
                    raise OSError("原子复制后文件大小复核失败")
                return
            finally:
                temporary_path.unlink(missing_ok=True)
        raise OSError("原子复制失败")

    def _ensure_within_allowed_roots(
        self,
        source_file: Path,
        target_file: Path,
        direction: SyncDirection,
    ) -> None:
        if direction == SyncDirection.FORWARD:
            source_root = self.config.source_dir
            target_root = self.config.target_dir
        else:
            source_root = self.config.target_dir
            target_root = self.config.source_dir
        resolved_source = source_file.resolve(strict=True)
        resolved_target_parent = target_file.parent.resolve(strict=False)
        if not _is_relative_to(resolved_source, source_root.resolve(strict=False)):
            raise OSError("源文件超出允许目录")
        if not _is_relative_to(
            resolved_target_parent,
            target_root.resolve(strict=False),
        ):
            raise OSError("目标文件超出允许目录")

    @staticmethod
    def _file_result(
        direction: SyncDirection,
        source_file: Path,
        target_file: Path,
        status: SyncStatus,
        message: str,
    ) -> FileSyncResult:
        return FileSyncResult(
            direction=direction,
            source_path=source_file.as_posix(),
            target_path=target_file.as_posix(),
            status=status,
            message=message,
        )

    @staticmethod
    def _merge_file_report(report: SyncReport, other: SyncReport) -> None:
        report.copied_files += other.copied_files
        report.skipped_files += other.skipped_files
        report.failed_files += other.failed_files
        remaining = MAX_RECORDED_FILE_RESULTS - len(report.files)
        if remaining > 0:
            report.files.extend(other.files[:remaining])

    def _log_file_result(self, result: FileSyncResult) -> None:
        direction = "正向" if result.direction == SyncDirection.FORWARD else "回写"
        action = {
            SyncStatus.COPIED: "复制",
            SyncStatus.SKIPPED: "跳过",
            SyncStatus.FAILED: "失败",
        }[result.status]
        self._log(
            f"{direction}{action}：{result.source_path} -> "
            f"{result.target_path}，{result.message}"
        )

    def _log(self, message: str) -> None:
        if self._log_callback:
            self._log_callback(message)

    def _should_stop(self) -> bool:
        return bool(self._stop_callback and self._stop_callback())


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "启用", "是"}:
        return True
    if normalized in {"0", "false", "no", "off", "禁用", "否", ""}:
        return False
    return default


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_path(value: Any, default: Path) -> Path:
    clean_value = str(value or "").strip()
    return Path(clean_value).expanduser() if clean_value else default


def _parse_extensions(value: Any) -> Tuple[str, ...]:
    if value is None:
        return DEFAULT_SYNC_EXTENSIONS
    if isinstance(value, str):
        raw_values = re.split(r"[,\n\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = []
    normalized = []
    for raw_value in raw_values:
        clean_value = str(raw_value).strip().lower()
        if not clean_value:
            continue
        extension = clean_value if clean_value.startswith(".") else f".{clean_value}"
        if extension not in normalized:
            normalized.append(extension)
    return tuple(normalized) if normalized else DEFAULT_SYNC_EXTENSIONS


def _parse_paths(
    value: Any,
    default: Tuple[Path, ...],
) -> Tuple[Path, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_values = value.splitlines()
    elif isinstance(value, (list, tuple, set)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = []
    paths = [
        Path(str(raw_value).strip()).expanduser()
        for raw_value in raw_values
        if str(raw_value).strip()
    ]
    return tuple(dict.fromkeys(paths)) if paths else default


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
