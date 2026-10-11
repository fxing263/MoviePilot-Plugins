"""沿用宿主 115 授权和秒传协议；普通上传由独立 OSS 适配器处理。"""

import hashlib
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterator, Optional

from app.sdk.network import RequestUtils

from .queue import FileChangedError, file_identity

PREID_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 2 * 1024 * 1024
ENDPOINTS = {"/open/folder/get_info", "/open/folder/add", "/open/upload/init", "/open/upload/get_token"}


class RetryLaterError(RuntimeError):
    """远端暂不可用，错误信息不包含凭据或原始响应。"""

    def __init__(self, message: str, delay: float = 0) -> None:
        super().__init__(message)
        self.delay = delay


class RemoteConflictError(ValueError):
    """同路径已有文件但不能确认内容一致，禁止覆盖。"""


def host_access_token() -> str:
    """复用当前宿主授权及刷新锁；不调用上传方法，也不关闭宿主持有的客户端。

    115 授权尚无独立 SDK 门面，此处集中适配当前 U115Pan.access_token 契约。
    """
    from app.modules.filemanager.storages.u115 import U115Pan

    token = U115Pan().access_token
    if not token:
        raise RetryLaterError("115尚未登录或授权失效，请在存储设置中重新授权", 3600)
    return token


@contextmanager
def open_source(task: dict) -> Iterator[BinaryIO]:
    """逐段拒绝符号链接并校验打开的 inode，哈希和二次校验始终读同一文件。"""
    path = Path(task["organized_path"])
    if file_identity(path) != task["identity"]:
        raise FileChangedError("整理文件已改变，请核对后重新整理登记")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    descriptor = None
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            check_source(stream, task)
            yield stream
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def check_source(stream: BinaryIO, task: dict) -> None:
    """提交哈希前确认正在读取的文件与登记身份一致。"""
    info = os.fstat(stream.fileno())
    actual = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
    if actual != task["identity"]:
        raise FileChangedError("整理文件在校验期间发生变化，已停止秒传")


def calculate_hashes(stream: BinaryIO, task: dict, stop: threading.Event) -> dict:
    """一次顺序读取计算完整 SHA1 和前 128 MiB SHA1，身份不变时复用缓存。"""
    cached = task.get("hashes", {})
    if all(re.fullmatch(r"[A-F0-9]{40}", cached.get(key, "")) for key in ("fileid", "preid")):
        return cached
    full, prefix = hashlib.sha1(), hashlib.sha1()
    offset = 0
    stream.seek(0)
    while True:
        if stop.is_set():
            raise InterruptedError("插件已停止")
        chunk = stream.read(CHUNK_BYTES)
        if not chunk:
            break
        full.update(chunk)
        if offset < PREID_BYTES:
            prefix.update(chunk[:PREID_BYTES - offset])
        offset += len(chunk)
    check_source(stream, task)
    return {"fileid": full.hexdigest().upper(), "preid": prefix.hexdigest().upper()}


