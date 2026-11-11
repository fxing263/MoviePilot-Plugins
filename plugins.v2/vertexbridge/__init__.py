"""将 Vertex 媒体识别、通知和聊天指令接入 MoviePilot。"""

import copy
import hashlib
import inspect
import re
import threading
import time
import uuid
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.schemas.types import EventType

try:
    from app.schemas.types import MessageType, NotificationChannel
except ImportError:
    from app.schemas.types import NotificationType as MessageType
    from app.schemas.types import MessageChannel as NotificationChannel

try:
    from app.sdk.events import Event, eventmanager
    from app.sdk.logging import logger
    from app.sdk.network import RequestUtils
    from app.sdk.plugin.base import _PluginBase
except ModuleNotFoundError as import_error:
    if not (import_error.name or "").startswith("app.sdk"):
        raise
    from app.core.event import Event, eventmanager
    from app.log import logger
    from app.plugins import _PluginBase
    from app.utils.http import RequestUtils


class BridgeNotification(BaseModel):
    """仅接收渲染后的通知文字，不接受用户指定的命令或收件人。"""

    title: str = Field(min_length=1, max_length=1000, description="通知标题")
    text: str = Field(default="", max_length=20000, description="通知正文")


class BridgeResponse(BaseModel):
    """返回是否已交给 MP 通知队列，不声称用户已收到。"""

    success: bool = Field(description="是否已接收")
    message: str = Field(default="", description="接收说明")


class RecognitionRequest(BaseModel):
    """只接收种子文字；不接收下载、整理或任意来源的执行参数。"""

    title: str = Field(min_length=1, max_length=4096)
    subtitle: str = Field(default="", max_length=8192)
    custom_words: Optional[str] = Field(default=None, max_length=8192)


class RecognitionResponse(BaseModel):
    """保留原生字段，避免宿主旧版 Context 响应模型裁掉质量信息。"""

    recognition_version: int = 2
    # 插件升级后 Vertex 据此把旧版本未匹配的条目自动重识别一次。
    bridge_version: str = ""
    meta_info: Dict[str, Any]
    source_meta_info: Dict[str, Any]
    media_info: Optional[Dict[str, Any]] = None


def _meta_snapshot(meta: Any) -> Dict[str, Any]:
    """用 MP 原生占位符匹配器输出列表，不修改宿主规则或全局分隔符。"""
    # 此匹配器没有 SDK 导出，使用 v2/v3 都保留的精确插件兼容入口。
    result = meta.to_dict()
    matcher = import_module("app.core.meta.customization").CustomizationMatcher()
    separator = matcher.custom_separator or "@"
    # 部分宿主加速器固定输出 @；从已应用识别词的 MP 原文调用同一个原生
    # 匹配器，避免把用户自定义分隔符或词条中的 @ 猜成边界。
    value = matcher.match(title=meta.org_string) or ""
    result["customization"] = value
    result["customization_items"] = list(dict.fromkeys(
        item.strip() for item in value.split(separator) if item.strip()
    ))
    return result


# 站点副标题常以分类前缀开头（韩剧：、动态漫:），只剥离以剧／漫／片／综艺／动画结尾的短前缀，
# 不误删「沙丘：预言」这类名字本身的冒号。
_SUBTITLE_TAG = re.compile(r"^[\u4e00-\u9fff]{0,4}(?:剧|漫|片|综艺|动画)\s*[:：]\s*")
_SUBTITLE_NOISE = re.compile(
    r"第\s*[0-9一二三四五六七八九十百千零]+(?:\s*[-~～至]\s*[0-9一二三四五六七八九十百千零]+)?\s*[季集期部话話]"
    r"|全\s*[0-9]+\s*[集话話期]|[0-9]+\s*集全|共\s*[0-9]+\s*[集话話期]"
    r"|\[[^\]]*\]|【[^】]*】|（[^）]*）|\([^)]*\)"
)


