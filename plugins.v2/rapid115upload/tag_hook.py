"""只在 qB 待整理查询中下推标签，复用宿主的状态检查和任务构造。"""

from contextvars import ContextVar
from functools import wraps
from inspect import signature
from threading import RLock
from typing import Any, Optional
from weakref import WeakKeyDictionary

from packaging.version import Version

from app.chain.transfer.settlement import TransferSettlementOwner
from app.modules.qbittorrent import QbittorrentModule
from app.modules.qbittorrent.qbittorrent import Qbittorrent
from app.schemas.types import TorrentStatus
from app.sdk.logging import logger
from app.sdk.services import DownloaderHelper


_PATCH_LOCK = RLock()
_STATE_ATTRIBUTE = "_qbittorrent_tag_monitor_state"
_MIN_TAG_API = Version("2.8.3")
_PENDING_TAG = "未整理"
_COMPLETED_TAG = "已整理"
_COMPLETION_CHECK = "_TransferChain__is_torrent_download_completed"


class TagMonitorHook:
    """管理一份插件配置；停用后在途查询保留原配置，新查询恢复宿主行为。

    此处是明确的宿主内部挂钩边界：依赖 qB 模块 list_torrents、transfer_completed
    和客户端 get_torrents；仅在选中 qB 的整种子完成检查中忽略宿主标签，
    不修改 SDK 全局方法、下载器连接或宿主配置。
    """

    def __init__(
        self, *, downloaders: tuple[str, ...], include_tags: tuple[str, ...],
        exclude_tags: tuple[str, ...] = (),
    ) -> None:
        if isinstance(include_tags, str) or isinstance(exclude_tags, str):
            raise ValueError("标签白名单和黑名单必须使用标签列表")
        for tag in (*include_tags, *exclude_tags):
            if not isinstance(tag, str) or not tag.strip() or any(char in tag for char in ",\r\n"):
                raise ValueError("每项须为一个非空标签，不支持项内逗号或换行")
        if not include_tags:
            raise ValueError("标签白名单不能为空")
        self.downloaders = tuple(dict.fromkeys(downloaders))
        self.include_tags = tuple(dict.fromkeys(tag.strip() for tag in include_tags))
        self.exclude_tags = frozenset(tag.strip() for tag in exclude_tags)
        self._state: Optional[_HookState] = None

    @property
    def installed(self) -> bool:
        """仅当前配置仍拥有全部挂钩时报告生效。"""
        with _PATCH_LOCK:
            return bool(
                self._state
                and self._state.owner is self
                and QbittorrentModule.list_torrents is self._state.list_wrapper
                and Qbittorrent.get_torrents is self._state.query_wrapper
                and QbittorrentModule.transfer_completed is self._state.completed_wrapper
                and getattr(TransferSettlementOwner, _COMPLETION_CHECK) is self._state.check_wrapper
            )

    def install(self, previous: Optional["TagMonitorHook"] = None) -> None:
        """原子安装或替换调用方原配置；失败时不撤销已生效的查询限制。"""
        with _PATCH_LOCK:
            if self.installed:
                return
            state = getattr(Qbittorrent.get_torrents, _STATE_ATTRIBUTE, None)
            if state is None:
                state = _HookState()
            elif not hasattr(state, "check_wrapper"):
                raise RuntimeError("旧版本标签查询尚未退出，请稍后重新启用插件")
            state.attach(self, previous)
            self._state = state

    def stop(self) -> None:
        """立即停止接管新查询，在途请求结束后再恢复内层方法，不等待网络。"""
        with _PATCH_LOCK:
            state = self._state
            if state is None or state.owner is not self:
                return
            state.owner = None
            state.restore_outer()
            if not state.active_calls:
                state.restore_inner()


