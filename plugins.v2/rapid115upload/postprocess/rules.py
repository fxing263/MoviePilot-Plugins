"""冻结上传后处理模式和路径映射，不读取本地文件或远端服务。"""

import copy
import math
import re
from pathlib import PurePosixPath

DEFAULTS = {"mode": "off", "mappings": [], "cd2_plugin_id": "CloudDriveDisk",
            "merge_delay": 45, "max_wait": 180, "min_interval": 3,
            "retry_base": 60, "retry_max": 3600}
MEDIA_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts",
                              ".m2ts", ".mts", ".mpg", ".mpeg", ".m4v", ".webm", ".vob"})


def absolute_path(value: str) -> PurePosixPath:
    """校验独立路径空间中的绝对非根路径，拒绝规范化会掩盖的穿越和歧义。"""
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//")
            or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {".", ".."} for part in value.split("/")) or "//" in value):
        raise ValueError("后处理路径必须为绝对路径，不能包含控制字符、反斜杠或路径穿越")
    path = PurePosixPath(value)
    if path == PurePosixPath("/"):
        raise ValueError("后处理路径不能为根目录")
    return path


def validate_config(config: dict) -> dict:
    """只校验当前模式的映射字段，保留其他模式参数；嵌套源目录使用最长前缀。"""
    if not isinstance(config, dict):
        raise ValueError("上传后处理配置必须为对象")
    result = copy.deepcopy(DEFAULTS)
    result.update({key: copy.deepcopy(config[key]) for key in result if key in config})
    if result["mode"] not in ("off", "strm", "cd2"):
        raise ValueError("上传后处理方式必须为关闭、本地 STRM 或 CD2 刷新之一")
    for key in ("merge_delay", "max_wait", "min_interval", "retry_base", "retry_max"):
        value = result[key]
        minimum = 0 if key == "merge_delay" else 1
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not minimum <= value <= 86400):
            raise ValueError(f"后处理 {key} 必须为 {minimum} 至 86400 秒的有限数字")
    if result["max_wait"] < result["merge_delay"] or result["retry_max"] < result["retry_base"]:
        raise ValueError("最长等待不能小于合并延迟，最大重试间隔不能小于初始间隔")
    if result["mode"] == "cd2" and (not isinstance(result["cd2_plugin_id"], str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", result["cd2_plugin_id"])):
        raise ValueError("CD2 插件 ID 无效")
    if not isinstance(result["mappings"], list):
        raise ValueError("后处理目录映射必须为列表")
    roots = set()
    for item in result["mappings"]:
        if not isinstance(item, dict):
            raise ValueError("后处理目录映射必须为对象")
        if result["mode"] == "off":
            continue
        keys = ("source_root", "strm_root", "playback_root") if result["mode"] == "strm" else ("source_root", "cd2_root")
        for key in keys:
            item[key] = str(absolute_path(item.get(key)))
        if item["source_root"] in roots:
            raise ValueError("后处理 115 源根目录不能重复")
        roots.add(item["source_root"])
    if result["mode"] != "off" and not roots:
        raise ValueError("启用上传后处理须配置目录映射")
    return result


def plan(task: dict, config: dict, now: float) -> dict:
    """在上传成功的同一持久化事务中保存此快照；后续切换配置不改变已入队的模式。"""
    record = {"mode": config.get("mode", "off"), "state": "pending", "error": "",
              "attempts": 0, "created_at": now, "ready_at": now,
              "remote_path": task.get("remote_path", "")}
    for key in ("merge_delay", "max_wait", "min_interval", "retry_base", "retry_max"):
        record[key] = config.get(key, DEFAULTS[key])
    if record["mode"] == "off":
        record["state"] = "disabled"
        return record
    try:
        checked = validate_config(config)
        remote = absolute_path(record["remote_path"])
        if remote.suffix.lower() not in MEDIA_EXTENSIONS or any(part.upper() in {"BDMV", "VIDEO_TS"} for part in remote.parts):
            record.update(state="skipped", error="非独立媒体文件或 BDMV 目录，保持原有处理流程")
            return record
        matches = [item for item in checked["mappings"]
                   if remote.is_relative_to(PurePosixPath(item["source_root"]))
                   and remote != PurePosixPath(item["source_root"])]
        if not matches:
            raise ValueError("上传成功，但最终 115 文件路径未匹配后处理目录映射")
        mapping = max(matches, key=lambda item: len(PurePosixPath(item["source_root"]).parts))
        relative = remote.relative_to(mapping["source_root"])
        if record["mode"] == "strm":
            record.update(target=str((PurePosixPath(mapping["strm_root"]) / relative).with_suffix(".strm")),
                          content=str(PurePosixPath(mapping["playback_root"]) / relative),
                          strm_root=mapping["strm_root"])
        else:
            record.update(target=str((PurePosixPath(mapping["cd2_root"]) / relative).parent),
                          cd2_plugin_id=checked["cd2_plugin_id"])
    except (ValueError, TypeError) as error:
        record.update(state="failed", error=str(error))
    return record