def _subtitle_name(subtitle: str) -> str:
    """取副标题首段的中文作品名；没有中文或过长时返回空，不猜测。"""
    head = re.split(r"[|｜]", subtitle or "", maxsplit=1)[0].strip()
    head = _SUBTITLE_TAG.sub("", head, count=1)
    head = re.split(r"\s*/\s*", head, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", _SUBTITLE_NOISE.sub(" ", head)).strip(" -_.·:：")
    if not name or len(name) > 60 or not re.search(r"[\u4e00-\u9fff]", name):
        return ""
    return name


def _recognize_native(payload: RecognitionRequest) -> RecognitionResponse:
    """在 MP 进程内使用原生解析和媒体链，原始季集在识别前独立快照。"""
    from app.chain.media import MediaChain

    try:
        from app.sdk.media import MetaInfo
    except ModuleNotFoundError as error:
        if not (error.name or "").startswith("app.sdk"):
            raise
        from app.core.metainfo import MetaInfo

    words = payload.custom_words.split("\n") if payload.custom_words else None
    # 旧版 MP 的空列表会回退全局识别词，用原生支持的注释词显式禁用替换。
    source = _meta_snapshot(MetaInfo(payload.title, payload.subtitle, custom_words=["# Vertex original coordinates"]))
    meta = MetaInfo(payload.title, payload.subtitle, custom_words=words)
    # 在媒体链执行前捕获解析时的分隔设置，不修改其它 MP 任务的全局状态。
    customization_meta = _meta_snapshot(meta)
    recognize = MediaChain().recognize_by_meta
    parameters = inspect.signature(recognize).parameters
    # 不同 MP 版本使用不同参数名；老版本无此参数时由原生链默认识别。
    kwargs = {"media_source": "themoviedb"} if "media_source" in parameters else {"source": "themoviedb"} if "source" in parameters else {}
    media = recognize(meta, **kwargs)
    if media is None:
        # MP 不用副标题里的中文名检索；英文／拼音名未命中时，以副标题中文名再走一次原生识别。
        # 只替换检索名称，季集、年份和质量仍来自原标题解析。
        name = _subtitle_name(payload.subtitle)
        if name and name != (meta.cn_name or ""):
            retry = copy.deepcopy(meta)
            retry.cn_name, retry.en_name = name, None
            media = recognize(retry, **kwargs)
            if media is not None:
                logger.info(f"Vertex 识别：英文名未命中，按副标题中文名「{name}」识别成功")
                meta = retry
    return RecognitionResponse(
        meta_info={**meta.to_dict(), "customization": customization_meta["customization"],
                   "customization_items": customization_meta["customization_items"]}, source_meta_info=source,
        media_info=media.to_dict() if media else None,
    )


def _probe_tmdb() -> bool:
    """宿主未公开最近请求状态；仅探测配置接口，异常不输出地址或凭据。"""
    response = None
    try:
        try:
            from app.sdk.config import settings
        except ModuleNotFoundError as error:
            if not (error.name or "").startswith("app.sdk"):
                raise
            from app.core.config import settings

        response = RequestUtils(
            ua=settings.NORMAL_USER_AGENT, proxies=settings.PROXY, timeout=5,
        ).get_res(
            url=f"https://{settings.TMDB_API_DOMAIN}/3/configuration",
            params={"api_key": settings.TMDB_API_KEY}, allow_redirects=False,
        )
        if response is None or response.status_code != 200:
            return False
        data = response.json()
        return isinstance(data, dict) and isinstance(data.get("images"), dict)
    except Exception:  # 宿主或传输层异常也不能把故障当成正常未匹配。
        return False
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """校验桥接地址和凭据，停用状态允许保留未填完的设置。"""
    result = {
        "enabled": config.get("enabled") is True,
        "recognition": config.get("recognition") is True,
        "commands": config.get("commands") is True,
        "vertex_url": str(config.get("vertex_url") or "").strip().rstrip("/"),
        "channel_id": str(config.get("channel_id") or "").strip(),
        "bridge_key": str(config.get("bridge_key") or "").strip(),
        "notify_channel": str(config.get("notify_channel") or ""),
        "notify_source": str(config.get("notify_source") or "").strip(),
        "notify_user": str(config.get("notify_user") or "").strip(),
    }
    if not result["enabled"]:
        return result
    if (
        result["notify_channel"]
        and result["notify_channel"] not in NotificationChannel.__members__
    ):
        raise ValueError("请选择有效的通知渠道")
    if (result["notify_source"] or result["notify_user"]) and not result[
        "notify_channel"
    ]:
        raise ValueError("指定通知服务或用户时，请先选择渠道")
    if result["commands"]:
        url = urlsplit(result["vertex_url"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("VT 地址须为 http(s)://主机:端口，不含账号或 /api 路径")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", result["channel_id"]):
            raise ValueError("请填写 VT 通知工具 ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", result["bridge_key"]):
            raise ValueError("桥接密钥须为 32–128 位字母、数字、下划线或短横线")
    return result


class VertexBridge(_PluginBase):
    """复用 MP 的通知渠道及命令事件，VT 保留执行和授权责任。"""

    plugin_name = "Vertex 桥接"
    plugin_desc = "提供 MP 原生媒体识别、VT 通知转发与 /vt 指令桥接。"
    plugin_icon = "mdi-transit-connection-variant"
    plugin_version = "1.3.1"
    plugin_author = "Vertex local"
    author_url = "https://github.com/vertex-app/vertex"
    plugin_config_prefix = "vertexbridge_"
    plugin_order = 50
    auth_level = 1

    def __init__(self) -> None:
        super().__init__()
        self._config = validate_config({})
        self._lock = threading.RLock()
        self._recent: Dict[str, float] = {}
        self._slots = threading.BoundedSemaphore(4)
        self._recognition_slot = threading.BoundedSemaphore(1)
        self._tmdb_probe_until = 0.0
        self._tmdb_probe_ok = False

    def init_plugin(self, config: Optional[Dict[str, Any]] = None) -> None:
        """配置校验失败时关闭桥接，不记录密钥或请求正文。"""
        try:
            checked = validate_config(config or {})
        except (ValueError, TypeError):
            checked = validate_config({})
            logger.error("Vertex 桥接配置无效，已停用，请检查地址、密钥和通知渠道")
        with self._lock:
            self._config = checked

    def get_state(self) -> bool:
        """返回当前桥接启用状态。"""
        return self._config["enabled"]

    def stop_service(self) -> None:
        """停止接收新任务；不创建轮询线程或定时任务。"""
        with self._lock:
            self._config = {**self._config, "enabled": False}

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """只注册 /vt 前缀，不占用 MP 的状态或下载命令。"""
        return [
            {
                "cmd": "/vt",
                "event": EventType.PluginAction,
                "desc": "Vertex 指令",
                "category": "Vertex",
                "data": {"action": "vertex_bridge_command"},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """通知与识别入口均由 MP API 令牌鉴权保护。"""
        return [
            {
                "path": "/notify",
                "endpoint": self.notify,
                "methods": ["POST"],
                "auth": "apikey",
                "summary": "接收 Vertex 通知",
                "response_model": BridgeResponse,
            },
            {
                "path": "/recognize",
                "endpoint": self.recognize,
                "methods": ["POST"],
                "auth": "apikey",
                "summary": "使用 MP 原生流程识别 Vertex 候选",
                "response_model": RecognitionResponse,
            },
        ]

    def recognize(self, payload: RecognitionRequest) -> RecognitionResponse:
        """同步路由由宿主线程池执行；繁忙即退回 VT 重试，不堆积识别任务。"""
        with self._lock:
            if not self._config["enabled"] or not self._config["recognition"]:
                raise HTTPException(status_code=503, detail="Vertex 桥接识别未启用")
            if not self._recognition_slot.acquire(blocking=False):
                raise HTTPException(status_code=429, detail="识别处理中，请稍后重试")
        try:
            result = _recognize_native(payload)
            result.bridge_version = self.plugin_version
            if result.media_info is None and not self._tmdb_available():
                raise HTTPException(status_code=503, detail="TMDB 暂不可用，请稍后重试")
            return result
        except HTTPException:
            raise
        except Exception as error:
            logger.error(f"Vertex 原生识别失败：{type(error).__name__}")
            raise HTTPException(status_code=502, detail="MP 原生识别失败，请查看插件日志") from None
        finally:
            self._recognition_slot.release()

    def _tmdb_available(self) -> bool:
        """在识别单并发槽内缓存探测结果 60 秒，成功识别不触发额外请求。"""
        if time.monotonic() >= self._tmdb_probe_until:
            self._tmdb_probe_ok = _probe_tmdb()
            self._tmdb_probe_until = time.monotonic() + 60
        return self._tmdb_probe_ok

    def notify(self, payload: BridgeNotification) -> BridgeResponse:
        """相同文字 60 秒内只入队一次，禁用时明确返回失败。"""
        digest = hashlib.sha256(
            (payload.title + "\0" + payload.text).encode()
        ).hexdigest()
        with self._lock:
            config = self._config
            if not config["enabled"]:
                raise HTTPException(status_code=503, detail="Vertex 桥接未启用")
            now = time.monotonic()
            self._recent = {
                key: stamp for key, stamp in self._recent.items() if now - stamp < 60
            }
            if digest in self._recent:
                return BridgeResponse(success=True, message="相同通知已接收")
            if len(self._recent) >= 200:
                raise HTTPException(status_code=429, detail="通知过多，请稍后重试")
            channel = (
                NotificationChannel[config["notify_channel"]]
                if config["notify_channel"]
                else None
            )
            self.post_message(
                channel=channel,
                source=config["notify_source"] or None,
                userid=config["notify_user"] or None,
                mtype=MessageType.Plugin,
                title="[VT] " + payload.title,
                text=payload.text,
            )
            self._recent[digest] = now
        return BridgeResponse(success=True, message="已交给 MP 通知队列")

    def _request(
        self,
        config: Dict[str, Any],
        channel: NotificationChannel,
        user: str,
        argument: str,
    ) -> Tuple[str, str]:
        parts = argument.strip().split(maxsplit=1)
        command = parts[0] if parts else "help"
        args = parts[1:]  # 下载器别名可以包含空格。
        response = None
        try:
            response = RequestUtils(
                headers={"X-Vertex-Key": config["bridge_key"]}, timeout=40, verify=True
            ).post_res(
                url=config["vertex_url"] + "/api/openapi/moviepilot/command",
                json={
                    "channelId": config["channel_id"],
                    "requestId": uuid.uuid4().hex,
                    "issuedAt": int(time.time() * 1000),
                    "command": command,
                    "args": args,
                    "user": {"channel": channel.name, "userId": user},
                },
                allow_redirects=False,
                raise_exception=True,
            )
            if response is None:
                raise ValueError("no response")
            if len(response.content) > 100000:
                raise ValueError("oversized response")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("invalid response")
            if not 200 <= response.status_code < 300 or body.get("success") is not True:
                if response.status_code == 403:
                    return "Vertex 拒绝指令", (
                        f"请在 VT 允许用户中添加 {channel.name}:{user}；"
                        "暂停／恢复删种还需开启「允许控制」。"
                    )
                if response.status_code == 401:
                    return (
                        "Vertex 连接配置错误",
                        "请检查通知工具 ID、桥接密钥和 VT 的「接收 MP 指令」开关。",
                    )
                if response.status_code == 400:
                    return (
                        "Vertex 指令无效",
                        "请发送 /vt 帮助，并检查两机时间是否一致。",
                    )
                if response.status_code == 429:
                    return "Vertex 繁忙", "命令未受理，请稍后查询状态。"
                raise ValueError("request rejected")
            data = body.get("data")
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("title"), str)
                or not isinstance(data.get("lines"), list)
                or not all(isinstance(line, str) for line in data["lines"])
            ):
                raise ValueError("invalid reply")
            text = "\n".join(data["lines"])[:12000]
            if command in {"help", "帮助"}:
                text = re.sub(r"(?m)^/", "/vt ", text)
            return data["title"][:200], text
        except Exception as error:
            # Transport exceptions may contain keys/URLs. Only log the class.
            logger.warning(f"Vertex 桥接请求失败：{type(error).__name__}")
            return (
                "Vertex 请求未确认",
                "连接失败、超时或接口响应异常；未自动重试。控制指令可能已执行，请先用 /vt 状态核实。",
            )
        finally:
            if response is not None:
                response.close()

    @eventmanager.register(EventType.PluginAction)
    def command(self, event: Event) -> None:
        """从 MP 已识别的发送者身份转发指令，回复原渠道的该用户。"""
        data = event.event_data if event else None
        if not isinstance(data, dict) or data.get("action") != "vertex_bridge_command":
            return
        config = self._config
        channel, user = data.get("channel"), data.get("user")
        if (
            not isinstance(channel, NotificationChannel)
            or user is None
            or not str(user).strip()
        ):
            return  # 不把无法定位用户的控制回复广播出去。
        user = str(user)
        if not config["enabled"] or not config["commands"]:
            title, text = "Vertex 桥接未启用", "请在 MP 插件中开启桥接和指令转发。"
        elif not self._slots.acquire(blocking=False):
            title, text = "Vertex 桥接繁忙", "请稍后再试。"
        else:
            try:
                argument = data.get("arg_str") or ""
                if not isinstance(argument, str) or len(argument) > 240:
                    title, text = "Vertex 指令无效", "指令过长，请发送 /vt 帮助。"
                else:
                    title, text = self._request(config, channel, user, argument)
            finally:
                self._slots.release()
        self.post_message(
            channel=channel,
            source=data.get("source"),
            userid=user,
            title="[VT] " + title,
            text=text,
        )

    def get_form(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """提供连接配置与通知去向，不收集下载器或站点凭据。"""
        fields = [
            ("VSwitch", "enabled", "启用插件", {}),
            ("VSwitch", "recognition", "为 VT 提供媒体识别", {}),
            ("VSwitch", "commands", "转发 /vt 指令", {}),
            (
                "VTextField",
                "vertex_url",
                "VT 地址",
                {"placeholder": "http://192.168.1.10:3000"},
            ),
            ("VTextField", "channel_id", "VT 通知工具 ID", {}),
            ("VTextField", "bridge_key", "桥接密钥", {"type": "password"}),
            (
                "VSelect",
                "notify_channel",
                "通知渠道",
                {
                    "items": [{"title": "按 MP 通知设置", "value": ""}]
                    + [
                        {"title": channel.value, "value": channel.name}
                        for channel in NotificationChannel
                    ]
                },
            ),
            ("VTextField", "notify_source", "通知服务 ID（可选）", {}),
            ("VTextField", "notify_user", "通知用户 ID（可选）", {}),
        ]
        content = [
            {"component": component, "props": {"model": model, "label": label, **props}}
            for component, model, label, props in fields
        ]
        content.append(
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal"},
                "text": "仅识别：开启媒体识别，在 VT 候选设置填写 MP 后端地址及系统 API 令牌，无需填写 VT 地址或开启指令。通知需在 MP 渠道允许插件消息；指令另配桥接密钥及 VT 允许用户。",
            }
        )
        return [{"component": "VForm", "content": content}], validate_config({})

    def get_page(self) -> List[Dict[str, Any]]:
        """显示支持的命令和当前状态，不展示密钥。"""
        return [
            {
                "component": "VAlert",
                "props": {"type": "info", "variant": "tonal"},
                "text": ("已启用。" if self.get_state() else "未启用。")
                + "指令：/vt 帮助、/vt 状态、/vt 候选、/vt 硬链接、/vt 删种预览 qb、/vt 暂停删种 qb、/vt 恢复删种 qb。",
            }
        ]
