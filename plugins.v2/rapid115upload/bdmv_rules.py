"""BDMV 独立目录复制的纯配置和种子清单约束。"""

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from apscheduler.triggers.cron import CronTrigger

BDMV_DEFAULTS = {"enabled": False, "cron": "0 2 * * *", "downloaders": [],
                 "cd2_plugin_id": "CloudDriveDisk", "mappings": []}


def absolute_path(value: str) -> PurePosixPath:
    """拒绝根目录和路径穿越，避免把共享下载根当成一个种子上传。"""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or "\x00" in value:
        raise ValueError("BDMV 路径必须为绝对路径")
    path = PurePosixPath(value)
    if path == PurePosixPath("/") or ".." in path.parts:
        raise ValueError("BDMV 路径不能为根目录或包含 ..")
    return path


def validate_bdmv(value: dict) -> dict:
    """BDMV 配置独立于普通整理白黑名单；开启时必须指定下载器和映射。"""
    if not isinstance(value, dict):
        raise ValueError("BDMV 配置必须为对象")
    result = copy.deepcopy(BDMV_DEFAULTS)
    result.update({key: copy.deepcopy(value[key]) for key in result if key in value})
    if not isinstance(result["enabled"], bool):
        raise ValueError("BDMV 开关必须为布尔值")
    # 旧版每日时间转换为等价 Cron，重载后不改变原计划。
    if "cron" not in value and "time" in value:
        legacy = value["time"]
        if not isinstance(legacy, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", legacy):
            raise ValueError("BDMV 旧扫描时间须为 HH:MM")
        hour, minute = legacy.split(":")
        result["cron"] = f"{int(minute)} {int(hour)} * * *"
    if not isinstance(result["cron"], str):
        raise ValueError("BDMV 扫描周期须为五段 Cron：分 时 日 月 周")
    result["cron"] = " ".join(result["cron"].split())
    try:
        CronTrigger.from_crontab(result["cron"])
    except (ValueError, TypeError) as error:
        raise ValueError("BDMV 扫描周期无效，请填写五段 Cron：分 时 日 月 周") from error
    if not isinstance(result["cd2_plugin_id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", result["cd2_plugin_id"]):
        raise ValueError("CD2 插件 ID 无效")
    names = result["downloaders"]
    if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() or any(c in name for c in ",\r\n") for name in names):
        raise ValueError("BDMV 下载器必须为名称列表")
    result["downloaders"] = list(dict.fromkeys(name.strip() for name in names))
    if not isinstance(result["mappings"], list):
        raise ValueError("BDMV 映射必须为列表")
    roots = []
    for item in result["mappings"]:
        if not isinstance(item, dict):
            raise ValueError("BDMV 映射必须为对象")
        for key in ("local_root", "cd2_source_root", "cd2_target_root"):
            item[key] = str(absolute_path(item.get(key)))
        root = PurePosixPath(item["local_root"])
        if any(root.is_relative_to(old) or old.is_relative_to(root) for old in roots):
            raise ValueError("BDMV 下载目录映射不能重复或互相包含")
        roots.append(root)
    if result["enabled"] and not (result["downloaders"] and result["mappings"]):
        raise ValueError("启用 BDMV 前须选择下载器并配置路径映射")
    return result


def torrent_identity(module: object, downloader: str, torrent: dict, files: list) -> dict:
    """整种子全部文件完成且位于独占内容目录时才产生稳定清单，不读取 MP 本地磁盘。"""
    torrent_hash = str(torrent.get("hash", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", torrent_hash):
        raise ValueError("种子 Hash 无效")
    if torrent.get("progress", 0) < 1 or not files:
        raise ValueError("种子尚未完整下载")
    content = absolute_path(torrent.get("content_path"))
    save = absolute_path(torrent.get("save_path"))
    if content == save:
        raise ValueError("内容路径不能是共享保存目录")
    manifest = []
    for item in files:
        name = PurePosixPath(str(item.get("name", "")))
        if not name.parts or name.is_absolute() or ".." in name.parts or "\x00" in str(name):
            raise ValueError("种子文件路径无效")
        full = save / name
        if full == content or not full.is_relative_to(content) or item.get("progress", 0) < 1:
            raise ValueError("种子不是完整的独立文件夹")
        size = item.get("size")
        if type(size) is not int or size < 0:
            raise ValueError("种子文件大小无效")
        manifest.append({"path": str(full.relative_to(content)), "size": size})
    manifest.sort(key=lambda item: item["path"])
    if len({item["path"] for item in manifest}) != len(manifest):
        raise ValueError("种子清单存在重复路径")
    local = str(absolute_path(str(module.normalize_return_path(Path(str(content)), downloader))))
    fingerprint = hashlib.sha256(json.dumps([torrent_hash, str(content), str(save), local, manifest], sort_keys=True).encode()).hexdigest()
    return {"download_hash": torrent_hash, "local_path": local, "manifest": manifest, "fingerprint": fingerprint}


def mapped_paths(identity: dict, mappings: list) -> tuple[str, str]:
    """保留下载根下的相对目录，CD2 源路径与网盘目标路径单独映射。"""
    local = PurePosixPath(identity["local_path"])
    mapping = next((item for item in mappings if local.is_relative_to(item["local_root"])), None)
    if not mapping or local == PurePosixPath(mapping["local_root"]):
        raise ValueError("种子内容目录未匹配 BDMV 映射")
    relative = local.relative_to(mapping["local_root"])
    return str(PurePosixPath(mapping["cd2_source_root"]) / relative), str(PurePosixPath(mapping["cd2_target_root"]) / relative)