class _HookState:
    """让配置热更新共享挂钩和在途计数，查询上下文在各线程间隔离。"""

    def __init__(self) -> None:
        self.original_list = QbittorrentModule.list_torrents
        self.original_query = Qbittorrent.get_torrents
        self.original_completed = QbittorrentModule.transfer_completed
        self.original_check = getattr(TransferSettlementOwner, _COMPLETION_CHECK)
        self.list_signature = signature(self.original_list)
        self.query_signature = signature(self.original_query)
        self.completed_signature = signature(self.original_completed)
        if not {"status", "hashs", "downloader"}.issubset(self.list_signature.parameters):
            raise RuntimeError("当前 qB 模块的种子查询接口不兼容")
        if not {"ids", "status", "tags"}.issubset(self.query_signature.parameters):
            raise RuntimeError("当前 qB 客户端的种子查询接口不兼容")
        if not {"hashs", "downloader"}.issubset(self.completed_signature.parameters):
            raise RuntimeError("当前 qB 模块的整理完成接口不兼容")
        self.owner: Optional[TagMonitorHook] = None
        self.active_calls = 0
        self.scope: ContextVar[Optional[tuple[Any, tuple[str, ...], frozenset[str]]]] = ContextVar(
            "qbittorrent_tag_monitor_scope", default=None
        )
        self.api_versions: WeakKeyDictionary = WeakKeyDictionary()
        self.version_lock = RLock()
        self.list_wrapper = self._make_list_wrapper()
        self.query_wrapper = self._make_query_wrapper()
        self.completed_wrapper = self._make_completed_wrapper()
        self.check_wrapper = self._make_check_wrapper()

    def attach(self, owner: TagMonitorHook, previous: Optional[TagMonitorHook]) -> None:
        """拒绝并存插件分身或未知替换，复用停用后尚未排空的查询状态。"""
        if self.owner is not None and self.owner is not owner and self.owner is not previous:
            raise RuntimeError("已有 qB 标签监控实例生效，请先停用该实例")
        if (
            QbittorrentModule.list_torrents not in (self.original_list, self.list_wrapper)
            or Qbittorrent.get_torrents not in (self.original_query, self.query_wrapper)
            or QbittorrentModule.transfer_completed not in (self.original_completed, self.completed_wrapper)
            or getattr(TransferSettlementOwner, _COMPLETION_CHECK) not in (self.original_check, self.check_wrapper)
        ):
            raise RuntimeError("qB 查询方法已被其他插件替换，无法安装标签监控")
        Qbittorrent.get_torrents = self.query_wrapper
        QbittorrentModule.list_torrents = self.list_wrapper
        QbittorrentModule.transfer_completed = self.completed_wrapper
        setattr(TransferSettlementOwner, _COMPLETION_CHECK, self.check_wrapper)
        self.owner = owner

    def restore_outer(self) -> None:
        """只撤销自己仍拥有的外层方法，保留其他插件后来安装的包装。"""
        if QbittorrentModule.list_torrents is self.list_wrapper:
            QbittorrentModule.list_torrents = self.original_list
        if QbittorrentModule.transfer_completed is self.completed_wrapper:
            QbittorrentModule.transfer_completed = self.original_completed
        if getattr(TransferSettlementOwner, _COMPLETION_CHECK) is self.check_wrapper:
            setattr(TransferSettlementOwner, _COMPLETION_CHECK, self.original_check)

    def _make_check_wrapper(self):
        @wraps(self.original_check)
        def check_completed(chain, download_hash, downloader):
            with _PATCH_LOCK:
                owner = self.owner
            if owner is None or not downloader or (owner.downloaders and downloader not in owner.downloaders):
                return self.original_check(chain, download_hash, downloader)
            try:
                if DownloaderHelper().get_service(downloader, type_filter="qbittorrent") is None:
                    return self.original_check(chain, download_hash, downloader)
                # 未携带内置标签的种子也必须能完成结算；普通按 Hash 查询仍保留宿主规则。
                torrents = chain.list_torrents(
                    hashs=download_hash, downloader=downloader, include_all_tags=True,
                )
                if not torrents:
                    logger.warning(f"qB 标签监控：{downloader}/{download_hash} 未查询到种子，暂不标记已整理")
                    return False
                return all((torrent.progress or 0) >= 100 for torrent in torrents)
            except Exception as error:
                logger.error(f"qB 标签监控：{downloader}/{download_hash} 完成状态检查失败：{error}")
                return False

        return check_completed

    def _make_completed_wrapper(self):
        @wraps(self.original_completed)
        def transfer_completed(module, *args, **kwargs):
            bound = self.completed_signature.bind(module, *args, **kwargs)
            with _PATCH_LOCK:
                owner = self.owner
            result = self.original_completed(*bound.args, **bound.kwargs)
            if owner is not None and _PENDING_TAG in owner.include_tags:
                self._remove_pending_tag(
                    module, bound.arguments.get("downloader"), bound.arguments.get("hashs"), owner,
                )
            return result

        setattr(transfer_completed, _STATE_ATTRIBUTE, self)
        return transfer_completed

    @staticmethod
    def _remove_pending_tag(module, downloader: Optional[str], torrent_hash: Any, owner: TagMonitorHook) -> None:
        """按明确的下载器和单个 Hash 确认宿主标记，再移除种子上的未整理标签。

        宿主打标签方法吞掉网络异常，因此不能仅凭调用返回就删除待处理标记。
        跟随宿主的整种子结算语义（包括其跳过/终态规则），不从单文件事件推断成功。
        """
        if not downloader or (owner.downloaders and downloader not in owner.downloaders):
            return
        if (
            not isinstance(torrent_hash, str) or not torrent_hash.strip()
            or torrent_hash.lower() == "all" or any(char in torrent_hash for char in "|,\r\n")
        ):
            return
        try:
            client = module.get_instance(downloader)
            if client is None or client.qbc is None:
                logger.warning(f"qB 标签监控：{downloader} 连接不可用，保留未整理标签")
                return
            qbc = client.qbc
            torrents = qbc.torrents_info(torrent_hashes=torrent_hash)
            target = next((
                row for row in torrents or []
                if str(row.get("hash") or "").lower() == torrent_hash.lower()
            ), None)
            tags = {tag.strip() for tag in (target.get("tags") or "").split(",")} if target else set()
            if _COMPLETED_TAG not in tags:
                logger.warning(f"qB 标签监控：{downloader}/{torrent_hash} 未确认已整理标记，保留未整理标签")
                return
            if _PENDING_TAG not in tags:
                return
            if module.get_instance(downloader) is not client or client.qbc is not qbc:
                logger.warning(f"qB 标签监控：{downloader} 连接已更新，保留未整理标签")
                return
            # 只解除目标种子上的标签，不能调用删除全局标签定义的 delete_torrents_tag。
            if client.remove_torrents_tag(ids=torrent_hash, tag=[_PENDING_TAG]):
                logger.info(f"qB 标签监控：{downloader}/{torrent_hash} 已移除未整理标签")
            else:
                logger.warning(f"qB 标签监控：{downloader}/{torrent_hash} 移除未整理标签失败，请重试")
        except Exception as error:
            logger.error(f"qB 标签监控：{downloader}/{torrent_hash} 标签收尾失败，保留未整理标签：{error}")

    def restore_inner(self) -> None:
        """全部在途查询退出后才能撤销标签下推，避免中途退回无标签查询。"""
        if Qbittorrent.get_torrents is self.query_wrapper:
            Qbittorrent.get_torrents = self.original_query

    def _make_list_wrapper(self):
        @wraps(self.original_list)
        def list_torrents(module, *args, **kwargs):
            bound = self.list_signature.bind(module, *args, **kwargs)
            status = bound.arguments.get("status")
            status_text = str(getattr(status, "value", status) or "").strip().lower()
            if bound.arguments.get("hashs") or status_text not in {"transfer", TorrentStatus.TRANSFER.value}:
                return self.original_list(*bound.args, **bound.kwargs)
            with _PATCH_LOCK:
                owner = self.owner
                if owner is not None:
                    self.active_calls += 1
            if owner is None:
                return self.original_list(*bound.args, **bound.kwargs)
            try:
                return self._list_selected(module, bound, owner)
            finally:
                with _PATCH_LOCK:
                    self.active_calls -= 1
                    if self.owner is None and not self.active_calls:
                        self.restore_inner()

        setattr(list_torrents, _STATE_ATTRIBUTE, self)
        return list_torrents

    def _list_selected(self, module, bound, owner: TagMonitorHook) -> list:
        requested = bound.arguments.get("downloader")
        # 每轮读取实例快照，宿主重连或配置热更新后不保留过期客户端。
        instances = module.get_instances()
        names = (requested,) if requested else (owner.downloaders or tuple(instances))
        results = []
        for name in names:
            if owner.downloaders and name not in owner.downloaders:
                continue
            client = instances.get(name)
            if client is None:
                continue
            token = self.scope.set((client, owner.include_tags, owner.exclude_tags))
            try:
                bound.arguments["downloader"] = name
                results.extend(self.original_list(*bound.args, **bound.kwargs) or [])
            finally:
                self.scope.reset(token)
        return results

    def _make_query_wrapper(self):
        @wraps(self.original_query)
        def get_torrents(client, *args, **kwargs):
            scope = self.scope.get()
            if scope is None:
                return self.original_query(client, *args, **kwargs)
            bound = self.query_signature.bind(client, *args, **kwargs)
            if bound.arguments.get("ids") or bound.arguments.get("status") != "completed":
                return self.original_query(*bound.args, **bound.kwargs)
            if scope[0] is not client:
                # 宿主在枚举与查询之间换了连接实例时跳过本轮，不能扩大查询范围。
                logger.warning("qB 标签监控：下载器实例已更新，等待下轮查询")
                return [], True
            return self._query_tags(client, scope[1], scope[2])

        setattr(get_torrents, _STATE_ATTRIBUTE, self)
        return get_torrents

    def _query_tags(
        self, client, include_tags: tuple[str, ...], exclude_tags: frozenset[str],
    ) -> tuple[list, bool]:
        query_tags = tuple(tag for tag in include_tags if tag not in exclude_tags)
        if not query_tags:
            return [], False
        qbc = client.qbc
        if qbc is None:
            return [], True
        try:
            with self.version_lock:
                version = self.api_versions.get(qbc)
                if version is None:
                    version = Version(str(qbc.app_web_api_version()))
                    self.api_versions[qbc] = version
            if version < _MIN_TAG_API:
                logger.warning(f"qB 标签查询需要 Web API >= {_MIN_TAG_API}，当前为 {version}，跳过本轮")
                return [], True
            # 已由插件白黑名单决定范围，不再叠加宿主 TORRENT_TAG。
            candidates = {}
            blocked = set()
            returned = 0
            for tag in query_tags:
                torrents = qbc.torrents_info(status_filter="completed", tag=tag)
                returned += len(torrents or [])
                for torrent in torrents or []:
                    torrent_tags = {part.strip() for part in (torrent.get("tags") or "").split(",")}
                    torrent_hash = torrent.get("hash")
                    if not torrent_hash:
                        continue
                    # 多次响应之间标签可能变化，任何一次命中黑名单都撤销本轮候选。
                    if exclude_tags.intersection(torrent_tags):
                        blocked.add(torrent_hash)
                        candidates.pop(torrent_hash, None)
                        continue
                    if (
                        torrent_hash in blocked or tag not in torrent_tags
                    ):
                        continue
                    candidates[torrent_hash] = torrent
            results = list(candidates.values())
            logger.debug(f"qB 标签监控：{len(query_tags)} 个白名单标签返回 {returned} 项，过滤去重后 {len(results)} 项")
            return results, False
        except Exception as error:
            # 失败不能重试为无标签查询，否则会重新引入全量扫描。
            logger.error(f"qB 标签监控查询失败，等待下轮重试：{error}")
            return [], True
