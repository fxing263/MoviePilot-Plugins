"""BDMV 目录复制边界：复用 CloudDrive 插件登录连接，不把提交回执当上传完成。"""

from importlib import import_module
from pathlib import PurePosixPath
from threading import Event
from typing import Any, Callable, Optional


class BdmvCd2Error(RuntimeError):
    """CD2 不可用、路径不合规或操作状态无法确认。"""


class BdmvCd2ConflictError(BdmvCd2Error):
    """目标已存在时拒绝复制，防止覆盖或把旧文件误认成本次上传。"""


def _path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value:
        raise BdmvCd2Error('CD2 路径必须是绝对 POSIX 路径')
    if any(part in ('.', '..') for part in value.split('/')):
        raise BdmvCd2Error('CD2 路径不能包含 . 或 ..')
    return str(PurePosixPath(value))


def _running_client(plugin_id: str) -> Any:
    from app.sdk.plugin.manager import PluginManager

    plugin = PluginManager().running_plugins.get(plugin_id)
    client = getattr(plugin, '_client', None)
    if client is None or not getattr(client, 'jwt_token', None):
        raise BdmvCd2Error(f'CloudDrive 插件 {plugin_id} 未运行或尚未登录')
    return client


def is_completed(task: dict) -> bool:
    """仅完整复制的明确终态允许回写标签；跳过、消失、取消均不是成功。"""
    return (
        task.get('mode') == 0 and task.get('status') == 3
        and task.get('total', 0) > 0 and task.get('uploaded') == task.get('total')
        and all(task.get(key) == 0 for key in ('failed', 'failed_folders', 'skipped', 'cancelled'))
    )