class RapidClient:
    """每次调度独占 HTTP 会话；单次请求失败即交回持久队列安排延迟。"""

    def __init__(self, stop: threading.Event, token_provider: Callable[[], str] = host_access_token,
                 transport: Optional[object] = None) -> None:
        self.stop = stop
        self.token_provider = token_provider
        self.http = transport if transport is not None else RequestUtils(timeout=20, use_session=True, verify=True)
        self._last_request = 0.0
        self.initialized = {}

    def close(self) -> None:
        """只关闭本插件会话，宿主授权会话不属于此生命周期。"""
        self.http.close()

    def _request(self, endpoint: str, data: dict) -> dict:
        if endpoint not in ENDPOINTS:
            raise ValueError("仅允许目录查询、建目录及秒传初始化")
        if self.stop.wait(max(0, 1 - (time.monotonic() - self._last_request))):
            raise InterruptedError("插件已停止")
        token = self.token_provider()
        if self.stop.is_set():
            raise InterruptedError("插件已停止")
        self._last_request = time.monotonic()
        try:
            response = self.http.request(
                "GET" if endpoint == "/open/upload/get_token" else "POST",
                f"https://proapi.115.com{endpoint}", data=data,
                headers={"Authorization": f"Bearer {token}"}, raise_exception=True,
            )
            if response is None:
                raise RetryLaterError("115请求未返回结果")
            if response.status_code == 429:
                raise RetryLaterError("115触发限流，至少冷却一小时", 3600)
            if response.status_code in {401, 403}:
                raise RetryLaterError("115授权不可用，请检查存储登录状态", 3600)
            response.raise_for_status()
            result = response.json()
        except RetryLaterError:
            raise
        except Exception as error:
            raise RetryLaterError("115网络请求或响应解析失败") from error
        if not isinstance(result, dict):
            raise RetryLaterError("115返回了无效响应")
        missing = endpoint == "/open/folder/get_info" and result.get("code") in {20004, 430004}
        exists = endpoint == "/open/folder/add" and result.get("code") == 20004
        if not missing and not exists and (result.get("code") != 0 or result.get("state") is not True):
            if "已达到当前访问上限" in str(result.get("message", "")):
                raise RetryLaterError("115访问上限，至少冷却一小时", 3600)
            raise RetryLaterError("115拒绝请求，请检查授权及账户状态")
        return result

    def _info(self, path: PurePosixPath) -> Optional[dict]:
        result = self._request("/open/folder/get_info", {"path": str(path)})
        if result.get("code") in {20004, 430004}:
            return None
        data = result.get("data")
        # 115也会用成功响应加空数据表示路径不存在，与宿主存储适配保持一致。
        if data is None or data == [] or data == {}:
            return None
        if not isinstance(data, dict) or not data.get("file_id"):
            raise RetryLaterError("115目标查询返回格式异常，稍后重新查询")
        return data

    def _folder(self, path: PurePosixPath) -> str:
        current = PurePosixPath("/")
        parent_id = "0"
        for part in path.parts[1:]:
            current /= part
            info = self._info(current)
            if info is None:
                result = self._request("/open/folder/add", {"pid": parent_id, "file_name": part})
                info = self._info(current) if result.get("code") == 20004 else result.get("data")
                if not isinstance(info, dict) or not info.get("file_id"):
                    raise RetryLaterError("115目录创建结果不明确")
            if "file_category" in info and str(info["file_category"]) != "0":
                raise RemoteConflictError("115目标父路径已被文件占用")
            parent_id = str(info["file_id"])
        return parent_id

    def verify_existing(self, task: dict, hashes: dict) -> Optional[dict]:
        """只接受远端路径、大小和 SHA1 一致的文件凭据。"""
        remote = PurePosixPath(task["remote_path"])
        existing = self._info(remote)
        if existing is not None:
            sha1 = str(existing.get("sha1") or existing.get("file_sha1") or "").upper()
            size = str(existing.get("size_byte", ""))
            if str(existing.get("file_category")) == "1" and sha1 == hashes["fileid"] and size == str(task["identity"][2]):
                return {"file_id": str(existing["file_id"]), "verified_existing": True}
            raise RemoteConflictError("115已有同名文件，但大小/SHA1无法确认一致；未覆盖")
        return None

    def attempt(self, task: dict, stream: BinaryIO, hashes: dict) -> Optional[dict]:
        """返回成功凭据或未命中；未命中保留初始化信息，由队列决定是否普通上传。"""
        remote = PurePosixPath(task["remote_path"])
        existing = self.verify_existing(task, hashes)
        if existing is not None:
            return existing
        parent_id = self._folder(remote.parent)
        check_source(stream, task)
        data = {"file_name": remote.name, "file_size": task["identity"][2],
                "target": f"U_1_{parent_id}", **hashes}
        result = self._initialize(data)
        if result.get("status") != 2 and result.get("code") in {700, 701}:
            check = str(result.get("sign_check", ""))
            match = re.fullmatch(r"(\d+)-(\d+)", check)
            if not match or not result.get("sign_key"):
                raise RetryLaterError("115二次校验参数无效")
            start, end = map(int, match.groups())
            if not 0 <= start <= end < task["identity"][2]:
                raise RetryLaterError("115二次校验区间超出文件范围")
            stream.seek(start)
            remaining, digest = end - start + 1, hashlib.sha1()
            while remaining:
                if self.stop.is_set():
                    raise InterruptedError("插件已停止")
                chunk = stream.read(min(remaining, CHUNK_BYTES))
                if not chunk:
                    raise FileChangedError("二次校验时文件被截断")
                digest.update(chunk)
                remaining -= len(chunk)
            check_source(stream, task)
            data.update(pick_code=result.get("pick_code"), sign_key=result["sign_key"],
                        sign_val=digest.hexdigest().upper())
            result = self._initialize(data)
        if result.get("status") == 2:
            return {"file_id": result.get("file_id"), "pick_code": result.get("pick_code"),
                    "verified_existing": False}
        if result.get("status") == 1:
            self.initialized = result
            return None
        raise RetryLaterError("115未确认秒传成功，稍后重试")

    def _initialize(self, data: dict) -> dict:
        result = self._request("/open/upload/init", data).get("data")
        if not isinstance(result, dict):
            raise RetryLaterError("115秒传初始化结果不完整")
        return result
