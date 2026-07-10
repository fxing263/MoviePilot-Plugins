import csv
import hashlib
import hmac
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from app.log import logger
from app.schemas import FileItem


PLUGIN_ID = "EmbyLibraryOrganizer"
STORAGE_115_NAME = "115网盘Plus"
STRM_SUFFIX = ".strm"
SIDECAR_SUFFIXES = {
    ".nfo",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tbn",
    ".srt",
    ".ass",
    ".ssa",
    ".vtt",
    ".sub",
}
TRASH_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "@eaDir",
}
TRASH_SUFFIXES = {
    ".tmp",
    ".part",
    ".download",
}
QUALITY_WEIGHTS = {
    "4320p": 600,
    "8k": 600,
    "2160p": 500,
    "4k": 500,
    "1080p": 400,
    "720p": 300,
    "remux": 80,
    "bluray": 70,
    "web-dl": 60,
    "webrip": 50,
}
VALID_DEDUPE_KEYS = {
    "file_id",
    "pickcode",
    "cloud_path",
    "media_key",
}
LOCAL_DELETE_MODES = {
    "quarantine",
    "delete",
}
KEEP_STRATEGIES = {
    "quality_then_naming",
    "preferred_path",
    "newest",
    "largest",
}
UNSAFE_TASK_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


