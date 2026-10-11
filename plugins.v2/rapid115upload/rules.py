"""媒体整理增强的目录映射和重试规则。"""

import copy
from pathlib import Path, PurePosixPath

from .bdmv_rules import BDMV_DEFAULTS, validate_bdmv

DEFAULTS = {"bdmv": BDMV_DEFAULTS, "enabled": False, "mappings": [], "watch_mappings": [],
            "concurrency": 2, "qb_enabled": False, "delete_after_upload": False,
            "remove_empty_parents": False,
            "downloaders": [], "include_tags": ["未整理"], "exclude_tags": ["已整理", "BDMV"]}
DEFAULT_RETRIES = [60, 360, 1440]


def validate_config(config: dict) -> dict:
    """整理根按路径组件互斥；失败依次等待指定分钟数，末档无限重复。"""
    if not isinstance(config, dict):
        raise ValueError("配置必须是对象")
    result = copy.deepcopy(DEFAULTS)
    result.update(copy.deepcopy({key: config[key] for key in DEFAULTS if key in config}))
    legacy_attempts = config.get("max_attempts", 3)
    if type(legacy_attempts) is not int or not 1 <= legacy_attempts <= 1000:
        raise ValueError("max_attempts 必须是 1 至 1000 的整数")
    if (not isinstance(result["enabled"], bool) or not isinstance(result["mappings"], list)
            or not isinstance(result["watch_mappings"], list)):
        raise ValueError("启用开关必须是布尔值，目录映射必须是列表")
    result["bdmv"] = validate_bdmv(result["bdmv"])
    if result["enabled"] and not (result["mappings"] or result["qb_enabled"] or result["bdmv"]["enabled"]):
        raise ValueError("启用前至少配置整理目录映射、qB标签监控或BDMV上传")
    if not isinstance(result["delete_after_upload"], bool):
        raise ValueError("上传后删除必须是布尔值")
    if not isinstance(result["remove_empty_parents"], bool):
        raise ValueError("清理空父目录必须是布尔值")
    for key, maximum in (("concurrency", 16),):
        if type(result[key]) is not int or not 1 <= result[key] <= maximum:
            raise ValueError(f"{key} 必须是 1 至 {maximum} 的整数")
    if not isinstance(result["qb_enabled"], bool):
        raise ValueError("qB 标签监控必须是布尔值")
    for key in ("downloaders", "include_tags", "exclude_tags"):
        values = result[key]
        if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip()
                or any(char in value for char in ",\r\n") for value in values):
            raise ValueError(f"{key} 必须是非空名称列表")
        result[key] = list(dict.fromkeys(value.strip() for value in values))
    if not result["include_tags"]:
        raise ValueError("标签白名单不能为空")
    roots = []
    remotes = []
    for mapping in result["mappings"] + result["watch_mappings"]:
        if not isinstance(mapping, dict):
            raise ValueError("目录映射必须是对象")
        attempts = mapping.setdefault("max_attempts", legacy_attempts)
        if type(attempts) is not int or not 1 <= attempts <= 1000:
            raise ValueError("目录最大秒传尝试次数必须是 1 至 1000 的整数")
        for key in ("library_root", "remote_root"):
            raw = mapping.get(key)
            if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//") or "\x00" in raw:
                raise ValueError("整理目录和115目录必须是绝对路径")
            path = PurePosixPath(raw)
            if ".." in path.parts or path == PurePosixPath("/"):
                raise ValueError("根目录不能是 / 或包含 ..")
            mapping[key] = str(path)
        root = Path(mapping["library_root"])
        remote = PurePosixPath(mapping["remote_root"])
        if root.resolve() != root:
            raise ValueError("整理根不能经过符号链接")
        for candidate, existing in ((root, roots), (remote, remotes)):
            if any(candidate.is_relative_to(old) or old.is_relative_to(candidate) for old in existing):
                raise ValueError("同类根目录不能重复或互相包含")
        roots.append(root)
        remotes.append(remote)
        initial_delay = mapping.setdefault("initial_delay_minutes", 0)
        if (isinstance(initial_delay, bool) or not isinstance(initial_delay, (int, float))
                or not 0 <= initial_delay <= 525600):
            raise ValueError("首次上传前等待必须为 0 至 525600 的有限分钟数")
        delays = mapping.setdefault("retry_minutes", list(DEFAULT_RETRIES))
        if not isinstance(delays, list) or not delays:
            raise ValueError("至少设置一个失败重试间隔")
        for delay in delays:
            if (isinstance(delay, bool) or not isinstance(delay, (int, float))
                    or not 1 <= delay <= 525600):
                raise ValueError("重试间隔必须为 1 至 525600 的有限分钟数")
    return result
