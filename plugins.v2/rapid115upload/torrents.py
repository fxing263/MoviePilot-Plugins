"""下载器关联适配边界：只核对已登记的明确 Hash，不扫描全部种子。"""

import hashlib
import json
from pathlib import Path, PurePosixPath

from app.sdk.config import settings

def _qb_module():
    """没有关联种子的任务无需加载或连接 qB。"""
    from app.sdk.plugin.manager import ModuleManager

    module = ModuleManager().get_running_module("QbittorrentModule")
    if module is None:
        raise IncompleteTorrentError("qB下载器模块尚未就绪")
    return module


def _is_primary_media(path: str) -> bool:
    """复用 MP 的主媒体扩展名配置，字幕及元数据不作为标签完成条件。"""
    return PurePosixPath(path).suffix.lower() in {ext.lower() for ext in settings.RMT_MEDIAEXT}


def reconcile(queue, stop):
    """全部选中主媒体文件均已上传且 MP 已整理后回写标签；失败独立重试不重传文件。"""
    groups = {}
    for task in queue.tasks():
        for link in task.get("links", []):
            downloader, torrent_hash = link.get("downloader"), link.get("download_hash")
            if downloader and torrent_hash and _is_primary_media(link.get("source_path", "")):
                groups.setdefault((downloader, torrent_hash), []).append((task, link))
    for (downloader, torrent_hash), entries in groups.items():
        if stop.is_set():
            return
        key = json.dumps([downloader, torrent_hash])
        signature = hashlib.sha256(json.dumps(sorted(
            (task["id"], link["source_path"]) for task, link in entries
        )).encode()).hexdigest()
        previous = queue.torrent_status(key)
        if previous.get("signature") == signature and previous.get("tagged"):
            continue
        if previous.get("retry_at", 0) > queue.clock():
            continue
        if not any(task["state"] == "uploaded" for task, _ in entries):
            continue
        try:
            _mark(downloader, torrent_hash, entries)
            queue.update_torrent(key, signature=signature, tagged=True, error="", retry_at=0)
        except Exception as error:
            message = str(error) if isinstance(error, IncompleteTorrentError) else "qB 标签回写失败，稍后重试"
            queue.update_torrent(key, tagged=False, error=message, retry_at=queue.clock() + 60)


class IncompleteTorrentError(ValueError):
    """清单、整理状态或上传覆盖不足时禁止标记整个种子。"""


def _mark(downloader, torrent_hash, entries):
    if (torrent_hash.lower() == "all" or any(char in torrent_hash for char in "|,\r\n")
            or not torrent_hash.strip()):
        raise IncompleteTorrentError("无效的种子 Hash")
    module = _qb_module()
    client = module.get_instance(downloader)
    if client is None or client.qbc is None:
        raise IncompleteTorrentError("关联的 qB 下载器不可用")
    qbc = client.qbc
    rows = qbc.torrents_info(torrent_hashes=torrent_hash)
    torrent = next((row for row in rows or [] if row.get("hash", "").lower() == torrent_hash), None)
    if not torrent or "已整理" not in {tag.strip() for tag in torrent.get("tags", "").split(",")}:
        raise IncompleteTorrentError("尚未确认整种子已整理")
    files = qbc.torrents_files(torrent_hash=torrent_hash)
    selected = [file for file in files or []
                if file.get("priority", 0) > 0 and _is_primary_media(file.get("name", ""))]
    if not selected or not torrent.get("save_path"):
        raise IncompleteTorrentError("种子没有可核对的选中主媒体文件或保存路径")
    covered = {(str(Path(link["source_path"])), task["identity"][2]) for task, link in entries
               if task["state"] == "uploaded"}
    for file in selected:
        name = PurePosixPath(file["name"])
        if name.is_absolute() or ".." in name.parts or file.get("progress", 0) < 1:
            raise IncompleteTorrentError("种子存在未完成文件或无效路径")
        path = module.normalize_return_path(Path(torrent["save_path"]) / str(name), downloader)
        if (str(Path(path)), file["size"]) not in covered:
            raise IncompleteTorrentError("种子仍有主媒体文件未整理入队或未上传（包括映射范围外文件）")
    if module.get_instance(downloader) is not client or client.qbc is not qbc:
        raise IncompleteTorrentError("下载器连接发生变化，稍后重新核对")
    qbc.torrents_add_tags(torrent_hashes=torrent_hash, tags="已上传")
    confirmed = qbc.torrents_info(torrent_hashes=torrent_hash)
    if not any(row.get("hash", "").lower() == torrent_hash and
               "已上传" in {tag.strip() for tag in row.get("tags", "").split(",")} for row in confirmed or []):
        raise IncompleteTorrentError("尚未确认已上传标签，稍后重试")