class IssueLevel(str, Enum):
    """巡检问题级别。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DuplicateType(str, Enum):
    """重复类型。"""

    REFERENCE = "reference"
    MEDIA = "media"


class ActionType(str, Enum):
    """处理动作类型。"""

    DELETE_LOCAL_STRM = "delete_local_strm"
    DELETE_SIDECAR = "delete_sidecar"
    DELETE_EMPTY_DIR = "delete_empty_dir"
    DELETE_CLOUD_FILE = "delete_cloud_file"


class ActionStatus(str, Enum):
    """动作执行状态。"""

    PENDING = "pending"
    DRY_RUN = "dry_run"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class CloudVerifyStatus(str, Enum):
    """115云端文件校验状态。"""

    UNCHECKED = "unchecked"
    FOUND = "found"
    MISSING = "missing"
    MISMATCHED = "mismatched"
    FAILED = "failed"


@dataclass
class OrganizerConfig:
    """媒体库整理配置。"""

    library_paths: List[Path] = field(default_factory=list)
    library_types: Dict[str, str] = field(default_factory=dict)
    exclude_patterns: List[str] = field(default_factory=list)
    protected_local_paths: List[Path] = field(default_factory=list)
    protected_115_paths: List[str] = field(default_factory=list)
    preferred_library_paths: List[Path] = field(default_factory=list)
    custom_identity_patterns: List[str] = field(default_factory=list)
    max_depth: int = 20
    follow_symlinks: bool = False
    delete_duplicate_strm: bool = True
    clean_trash_files: bool = True
    delete_sidecar_files: bool = False
    delete_orphan_sidecar_files: bool = False
    delete_empty_dirs: bool = False
    check_nfo_files: bool = False
    check_image_files: bool = False
    sync_delete_115: bool = False
    dry_run: bool = True
    require_confirm: bool = True
    max_delete_count: int = 20
    local_delete_mode: str = "quarantine"
    dedupe_keys: List[str] = field(
        default_factory=lambda: ["file_id", "pickcode", "cloud_path", "media_key"]
    )
    keep_strategy: str = "quality_then_naming"


@dataclass
class StrmIdentity:
    """STRM 指向的115文件身份。"""

    original_url: str
    normalized_url: str = ""
    host: str = ""
    scheme: str = ""
    file_id: Optional[str] = None
    pickcode: Optional[str] = None
    cloud_path: Optional[str] = None
    is_url: bool = False
    is_115: bool = False
    parse_errors: List[str] = field(default_factory=list)

    def key_values(self) -> Dict[str, str]:
        """返回可用于去重的身份键值。"""
        values = {}
        if self.file_id:
            values["file_id"] = self.file_id
        if self.pickcode:
            values["pickcode"] = self.pickcode
        if self.cloud_path:
            values["cloud_path"] = self.cloud_path
        if self.normalized_url:
            values["normalized_url"] = self.normalized_url
        return values

    def primary_key(self) -> Optional[str]:
        """返回最稳定的115身份键。"""
        if self.file_id:
            return f"file_id:{self.file_id}"
        if self.pickcode:
            return f"pickcode:{self.pickcode}"
        if self.cloud_path:
            return f"cloud_path:{self.cloud_path}"
        if self.normalized_url:
            return f"url:{self.normalized_url}"
        return None


@dataclass
class LibraryFile:
    """媒体库中的文件记录。"""

    path: Path
    library_root: Path
    relative_path: str
    suffix: str
    size: int
    modify_time: float
    library_type: str = "mixed"
    content: Optional[str] = None
    identity: Optional[StrmIdentity] = None
    media_key: Optional[str] = None


@dataclass
class ScanIssue:
    """媒体库巡检问题。"""

    level: IssueLevel
    code: str
    path: str
    message: str
    suggestion: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DuplicateGroup:
    """重复媒体或重复引用分组。"""

    group_id: str
    duplicate_type: DuplicateType
    key: str
    keep_path: str
    candidate_paths: List[str]
    all_paths: List[str]
    reason: str
    risk: str
    score_details: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PlanAction:
    """待执行的整理动作。"""

    action_id: str
    action_type: ActionType
    path: str
    group_id: str = ""
    prerequisite_action_id: Optional[str] = None
    cloud_file_id: Optional[str] = None
    cloud_pickcode: Optional[str] = None
    cloud_path: Optional[str] = None
    cloud_verify_status: CloudVerifyStatus = CloudVerifyStatus.UNCHECKED
    source_size: Optional[int] = None
    source_modify_time: Optional[float] = None
    source_sha1: Optional[str] = None
    allowed: bool = True
    risk: str = "low"
    reason: str = ""
    skip_reason: str = ""


@dataclass
class OrganizerPlan:
    """媒体库整理计划。"""

    task_id: str
    created_at: str
    dry_run: bool
    require_confirm: bool
    issues: List[ScanIssue]
    duplicate_groups: List[DuplicateGroup]
    actions: List[PlanAction]
    summary: Dict[str, Any]


@dataclass
class ActionResult:
    """整理动作执行结果。"""

    action_id: str
    action_type: ActionType
    path: str
    status: ActionStatus
    message: str = ""
    backup_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReport:
    """整理计划执行报告。"""

    task_id: str
    started_at: str
    finished_at: str
    dry_run: bool
    confirmed: bool
    results: List[ActionResult]
    summary: Dict[str, Any]


@dataclass
class QuarantineItem:
    """隔离区文件记录。"""

    backup_path: str
    original_path: str
    size: int
    modify_time: float


@dataclass
class ScanResult:
    """媒体库扫描结果。"""

    started_at: str
    finished_at: str
    files: List[LibraryFile]
    issues: List[ScanIssue]
    summary: Dict[str, Any]


@dataclass
class ConfigValidationIssue:
    """配置校验问题。"""

    level: IssueLevel
    code: str
    message: str
    suggestion: str = ""


class StrmParser:
    """STRM 内容解析器。"""

    _file_id_patterns = (
        re.compile(r"(?:file_id|fileid|fid|cid|id)[=/:\-_]+(\d{3,})", re.I),
    )
    _pickcode_patterns = (
        re.compile(r"(?:pickcode|pick_code|pc)[=/:\-_]+([A-Za-z0-9]{6,})", re.I),
        re.compile(r"/(?:pickcode|pc)/([A-Za-z0-9]{6,})", re.I),
    )

    def __init__(self, custom_identity_patterns: Optional[List[str]] = None) -> None:
        """初始化 STRM 解析器。"""
        self._custom_patterns = [
            re.compile(pattern, re.I)
            for pattern in custom_identity_patterns or []
            if pattern
        ]

    def parse(self, content: str) -> StrmIdentity:
        """解析 STRM 内容中的 URL 与115身份。"""
        original_url = content.strip()
        identity = StrmIdentity(original_url=original_url)
        parsed = urlparse(original_url)
        identity.scheme = parsed.scheme
        identity.host = parsed.netloc.lower()
        identity.is_url = bool(parsed.scheme and parsed.netloc)
        if not identity.is_url:
            identity.parse_errors.append("STRM内容不是有效URL")
            return identity

        query = parse_qs(parsed.query)
        identity.file_id = self._first_query_value(
            query, ("file_id", "fileid", "fid", "cid", "id")
        )
        identity.pickcode = self._first_query_value(
            query, ("pickcode", "pick_code", "pc")
        )
        identity.cloud_path = self._first_query_value(
            query, ("path", "file_path", "filepath", "cloud_path")
        )
        if identity.cloud_path:
            identity.cloud_path = self._normalize_cloud_path(identity.cloud_path)

        searchable = unquote(original_url)
        if not identity.file_id:
            identity.file_id = self._search_patterns(searchable, self._file_id_patterns)
        if not identity.pickcode:
            identity.pickcode = self._search_patterns(searchable, self._pickcode_patterns)
        if not identity.cloud_path:
            identity.cloud_path = self._extract_path_hint(parsed)

        self._apply_custom_patterns(identity, searchable)
        identity.normalized_url = self._normalize_url(parsed)
        identity.is_115 = self._is_115_url(identity)
        if identity.is_115 and not identity.primary_key():
            identity.parse_errors.append("无法解析115文件身份")
        return identity

    @staticmethod
    def _first_query_value(query: Dict[str, List[str]], names: Iterable[str]) -> Optional[str]:
        """从 URL query 中取出第一个可用值。"""
        lowered = {key.lower(): value for key, value in query.items()}
        for name in names:
            value = lowered.get(name)
            if value and value[0]:
                return unquote(value[0]).strip()
        return None

    @staticmethod
    def _search_patterns(text: str, patterns: Iterable[re.Pattern]) -> Optional[str]:
        """使用正则表达式查找身份字段。"""
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _normalize_cloud_path(path: str) -> str:
        """规范化115云端路径。"""
        normalized = unquote(path).strip()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    @staticmethod
    def _extract_path_hint(parsed) -> Optional[str]:
        """从 URL 路径中提取可能的云端路径。"""
        path = unquote(parsed.path or "").strip()
        for marker in ("/file/", "/path/", "/115/"):
            if marker in path:
                candidate = path.split(marker, 1)[1]
                if candidate:
                    return StrmParser._normalize_cloud_path(candidate)
        return None

    def _apply_custom_patterns(self, identity: StrmIdentity, text: str) -> None:
        """应用用户自定义身份解析规则。"""
        for pattern in self._custom_patterns:
            match = pattern.search(text)
            if not match:
                continue
            group_dict = match.groupdict()
            identity.file_id = identity.file_id or group_dict.get("file_id")
            identity.pickcode = identity.pickcode or group_dict.get("pickcode")
            cloud_path = group_dict.get("cloud_path")
            if cloud_path and not identity.cloud_path:
                identity.cloud_path = self._normalize_cloud_path(cloud_path)

    @staticmethod
    def _normalize_url(parsed) -> str:
        """生成可稳定比较的 URL。"""
        query = parse_qs(parsed.query, keep_blank_values=False)
        ignored = {"token", "apikey", "sign", "ts", "t", "expires", "expire"}
        stable_query = {
            key: values[-1]
            for key, values in sorted(query.items())
            if key.lower() not in ignored and values
        }
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                unquote(parsed.path),
                "",
                urlencode(stable_query),
                "",
            )
        )

    @staticmethod
    def _is_115_url(identity: StrmIdentity) -> bool:
        """判断 URL 是否属于115 STRM场景。"""
        host = identity.host.lower()
        if "115" in host or "anxia" in host:
            return True
        if identity.file_id or identity.pickcode:
            return True
        if identity.cloud_path and "115" in identity.original_url.lower():
            return True
        return False


class MediaKeyResolver:
    """媒体文件归一化键解析器。"""

    _episode_pattern = re.compile(r"(?i)\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b")
    _season_dir_pattern = re.compile(r"(?i)^Season\s+(?P<season>\d{1,2})$")
    _loose_episode_pattern = re.compile(
        r"(?i)(?:^|[\s._\-\[\(第])(?P<episode>\d{1,3})(?:$|[\s._\-\]\)集话])"
    )
    _year_pattern = re.compile(r"(19\d{2}|20\d{2})")
    _tmdb_pattern = re.compile(r"(?i)(?:tmdbid|tmdb)[=._\-\s\{\[\(]*(?P<tmdbid>\d{2,})")
    _imdb_pattern = re.compile(r"(?i)(?:imdbid|imdb)[=._\-\s\{\[\(]*(?P<imdbid>tt\d{5,})")
    _tvdb_pattern = re.compile(r"(?i)(?:tvdbid|tvdb)[=._\-\s\{\[\(]*(?P<tvdbid>\d{2,})")

    def resolve(self, file_path: Path, library_root: Path, library_type: str = "mixed") -> Optional[str]:
        """根据媒体库类型解析电影或剧集键。"""
        relative = file_path.relative_to(library_root)
        parts = relative.parts
        stem = file_path.stem
        source_name = parts[0] if len(parts) > 1 else stem
        external_ids = self._extract_external_ids(" ".join(parts))
        external_key = self._external_key(external_ids)
        episode_match = self._episode_pattern.search(stem)
        if library_type in ("tv", "anime", "mixed") and episode_match:
            title = self._normalize_title(source_name)
            season = int(episode_match.group("season"))
            episode = int(episode_match.group("episode"))
            if external_key:
                return f"episode:{external_key}:s{season:02d}e{episode:03d}"
            return f"episode:{title}:s{season:02d}e{episode:03d}"

        loose_episode = self._resolve_loose_episode(parts, stem, library_type)
        if loose_episode:
            season, episode = loose_episode
            title = self._normalize_title(source_name)
            if external_key:
                return f"episode:{external_key}:s{season:02d}e{episode:03d}"
            return f"episode:{title}:s{season:02d}e{episode:03d}"

        if library_type in ("movie", "mixed"):
            title = self._normalize_title(source_name)
            year_match = self._year_pattern.search(source_name)
            year = year_match.group(1) if year_match else ""
            if external_key:
                return f"movie:{external_key}:{year}"
            return f"movie:{title}:{year}"
        return None

    @classmethod
    def parse(cls, media_key: Optional[str]) -> Dict[str, Any]:
        """解析媒体键为可查询结构。"""
        if not media_key:
            return {}
        parts = media_key.split(":")
        if len(parts) < 3:
            return {}
        if parts[0] == "movie":
            parsed = {
                "kind": "movie",
                "title": parts[1],
                "year": parts[2],
            }
            cls._apply_external_key(parsed, parts[1])
            if len(parts) >= 4:
                parsed["title"] = parts[3]
            return parsed
        if parts[0] == "episode" and len(parts) >= 3:
            season_match = re.match(r"s(\d{2})e(\d{3})", parts[2])
            if not season_match:
                return {}
            parsed = {
                "kind": "episode",
                "title": parts[1],
                "season": int(season_match.group(1)),
                "episode": int(season_match.group(2)),
            }
            cls._apply_external_key(parsed, parts[1])
            if len(parts) >= 4:
                parsed["title"] = parts[3]
            return parsed
        return {}

    @classmethod
    def _normalize_title(cls, value: str) -> str:
        """规范化媒体标题。"""
        title = Path(value).stem
        title = cls._tmdb_pattern.sub("", title)
        title = cls._imdb_pattern.sub("", title)
        title = cls._tvdb_pattern.sub("", title)
        title = cls._year_pattern.sub("", title)
        title = re.sub(r"(?i)\bS\d{1,2}E\d{1,3}\b", "", title)
        title = re.sub(r"[\[\]\(\)【】._\-]+", " ", title)
        title = re.sub(r"[\{\}]+", " ", title)
        return re.sub(r"\s+", " ", title).strip().lower()

    @classmethod
    def _extract_external_ids(cls, text: str) -> Dict[str, str]:
        """从路径文本中提取外部媒体库标识。"""
        values = {}
        tmdb_match = cls._tmdb_pattern.search(text)
        imdb_match = cls._imdb_pattern.search(text)
        tvdb_match = cls._tvdb_pattern.search(text)
        if tmdb_match:
            values["tmdbid"] = tmdb_match.group("tmdbid")
        if imdb_match:
            values["imdbid"] = imdb_match.group("imdbid")
        if tvdb_match:
            values["tvdbid"] = tvdb_match.group("tvdbid")
        return values

    @staticmethod
    def _external_key(external_ids: Dict[str, str]) -> str:
        """生成媒体键中的外部标识片段。"""
        if external_ids.get("tmdbid"):
            return f"tmdbid={external_ids['tmdbid']}"
        if external_ids.get("imdbid"):
            return f"imdbid={external_ids['imdbid']}"
        if external_ids.get("tvdbid"):
            return f"tvdbid={external_ids['tvdbid']}"
        return ""

    @staticmethod
    def _apply_external_key(parsed: Dict[str, Any], key: str) -> None:
        """将媒体键中的外部标识写入解析结果。"""
        if "=" not in key:
            return
        name, value = key.split("=", 1)
        if name in ("tmdbid", "imdbid", "tvdbid") and value:
            parsed[name] = value

    @classmethod
    def _resolve_loose_episode(
        cls,
        parts: Tuple[str, ...],
        stem: str,
        library_type: str,
    ) -> Optional[Tuple[int, int]]:
        """从季目录或简单集号中解析剧集键。"""
        if library_type not in ("tv", "anime", "mixed"):
            return None
        season = cls._season_from_parts(parts)
        episode = cls._loose_episode_number(stem)
        if season is not None and episode is not None:
            return season, episode
        if library_type in ("anime", "tv") and episode is not None:
            return 1, episode
        return None

    @classmethod
    def _season_from_parts(cls, parts: Tuple[str, ...]) -> Optional[int]:
        """从路径分段中解析季号。"""
        for part in parts:
            match = cls._season_dir_pattern.match(part)
            if match:
                return int(match.group("season"))
        return None

    @classmethod
    def _loose_episode_number(cls, stem: str) -> Optional[int]:
        """从文件名中解析宽松集号。"""
        cleaned = cls._year_pattern.sub("", stem)
        cleaned = cls._tmdb_pattern.sub("", cleaned)
        cleaned = cls._imdb_pattern.sub("", cleaned)
        cleaned = cls._tvdb_pattern.sub("", cleaned)
        matches = [
            int(match.group("episode"))
            for match in cls._loose_episode_pattern.finditer(cleaned)
        ]
        if not matches:
            return None
        return matches[-1]


class LibraryScanner:
    """Emby媒体库扫描器。"""

    def __init__(self, config: OrganizerConfig) -> None:
        """初始化媒体库扫描器。"""
        self.config = config
        self.parser = StrmParser(config.custom_identity_patterns)
        self.media_key_resolver = MediaKeyResolver()
        self._exclude_regex = [
            re.compile(pattern)
            for pattern in config.exclude_patterns
            if pattern
        ]

    def scan(self) -> ScanResult:
        """扫描所有配置的媒体库。"""
        started_at = self._now()
        files: List[LibraryFile] = []
        issues: List[ScanIssue] = []
        directory_paths: Set[Path] = set()
        directories_with_files: Set[Path] = set()

        for library_root in self.config.library_paths:
            root = library_root.expanduser().resolve()
            if not root.exists():
                issues.append(
                    ScanIssue(
                        level=IssueLevel.ERROR,
                        code="library_not_found",
                        path=root.as_posix(),
                        message="媒体库路径不存在",
                        suggestion="请检查插件配置中的媒体库路径",
                    )
                )
                continue
            if not root.is_dir():
                issues.append(
                    ScanIssue(
                        level=IssueLevel.ERROR,
                        code="library_not_directory",
                        path=root.as_posix(),
                        message="媒体库路径不是目录",
                    )
                )
                continue
            library_type = self.config.library_types.get(root.as_posix(), "mixed")
            for item_path in self._walk(root):
                if self._is_excluded(item_path):
                    continue
                try:
                    if item_path.is_dir():
                        directory_paths.add(item_path)
                        continue
                    directories_with_files.add(item_path.parent)
                    file_record = self._build_file_record(item_path, root, library_type)
                    files.append(file_record)
                    self._inspect_file(file_record, issues)
                except OSError as err:
                    issues.append(
                        ScanIssue(
                            level=IssueLevel.WARNING,
                            code="file_read_failed",
                            path=item_path.as_posix(),
                            message=f"文件读取失败：{str(err)}",
                        )
                    )

        self._inspect_empty_dirs(directory_paths, directories_with_files, issues)
        self._inspect_orphan_sidecars(files, issues)
        finished_at = self._now()
        return ScanResult(
            started_at=started_at,
            finished_at=finished_at,
            files=files,
            issues=issues,
            summary=self._build_scan_summary(files, issues),
        )

    def _walk(self, root: Path) -> Iterable[Path]:
        """按最大深度遍历媒体库目录。"""
        root_resolved = root.resolve()
        stack = [root]
        visited_directories = {root_resolved}
        while stack:
            current = stack.pop()
            try:
                children = sorted(current.iterdir(), key=lambda path: path.name.lower())
            except OSError as err:
                logger.warning(f"【{PLUGIN_ID}】读取目录失败：{current} - {str(err)}")
                continue
            for child in children:
                try:
                    if child.is_symlink():
                        if not self.config.follow_symlinks:
                            continue
                        resolved_child = child.resolve(strict=True)
                        try:
                            resolved_child.relative_to(root_resolved)
                        except ValueError:
                            logger.warning(
                                f"【{PLUGIN_ID}】符号链接目标超出媒体库，已跳过：{child}"
                            )
                            continue
                    else:
                        resolved_child = child.resolve()
                except OSError as err:
                    logger.warning(
                        f"【{PLUGIN_ID}】解析媒体库路径失败：{child} - {str(err)}"
                    )
                    continue
                if self._depth(root, child) > self.config.max_depth:
                    continue
                yield child
                if child.is_dir():
                    if resolved_child in visited_directories:
                        continue
                    visited_directories.add(resolved_child)
                    stack.append(child)

    @staticmethod
    def _depth(root: Path, path: Path) -> int:
        """计算路径相对媒体库根目录的深度。"""
        try:
            return len(path.relative_to(root).parts)
        except ValueError:
            return 0

    def _is_excluded(self, path: Path) -> bool:
        """判断路径是否命中排除规则。"""
        path_text = path.as_posix()
        return any(pattern.search(path_text) for pattern in self._exclude_regex)

    def _build_file_record(self, path: Path, root: Path, library_type: str) -> LibraryFile:
        """构造媒体库文件记录。"""
        suffix = path.suffix.lower()
        stat = path.stat()
        content = None
        identity = None
        media_key = None
        if suffix == STRM_SUFFIX:
            content = self._read_strm(path)
            identity = self.parser.parse(content) if content.strip() else None
            media_key = self.media_key_resolver.resolve(path, root, library_type)
        return LibraryFile(
            path=path,
            library_root=root,
            relative_path=path.relative_to(root).as_posix(),
            suffix=suffix,
            size=stat.st_size,
            modify_time=stat.st_mtime,
            library_type=library_type,
            content=content,
            identity=identity,
            media_key=media_key,
        )

    @staticmethod
    def _read_strm(path: Path) -> str:
        """读取 STRM 文件内容。"""
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    def _inspect_file(self, file_record: LibraryFile, issues: List[ScanIssue]) -> None:
        """检查单个文件的基础问题。"""
        path = file_record.path
        if path.name in TRASH_FILE_NAMES or file_record.suffix in TRASH_SUFFIXES:
            issues.append(
                ScanIssue(
                    level=IssueLevel.INFO,
                    code="trash_file",
                    path=path.as_posix(),
                    message="发现常见临时或垃圾文件",
                    suggestion="确认无用后可清理",
                )
            )
        if file_record.suffix != STRM_SUFFIX:
            return
        content = file_record.content or ""
        if not content:
            issues.append(
                ScanIssue(
                    level=IssueLevel.ERROR,
                    code="empty_strm",
                    path=path.as_posix(),
                    message="STRM文件为空",
                    suggestion="重新生成该STRM或删除无效文件",
                )
            )
            return
        if len([line for line in content.splitlines() if line.strip()]) > 1:
            issues.append(
                ScanIssue(
                    level=IssueLevel.WARNING,
                    code="multiline_strm",
                    path=path.as_posix(),
                    message="STRM文件包含多行内容",
                    suggestion="确认播放器实际读取的URL是否正确",
                )
            )
        identity = file_record.identity
        if not identity or not identity.is_url:
            issues.append(
                ScanIssue(
                    level=IssueLevel.ERROR,
                    code="invalid_strm_url",
                    path=path.as_posix(),
                    message="STRM内容不是有效URL",
                )
            )
            return
        if not identity.is_115:
            issues.append(
                ScanIssue(
                    level=IssueLevel.WARNING,
                    code="non_115_strm",
                    path=path.as_posix(),
                    message="STRM链接不是115场景链接",
                    suggestion="确认该文件是否属于本插件管理范围",
                )
            )
        for error in identity.parse_errors:
            issues.append(
                ScanIssue(
                    level=IssueLevel.WARNING,
                    code="strm_identity_unresolved",
                    path=path.as_posix(),
                    message=error,
                    suggestion="在配置中补充自定义解析规则，或重新生成STRM",
                )
            )
        self._inspect_media_naming(file_record, issues)
        self._inspect_metadata_files(file_record, issues)

    @staticmethod
    def _inspect_media_naming(
        file_record: LibraryFile,
        issues: List[ScanIssue],
    ) -> None:
        """检查基础媒体命名结构。"""
        path = file_record.path
        path_text = path.as_posix()
        stem = path.stem
        relative_parts = Path(file_record.relative_path).parts
        has_episode_token = bool(re.search(r"(?i)\bS\d{1,2}E\d{1,3}\b", stem))
        has_season_dir = any(re.search(r"(?i)^Season\s+\d{1,2}$", part) for part in path.parts)
        if len(relative_parts) == 1:
            issues.append(
                ScanIssue(
                    level=IssueLevel.INFO,
                    code="root_strm_file",
                    path=path.as_posix(),
                    message="STRM文件位于媒体库根目录",
                    suggestion="建议按电影或剧集目录结构归档后再让Emby识别",
                )
            )
        if has_season_dir and not has_episode_token:
            issues.append(
                ScanIssue(
                    level=IssueLevel.WARNING,
                    code="episode_number_missing",
                    path=path.as_posix(),
                    message="剧集STRM位于季目录但文件名缺少SxxExx",
                    suggestion="按 S01E01 这类格式重命名后再让Emby识别",
                )
            )
        if file_record.library_type in ("movie", "mixed") and not has_episode_token:
            source_name = relative_parts[0] if len(relative_parts) > 1 else stem
            if not re.search(r"(19\d{2}|20\d{2})", source_name):
                issues.append(
                    ScanIssue(
                        level=IssueLevel.INFO,
                        code="movie_year_missing",
                        path=path.as_posix(),
                        message="电影STRM路径缺少年份",
                        suggestion="建议使用 片名 (年份) 的目录或文件命名",
                    )
                )
        years = re.findall(r"(19\d{2}|20\d{2})", path_text)
        if len(set(years)) > 1:
            issues.append(
                ScanIssue(
                    level=IssueLevel.WARNING,
                    code="year_mismatch",
                    path=path.as_posix(),
                    message="路径中出现多个不同年份，可能影响Emby识别",
                    suggestion="确认目录名和文件名年份一致",
                    details={"years": sorted(set(years))},
                )
            )

    def _inspect_metadata_files(
        self,
        file_record: LibraryFile,
        issues: List[ScanIssue],
    ) -> None:
        """检查 STRM 对应的 NFO 和图片文件。"""
        path = file_record.path
        if self.config.check_nfo_files and not path.with_suffix(".nfo").exists():
            issues.append(
                ScanIssue(
                    level=IssueLevel.INFO,
                    code="missing_nfo",
                    path=path.as_posix(),
                    message="STRM缺少同名NFO文件",
                    suggestion="确认是否需要重新刮削或生成NFO",
                )
            )
        if self.config.check_image_files and not self._has_related_image(path):
            issues.append(
                ScanIssue(
                    level=IssueLevel.INFO,
                    code="missing_image",
                    path=path.as_posix(),
                    message="STRM缺少同名图片或目录级封面",
                    suggestion="确认是否需要重新生成封面图",
                )
            )

    @staticmethod
    def _has_related_image(path: Path) -> bool:
        """判断 STRM 是否存在相关图片。"""
        image_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
        if any(path.with_suffix(suffix).exists() for suffix in image_suffixes):
            return True
        directory_image_names = {
            "poster",
            "fanart",
            "thumb",
            "folder",
            "cover",
        }
        return any(
            (path.parent / f"{name}{suffix}").exists()
            for name in directory_image_names
            for suffix in image_suffixes
        )

    @staticmethod
    def _inspect_empty_dirs(
        directory_paths: Set[Path],
        directories_with_files: Set[Path],
        issues: List[ScanIssue],
    ) -> None:
        """检查空目录。"""
        for directory in sorted(directory_paths):
            if directory not in directories_with_files and not any(directory.iterdir()):
                issues.append(
                    ScanIssue(
                        level=IssueLevel.INFO,
                        code="empty_directory",
                        path=directory.as_posix(),
                        message="发现空目录",
                        suggestion="确认不再使用后可清理",
                    )
                )

    @staticmethod
    def _inspect_orphan_sidecars(files: List[LibraryFile], issues: List[ScanIssue]) -> None:
        """检查没有对应 STRM 的伴随文件。"""
        strm_stems = {
            file.path.with_suffix("").as_posix()
            for file in files
            if file.suffix == STRM_SUFFIX
        }
        for file in files:
            if file.suffix not in SIDECAR_SUFFIXES:
                continue
            if file.path.with_suffix("").as_posix() not in strm_stems:
                issues.append(
                    ScanIssue(
                        level=IssueLevel.INFO,
                        code="orphan_sidecar",
                        path=file.path.as_posix(),
                        message="发现没有对应STRM的伴随文件",
                        suggestion="确认不再使用后可随重复项清理",
                    )
                )

    @staticmethod
    def _build_scan_summary(files: List[LibraryFile], issues: List[ScanIssue]) -> Dict[str, Any]:
        """生成扫描摘要。"""
        strm_count = len([file for file in files if file.suffix == STRM_SUFFIX])
        issue_code_counts: Dict[str, int] = {}
        issue_level_counts: Dict[str, int] = {}
        for issue in issues:
            issue_code_counts[issue.code] = issue_code_counts.get(issue.code, 0) + 1
            issue_level_counts[issue.level.value] = issue_level_counts.get(issue.level.value, 0) + 1
        return {
            "file_count": len(files),
            "strm_count": strm_count,
            "issue_count": len(issues),
            "error_count": len([issue for issue in issues if issue.level == IssueLevel.ERROR]),
            "warning_count": len([issue for issue in issues if issue.level == IssueLevel.WARNING]),
            "issue_code_counts": issue_code_counts,
            "issue_level_counts": issue_level_counts,
        }

    @staticmethod
    def _now() -> str:
        """返回当前时间字符串。"""
        return datetime.now().isoformat(timespec="seconds")


class DuplicateAnalyzer:
    """重复媒体分析器。"""

    def __init__(self, config: OrganizerConfig) -> None:
        """初始化重复媒体分析器。"""
        self.config = config

    def analyze(self, files: List[LibraryFile]) -> List[DuplicateGroup]:
        """分析重复引用与重复媒体。"""
        strm_files = [file for file in files if file.suffix == STRM_SUFFIX and file.identity]
        groups: List[DuplicateGroup] = []
        groups.extend(self._analyze_reference_duplicates(strm_files))
        groups.extend(self._analyze_media_duplicates(strm_files))
        return groups

    def choose_keep_file(self, files: List[LibraryFile]) -> LibraryFile:
        """根据保留策略选择应保留的文件。"""
        return max(files, key=self._score_file)

    def _analyze_reference_duplicates(self, files: List[LibraryFile]) -> List[DuplicateGroup]:
        """分析多个 STRM 指向同一115身份的情况。"""
        buckets: Dict[str, List[LibraryFile]] = {}
        for file in files:
            for key_name, key_value in self._reference_keys(file):
                buckets.setdefault(f"{key_name}:{key_value}", []).append(file)
        duplicate_groups = []
        for index, (key, bucket) in enumerate(sorted(buckets.items()), start=1):
            if len(bucket) < 2:
                continue
            unique_paths = {file.path.as_posix() for file in bucket}
            if len(unique_paths) < 2:
                continue
            keep_file = self.choose_keep_file(bucket)
            candidates = [file for file in bucket if file.path != keep_file.path]
            duplicate_groups.append(
                DuplicateGroup(
                    group_id=f"reference-{index}",
                    duplicate_type=DuplicateType.REFERENCE,
                    key=key,
                    keep_path=keep_file.path.as_posix(),
                    candidate_paths=[file.path.as_posix() for file in candidates],
                    all_paths=[file.path.as_posix() for file in bucket],
                    reason="多个STRM指向同一个115文件，建议只保留一个本地入口",
                    risk="low",
                    score_details=self._score_details(bucket, keep_file),
                )
            )
        return duplicate_groups

    def _reference_keys(self, file: LibraryFile) -> List[Tuple[str, str]]:
        """返回按配置启用的引用重复键。"""
        if not file.identity:
            return []
        identity_values = file.identity.key_values()
        keys = []
        for key_name in self.config.dedupe_keys:
            if key_name == "media_key":
                continue
            key_value = identity_values.get(key_name)
            if key_value:
                keys.append((key_name, key_value))
        if not keys and file.identity.primary_key():
            keys.append(("primary", file.identity.primary_key() or ""))
        return keys

    def _analyze_media_duplicates(self, files: List[LibraryFile]) -> List[DuplicateGroup]:
        """分析多个115文件对应同一媒体内容的情况。"""
        if "media_key" not in self.config.dedupe_keys:
            return []
        buckets: Dict[str, List[LibraryFile]] = {}
        for file in files:
            if not file.media_key:
                continue
            buckets.setdefault(file.media_key, []).append(file)
        duplicate_groups = []
        for index, (key, bucket) in enumerate(sorted(buckets.items()), start=1):
            identity_keys = {
                file.identity.primary_key()
                for file in bucket
                if file.identity and file.identity.primary_key()
            }
            if len(bucket) < 2 or len(identity_keys) < 2:
                continue
            keep_file = self.choose_keep_file(bucket)
            candidates = [file for file in bucket if file.path != keep_file.path]
            duplicate_groups.append(
                DuplicateGroup(
                    group_id=f"media-{index}",
                    duplicate_type=DuplicateType.MEDIA,
                    key=key,
                    keep_path=keep_file.path.as_posix(),
                    candidate_paths=[file.path.as_posix() for file in candidates],
                    all_paths=[file.path.as_posix() for file in bucket],
                    reason="多个不同115文件疑似对应同一媒体内容，可按策略保留最佳版本",
                    risk="high",
                    score_details=self._score_details(bucket, keep_file),
                )
            )
        return duplicate_groups

    def _score_file(self, file: LibraryFile) -> Tuple[int, float, int, str]:
        """计算保留候选文件评分。"""
        detail = self._score_detail(file)
        return self._score_sort_key(detail)

    def _score_detail(self, file: LibraryFile) -> Dict[str, Any]:
        """计算保留候选文件评分明细。"""
        path_text = file.path.as_posix().lower()
        preferred_score = self._preferred_path_score(file.path)
        naming_score = self._naming_score(file)
        quality_score = sum(
            weight for token, weight in QUALITY_WEIGHTS.items() if token in path_text
        )
        sidecar_score = self._sidecar_score(file.path)
        total = preferred_score + naming_score + quality_score + sidecar_score
        return {
            "path": file.path.as_posix(),
            "total": total,
            "preferred_path": preferred_score,
            "naming": naming_score,
            "quality": quality_score,
            "sidecar": sidecar_score,
            "modify_time": file.modify_time,
            "size": file.size,
        }

    def _score_details(
        self,
        files: List[LibraryFile],
        keep_file: LibraryFile,
    ) -> List[Dict[str, Any]]:
        """生成重复组评分明细。"""
        details = [self._score_detail(file) for file in files]
        details.sort(
            key=lambda item: self._score_sort_key(item),
            reverse=True,
        )
        for index, item in enumerate(details, start=1):
            item["rank"] = index
            item["keep"] = item["path"] == keep_file.path.as_posix()
        return details

    def _score_sort_key(self, detail: Dict[str, Any]) -> Tuple[Any, ...]:
        """按保留策略生成排序键。"""
        strategy = self.config.keep_strategy
        if strategy == "preferred_path":
            return (
                int(detail["preferred_path"]),
                int(detail["quality"]),
                int(detail["naming"]),
                int(detail["sidecar"]),
                float(detail["modify_time"]),
                int(detail["size"]),
                str(detail["path"]),
            )
        if strategy == "newest":
            return (
                float(detail["modify_time"]),
                int(detail["quality"]),
                int(detail["naming"]),
                int(detail["sidecar"]),
                int(detail["size"]),
                str(detail["path"]),
            )
        if strategy == "largest":
            return (
                int(detail["size"]),
                int(detail["quality"]),
                int(detail["naming"]),
                int(detail["sidecar"]),
                float(detail["modify_time"]),
                str(detail["path"]),
            )
        return (
            int(detail["total"]),
            float(detail["modify_time"]),
            int(detail["size"]),
            str(detail["path"]),
        )

    def _preferred_path_score(self, path: Path) -> int:
        """计算路径优先级得分。"""
        for index, preferred_path in enumerate(self.config.preferred_library_paths):
            try:
                path.resolve().relative_to(preferred_path.expanduser().resolve())
                return 1000 - index
            except ValueError:
                continue
        return 0

    @staticmethod
    def _naming_score(file: LibraryFile) -> int:
        """计算命名规范得分。"""
        score = 0
        stem = file.path.stem
        if re.search(r"(?i)\bS\d{1,2}E\d{1,3}\b", stem):
            score += 120
        if re.search(r"(19\d{2}|20\d{2})", file.path.as_posix()):
            score += 80
        if file.media_key:
            score += 100
        return score

    @staticmethod
    def _sidecar_score(path: Path) -> int:
        """计算伴随元数据完整度得分。"""
        score = 0
        for suffix in SIDECAR_SUFFIXES:
            if path.with_suffix(suffix).exists():
                score += 10
        return score


class PlanBuilder:
    """整理计划生成器。"""

    def __init__(self, config: OrganizerConfig) -> None:
        """初始化整理计划生成器。"""
        self.config = config

    def build(self, scan_result: ScanResult, duplicate_groups: List[DuplicateGroup]) -> OrganizerPlan:
        """根据扫描结果和重复分组生成整理计划。"""
        task_id = datetime.now().strftime("%Y%m%d%H%M%S")
        file_map = {file.path.as_posix(): file for file in scan_result.files}
        actions: List[PlanAction] = []
        cloud_reference_counts = self._build_cloud_reference_counts(scan_result.files)

        for group in duplicate_groups:
            for candidate_path in group.candidate_paths:
                candidate_file = file_map.get(candidate_path)
                if not candidate_file:
                    continue
                local_action = None
                if self.config.delete_duplicate_strm:
                    local_action = self._build_local_strm_action(
                        task_id,
                        group,
                        candidate_file,
                    )
                    actions.append(local_action)
                if self.config.delete_sidecar_files:
                    actions.extend(
                        self._build_sidecar_actions(task_id, group, candidate_file)
                    )
                if self.config.sync_delete_115:
                    actions.append(
                        self._build_cloud_delete_action(
                            task_id,
                            group,
                            candidate_file,
                            cloud_reference_counts,
                            prerequisite_action_id=(
                                local_action.action_id if local_action else None
                            ),
                        )
                    )
                if self.config.delete_empty_dirs:
                    actions.append(
                        self._build_empty_dir_action(task_id, group, candidate_file)
                    )
        actions.extend(
            self._build_issue_actions(task_id, scan_result.issues, file_map)
        )
        actions = self._limit_actions(
            self._apply_local_protection(self._deduplicate_actions(actions))
        )
        return OrganizerPlan(
            task_id=task_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            dry_run=self.config.dry_run,
            require_confirm=self.config.require_confirm,
            issues=scan_result.issues,
            duplicate_groups=duplicate_groups,
            actions=actions,
            summary=self._build_plan_summary(scan_result, duplicate_groups, actions),
        )

    def rebuild_group_actions(
        self,
        task_id: str,
        group: DuplicateGroup,
        files: List[LibraryFile],
    ) -> List[PlanAction]:
        """按当前重复分组候选项重新生成整理动作。"""
        file_map = {file.path.as_posix(): file for file in files}
        reference_counts = self._build_cloud_reference_counts(files)
        actions = []
        for candidate_path in group.candidate_paths:
            candidate_file = file_map.get(candidate_path)
            if not candidate_file:
                continue
            local_action = None
            if self.config.delete_duplicate_strm:
                local_action = self._build_local_strm_action(
                    task_id,
                    group,
                    candidate_file,
                )
                actions.append(local_action)
            if self.config.delete_sidecar_files:
                actions.extend(
                    self._build_sidecar_actions(task_id, group, candidate_file)
                )
            if self.config.sync_delete_115:
                actions.append(
                    self._build_cloud_delete_action(
                        task_id,
                        group,
                        candidate_file,
                        reference_counts,
                        prerequisite_action_id=(
                            local_action.action_id if local_action else None
                        ),
                    )
                )
            if self.config.delete_empty_dirs:
                actions.append(
                    self._build_empty_dir_action(task_id, group, candidate_file)
                )
        return self._limit_actions(
            self._apply_local_protection(self._deduplicate_actions(actions))
        )

    def _build_local_strm_action(
        self,
        task_id: str,
        group: DuplicateGroup,
        file: LibraryFile,
    ) -> PlanAction:
        """生成本地 STRM 删除动作。"""
        return PlanAction(
            action_id=self._action_id(task_id, "local", file.path.as_posix()),
            action_type=ActionType.DELETE_LOCAL_STRM,
            path=file.path.as_posix(),
            group_id=group.group_id,
            source_size=file.size,
            source_modify_time=file.modify_time,
            source_sha1=self._file_sha1(file.path),
            allowed=True,
            risk="medium" if group.duplicate_type == DuplicateType.MEDIA else "low",
            reason=group.reason,
        )

    def _build_sidecar_actions(
        self,
        task_id: str,
        group: DuplicateGroup,
        file: LibraryFile,
    ) -> List[PlanAction]:
        """生成伴随文件清理动作。"""
        actions = []
        for suffix in SIDECAR_SUFFIXES:
            sidecar_path = file.path.with_suffix(suffix)
            if not sidecar_path.exists():
                continue
            sidecar_stat = sidecar_path.stat()
            actions.append(
                PlanAction(
                    action_id=self._action_id(task_id, "sidecar", sidecar_path.as_posix()),
                    action_type=ActionType.DELETE_SIDECAR,
                    path=sidecar_path.as_posix(),
                    group_id=group.group_id,
                    source_size=sidecar_stat.st_size,
                    source_modify_time=sidecar_stat.st_mtime,
                    source_sha1=self._file_sha1(sidecar_path),
                    allowed=True,
                    risk="medium",
                    reason="重复STRM的伴随文件可随本地入口清理",
                )
            )
        return actions

    def _build_empty_dir_action(
        self,
        task_id: str,
        group: DuplicateGroup,
        file: LibraryFile,
    ) -> PlanAction:
        """生成空目录清理动作。"""
        parent_path = file.path.parent
        return PlanAction(
            action_id=self._action_id(task_id, "empty-dir", parent_path.as_posix()),
            action_type=ActionType.DELETE_EMPTY_DIR,
            path=parent_path.as_posix(),
            group_id=group.group_id,
            allowed=True,
            risk="medium",
            reason="重复STRM删除后可尝试清理空目录",
        )

    def _build_issue_actions(
        self,
        task_id: str,
        issues: List[ScanIssue],
        file_map: Dict[str, LibraryFile],
    ) -> List[PlanAction]:
        """根据巡检问题生成可选整理动作。"""
        actions = []
        for issue in issues:
            source_file = file_map.get(issue.path)
            source_size = source_file.size if source_file else None
            source_modify_time = source_file.modify_time if source_file else None
            source_sha1 = (
                self._file_sha1(source_file.path) if source_file else None
            )
            if issue.code == "trash_file" and self.config.clean_trash_files:
                actions.append(
                    PlanAction(
                        action_id=self._action_id(task_id, "trash", issue.path),
                        action_type=ActionType.DELETE_SIDECAR,
                        path=issue.path,
                        source_size=source_size,
                        source_modify_time=source_modify_time,
                        source_sha1=source_sha1,
                        allowed=True,
                        risk="low",
                        reason="常见临时或垃圾文件可清理",
                    )
                )
            elif (
                issue.code == "orphan_sidecar"
                and self.config.delete_orphan_sidecar_files
            ):
                actions.append(
                    PlanAction(
                        action_id=self._action_id(task_id, "orphan-sidecar", issue.path),
                        action_type=ActionType.DELETE_SIDECAR,
                        path=issue.path,
                        source_size=source_size,
                        source_modify_time=source_modify_time,
                        source_sha1=source_sha1,
                        allowed=True,
                        risk="medium",
                        reason="没有对应STRM的伴随文件可清理",
                    )
                )
            elif issue.code == "empty_directory" and self.config.delete_empty_dirs:
                actions.append(
                    PlanAction(
                        action_id=self._action_id(task_id, "empty-dir", issue.path),
                        action_type=ActionType.DELETE_EMPTY_DIR,
                        path=issue.path,
                        allowed=True,
                        risk="low",
                        reason="空目录可清理",
                    )
                )
        return actions

    def _build_cloud_delete_action(
        self,
        task_id: str,
        group: DuplicateGroup,
        file: LibraryFile,
        reference_counts: Dict[str, int],
        prerequisite_action_id: Optional[str],
    ) -> PlanAction:
        """生成115云端删除动作。"""
        identity = file.identity
        skip_reason = self._cloud_delete_skip_reason(
            group,
            file,
            reference_counts,
            prerequisite_action_id,
        )
        return PlanAction(
            action_id=self._action_id(task_id, "cloud", file.path.as_posix()),
            action_type=ActionType.DELETE_CLOUD_FILE,
            path=file.path.as_posix(),
            group_id=group.group_id,
            prerequisite_action_id=prerequisite_action_id,
            cloud_file_id=identity.file_id if identity else None,
            cloud_pickcode=identity.pickcode if identity else None,
            cloud_path=identity.cloud_path if identity else None,
            allowed=not skip_reason,
            source_size=file.size,
            source_modify_time=file.modify_time,
            source_sha1=self._file_sha1(file.path),
            risk="high",
            reason="媒体重复候选项对应的115文件可移入回收站",
            skip_reason=skip_reason,
        )

    @staticmethod
    def _file_sha1(path: Path) -> Optional[str]:
        """计算计划动作源文件哈希。"""
        try:
            if not path.is_file():
                return None
            digest = hashlib.sha1()
            with path.open("rb") as file_obj:
                for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    def _cloud_delete_skip_reason(
        self,
        group: DuplicateGroup,
        file: LibraryFile,
        reference_counts: Dict[str, int],
        prerequisite_action_id: Optional[str],
    ) -> str:
        """返回云端删除保护原因。"""
        identity = file.identity
        if group.duplicate_type != DuplicateType.MEDIA:
            return "引用重复仍有保留STRM依赖同一115文件，禁止删除云端文件"
        if not prerequisite_action_id:
            return "未启用本地重复STRM清理，禁止删除云端文件"
        if not identity:
            return "无法解析115身份，禁止删除云端文件"
        if not identity.file_id:
            return "缺少115 file_id，无法安全调用回收站删除"
        if not identity.cloud_path:
            return "缺少115云端路径，无法执行删除前校验"
        primary_key = identity.primary_key()
        if primary_key and reference_counts.get(primary_key, 0) > 1:
            return "该115文件仍被多个STRM引用，禁止删除云端文件"
        if self._is_protected_cloud_path(identity.cloud_path):
            return "云端路径命中保护规则，禁止删除云端文件"
        return ""

    def _is_protected_cloud_path(self, cloud_path: Optional[str]) -> bool:
        """判断云端路径是否受保护。"""
        if not cloud_path:
            return False
        normalized = cloud_path.rstrip("/")
        for protected_path in self.config.protected_115_paths:
            protected = protected_path.rstrip("/")
            if protected and normalized.startswith(protected):
                return True
        return False

    @staticmethod
    def _build_cloud_reference_counts(files: List[LibraryFile]) -> Dict[str, int]:
        """统计115身份引用次数。"""
        counts: Dict[str, int] = {}
        for file in files:
            if not file.identity:
                continue
            primary_key = file.identity.primary_key()
            if not primary_key:
                continue
            counts[primary_key] = counts.get(primary_key, 0) + 1
        return counts

    def _limit_actions(self, actions: List[PlanAction]) -> List[PlanAction]:
        """按照单次最大删除数量限制动作。"""
        delete_actions = [
            action
            for action in actions
            if action.allowed
            and action.action_type
            in {
                ActionType.DELETE_LOCAL_STRM,
                ActionType.DELETE_SIDECAR,
                ActionType.DELETE_CLOUD_FILE,
            }
        ]
        if len(delete_actions) <= self.config.max_delete_count:
            return actions
        allowed_count = 0
        limited = []
        for action in actions:
            if action.allowed and allowed_count >= self.config.max_delete_count:
                action.allowed = False
                action.skip_reason = "超过单次最大处理数量限制"
            if action.allowed and action.action_type in {
                ActionType.DELETE_LOCAL_STRM,
                ActionType.DELETE_SIDECAR,
                ActionType.DELETE_CLOUD_FILE,
            }:
                allowed_count += 1
            limited.append(action)
        return limited

    def _apply_local_protection(self, actions: List[PlanAction]) -> List[PlanAction]:
        """在计划阶段阻断命中本地保护路径的动作。"""
        for action in actions:
            if action.action_type not in {
                ActionType.DELETE_LOCAL_STRM,
                ActionType.DELETE_SIDECAR,
                ActionType.DELETE_EMPTY_DIR,
            }:
                continue
            if self._is_protected_local_path(Path(action.path)):
                action.allowed = False
                action.skip_reason = "本地路径命中保护规则，禁止删除或隔离"
        return actions

    def _is_protected_local_path(self, path: Path) -> bool:
        """判断路径是否命中本地保护规则。"""
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser().absolute()
        for protected_path in self.config.protected_local_paths:
            try:
                protected = protected_path.expanduser().resolve()
            except OSError:
                protected = protected_path.expanduser().absolute()
            try:
                resolved.relative_to(protected)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _deduplicate_actions(actions: List[PlanAction]) -> List[PlanAction]:
        """按动作ID去重，避免重复处理同一路径。"""
        deduped = []
        seen = set()
        for action in actions:
            if action.action_id in seen:
                continue
            seen.add(action.action_id)
            deduped.append(action)
        return deduped

    @staticmethod
    def _action_id(task_id: str, action_name: str, path: str) -> str:
        """生成稳定的动作ID。"""
        digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
        return f"{task_id}-{action_name}-{digest}"

    @staticmethod
    def _build_plan_summary(
        scan_result: ScanResult,
        duplicate_groups: List[DuplicateGroup],
        actions: List[PlanAction],
    ) -> Dict[str, Any]:
        """生成整理计划摘要。"""
        media_key_items = PlanBuilder._build_media_key_summary(scan_result.files)
        return {
            **scan_result.summary,
            "duplicate_group_count": len(duplicate_groups),
            "reference_duplicate_count": len(
                [group for group in duplicate_groups if group.duplicate_type == DuplicateType.REFERENCE]
            ),
            "media_duplicate_count": len(
                [group for group in duplicate_groups if group.duplicate_type == DuplicateType.MEDIA]
            ),
            "action_count": len(actions),
            "allowed_action_count": len([action for action in actions if action.allowed]),
            "blocked_action_count": len([action for action in actions if not action.allowed]),
            "high_risk_action_count": len([action for action in actions if action.risk == "high"]),
            "cloud_delete_count": len(
                [action for action in actions if action.action_type == ActionType.DELETE_CLOUD_FILE]
            ),
            "media_key_count": len(media_key_items),
            "media_keys": media_key_items,
        }

    @staticmethod
    def _build_media_key_summary(files: List[LibraryFile]) -> List[Dict[str, Any]]:
        """生成扫描媒体键摘要。"""
        media_key_paths: Dict[str, List[str]] = {}
        for file in files:
            if file.suffix != STRM_SUFFIX or not file.media_key:
                continue
            media_key_paths.setdefault(file.media_key, []).append(file.path.as_posix())
        return [
            {
                "media_key": media_key,
                "path_count": len(paths),
                "paths": sorted(paths),
            }
            for media_key, paths in sorted(media_key_paths.items())
        ]


class PlanExecutor:
    """整理计划执行器。"""

    def __init__(
        self,
        config: OrganizerConfig,
        data_path: Path,
        cloud_delete_func: Optional[Callable[[FileItem], bool]] = None,
        cloud_verify_func: Optional[Callable[[str, Path], Optional[FileItem]]] = None,
    ) -> None:
        """初始化整理计划执行器。"""
        self.config = config
        self.data_path = data_path.expanduser().resolve()
        self.cloud_delete_func = cloud_delete_func
        self.cloud_verify_func = cloud_verify_func

    def execute(
        self,
        plan: OrganizerPlan,
        confirmed: bool = False,
        confirm_token: Optional[str] = None,
        expected_confirm_token: Optional[str] = None,
    ) -> ExecutionReport:
        """执行整理计划。"""
        started_at = datetime.now().isoformat(timespec="seconds")
        results = []
        if plan.require_confirm and not confirmed:
            results = [
                ActionResult(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    path=action.path,
                    status=ActionStatus.SKIPPED,
                    message="计划需要确认后才能执行",
                )
                for action in plan.actions
            ]
        elif (
            self._requires_cloud_confirm_token(plan)
            and not self._cloud_confirm_token_matches(
                confirm_token,
                expected_confirm_token,
            )
        ):
            results = [
                ActionResult(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    path=action.path,
                    status=ActionStatus.SKIPPED,
                    message=(
                        "计划包含115云端删除动作，必须提供匹配的确认token"
                    ),
                )
                for action in plan.actions
            ]
        else:
            snapshot_results = {
                action.action_id: self._validate_action_source_snapshot(action)
                for action in plan.actions
                if action.allowed and not plan.dry_run
            }
            completed_results: Dict[str, ActionResult] = {}
            for action in plan.actions:
                result = self._execute_action(
                    plan,
                    action,
                    snapshot_result=snapshot_results.get(action.action_id),
                    completed_results=completed_results,
                )
                results.append(result)
                completed_results[action.action_id] = result
        finished_at = datetime.now().isoformat(timespec="seconds")
        return ExecutionReport(
            task_id=plan.task_id,
            started_at=started_at,
            finished_at=finished_at,
            dry_run=plan.dry_run,
            confirmed=confirmed,
            results=results,
            summary=self._build_execution_summary(results),
        )

    def _execute_action(
        self,
        plan: OrganizerPlan,
        action: PlanAction,
        snapshot_result: Optional[ActionResult],
        completed_results: Dict[str, ActionResult],
    ) -> ActionResult:
        """执行单个整理动作。"""
        if not action.allowed:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message=action.skip_reason or "动作未被允许执行",
            )
        if plan.dry_run:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.DRY_RUN,
                message="演练模式未执行实际删除",
            )
        if snapshot_result:
            return snapshot_result
        if action.action_type == ActionType.DELETE_CLOUD_FILE:
            if action.group_id:
                prerequisite_action_id = action.prerequisite_action_id
                prerequisite_result = completed_results.get(
                    prerequisite_action_id or ""
                )
                if not prerequisite_action_id:
                    return ActionResult(
                        action_id=action.action_id,
                        action_type=action.action_type,
                        path=action.path,
                        status=ActionStatus.SKIPPED,
                        message="115删除动作缺少本地清理前置动作",
                    )
                if (
                    not prerequisite_result
                    or prerequisite_result.status != ActionStatus.DONE
                    or prerequisite_result.action_type
                    != ActionType.DELETE_LOCAL_STRM
                    or prerequisite_result.path != action.path
                ):
                    return ActionResult(
                        action_id=action.action_id,
                        action_type=action.action_type,
                        path=action.path,
                        status=ActionStatus.SKIPPED,
                        message="本地重复STRM未成功清理，跳过115删除",
                    )
            return self._delete_cloud_file(action)
        if action.action_type == ActionType.DELETE_EMPTY_DIR:
            return self._delete_empty_dir(action)
        return self._delete_local_path(plan.task_id, action)

    @staticmethod
    def _requires_cloud_confirm_token(plan: OrganizerPlan) -> bool:
        """判断计划是否需要115删除确认token。"""
        if plan.dry_run:
            return False
        return any(
            action.allowed and action.action_type == ActionType.DELETE_CLOUD_FILE
            for action in plan.actions
        )

    @staticmethod
    def _cloud_confirm_token_matches(
        confirm_token: Optional[str],
        expected_confirm_token: Optional[str],
    ) -> bool:
        """判断115删除确认token是否完整且匹配。"""
        if not confirm_token or not expected_confirm_token:
            return False
        return hmac.compare_digest(
            str(confirm_token),
            str(expected_confirm_token),
        )

    def _validate_action_source_snapshot(self, action: PlanAction) -> Optional[ActionResult]:
        """校验动作源文件是否与计划生成时一致。"""
        if action.action_type in {
            ActionType.DELETE_LOCAL_STRM,
            ActionType.DELETE_SIDECAR,
            ActionType.DELETE_EMPTY_DIR,
        } and not self._is_managed_local_path(Path(action.path)):
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径不在已配置的媒体库内",
            )
        if action.action_type == ActionType.DELETE_EMPTY_DIR:
            return None
        if (
            action.source_size is None
            and action.source_modify_time is None
            and not action.source_sha1
        ):
            return None
        path = Path(action.path)
        if not path.exists():
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="计划源文件已不存在，请重新扫描",
            )
        if not path.is_file():
            return None
        try:
            stat = path.stat()
        except OSError as err:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message=f"计划源文件状态读取失败：{str(err)}",
            )
        if action.source_size is not None and stat.st_size != action.source_size:
            return self._stale_action_result(action)
        if (
            action.source_modify_time is not None
            and abs(stat.st_mtime - action.source_modify_time) > 0.001
        ):
            current_sha1 = PlanBuilder._file_sha1(path)
            if action.source_sha1 and current_sha1 == action.source_sha1:
                return None
            return self._stale_action_result(action)
        if action.source_sha1:
            current_sha1 = PlanBuilder._file_sha1(path)
            if current_sha1 and current_sha1 != action.source_sha1:
                return self._stale_action_result(action)
        return None

    @staticmethod
    def _stale_action_result(action: PlanAction) -> ActionResult:
        """生成计划源文件变化跳过结果。"""
        return ActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            path=action.path,
            status=ActionStatus.SKIPPED,
            message="计划源文件已变化，请重新扫描后再执行",
        )

    def _delete_empty_dir(self, action: PlanAction) -> ActionResult:
        """删除空目录。"""
        path = Path(action.path)
        if not self._is_managed_local_path(path):
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径不在已配置的媒体库内",
            )
        if self._is_protected_local_path(path):
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径命中保护规则",
            )
        if not path.exists():
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="目录不存在",
            )
        if not path.is_dir():
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="路径不是目录",
            )
        try:
            path.rmdir()
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.DONE,
                message="已删除空目录",
            )
        except OSError:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="目录非空，跳过清理",
            )

    def _delete_local_path(self, task_id: str, action: PlanAction) -> ActionResult:
        """删除或隔离本地路径。"""
        path = Path(action.path)
        if not self._is_managed_local_path(path):
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径不在已配置的媒体库内",
            )
        if self._is_protected_local_path(path):
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径命中保护规则",
            )
        if not path.exists():
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="本地路径不存在",
            )
        try:
            if self.config.local_delete_mode == "quarantine":
                backup_path = self._quarantine_path(task_id, path)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(path.as_posix(), backup_path.as_posix())
                return ActionResult(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    path=action.path,
                    status=ActionStatus.DONE,
                    message="已移动到插件隔离区",
                    backup_path=backup_path.as_posix(),
                )
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.DONE,
                message="已删除本地路径",
            )
        except OSError as err:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.FAILED,
                message=f"本地删除失败：{str(err)}",
            )

    def _delete_cloud_file(self, action: PlanAction) -> ActionResult:
        """将115云端文件移入回收站。"""
        if not self.cloud_delete_func:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.FAILED,
                message="未配置115删除执行器",
            )
        if not action.cloud_file_id:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="缺少115 file_id",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )
        if not action.cloud_path:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="缺少115云端路径，无法执行删除前校验",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )
        verify_result = self._verify_cloud_file(action)
        if verify_result:
            return verify_result
        try:
            snapshot = getattr(action, "_cloud_snapshot", self._cloud_snapshot(action))
            file_item = FileItem(
                storage=STORAGE_115_NAME,
                fileid=action.cloud_file_id,
                path=action.cloud_path or "/",
                pickcode=action.cloud_pickcode,
                type="file",
            )
            if self.cloud_delete_func(file_item):
                return ActionResult(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    path=action.path,
                    status=ActionStatus.DONE,
                    message="115文件已移入回收站",
                    details={"cloud_snapshot": snapshot},
                )
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.FAILED,
                message="115删除接口返回失败",
                details={"cloud_snapshot": snapshot},
            )
        except Exception as err:
            logger.error(f"【{PLUGIN_ID}】115删除失败：{str(err)}")
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.FAILED,
                message=f"115删除失败：{str(err)}",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )

    def _verify_cloud_file(self, action: PlanAction) -> Optional[ActionResult]:
        """执行115删除前的云端文件存在性校验。"""
        if not self.cloud_verify_func:
            action.cloud_verify_status = CloudVerifyStatus.UNCHECKED
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="未配置115删除前校验器",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )
        try:
            file_item = self.cloud_verify_func(STORAGE_115_NAME, Path(action.cloud_path))
        except Exception as err:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message=f"115文件校验失败：{str(err)}",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )
        if not file_item:
            action.cloud_verify_status = CloudVerifyStatus.MISSING
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="115文件不存在，跳过回收站删除",
                details={"cloud_snapshot": self._cloud_snapshot(action)},
            )
        if not file_item.fileid:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            snapshot = self._cloud_snapshot(action, file_item=file_item)
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="115文件校验结果缺少file_id，跳过回收站删除",
                details={"cloud_snapshot": snapshot},
            )
        if str(file_item.fileid) != str(action.cloud_file_id):
            action.cloud_verify_status = CloudVerifyStatus.MISMATCHED
            snapshot = self._cloud_snapshot(action, file_item=file_item)
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                path=action.path,
                status=ActionStatus.SKIPPED,
                message="115文件ID与计划不一致，跳过回收站删除",
                details={"cloud_snapshot": snapshot},
            )
        action.cloud_verify_status = CloudVerifyStatus.FOUND
        snapshot = self._cloud_snapshot(action, file_item=file_item)
        action._cloud_snapshot = snapshot
        return None

    @staticmethod
    def _cloud_snapshot(
        action: PlanAction,
        file_item: Optional[FileItem] = None,
    ) -> Dict[str, Any]:
        """生成115删除前校验快照。"""
        snapshot = {
            "storage": STORAGE_115_NAME,
            "planned_file_id": action.cloud_file_id or "",
            "planned_pickcode": action.cloud_pickcode or "",
            "planned_path": action.cloud_path or "",
            "verify_status": action.cloud_verify_status.value,
        }
        if file_item:
            snapshot.update(
                {
                    "verified_file_id": str(file_item.fileid or ""),
                    "verified_pickcode": str(file_item.pickcode or ""),
                    "verified_path": str(file_item.path or ""),
                    "verified_name": str(file_item.name or ""),
                    "verified_type": str(file_item.type or ""),
                    "verified_storage": str(file_item.storage or ""),
                }
            )
        return snapshot

    def _is_protected_local_path(self, path: Path) -> bool:
        """判断本地路径是否受保护。"""
        resolved = path.expanduser().resolve()
        for protected_path in self.config.protected_local_paths:
            protected = protected_path.expanduser().resolve()
            try:
                resolved.relative_to(protected)
                return True
            except ValueError:
                continue
        return False

    def _is_managed_local_path(self, path: Path) -> bool:
        """判断本地路径是否位于已配置的媒体库内。"""
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return False
        for library_path in self.config.library_paths:
            try:
                relative_path = resolved.relative_to(
                    library_path.expanduser().resolve()
                )
                if relative_path.parts:
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _quarantine_path(self, task_id: str, path: Path) -> Path:
        """计算本地隔离区路径。"""
        resolved_path = path.expanduser().resolve()
        safe_parts = [
            part
            for part in resolved_path.parts
            if part not in (resolved_path.anchor, "/")
        ]
        safe_task_id = UNSAFE_TASK_ID_PATTERN.sub("_", task_id).strip("_") or "task"
        return self.data_path / "quarantine" / safe_task_id / Path(*safe_parts)

    @staticmethod
    def _build_execution_summary(results: List[ActionResult]) -> Dict[str, Any]:
        """生成执行摘要。"""
        return {
            "result_count": len(results),
            "done_count": len([result for result in results if result.status == ActionStatus.DONE]),
            "dry_run_count": len([result for result in results if result.status == ActionStatus.DRY_RUN]),
            "skipped_count": len([result for result in results if result.status == ActionStatus.SKIPPED]),
            "failed_count": len([result for result in results if result.status == ActionStatus.FAILED]),
        }


class QuarantineManager:
    """隔离区管理器。"""

    def __init__(self, data_path: Path) -> None:
        """初始化隔离区管理器。"""
        self.data_path = data_path.expanduser().resolve()
        self.quarantine_path = self.data_path / "quarantine"

    def list_items(self) -> List[QuarantineItem]:
        """列出隔离区中的文件。"""
        if not self.quarantine_path.exists():
            return []
        items = []
        for path in sorted(self.quarantine_path.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            items.append(
                QuarantineItem(
                    backup_path=path.as_posix(),
                    original_path=self._restore_target_from_backup(path).as_posix(),
                    size=stat.st_size,
                    modify_time=stat.st_mtime,
                )
            )
        return items

    def restore(self, backup_path: Path, overwrite: bool = False) -> Tuple[bool, str]:
        """从隔离区恢复文件。"""
        backup_path = backup_path.expanduser().resolve()
        try:
            backup_path.relative_to(self.quarantine_path.expanduser().resolve())
        except ValueError:
            return False, "备份路径不在插件隔离区内"
        if not backup_path.exists():
            return False, "备份文件不存在"
        if not backup_path.is_file():
            return False, "备份路径不是文件"
        target_path = self._restore_target_from_backup(backup_path)
        target_exists = target_path.exists() or target_path.is_symlink()
        if target_path.is_dir():
            return False, "目标路径是目录，拒绝递归覆盖"
        if target_exists and not overwrite:
            return False, "目标路径已存在，未覆盖"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_exists and overwrite:
            target_path.unlink()
        shutil.move(backup_path.as_posix(), target_path.as_posix())
        self._cleanup_empty_parents(backup_path.parent)
        return True, target_path.as_posix()

    def restore_batch(self, batch_id: str, overwrite: bool = False) -> Dict[str, Any]:
        """按隔离批次恢复文件。"""
        if (
            not batch_id
            or batch_id in {".", ".."}
            or Path(batch_id).name != batch_id
        ):
            return {
                "total": 0,
                "restored": [],
                "failed": [{"path": batch_id, "message": "隔离批次ID无效"}],
            }
        batch_path = (self.quarantine_path / batch_id).expanduser().resolve()
        try:
            batch_path.relative_to(self.quarantine_path.expanduser().resolve())
        except ValueError:
            return {
                "total": 0,
                "restored": [],
                "failed": [{"path": batch_path.as_posix(), "message": "批次路径不在插件隔离区内"}],
            }
        if not batch_path.is_dir():
            return {
                "total": 0,
                "restored": [],
                "failed": [{"path": batch_path.as_posix(), "message": "隔离批次不存在"}],
            }
        backup_files = [path for path in sorted(batch_path.rglob("*")) if path.is_file()]
        restored = []
        failed = []
        for backup_file in backup_files:
            state, message = self.restore(backup_file, overwrite=overwrite)
            if state:
                restored.append(message)
            else:
                failed.append({"path": backup_file.as_posix(), "message": message})
        self._cleanup_empty_parents(batch_path)
        return {
            "total": len(backup_files),
            "restored": restored,
            "failed": failed,
        }

    def clean_expired(self, retention_days: int) -> Tuple[int, List[str]]:
        """清理超过保留天数的隔离区文件。"""
        if retention_days <= 0 or not self.quarantine_path.exists():
            return 0, []
        cutoff_time = datetime.now().timestamp() - retention_days * 86400
        deleted_paths = []
        for path in sorted(self.quarantine_path.rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime > cutoff_time:
                    continue
                path.unlink()
                deleted_paths.append(path.as_posix())
                self._cleanup_empty_parents(path.parent)
            except OSError as err:
                logger.warning(f"【{PLUGIN_ID}】清理隔离区文件失败：{path} - {str(err)}")
        return len(deleted_paths), deleted_paths

    def _restore_target_from_backup(self, backup_path: Path) -> Path:
        """根据隔离区路径推导原始路径。"""
        relative = backup_path.relative_to(self.quarantine_path)
        parts = relative.parts
        if len(parts) <= 1:
            return Path("/") / Path(*parts)
        return Path("/") / Path(*parts[1:])

    def _cleanup_empty_parents(self, path: Path) -> None:
        """清理隔离区中的空父目录。"""
        current = path
        while current != self.quarantine_path and self.quarantine_path in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


class ReportExporter:
    """整理报告导出器。"""

    def export_json(
        self,
        plan: OrganizerPlan,
        path: Path,
        actions: Optional[List[PlanAction]] = None,
        issues: Optional[List[ScanIssue]] = None,
        duplicate_groups: Optional[List[DuplicateGroup]] = None,
    ) -> Path:
        """导出 JSON 报告。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_primitive(plan)
        if actions is not None:
            data["actions"] = self._to_primitive(actions)
        if issues is not None:
            data["issues"] = self._to_primitive(issues)
        if duplicate_groups is not None:
            data["duplicate_groups"] = self._to_primitive(duplicate_groups)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def export_execution_json(
        self,
        report: Dict[str, Any],
        path: Path,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> Path:
        """导出 JSON 执行报告。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(report)
        if results is not None:
            data["results"] = results
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def export_markdown(
        self,
        plan: OrganizerPlan,
        path: Path,
        actions: Optional[List[PlanAction]] = None,
        issues: Optional[List[ScanIssue]] = None,
        duplicate_groups: Optional[List[DuplicateGroup]] = None,
    ) -> Path:
        """导出 Markdown 报告。"""
        export_actions = actions if actions is not None else plan.actions
        export_issues = issues if issues is not None else plan.issues
        export_groups = duplicate_groups if duplicate_groups is not None else plan.duplicate_groups
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Emby媒体库整理报告 {plan.task_id}",
            "",
            "## 摘要",
        ]
        for key, value in plan.summary.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## 重复分组"])
        for group in plan.duplicate_groups:
            lines.append(f"- {group.group_id} [{group.duplicate_type.value}] {group.key}")
            lines.append(f"  - 保留: {group.keep_path}")
            lines.append(f"  - 删除候选: {', '.join(group.candidate_paths)}")
            if group.score_details:
                lines.append("  - 评分明细:")
                for item in group.score_details:
                    keep_mark = "保留" if item.get("keep") else "候选"
                    lines.append(
                        "    - "
                        f"#{item.get('rank', '')} {keep_mark} "
                        f"{item.get('path', '')} "
                        f"总分:{item.get('total', 0)} "
                        f"质量:{item.get('quality', 0)} "
                        f"命名:{item.get('naming', 0)} "
                        f"伴随:{item.get('sidecar', 0)} "
                        f"优先路径:{item.get('preferred_path', 0)}"
                    )
        lines.extend(["", "## 巡检问题"])
        for issue in export_issues:
            lines.append(f"- [{issue.level.value}] {issue.code}: {issue.path}")
            lines.append(f"  - {issue.message}")
            if issue.suggestion:
                lines.append(f"  - 建议: {issue.suggestion}")
        lines.extend(["", "## 处理动作"])
        for action in export_actions:
            status = "允许" if action.allowed else f"跳过：{action.skip_reason}"
            lines.append(f"- {action.action_type.value}: {action.path} ({status})")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def export_execution_markdown(
        self,
        report: Dict[str, Any],
        path: Path,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> Path:
        """导出 Markdown 执行报告。"""
        export_results = results if results is not None else report.get("results") or []
        summary = report.get("summary") or {}
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Emby媒体库整理执行报告 {report.get('task_id') or 'execution'}",
            "",
            "## 摘要",
            f"- started_at: {report.get('started_at') or ''}",
            f"- finished_at: {report.get('finished_at') or ''}",
            f"- dry_run: {report.get('dry_run')}",
            f"- confirmed: {report.get('confirmed')}",
        ]
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## 执行结果"])
        for result in export_results:
            lines.append(
                f"- [{result.get('status')}] {result.get('action_type')}: {result.get('path')}"
            )
            if result.get("message"):
                lines.append(f"  - {result.get('message')}")
            snapshot = (result.get("details") or {}).get("cloud_snapshot") or {}
            if snapshot:
                lines.append(
                    "  - 115快照: "
                    f"{snapshot.get('planned_file_id') or ''} -> "
                    f"{snapshot.get('verified_file_id') or ''} "
                    f"({snapshot.get('verify_status') or ''})"
                )
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def export_csv(
        self,
        plan: OrganizerPlan,
        path: Path,
        actions: Optional[List[PlanAction]] = None,
    ) -> Path:
        """导出 CSV 处理动作报告。"""
        export_actions = actions if actions is not None else plan.actions
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=[
                    "action_id",
                    "action_type",
                    "path",
                    "group_id",
                    "cloud_file_id",
                    "cloud_path",
                    "cloud_verify_status",
                    "source_size",
                    "source_modify_time",
                    "source_sha1",
                    "allowed",
                    "risk",
                    "reason",
                    "skip_reason",
                    "details",
                ],
            )
            writer.writeheader()
            for action in export_actions:
                writer.writerow(
                    {
                        "action_id": action.action_id,
                        "action_type": action.action_type.value,
                        "path": action.path,
                        "group_id": action.group_id,
                        "cloud_file_id": action.cloud_file_id or "",
                        "cloud_path": action.cloud_path or "",
                        "cloud_verify_status": action.cloud_verify_status.value,
                        "source_size": action.source_size or "",
                        "source_modify_time": action.source_modify_time or "",
                        "source_sha1": action.source_sha1 or "",
                        "allowed": action.allowed,
                        "risk": action.risk,
                        "reason": action.reason,
                        "skip_reason": action.skip_reason,
                        "details": json.dumps(
                            self._to_primitive(getattr(action, "details", {})),
                            ensure_ascii=False,
                        ),
                    }
                )
        return path

    def export_execution_csv(
        self,
        report: Dict[str, Any],
        path: Path,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> Path:
        """导出 CSV 执行报告。"""
        export_results = results if results is not None else report.get("results") or []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=[
                    "action_id",
                    "action_type",
                    "path",
                    "status",
                    "message",
                    "backup_path",
                    "planned_file_id",
                    "planned_pickcode",
                    "planned_path",
                    "verify_status",
                    "verified_file_id",
                    "verified_pickcode",
                    "verified_path",
                    "verified_name",
                    "details",
                ],
            )
            writer.writeheader()
            for result in export_results:
                details = result.get("details") or {}
                snapshot = details.get("cloud_snapshot") or {}
                writer.writerow(
                    {
                        "action_id": result.get("action_id") or "",
                        "action_type": result.get("action_type") or "",
                        "path": result.get("path") or "",
                        "status": result.get("status") or "",
                        "message": result.get("message") or "",
                        "backup_path": result.get("backup_path") or "",
                        "planned_file_id": snapshot.get("planned_file_id") or "",
                        "planned_pickcode": snapshot.get("planned_pickcode") or "",
                        "planned_path": snapshot.get("planned_path") or "",
                        "verify_status": snapshot.get("verify_status") or "",
                        "verified_file_id": snapshot.get("verified_file_id") or "",
                        "verified_pickcode": snapshot.get("verified_pickcode") or "",
                        "verified_path": snapshot.get("verified_path") or "",
                        "verified_name": snapshot.get("verified_name") or "",
                        "details": json.dumps(
                            self._to_primitive(details),
                            ensure_ascii=False,
                        ),
                    }
                )
        return path

    def export_groups_csv(
        self,
        plan: OrganizerPlan,
        path: Path,
        duplicate_groups: Optional[List[DuplicateGroup]] = None,
    ) -> Path:
        """导出 CSV 重复分组报告。"""
        export_groups = duplicate_groups if duplicate_groups is not None else plan.duplicate_groups
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=[
                    "group_id",
                    "duplicate_type",
                    "key",
                    "risk",
                    "keep_path",
                    "candidate_paths",
                    "all_paths",
                    "reason",
                    "score_details",
                ],
            )
            writer.writeheader()
            for group in export_groups:
                writer.writerow(
                    {
                        "group_id": group.group_id,
                        "duplicate_type": group.duplicate_type.value,
                        "key": group.key,
                        "risk": group.risk,
                        "keep_path": group.keep_path,
                        "candidate_paths": "\n".join(group.candidate_paths),
                        "all_paths": "\n".join(group.all_paths),
                        "reason": group.reason,
                        "score_details": json.dumps(
                            self._to_primitive(group.score_details),
                            ensure_ascii=False,
                        ),
                    }
                )
        return path

    def export_issues_csv(
        self,
        plan: OrganizerPlan,
        path: Path,
        issues: Optional[List[ScanIssue]] = None,
    ) -> Path:
        """导出 CSV 巡检问题报告。"""
        export_issues = issues if issues is not None else plan.issues
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=[
                    "level",
                    "code",
                    "path",
                    "message",
                    "suggestion",
                    "details",
                ],
            )
            writer.writeheader()
            for issue in export_issues:
                writer.writerow(
                    {
                        "level": issue.level.value,
                        "code": issue.code,
                        "path": issue.path,
                        "message": issue.message,
                        "suggestion": issue.suggestion,
                        "details": json.dumps(
                            self._to_primitive(issue.details),
                            ensure_ascii=False,
                        ),
                    }
                )
        return path

    @staticmethod
    def _to_primitive(value: Any) -> Any:
        """将报告对象转换为可序列化结构。"""
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return value.as_posix()
        if hasattr(value, "__dataclass_fields__"):
            return {
                key: ReportExporter._to_primitive(item)
                for key, item in asdict(value).items()
            }
        if isinstance(value, list):
            return [ReportExporter._to_primitive(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): ReportExporter._to_primitive(item)
                for key, item in value.items()
            }
        return value


class PlanSerializer:
    """整理计划序列化器。"""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OrganizerPlan:
        """从字典恢复整理计划。"""
        return OrganizerPlan(
            task_id=str(data.get("task_id") or ""),
            created_at=str(data.get("created_at") or ""),
            dry_run=bool(data.get("dry_run", True)),
            require_confirm=bool(data.get("require_confirm", True)),
            issues=[
                cls._issue_from_dict(item)
                for item in data.get("issues") or []
            ],
            duplicate_groups=[
                cls._duplicate_group_from_dict(item)
                for item in data.get("duplicate_groups") or []
            ],
            actions=[
                cls._action_from_dict(item)
                for item in data.get("actions") or []
            ],
            summary=data.get("summary") or {},
        )

    @staticmethod
    def _issue_from_dict(data: Dict[str, Any]) -> ScanIssue:
        """从字典恢复巡检问题。"""
        return ScanIssue(
            level=IssueLevel(data.get("level") or IssueLevel.INFO.value),
            code=str(data.get("code") or ""),
            path=str(data.get("path") or ""),
            message=str(data.get("message") or ""),
            suggestion=str(data.get("suggestion") or ""),
            details=data.get("details") or {},
        )

    @staticmethod
    def _duplicate_group_from_dict(data: Dict[str, Any]) -> DuplicateGroup:
        """从字典恢复重复分组。"""
        return DuplicateGroup(
            group_id=str(data.get("group_id") or ""),
            duplicate_type=DuplicateType(data.get("duplicate_type") or DuplicateType.REFERENCE.value),
            key=str(data.get("key") or ""),
            keep_path=str(data.get("keep_path") or ""),
            candidate_paths=list(data.get("candidate_paths") or []),
            all_paths=list(data.get("all_paths") or []),
            reason=str(data.get("reason") or ""),
            risk=str(data.get("risk") or "low"),
            score_details=list(data.get("score_details") or []),
        )

    @staticmethod
    def _action_from_dict(data: Dict[str, Any]) -> PlanAction:
        """从字典恢复处理动作。"""
        return PlanAction(
            action_id=str(data.get("action_id") or ""),
            action_type=ActionType(data.get("action_type") or ActionType.DELETE_LOCAL_STRM.value),
            path=str(data.get("path") or ""),
            group_id=str(data.get("group_id") or ""),
            prerequisite_action_id=data.get("prerequisite_action_id"),
            cloud_file_id=data.get("cloud_file_id"),
            cloud_pickcode=data.get("cloud_pickcode"),
            cloud_path=data.get("cloud_path"),
            cloud_verify_status=CloudVerifyStatus(
                data.get("cloud_verify_status") or CloudVerifyStatus.UNCHECKED.value
            ),
            source_size=data.get("source_size"),
            source_modify_time=data.get("source_modify_time"),
            source_sha1=data.get("source_sha1"),
            allowed=bool(data.get("allowed", True)),
            risk=str(data.get("risk") or "low"),
            reason=str(data.get("reason") or ""),
            skip_reason=str(data.get("skip_reason") or ""),
        )


class EmbyLibraryOrganizerEngine:
    """Emby媒体库整理核心引擎。"""

    def __init__(self, config: OrganizerConfig) -> None:
        """初始化整理核心引擎。"""
        self.config = config
        self.scanner = LibraryScanner(config)
        self.analyzer = DuplicateAnalyzer(config)
        self.plan_builder = PlanBuilder(config)

    def create_plan(self) -> OrganizerPlan:
        """扫描媒体库并生成整理计划。"""
        scan_result = self.scanner.scan()
        duplicate_groups = self.analyzer.analyze(scan_result.files)
        return self.plan_builder.build(scan_result, duplicate_groups)

    def execute_plan(
        self,
        plan: OrganizerPlan,
        data_path: Path,
        confirmed: bool = False,
        confirm_token: Optional[str] = None,
        expected_confirm_token: Optional[str] = None,
        cloud_delete_func: Optional[Callable[[FileItem], bool]] = None,
        cloud_verify_func: Optional[Callable[[str, Path], Optional[FileItem]]] = None,
    ) -> ExecutionReport:
        """执行整理计划。"""
        executor = PlanExecutor(
            config=self.config,
            data_path=data_path,
            cloud_delete_func=cloud_delete_func,
            cloud_verify_func=cloud_verify_func,
        )
        return executor.execute(
            plan,
            confirmed=confirmed,
            confirm_token=confirm_token,
            expected_confirm_token=expected_confirm_token,
        )


def config_from_dict(config: Optional[Dict[str, Any]]) -> OrganizerConfig:
    """将插件配置字典转换为整理配置。"""
    config = config or {}
    library_paths, library_types = _parse_library_paths(config)
    return OrganizerConfig(
        library_paths=library_paths,
        library_types={**library_types, **(config.get("library_types") or {})},
        exclude_patterns=_parse_lines(config.get("exclude_patterns")),
        protected_local_paths=_parse_paths(config.get("protected_local_paths")),
        protected_115_paths=_parse_lines(config.get("protected_115_paths")),
        preferred_library_paths=_parse_paths(config.get("preferred_library_paths")),
        custom_identity_patterns=_parse_lines(config.get("custom_identity_patterns")),
        max_depth=_parse_int(config.get("max_depth"), 20),
        follow_symlinks=_parse_bool(config.get("follow_symlinks"), False),
        delete_duplicate_strm=_parse_bool(config.get("delete_duplicate_strm"), True),
        clean_trash_files=_parse_bool(config.get("clean_trash_files"), True),
        delete_sidecar_files=_parse_bool(config.get("delete_sidecar_files"), False),
        delete_orphan_sidecar_files=_parse_bool(
            config.get("delete_orphan_sidecar_files"),
            False,
        ),
        delete_empty_dirs=_parse_bool(config.get("delete_empty_dirs"), False),
        check_nfo_files=_parse_bool(config.get("check_nfo_files"), False),
        check_image_files=_parse_bool(config.get("check_image_files"), False),
        sync_delete_115=_parse_bool(config.get("sync_delete_115"), False),
        dry_run=_parse_bool(config.get("dry_run"), True),
        require_confirm=_parse_bool(config.get("require_confirm"), True),
        max_delete_count=_parse_int(config.get("max_delete_count"), 20),
        local_delete_mode=str(config.get("local_delete_mode") or "quarantine"),
        dedupe_keys=_parse_lines(config.get("dedupe_keys")) or [
            "file_id",
            "pickcode",
            "cloud_path",
            "media_key",
        ],
        keep_strategy=str(config.get("keep_strategy") or "quality_then_naming"),
    )


def validate_config(config: OrganizerConfig) -> List[ConfigValidationIssue]:
    """校验整理配置。"""
    issues = []
    if not config.library_paths:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="library_paths_required",
                message="未配置任何媒体库路径",
                suggestion="请至少配置一个混合、电影、剧集或动漫媒体库路径",
            )
        )
    for library_path in config.library_paths:
        if not library_path.expanduser().exists():
            issues.append(
                ConfigValidationIssue(
                    level=IssueLevel.WARNING,
                    code="library_path_not_found",
                    message=f"媒体库路径不存在：{library_path.as_posix()}",
                    suggestion="请确认路径已挂载，或从插件配置中移除该路径",
                )
            )
    if config.sync_delete_115 and config.dry_run:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.INFO,
                code="cloud_delete_dry_run",
                message="已启用115同步删除，但当前仍处于演练模式",
                suggestion="确认计划无误后再关闭演练模式",
            )
        )
    if config.sync_delete_115 and not config.protected_115_paths:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.WARNING,
                code="protected_115_paths_empty",
                message="已启用115同步删除，但未配置115保护路径",
                suggestion="建议配置资源根目录、保种目录或其它不可删除目录作为保护路径",
            )
        )
    if config.max_delete_count <= 0:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="invalid_max_delete_count",
                message="单次最大删除数量必须大于0",
                suggestion="请将单次最大删除数量设置为正整数",
            )
        )
    if config.max_depth <= 0:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="invalid_max_depth",
                message="最大扫描深度必须大于0",
                suggestion="请将最大扫描深度设置为正整数",
            )
        )
    if config.local_delete_mode not in LOCAL_DELETE_MODES:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="invalid_local_delete_mode",
                message=f"不支持的本地删除模式：{config.local_delete_mode}",
                suggestion="本地删除模式只能选择 quarantine 或 delete",
            )
        )
    if config.local_delete_mode == "delete":
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.WARNING,
                code="local_delete_without_quarantine",
                message="本地删除模式未使用隔离区",
                suggestion="建议使用隔离区模式，确认无误后再清理过期隔离文件",
            )
        )
    if config.keep_strategy not in KEEP_STRATEGIES:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="invalid_keep_strategy",
                message=f"不支持的保留策略：{config.keep_strategy}",
                suggestion="保留策略只能使用 quality_then_naming、preferred_path、newest 或 largest",
            )
        )
    invalid_dedupe_keys = [
        key for key in config.dedupe_keys if key not in VALID_DEDUPE_KEYS
    ]
    if invalid_dedupe_keys:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="invalid_dedupe_keys",
                message=f"存在不支持的去重身份键：{', '.join(invalid_dedupe_keys)}",
                suggestion="去重身份键只能使用 file_id、pickcode、cloud_path、media_key",
            )
        )
    if not any(key in config.dedupe_keys for key in VALID_DEDUPE_KEYS):
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code="dedupe_keys_required",
                message="未配置任何有效去重身份键",
                suggestion="请至少配置 file_id、pickcode、cloud_path 或 media_key 中的一个",
            )
        )
    for pattern in config.exclude_patterns:
        _append_regex_validation_issue(
            issues=issues,
            pattern=pattern,
            code="invalid_exclude_pattern",
            message="排除正则无效",
        )
    for pattern in config.custom_identity_patterns:
        _append_regex_validation_issue(
            issues=issues,
            pattern=pattern,
            code="invalid_custom_identity_pattern",
            message="自定义STRM身份解析正则无效",
        )
    return issues


def plan_to_dict(plan: OrganizerPlan) -> Dict[str, Any]:
    """将整理计划转换为字典。"""
    return ReportExporter._to_primitive(plan)


def plan_from_dict(data: Dict[str, Any]) -> OrganizerPlan:
    """从字典恢复整理计划。"""
    return PlanSerializer.from_dict(data)


def execution_report_to_dict(report: ExecutionReport) -> Dict[str, Any]:
    """将执行报告转换为字典。"""
    return ReportExporter._to_primitive(report)


def _parse_lines(value: Any) -> List[str]:
    """解析多行配置。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _parse_library_paths(config: Dict[str, Any]) -> Tuple[List[Path], Dict[str, str]]:
    """解析媒体库路径与类型。"""
    path_types: Dict[str, str] = {}
    paths = []
    for path in _parse_paths(config.get("library_paths")):
        paths.append(path)
        path_types[path.as_posix()] = "mixed"
    typed_config = {
        "movie_library_paths": "movie",
        "tv_library_paths": "tv",
        "anime_library_paths": "anime",
    }
    for key, library_type in typed_config.items():
        for path in _parse_paths(config.get(key)):
            if path not in paths:
                paths.append(path)
            path_types[path.as_posix()] = library_type
    return paths, path_types


def _parse_paths(value: Any) -> List[Path]:
    """解析多行路径配置。"""
    return [Path(line).expanduser() for line in _parse_lines(value)]


def _parse_int(value: Any, default: int) -> int:
    """解析整数配置。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any, default: bool) -> bool:
    """解析布尔配置。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on", "y"):
        return True
    if normalized in ("0", "false", "no", "off", "n", ""):
        return False
    return default


def _append_regex_validation_issue(
    issues: List[ConfigValidationIssue],
    pattern: str,
    code: str,
    message: str,
) -> None:
    """追加正则表达式配置校验问题。"""
    try:
        re.compile(pattern)
    except re.error as err:
        issues.append(
            ConfigValidationIssue(
                level=IssueLevel.ERROR,
                code=code,
                message=f"{message}：{pattern}，{str(err)}",
                suggestion="请修正该正则表达式，或从配置中移除",
            )
        )