class BdmvCd2Adapter:
    """每次操作取得当前运行连接；不登录、不关闭共享连接、不自动重试提交。"""

    def __init__(self, plugin_id: str = 'CloudDriveDisk', timeout: float = 30,
                 stop: Optional[Event] = None) -> None:
        self.plugin_id = plugin_id
        self.stop = stop
        self.timeout = max(1.0, min(float(timeout), 120.0))

    def _check_stop(self) -> None:
        if self.stop is not None and self.stop.is_set():
            raise BdmvCd2Error('BDMV 操作已停止')

    def _connection(self) -> tuple:
        self._check_stop()
        client = _running_client(self.plugin_id)
        # 协议随已安装的 CD2 客户端提供，未启用 BDMV 时不加载 grpc/protobuf。
        module = import_module(type(client).__module__)
        proto = getattr(module, 'clouddrive_pb2', None)
        empty = getattr(module, 'empty_pb2', None)
        if proto is None or empty is None:
            raise BdmvCd2Error('CloudDrive 客户端协议版本不兼容')
        return client, proto, empty

    def _call(self, connection: tuple, method: str, request: Any) -> Any:
        self._check_stop()
        client = connection[0]
        try:
            return getattr(client.stub, method)(
                request, metadata=[('authorization', f'Bearer {client.jwt_token}')],
                timeout=self.timeout,
            )
        except Exception as exc:
            raise BdmvCd2Error(f'CD2 {method} 调用失败，结果未确认') from exc

    def _list(self, connection: tuple, path: str) -> list:
        replies = self._call(connection, 'GetSubFiles', connection[1].ListSubFileRequest(
            path=path, forceRefresh=True,
        ))
        try:
            items = []
            for reply in replies:
                self._check_stop()
                items.extend(reply.subFiles)
            return items
        except Exception as exc:
            raise BdmvCd2Error('CD2 目录查询未完整返回') from exc

    def _find(self, connection: tuple, path: str) -> Any:
        return self._call(connection, 'FindFileByPath', connection[1].FindFileByPathRequest(
            parentPath='', path=path,
        ))

    @staticmethod
    def _require_115(item: Any) -> None:
        # CloudAPI.name 是协议给出的提供商名；不以用户可改的目录名猜测网盘类型。
        provider = str(getattr(getattr(item, 'CloudAPI', None), 'name', '')).lower()
        if (not getattr(item, 'isDirectory', False) or getattr(item, 'isLocal', False)
                or provider not in {'115', '115open', '115drive', '115 drive'}):
            raise BdmvCd2Error('CD2 目标必须是可确认的 115 网盘目录')

    def _source(self, connection: tuple, path: str) -> Any:
        item = self._find(connection, path)
        if not getattr(item, 'isLocal', False) or not getattr(item, 'isDirectory', False):
            raise BdmvCd2Error('BDMV 源必须是 CD2 已添加的本地文件夹')
        return item

    def inspect_source(self, path: str) -> dict:
        """验证 CD2 本地目录，不将 MP 文件系统路径自动解释为 CD2 路径。"""
        path = _path(path)
        if path == '/':
            raise BdmvCd2Error('不能上传 CD2 根目录')
        item = self._source(self._connection(), path)
        return {'path': path, 'name': item.name, 'is_local': True, 'is_directory': True}

    def _target_parent(self, connection: tuple, path: str) -> Any:
        parts = PurePosixPath(path).parts[1:]
        if len(parts) < 1:
            raise BdmvCd2Error('目标必须位于 115 网盘内')
        parent = '/'
        item: Optional[Any] = None
        for part in parts:
            matches = [child for child in self._list(connection, parent) if child.name == part]
            if len(matches) > 1:
                raise BdmvCd2ConflictError('CD2 目标目录重名，无法唯一确认')
            if matches:
                item = matches[0]
                self._require_115(item)
            else:
                if item is None:
                    raise BdmvCd2Error('115 网盘挂载点不存在，不能自动创建网盘')
                result = self._call(connection, 'CreateFolder', connection[1].CreateFolderRequest(
                    parentPath=parent, folderName=part,
                ))
                if not result.result.success:
                    raise BdmvCd2Error('CD2 创建目标目录未成功')
                item = result.folderCreated
                self._require_115(item)
            parent = str(PurePosixPath(parent) / part)
        return item

    def _check_manifest(self, connection: tuple, source: str, manifest: list[dict]) -> None:
        expected = {}
        for entry in manifest:
            path = str(entry['path'])
            if path.startswith('/') or any(part in ('', '.', '..') for part in path.split('/')):
                raise BdmvCd2Error('种子文件清单包含不安全的相对路径')
            if path in expected:
                raise BdmvCd2Error('种子文件清单包含重复路径')
            expected[path] = int(entry['size'])
        actual = {}
        pending = [('', source)]
        while pending:
            relative, directory = pending.pop()
            for child in self._list(connection, directory):
                name = str(child.name)
                if name in ('', '.', '..') or '/' in name or '\\' in name:
                    raise BdmvCd2Error('CD2 文件名无效')
                if not getattr(child, 'isLocal', False):
                    raise BdmvCd2Error('CD2 源目录包含非本地条目')
                child_relative = str(PurePosixPath(relative) / name)
                if child.isDirectory:
                    pending.append((child_relative, str(PurePosixPath(directory) / name)))
                else:
                    if child_relative in actual:
                        raise BdmvCd2Error('CD2 源目录包含重复文件')
                    actual[child_relative] = int(child.size)
        if not expected or actual != expected:
            raise BdmvCd2Error('CD2 目录文件与完整种子清单不一致')

    def submit(self, source: str, target_parent: str, manifest: Optional[list[dict]] = None,
               before_submit: Optional[Callable[[], None]] = None) -> dict:
        """复制完整目录；目标已存在即拒绝，RPC 超时必须由队列先查证再决定重试。"""
        source, target_parent = _path(source), _path(target_parent)
        if source == '/':
            raise BdmvCd2Error('不能上传 CD2 根目录')
        connection = self._connection()
        self._source(connection, source)
        if manifest is not None:
            self._check_manifest(connection, source, manifest)
        self._target_parent(connection, target_parent)
        name = PurePosixPath(source).name
        if any(item.name == name for item in self._list(connection, target_parent)):
            raise BdmvCd2ConflictError('115 目标目录已存在，已停止提交以避免覆盖')
        request = connection[1].CopyFileRequest(
            theFilePaths=[source], destPath=target_parent,
            conflictPolicy=2, handleConflictRecursively=True,
        )
        self._check_stop()
        # 预检失败可安全重试；只在真正准备发送复制请求前保存提交意图。
        if before_submit is not None:
            before_submit()
        result = self._call(connection, 'CopyFile', request)
        if not result.success:
            raise BdmvCd2Error('CD2 未接受目录复制请求')
        return {'source': source, 'dest': target_parent,
                'result_paths': list(result.resultFilePaths)}

    def tasks(self) -> list[dict]:
        """查询可持久化的复制快照；保留 CD2 原始源/目标及纳秒时间用于唯一关联。"""
        connection = self._connection()
        reply = self._call(connection, 'GetCopyTasks', connection[2].Empty())
        fields = {'mode': 'taskMode', 'status': 'status', 'total': 'totalFiles',
                  'uploaded': 'uploadedFiles', 'failed': 'failedFiles',
                  'failed_folders': 'failedFolders', 'skipped': 'skippedFiles',
                  'cancelled': 'cancelledFiles', 'total_bytes': 'totalBytes',
                  'uploaded_bytes': 'uploadedBytes'}
        result = []
        for task in reply.copyTasks:
            row = {key: int(getattr(task, field)) for key, field in fields.items()}
            row.update(source=task.sourcePath, dest=task.destPath, paused=bool(task.paused),
                       start=f'{task.startTime.seconds}.{task.startTime.nanos:09d}',
                       errors=[error.message for error in task.errors])
            result.append(row)
        return result
