"""上传后定向刷新 CD2 缓存；复用连接，不创建目录或遍历无关子树。"""

from pathlib import PurePosixPath
from threading import Event
from time import monotonic
from typing import Any, Callable, Optional

from ..bdmv_cd2 import BdmvCd2Adapter, BdmvCd2Error


class RefreshError(BdmvCd2Error):
    """刷新尚未确认成功，调用方应保留目录并退避重试。"""


class RefreshAdapter(BdmvCd2Adapter):
    """完整消费刷新流；cache 仅供同实例同批祖先去重，叶子每次重刷。"""

    def __init__(self, plugin_id: str, stop: Optional[Event],
                 before_rpc: Callable[[], None], timeout: float = 30) -> None:
        super().__init__(plugin_id=plugin_id, timeout=timeout, stop=stop)
        self.before_rpc = before_rpc

    def _check_stop(self) -> None:
        if self.stop is not None and self.stop.is_set():
            raise InterruptedError('CD2 刷新已停止')

    def _call(self, connection: tuple, method: str, request: Any) -> Any:
        self._check_stop()
        self.before_rpc()
        self._check_stop()
        return super()._call(connection, method, request)

    def _directory(self, connection: tuple, path: str) -> bool:
        try:
            item = self._find(connection, path)
        except BdmvCd2Error as exc:
            code = getattr(exc.__cause__, 'code', None)
            status = code() if callable(code) else None
            if getattr(status, 'name', None) == 'NOT_FOUND':
                return False
            raise RefreshError(f'CD2 目录不可访问：{path}，未继续探测祖先') from exc
        full_path = getattr(item, 'fullPathName', '')
        if not full_path:
            return False
        if full_path != path or not getattr(item, 'isDirectory', False):
            raise RefreshError(f'CD2 返回的目标不是对应目录：{path}')
        return True

    def _refresh(self, connection: tuple, path: str, cache: dict) -> None:
        if path in cache:
            return
        stream = None
        succeeded = False
        try:
            stream = self._call(connection, 'GetSubFiles', connection[1].ListSubFileRequest(
                path=path, forceRefresh=True,
            ))
            started = monotonic()
            for _reply in stream:
                self._check_stop()
                if monotonic() - started > self.timeout:
                    raise TimeoutError('CD2 刷新流超时')
            self._check_stop()
            if monotonic() - started > self.timeout:
                raise TimeoutError('CD2 刷新流超时')
            succeeded = True
            cache[path] = True
        except InterruptedError:
            raise
        except Exception as exc:
            raise RefreshError(f'CD2 目录刷新未完整完成：{path}') from exc
        finally:
            if not succeeded and stream is not None:
                cancel = getattr(stream, 'cancel', None)
                if callable(cancel):
                    cancel()

    def refresh(self, directory: str, cache: dict) -> None:
        """先刷新直接父目录；明确缺失时最远只发现到 CD2 挂载根。"""
        if (not isinstance(directory, str) or not directory.startswith('/')
                or directory.startswith('//') or '\\' in directory
                or any(part in ('.', '..') for part in directory.split('/'))):
            raise RefreshError('CD2 刷新路径必须是无越界的绝对 POSIX 路径')
        target = PurePosixPath(directory)
        if target == PurePosixPath('/'):
            raise RefreshError('禁止刷新 CD2 全局根目录')
        self._check_stop()
        # 同一批中后续完成的上传可能再次提交同一叶子，不能复用其旧刷新结果。
        cache.pop(str(target), None)
        connection = self._connection()
        pending = []
        current = target
        while str(current) not in cache and not self._directory(connection, str(current)):
            if current.parent == PurePosixPath('/'):
                raise RefreshError(f'CD2 挂载根不可访问：{current}')
            pending.append(current)
            current = current.parent
        self._refresh(connection, str(current), cache)
        for child in reversed(pending):
            self._check_stop()
            if not self._directory(connection, str(child)):
                raise RefreshError(f'CD2 刷新祖先后仍未发现目录：{child}')
            self._refresh(connection, str(child), cache)
