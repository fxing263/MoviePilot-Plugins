"""复用宿主已使用的 oss2 协议，以已打开的文件句柄完成可停止的普通上传。"""

from urllib.parse import urlparse

import oss2
from oss2.models import PartInfo

from .client import RetryLaterError, check_source


def upload(client, task, stream, hashes, initialized, progress=None):
    """仅在秒传次数耗尽后调用；分片前检查停止和文件身份，失败时回收分片。"""
    callback = initialized.get("callback")
    bucket_name, object_name = initialized.get("bucket"), initialized.get("object")
    if not bucket_name or not object_name or not isinstance(callback, dict):
        raise RetryLaterError("115普通上传初始化信息不完整")
    bucket = _bucket(client, bucket_name)
    def request(method, *args, **kwargs):
        nonlocal bucket
        for retry in range(6):
            if client.stop.is_set():
                raise InterruptedError("插件已停止")
            try:
                return getattr(bucket, method)(*args, **kwargs)
            except oss2.exceptions.OssError as error:
                if error.status != 403 or error.code != "SecurityTokenExpired" or retry == 5:
                    raise
                bucket = _bucket(client, bucket_name)
        return None

    upload_id = None
    completed = False
    try:
        check_source(stream, task)
        if client.stop.is_set():
            raise InterruptedError("插件已停止")
        upload_id = request("init_multipart_upload", object_name).upload_id
        size = task["identity"][2]
        part_size = oss2.determine_part_size(size, preferred_size=8 * 1024 * 1024)
        if progress:
            progress("uploading", 0, size)
        stream.seek(0)
        parts = []
        offset = 0
        while offset < size:
            if client.stop.is_set():
                raise InterruptedError("插件已停止")
            check_source(stream, task)
            chunk = stream.read(min(part_size, size - offset))
            if not chunk:
                raise RetryLaterError("普通上传读取文件不完整")
            number = len(parts) + 1
            def on_progress(consumed, _total, base=offset):
                progress("uploading", base + consumed, size)

            kwargs = {"progress_callback": on_progress} if progress else {}
            result = request("upload_part", object_name, upload_id, number, chunk, **kwargs)
            parts.append(PartInfo(number, result.etag))
            offset += len(chunk)
        check_source(stream, task)
        if client.stop.is_set():
            raise InterruptedError("插件已停止")
        if progress:
            progress("verifying", size, size)
        headers = {"x-oss-callback": oss2.utils.b64encode_as_string(callback["callback"]),
                   "x-oss-callback-var": oss2.utils.b64encode_as_string(callback["callback_var"]),
                   "x-oss-forbid-overwrite": "true"}
        request("complete_multipart_upload", object_name, upload_id, parts, headers=headers)
        completed = True
        # SDK 回调成功还要按最终网盘路径核对，避免把弱返回值当作完成凭据。
        result = client.verify_existing(task, hashes)
        if result is None:
            raise RetryLaterError("普通上传已提交，等待115路径校验")
        return result
    finally:
        if upload_id and not completed:
            try:
                bucket.abort_multipart_upload(object_name, upload_id)
            except Exception:  # 网络中断时保留主异常，不泄露 OSS 凭据。
                pass


def _bucket(client, bucket_name):
    """沿用宿主凭据刷新协议，仅接受 HTTPS 阿里云 OSS 地址。"""
    token = client._request("/open/upload/get_token", {}).get("data")  # pylint: disable=protected-access
    if not isinstance(token, dict):
        raise RetryLaterError("115上传凭据暂不可用")
    endpoint = urlparse(token.get("endpoint", ""))
    if (endpoint.scheme != "https" or not endpoint.hostname
            or not endpoint.hostname.endswith(".aliyuncs.com")
            or endpoint.username or endpoint.password or endpoint.port not in (None, 443)):
        raise RetryLaterError("115返回了不受支持的对象存储地址")
    auth = oss2.StsAuth(token["AccessKeyId"], token["AccessKeySecret"], token["SecurityToken"])
    return oss2.Bucket(auth, token["endpoint"], bucket_name, connect_timeout=20)
