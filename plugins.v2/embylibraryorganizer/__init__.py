import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from apscheduler.triggers.cron import CronTrigger

from app.chain.storage import StorageChain
from app.db.mediaserver_oper import MediaServerOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MediaType, NotificationType

from .core import (
    ActionType,
    CloudVerifyStatus,
    ConfigValidationIssue,
    EmbyLibraryOrganizerEngine,
    IssueLevel,
    LibraryFile,
    MediaKeyResolver,
    OrganizerConfig,
    OrganizerPlan,
    PlanAction,
    PlanBuilder,
    QuarantineManager,
    ReportExporter,
    STRM_SUFFIX,
    STORAGE_115_NAME,
    StrmParser,
    config_from_dict,
    execution_report_to_dict,
    owned_sidecar_paths,
    plan_from_dict,
    plan_to_dict,
    validate_config,
)


SECONDARY_CATEGORY_ROOT_TYPES = {
    "电影": "movie",
    "电视剧": "tv",
    "剧集": "tv",
    "动漫": "anime",
}
SXXEXX_EPISODE_PATTERN = re.compile(r"(?i)(S\d{1,2}E)(\d{1,3})")
CHINESE_EPISODE_PATTERN = re.compile(r"第(\d{1,3})(集|话)")


class EmbyLibraryOrganizer(_PluginBase):
    """Emby媒体库整理插件。"""

    _MAX_VISIBLE_METADATA_FILES = 200
    _OVERVIEW_SAMPLE_SIZE = 5
    _DETAIL_PAGE_SIZE = 20

    plugin_name = "Emby媒体库整理"
    plugin_desc = (
        "巡检基于115 STRM方案建立的Emby媒体库，识别重复、生成整理计划，"
        "并在确认后安全清理本地与115文件。"
    )
    plugin_icon = (
        "https://raw.githubusercontent.com/jxxghp/MoviePilot-Frontend/"
        "refs/heads/v2/src/assets/images/misc/emby.png"
    )
    plugin_version = "1.0.2"
    plugin_label = "媒体库整理"
    plugin_author = "zhaojg"
    plugin_config_prefix = "embylibraryorganizer_"
    plugin_order = 45
    auth_level = 2

    _enabled = False
    _config: Dict[str, Any] = {}
    _latest_plan: Optional[OrganizerPlan] = None
    _task_status = "idle"
    _last_error = ""

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态。"""
        self.stop_service()
        self._config = self._merge_defaults(config or {})
        self._enabled = bool(self._config.get("enabled", False))
        self._latest_plan = self._load_latest_plan()

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表。"""
        return [
            {
                "path": "/scan",
                "endpoint": self.api_scan,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "扫描媒体库并生成整理计划",
                "description": "扫描配置的Emby媒体库，返回重复识别结果和整理计划。",
            },
            {
                "path": "/scan_orphan_metadata",
                "endpoint": self.api_scan_orphan_metadata,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "扫描多余元数据文件",
                "description": "仅检查电影目录和电视剧季目录中的多余元数据并生成清理计划。",
            },
            {
                "path": "/scan_missing_metadata",
                "endpoint": self.api_scan_missing_metadata,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "查询STRM缺失元数据",
                "description": "仅查询所选二级分类中缺少NFO或MediaInfo的STRM。",
            },
            {
                "path": "/categories",
                "endpoint": self.api_get_categories,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取媒体库二级分类",
                "description": "返回从已配置媒体库路径识别出的二级分类。",
            },
            {
                "path": "/view",
                "endpoint": self.api_set_page_view,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "切换插件详情视图",
                "description": "在概览和缺失元数据完整结果之间切换并设置页码。",
            },
            {
                "path": "/delete_missing_strm",
                "endpoint": self.api_delete_missing_strm,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理缺失元数据的STRM",
                "description": "清理指定STRM，并可选择联动清理其现有文件级元数据。",
            },
            {
                "path": "/delete_episode_group",
                "endpoint": self.api_delete_episode_group,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理同格式剧集STRM",
                "description": "清理同一季目录中仅集号不同的STRM及其文件级元数据。",
            },
            {
                "path": "/validate",
                "endpoint": self.api_validate,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "校验插件配置",
                "description": "校验媒体库路径、删除保护和删除数量等关键配置。",
            },
            {
                "path": "/plan",
                "endpoint": self.api_get_plan,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取最近整理计划",
                "description": "返回最近一次扫描生成的整理计划。",
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取插件任务状态",
                "description": "返回当前扫描或执行状态。",
            },
            {
                "path": "/execute",
                "endpoint": self.api_execute,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行最近整理计划",
                "description": "在确认后执行最近一次整理计划。",
            },
            {
                "path": "/confirm_token",
                "endpoint": self.api_confirm_token,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取高风险确认token",
                "description": "为最近整理计划生成115云端删除确认token。",
            },
            {
                "path": "/preflight",
                "endpoint": self.api_preflight,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "预检115删除动作",
                "description": "只读校验最近计划中的115云端删除动作，不执行删除。",
            },
            {
                "path": "/actions",
                "endpoint": self.api_actions,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询整理动作",
                "description": "按类型、风险和状态过滤最近整理计划中的动作。",
            },
            {
                "path": "/groups",
                "endpoint": self.api_groups,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询重复分组",
                "description": "返回重复分组及其关联整理动作，供人工审查。",
            },
            {
                "path": "/group/keep",
                "endpoint": self.api_set_group_keep,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "设置重复分组保留项",
                "description": "按重复分组指定保留路径，并重新生成该组整理动作。",
            },
            {
                "path": "/issues",
                "endpoint": self.api_issues,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询巡检问题",
                "description": "按问题代码和级别过滤最近整理计划中的巡检问题。",
            },
            {
                "path": "/mediaserver_check",
                "endpoint": self.api_mediaserver_check,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "媒体服务器缓存对照",
                "description": "使用MoviePilot本地媒体服务器缓存对照最近扫描计划。",
            },
            {
                "path": "/action",
                "endpoint": self.api_update_action,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "更新整理动作状态",
                "description": "根据 action_id 启用或禁用整理动作。",
            },
            {
                "path": "/actions/update",
                "endpoint": self.api_update_actions,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "批量更新整理动作状态",
                "description": "按动作ID或筛选条件批量启用或禁用整理动作。",
            },
            {
                "path": "/quarantine",
                "endpoint": self.api_quarantine,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询隔离区",
                "description": "列出本插件隔离区中的可恢复文件。",
            },
            {
                "path": "/restore",
                "endpoint": self.api_restore,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "恢复隔离文件",
                "description": "将隔离区文件恢复到原始路径。",
            },
            {
                "path": "/restore_batch",
                "endpoint": self.api_restore_batch,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "按批次恢复隔离文件",
                "description": "将同一执行批次的隔离文件恢复到原始路径。",
            },
            {
                "path": "/clean_quarantine",
                "endpoint": self.api_clean_quarantine,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理过期隔离文件",
                "description": "按保留天数删除插件隔离区中的过期文件。",
            },
            {
                "path": "/history",
                "endpoint": self.api_history,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取整理历史",
                "description": "返回最近的扫描和执行历史。",
            },
            {
                "path": "/execution",
                "endpoint": self.api_execution,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询最近执行结果",
                "description": "按状态、动作类型和云端快照过滤最近执行结果。",
            },
            {
                "path": "/clear_history",
                "endpoint": self.api_clear_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理整理历史",
                "description": "清理扫描历史、执行历史和最近计划。",
            },
            {
                "path": "/clear_reports",
                "endpoint": self.api_clear_reports,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理导出报告",
                "description": "删除插件数据目录下的导出报告文件。",
            },
            {
                "path": "/export",
                "endpoint": self.api_export,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导出最近整理计划",
                "description": "导出最近一次整理计划，支持 json、csv、markdown。",
            },
            {
                "path": "/export_execution",
                "endpoint": self.api_export_execution,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导出最近执行报告",
                "description": "导出最近一次整理执行报告，包含115删除前校验快照。",
            },
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
        return self._form_schema(), self._default_config()

    def get_page(self) -> Optional[List[dict]]:
        """返回插件详情页面。"""
        page_state = self.get_data("page_state") or {}
        if page_state.get("mode") == "missing_metadata":
            return self._missing_metadata_detail_page(
                int(page_state.get("page") or 1)
            )
        latest = self._latest_plan_data()
        orphan_plan = self.get_data("latest_orphan_plan") or latest
        missing_plan = self.get_data("latest_missing_plan") or latest
        summary = latest.get("summary") or {}
        latest_execution = self.get_data("latest_execution") or {}
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "多余元数据扫描用于清理孤儿文件；缺失元数据查询按所选二级分类查找缺少NFO或MediaInfo的STRM。",
                },
            },
            {
                "component": "VTable",
                "content": [
                    {
                        "component": "tbody",
                        "content": [
                            self._summary_row("扫描文件", summary.get("file_count", 0)),
                            self._summary_row("STRM数量", summary.get("strm_count", 0)),
                            self._summary_row(
                                "多余元数据",
                                (summary.get("issue_code_counts") or {}).get(
                                    "orphan_sidecar",
                                    0,
                                ),
                            ),
                            self._summary_row("清理动作", summary.get("action_count", 0)),
                            self._summary_row(
                                "缺失元数据STRM",
                                self._missing_metadata_strm_count(missing_plan),
                            ),
                        ],
                    }
                ],
            },
            self._orphan_metadata_table(orphan_plan, latest_execution),
            self._missing_metadata_table(missing_plan),
            {
                "component": "VBtn",
                "props": {
                    "color": "info",
                    "variant": "tonal",
                    "block": True,
                    "class": "mt-4",
                    "prepend-icon": "mdi-format-list-bulleted",
                },
                "text": "查看全部缺失项",
                "events": {
                    "click": {
                        "api": "plugin/EmbyLibraryOrganizer/view?mode=missing_metadata&page=1",
                        "method": "post",
                    },
                },
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "block": True,
                                    "prepend-icon": "mdi-magnify-scan",
                                },
                                "text": "扫描多余元数据",
                                "events": {
                                    "click": {
                                        "api": "plugin/EmbyLibraryOrganizer/scan_orphan_metadata",
                                        "method": "post",
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "info",
                                    "block": True,
                                    "prepend-icon": "mdi-file-search-outline",
                                },
                                "text": "查询缺失元数据",
                                "events": {
                                    "click": {
                                        "api": "plugin/EmbyLibraryOrganizer/scan_missing_metadata",
                                        "method": "post",
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "secondary",
                                    "block": True,
                                    "prepend-icon": "mdi-file-export",
                                },
                                "text": "导出JSON",
                                "events": {
                                    "click": {
                                        "api": "plugin/EmbyLibraryOrganizer/export?file_type=json",
                                        "method": "post",
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "warning",
                                    "block": True,
                                    "prepend-icon": "mdi-shield-check",
                                },
                                "text": "确认执行",
                                "events": {
                                    "click": {
                                        "api": "plugin/EmbyLibraryOrganizer/execute?confirmed=true",
                                        "method": "post",
                                    },
                                },
                            }
                        ],
                    },
                ],
            },
        ]

    def get_dashboard_meta(self) -> Optional[List[Dict[str, str]]]:
        """返回插件仪表盘元信息。"""
        return [
            {
                "key": "summary",
                "name": "媒体库整理摘要",
            }
        ]

    def get_dashboard(
        self,
        key: str = "summary",
        **kwargs: Any,
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], Optional[List[dict]]]]:
        """返回插件仪表盘组件。"""
        if key != "summary":
            return None
        latest = self._latest_plan_data()
        summary = latest.get("summary") or {}
        return (
            {"cols": 12, "md": 6},
            {
                "refresh": 30,
                "border": True,
                "title": "Emby媒体库整理",
                "subtitle": f"状态：{self._task_status}",
            },
            [
                {
                    "component": "VRow",
                    "content": [
                        self._dashboard_metric("STRM", summary.get("strm_count", 0)),
                        self._dashboard_metric("问题", summary.get("issue_count", 0)),
                        self._dashboard_metric(
                            "重复",
                            summary.get("duplicate_group_count", 0),
                        ),
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        self._dashboard_metric(
                            "允许动作",
                            summary.get("allowed_action_count", 0),
                        ),
                        self._dashboard_metric(
                            "阻断动作",
                            summary.get("blocked_action_count", 0),
                        ),
                        self._dashboard_metric(
                            "高风险",
                            summary.get("high_risk_action_count", 0),
                        ),
                    ],
                },
            ],
        )

    def get_service(self) -> List[Dict[str, Any]]:
        """返回插件定时服务列表。"""
        if not self._enabled:
            return []
        cron = str(self._config.get("cron") or "").strip()
        if not cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(cron)
        except ValueError as err:
            logger.error(f"【{self.plugin_name}】定时扫描Cron配置无效：{str(err)}")
            return []
        return [
            {
                "id": "emby_library_organizer_scan",
                "name": "Emby媒体库整理扫描",
                "trigger": trigger,
                "func": self.scan_once,
                "kwargs": {},
            }
        ]

    def stop_service(self) -> None:
        """停止插件后台服务。"""
        return None

    def api_scan(self) -> Dict[str, Any]:
        """扫描媒体库并生成整理计划。"""
        return self.scan_once()

    def api_scan_orphan_metadata(self) -> Dict[str, Any]:
        """仅扫描多余元数据并生成清理计划。"""
        return self._scan_and_save(orphan_metadata_only=True)

    def api_scan_missing_metadata(self) -> Dict[str, Any]:
        """查询所选二级分类中缺失元数据的STRM。"""
        return self._scan_and_save(missing_metadata_only=True)

    def api_get_categories(self) -> Dict[str, Any]:
        """返回自动识别的媒体库二级分类。"""
        return {
            "code": 0,
            "msg": "",
            "data": self._discover_secondary_categories(),
        }

    def api_set_page_view(
        self,
        mode: str = "overview",
        page: int = 1,
    ) -> Dict[str, Any]:
        """切换详情页视图并保存当前页码。"""
        if mode not in ("overview", "missing_metadata"):
            mode = "overview"
        page = max(int(page or 1), 1)
        self.save_data("page_state", {"mode": mode, "page": page})
        return {"code": 0, "msg": "", "data": {"mode": mode, "page": page}}

    def api_delete_missing_strm(
        self,
        path: str,
        include_sidecars: bool = False,
    ) -> Dict[str, Any]:
        """清理缺失元数据查询结果中的指定STRM及可选联动文件。"""
        missing_plan = self.get_data("latest_missing_plan") or {}
        candidate_paths = {
            str(issue.get("path") or "")
            for issue in missing_plan.get("issues") or []
            if issue.get("code") in ("missing_nfo", "missing_mediainfo")
        }
        if path not in candidate_paths:
            return {"code": 1, "msg": "该STRM不在当前缺失元数据查询结果中"}
        strm_path = Path(path).expanduser()
        if (
            strm_path.is_symlink()
            or not strm_path.is_file()
            or strm_path.suffix.lower() != STRM_SUFFIX
        ):
            return {"code": 1, "msg": "STRM文件不存在或类型无效，请重新查询"}
        organizer_config = config_from_dict(self._config)
        resolved_path = strm_path.resolve()
        if not any(
            self._path_is_within(resolved_path, root.expanduser().resolve())
            for root in organizer_config.library_paths
        ):
            return {"code": 1, "msg": "STRM路径不在已配置媒体库内"}
        cleanup_paths = [resolved_path]
        if include_sidecars:
            cleanup_paths.extend(owned_sidecar_paths(resolved_path))
        return self._execute_manual_cleanup(
            cleanup_paths=cleanup_paths,
            organizer_config=organizer_config,
            strm_count=1,
        )

    def api_delete_episode_group(self, path: str) -> Dict[str, Any]:
        """清理电视剧季目录中仅集号不同的同格式STRM及联动文件。"""
        missing_plan = self.get_data("latest_missing_plan") or {}
        candidate_paths = {
            str(issue.get("path") or "")
            for issue in missing_plan.get("issues") or []
            if issue.get("code") in ("missing_nfo", "missing_mediainfo")
        }
        if path not in candidate_paths:
            return {"code": 1, "msg": "该STRM不在当前缺失元数据查询结果中"}
        strm_path = Path(path).expanduser()
        if strm_path.is_symlink() or not strm_path.is_file():
            return {"code": 1, "msg": "STRM文件不存在，请重新查询"}
        resolved_path = strm_path.resolve()
        if (
            self._category_library_type(resolved_path) != "tv"
            or not resolved_path.parent.name.casefold().startswith("season ")
        ):
            return {"code": 1, "msg": "同格式整组清理仅支持电视剧季目录"}
        template = self._episode_name_template(resolved_path.stem)
        if not template:
            return {"code": 1, "msg": "文件名未识别到SxxExx或第X集格式"}
        matched_strm_paths = sorted(
            candidate.resolve()
            for candidate in resolved_path.parent.iterdir()
            if not candidate.is_symlink()
            and candidate.is_file()
            and candidate.suffix.lower() == STRM_SUFFIX
            and self._episode_name_template(candidate.stem) == template
        )
        organizer_config = config_from_dict(self._config)
        if len(matched_strm_paths) > organizer_config.max_delete_count:
            return {
                "code": 1,
                "msg": (
                    f"同格式匹配到{len(matched_strm_paths)}个STRM，超过单次最大删除数量"
                    f"{organizer_config.max_delete_count}"
                ),
            }
        cleanup_paths: List[Path] = []
        for matched_path in matched_strm_paths:
            cleanup_paths.append(matched_path)
            cleanup_paths.extend(owned_sidecar_paths(matched_path))
        cleanup_paths = list(dict.fromkeys(cleanup_paths))
        return self._execute_manual_cleanup(
            cleanup_paths=cleanup_paths,
            organizer_config=organizer_config,
            strm_count=len(matched_strm_paths),
        )

    def api_validate(self) -> Dict[str, Any]:
        """校验插件配置。"""
        issues = [
            *validate_config(config_from_dict(self._config)),
            *self._validate_cron(self._config),
        ]
        return {
            "code": 0,
            "msg": "",
            "data": [plan_to_dict(issue) for issue in issues],
        }

    def api_get_plan(self) -> Dict[str, Any]:
        """获取最近一次整理计划。"""
        data = self._latest_plan_data()
        return {
            "code": 0,
            "msg": "",
            "data": data,
        }

    def api_execute(
        self,
        confirmed: bool = False,
        confirm_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行最近一次整理计划。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可执行的整理计划，请先扫描",
            }
        self._task_status = "executing"
        self._last_error = ""
        try:
            storage_chain = StorageChain()
            engine = EmbyLibraryOrganizerEngine(config_from_dict(self._config))
            report = engine.execute_plan(
                plan=self._latest_plan,
                data_path=self.get_data_path(),
                confirmed=confirmed,
                confirm_token=confirm_token,
                expected_confirm_token=self._plan_confirm_token(self._latest_plan),
                cloud_delete_func=storage_chain.delete_file,
                cloud_verify_func=storage_chain.get_file_item,
            )
            data = execution_report_to_dict(report)
            self.save_data("latest_execution", data)
            self._append_history("execution_history", data)
            self._post_execution_notice(data)
            self._task_status = "idle"
            return {
                "code": 0,
                "msg": "执行完成",
                "data": data,
            }
        except Exception as err:
            self._task_status = "failed"
            self._last_error = str(err)
            logger.error(f"【{self.plugin_name}】执行失败：{str(err)}")
            return {"code": 1, "msg": f"执行失败：{str(err)}"}

    def api_confirm_token(self) -> Dict[str, Any]:
        """获取最近整理计划的高风险确认token。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可确认的整理计划，请先扫描",
            }
        cloud_actions = [
            action
            for action in self._latest_plan.actions
            if action.allowed and action.action_type == ActionType.DELETE_CLOUD_FILE
        ]
        return {
            "code": 0,
            "msg": "",
            "data": {
                "token": self._plan_confirm_token(self._latest_plan),
                "required": bool(cloud_actions) and not self._latest_plan.dry_run,
                "cloud_delete_count": len(cloud_actions),
                "task_id": self._latest_plan.task_id,
            },
        }

    def api_preflight(self) -> Dict[str, Any]:
        """只读预检最近计划中的115删除动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可预检的整理计划，请先扫描",
            }
        storage_chain = StorageChain()
        results = []
        for action in self._latest_plan.actions:
            if action.action_type != ActionType.DELETE_CLOUD_FILE:
                continue
            results.append(
                self._preflight_cloud_action(
                    action=action,
                    cloud_verify_func=storage_chain.get_file_item,
                )
            )
        data = plan_to_dict(self._latest_plan)
        self.save_data("latest_plan", data)
        return {
            "code": 0,
            "msg": "预检完成",
            "data": {
                "task_id": self._latest_plan.task_id,
                "count": len(results),
                "found_count": len(
                    [
                        result
                        for result in results
                        if result.get("verify_status") == CloudVerifyStatus.FOUND.value
                    ]
                ),
                "results": results,
                "plan": data,
            },
        }

    def api_status(self) -> Dict[str, Any]:
        """获取插件任务状态。"""
        latest_summary = {}
        if self._latest_plan:
            latest_summary = self._latest_plan.summary
        return {
            "code": 0,
            "msg": "",
            "data": {
                "enabled": self._enabled,
                "status": self._task_status,
                "last_error": self._last_error,
                "latest_summary": latest_summary,
            },
        }

    def api_actions(
        self,
        action_type: Optional[str] = None,
        risk: Optional[str] = None,
        allowed: Optional[bool] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询最近整理计划中的动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可查询的整理计划，请先扫描",
            }
        actions = self._filter_actions(
            action_type=action_type,
            risk=risk,
            allowed=allowed,
            group_id=group_id,
        )
        return {
            "code": 0,
            "msg": "",
            "data": [plan_to_dict(action) for action in actions],
        }

    def api_groups(
        self,
        duplicate_type: Optional[str] = None,
        risk: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询最近整理计划中的重复分组和关联动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可查询的整理计划，请先扫描",
            }
        groups = self._filter_groups(risk=risk)
        if duplicate_type:
            groups = [
                group
                for group in groups
                if group.duplicate_type.value == duplicate_type
            ]
        actions_by_group: Dict[str, List[Any]] = {}
        for action in self._latest_plan.actions:
            if not action.group_id:
                continue
            actions_by_group.setdefault(action.group_id, []).append(action)
        return {
            "code": 0,
            "msg": "",
            "data": [
                {
                    **plan_to_dict(group),
                    "actions": [
                        plan_to_dict(action)
                        for action in actions_by_group.get(group.group_id, [])
                    ],
                }
                for group in groups
            ],
        }

    def api_set_group_keep(self, group_id: str, keep_path: str) -> Dict[str, Any]:
        """设置重复分组保留路径并重建该组动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可更新的整理计划，请先扫描",
            }
        group = self._find_duplicate_group(group_id)
        if not group:
            return {
                "code": 1,
                "msg": "重复分组不存在",
            }
        if keep_path not in group.all_paths:
            return {
                "code": 1,
                "msg": "保留路径不属于该重复分组",
            }
        if keep_path == group.keep_path:
            return {
                "code": 0,
                "msg": "保留路径未变化",
                "data": plan_to_dict(self._latest_plan),
            }
        old_keep_path = group.keep_path
        group.keep_path = keep_path
        group.candidate_paths = [path for path in group.all_paths if path != keep_path]
        self._mark_group_score_keep(group)
        files = self._library_files_from_group(group)
        builder = PlanBuilder(config_from_dict(self._config))
        new_group_actions = builder.rebuild_group_actions(
            task_id=self._latest_plan.task_id,
            group=group,
            files=files,
        )
        self._latest_plan.actions = [
            action
            for action in self._latest_plan.actions
            if action.group_id != group.group_id
        ] + new_group_actions
        self._latest_plan.summary = self._refresh_plan_summary(self._latest_plan)
        data = plan_to_dict(self._latest_plan)
        self.save_data("latest_plan", data)
        return {
            "code": 0,
            "msg": "重复分组保留项已更新",
            "data": {
                "old_keep_path": old_keep_path,
                "new_keep_path": keep_path,
                "plan": data,
            },
        }

    def api_issues(
        self,
        issue_code: Optional[str] = None,
        issue_level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询最近整理计划中的巡检问题。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可查询的整理计划，请先扫描",
            }
        issues = self._filter_issues(issue_code=issue_code, issue_level=issue_level)
        return {
            "code": 0,
            "msg": "",
            "data": [plan_to_dict(issue) for issue in issues],
        }

    def api_mediaserver_check(self, scope: str = "all") -> Dict[str, Any]:
        """使用本地媒体服务器缓存对照最近扫描计划。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可对照的整理计划，请先扫描",
            }
        oper = MediaServerOper()
        results = []
        media_key_items = self._mediaserver_check_media_keys(scope=scope)
        for media_key, paths in media_key_items:
            parsed = MediaKeyResolver.parse(media_key)
            item_id = self._query_mediaserver_item_id(oper, parsed)
            results.append(
                {
                    "media_key": media_key,
                    "exists": bool(item_id),
                    "item_id": item_id,
                    "kind": parsed.get("kind", ""),
                    "tmdbid": parsed.get("tmdbid", ""),
                    "imdbid": parsed.get("imdbid", ""),
                    "tvdbid": parsed.get("tvdbid", ""),
                    "path_count": len(paths),
                    "paths": paths,
                }
            )
        return {
            "code": 0,
            "msg": "",
            "data": {
                "scope": scope,
                "total": len(results),
                "matched": len([item for item in results if item["exists"]]),
                "missing": len([item for item in results if not item["exists"]]),
                "items": results,
            },
        }

    def api_update_action(self, action_id: str, enabled: bool = True) -> Dict[str, Any]:
        """启用或禁用最近整理计划中的动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可更新的整理计划，请先扫描",
            }
        for action in self._latest_plan.actions:
            if action.action_id != action_id:
                continue
            state, message = self._set_action_enabled(action, enabled)
            if not state:
                return {
                    "code": 1,
                    "msg": message,
                }
            data = plan_to_dict(self._latest_plan)
            self.save_data("latest_plan", data)
            return {
                "code": 0,
                "msg": "动作已更新",
                "data": data,
            }
        return {
            "code": 1,
            "msg": "动作不存在",
        }

    def api_update_actions(
        self,
        enabled: bool = True,
        action_ids: Optional[List[str]] = None,
        action_type: Optional[str] = None,
        risk: Optional[str] = None,
        allowed: Optional[bool] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量启用或禁用最近整理计划中的动作。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可更新的整理计划，请先扫描",
            }
        selected_actions = self._select_actions_for_update(
            action_ids=action_ids,
            action_type=action_type,
            risk=risk,
            allowed=allowed,
            group_id=group_id,
        )
        updated = []
        skipped = []
        for action in selected_actions:
            state, message = self._set_action_enabled(action, enabled)
            item = {
                "action_id": action.action_id,
                "path": action.path,
                "message": message,
            }
            if state:
                updated.append(item)
            else:
                skipped.append(item)
        known_ids = {action.action_id for action in self._latest_plan.actions}
        requested_ids = set(action_ids or [])
        not_found = sorted(requested_ids - known_ids)
        data = plan_to_dict(self._latest_plan)
        self.save_data("latest_plan", data)
        return {
            "code": 0,
            "msg": "批量动作已更新",
            "data": {
                "updated": updated,
                "skipped": skipped,
                "not_found": not_found,
                "plan": data,
            },
        }

    def api_quarantine(self) -> Dict[str, Any]:
        """查询插件隔离区文件。"""
        manager = QuarantineManager(self.get_data_path())
        return {
            "code": 0,
            "msg": "",
            "data": [plan_to_dict(item) for item in manager.list_items()],
        }

    def api_restore(self, backup_path: str, overwrite: bool = False) -> Dict[str, Any]:
        """恢复隔离区文件。"""
        manager = QuarantineManager(self.get_data_path())
        state, message = manager.restore(Path(backup_path), overwrite=overwrite)
        return {
            "code": 0 if state else 1,
            "msg": "恢复完成" if state else message,
            "data": {
                "path": message if state else "",
            },
        }

    def api_restore_batch(self, batch_id: str, overwrite: bool = False) -> Dict[str, Any]:
        """按执行批次恢复隔离区文件。"""
        manager = QuarantineManager(self.get_data_path())
        data = manager.restore_batch(batch_id=batch_id, overwrite=overwrite)
        failed = data.get("failed") or []
        return {
            "code": 1 if failed else 0,
            "msg": "批次恢复完成" if not failed else "批次恢复存在失败项",
            "data": data,
        }

    def api_clean_quarantine(self, retention_days: Optional[int] = None) -> Dict[str, Any]:
        """清理超过保留天数的隔离区文件。"""
        manager = QuarantineManager(self.get_data_path())
        days = int(retention_days or self._config.get("quarantine_retention_days") or 30)
        count, paths = manager.clean_expired(days)
        return {
            "code": 0,
            "msg": "隔离区清理完成",
            "data": {
                "count": count,
                "paths": paths,
                "retention_days": days,
            },
        }

    def api_history(self) -> Dict[str, Any]:
        """获取整理历史。"""
        return {
            "code": 0,
            "msg": "",
            "data": {
                "scan_history": self.get_data("scan_history") or [],
                "execution_history": self.get_data("execution_history") or [],
            },
        }

    def api_execution(
        self,
        status: Optional[str] = None,
        action_type: Optional[str] = None,
        has_cloud_snapshot: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """查询最近一次整理执行结果。"""
        execution_report = self.get_data("latest_execution")
        if not execution_report:
            return {
                "code": 1,
                "msg": "没有可查询的执行报告，请先执行整理计划",
            }
        results = self._filter_execution_results(
            execution_report.get("results") or [],
            status=status,
            action_type=action_type,
            has_cloud_snapshot=has_cloud_snapshot,
        )
        return {
            "code": 0,
            "msg": "",
            "data": {
                **execution_report,
                "results": results,
                "filtered_count": len(results),
            },
        }

    def api_clear_history(self) -> Dict[str, Any]:
        """清理扫描、执行历史和最近计划。"""
        for key in ("scan_history", "execution_history", "latest_plan", "latest_execution"):
            self.del_data(key)
        self._latest_plan = None
        return {
            "code": 0,
            "msg": "历史已清理",
        }

    def api_clear_reports(self) -> Dict[str, Any]:
        """清理导出报告文件。"""
        report_dir = self.get_data_path() / "reports"
        count = 0
        if report_dir.exists():
            for path in report_dir.iterdir():
                if path.is_file():
                    path.unlink()
                    count += 1
        return {
            "code": 0,
            "msg": "报告已清理",
            "data": {
                "count": count,
            },
        }

    def api_export(
        self,
        file_type: str = "json",
        report_scope: str = "all",
        action_type: Optional[str] = None,
        risk: Optional[str] = None,
        allowed: Optional[bool] = None,
        group_id: Optional[str] = None,
        issue_code: Optional[str] = None,
        issue_level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """导出最近一次整理计划。"""
        if not self._latest_plan:
            return {
                "code": 1,
                "msg": "没有可导出的整理计划，请先扫描",
            }
        exporter = ReportExporter()
        report_dir = self.get_data_path() / "reports"
        file_type = str(file_type or "json").lower()
        report_scope = str(report_scope or "all").lower()
        if report_scope not in ("all", "actions", "issues", "groups"):
            report_scope = "all"
        actions = self._filter_actions(
            action_type=action_type,
            risk=risk,
            allowed=allowed,
            group_id=group_id,
        )
        issues = self._filter_issues(issue_code=issue_code, issue_level=issue_level)
        groups = self._filter_groups(group_id=group_id, risk=risk)
        filter_suffix = self._export_filter_suffix(
            action_type,
            risk,
            allowed,
            group_id,
            issue_code,
            issue_level,
            report_scope,
        )
        if file_type == "csv":
            if report_scope == "issues":
                output_path = exporter.export_issues_csv(
                    self._latest_plan,
                    report_dir / f"{self._latest_plan.task_id}{filter_suffix}.csv",
                    issues=issues,
                )
            elif report_scope == "groups":
                output_path = exporter.export_groups_csv(
                    self._latest_plan,
                    report_dir / f"{self._latest_plan.task_id}{filter_suffix}.csv",
                    duplicate_groups=groups,
                )
            else:
                output_path = exporter.export_csv(
                    self._latest_plan,
                    report_dir / f"{self._latest_plan.task_id}{filter_suffix}.csv",
                    actions=actions,
                )
        elif file_type in ("md", "markdown"):
            output_path = exporter.export_markdown(
                self._latest_plan,
                report_dir / f"{self._latest_plan.task_id}{filter_suffix}.md",
                actions=actions,
                issues=issues,
                duplicate_groups=groups,
            )
        else:
            output_path = exporter.export_json(
                self._latest_plan,
                report_dir / f"{self._latest_plan.task_id}{filter_suffix}.json",
                actions=actions,
                issues=issues,
                duplicate_groups=groups,
            )
        return {
            "code": 0,
            "msg": "导出完成",
            "data": {
                "path": output_path.as_posix(),
            },
        }

    def api_export_execution(
        self,
        file_type: str = "json",
        status: Optional[str] = None,
        action_type: Optional[str] = None,
        has_cloud_snapshot: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """导出最近一次整理执行报告。"""
        execution_report = self.get_data("latest_execution")
        if not execution_report:
            return {
                "code": 1,
                "msg": "没有可导出的执行报告，请先执行整理计划",
            }
        exporter = ReportExporter()
        task_id = str(execution_report.get("task_id") or "execution")
        file_type = str(file_type or "json").lower()
        results = self._filter_execution_results(
            execution_report.get("results") or [],
            status=status,
            action_type=action_type,
            has_cloud_snapshot=has_cloud_snapshot,
        )
        filter_suffix = self._export_filter_suffix(
            action_type=action_type,
            risk=None,
            allowed=None,
            group_id=None,
            issue_code=status,
            issue_level="cloud_snapshot" if has_cloud_snapshot else None,
            report_scope="execution",
        )
        output_stem = f"{task_id}{filter_suffix}"
        report_dir = self.get_data_path() / "reports"
        if file_type == "csv":
            output_path = exporter.export_execution_csv(
                execution_report,
                report_dir / f"{output_stem}.csv",
                results=results,
            )
        elif file_type in ("md", "markdown"):
            output_path = exporter.export_execution_markdown(
                execution_report,
                report_dir / f"{output_stem}.md",
                results=results,
            )
        else:
            output_path = exporter.export_execution_json(
                execution_report,
                report_dir / f"{output_stem}.json",
                results=results,
            )
        return {
            "code": 0,
            "msg": "执行报告导出完成",
            "data": {
                "path": output_path.as_posix(),
                "filtered_count": len(results),
            },
        }

    def scan_once(self) -> Dict[str, Any]:
        """执行一次媒体库扫描并保存计划。"""
        return self._scan_and_save(orphan_metadata_only=False)

    def _scan_and_save(
        self,
        orphan_metadata_only: bool = False,
        missing_metadata_only: bool = False,
    ) -> Dict[str, Any]:
        """按指定范围扫描媒体库并保存计划。"""
        self._task_status = "scanning"
        self._last_error = ""
        try:
            organizer_config = config_from_dict(self._config)
            if missing_metadata_only:
                category_paths, category_error = self._selected_category_paths()
                if category_error:
                    self._task_status = "failed"
                    self._last_error = category_error
                    logger.warning(f"【{self.plugin_name}】缺失元数据查询未启动：{category_error}")
                    return {"code": 1, "msg": category_error}
                organizer_config.library_paths = category_paths
                organizer_config.library_types = {
                    path.as_posix(): self._category_library_type(path)
                    for path in category_paths
                }
                organizer_config.clean_trash_files = False
                organizer_config.delete_duplicate_strm = False
                organizer_config.delete_sidecar_files = False
                organizer_config.delete_orphan_sidecar_files = False
                organizer_config.delete_empty_dirs = False
                organizer_config.sync_delete_115 = False
            if orphan_metadata_only:
                organizer_config.clean_trash_files = False
                organizer_config.delete_duplicate_strm = False
                organizer_config.delete_sidecar_files = False
                organizer_config.delete_orphan_sidecar_files = True
                organizer_config.delete_empty_dirs = False
                organizer_config.sync_delete_115 = False
            validation_issues = validate_config(organizer_config)
            errors = [
                issue
                for issue in validation_issues
                if issue.level == IssueLevel.ERROR
            ]
            if errors:
                self._task_status = "failed"
                self._last_error = errors[0].message
                logger.warning(
                    f"【{self.plugin_name}】扫描未启动，配置校验失败："
                    f"{errors[0].message}"
                )
                return {
                    "code": 1,
                    "msg": errors[0].message,
                    "data": [plan_to_dict(issue) for issue in validation_issues],
                }
            engine = EmbyLibraryOrganizerEngine(organizer_config)
            if missing_metadata_only:
                self._latest_plan = engine.create_missing_metadata_plan()
            elif orphan_metadata_only:
                self._latest_plan = engine.create_orphan_metadata_plan()
            else:
                self._latest_plan = engine.create_plan()
            data = plan_to_dict(self._latest_plan)
            self.save_data("latest_plan", data)
            if missing_metadata_only:
                self.save_data("latest_missing_plan", data)
            elif orphan_metadata_only:
                self.save_data("latest_orphan_plan", data)
            self._append_history("scan_history", data)
            self._task_status = "idle"
            return {
                "code": 0,
                "msg": "扫描完成",
                "data": data,
            }
        except Exception as err:
            self._task_status = "failed"
            self._last_error = str(err)
            logger.error(f"【{self.plugin_name}】扫描失败：{str(err)}")
            return {"code": 1, "msg": f"扫描失败：{str(err)}"}

    def _selected_category_paths(self) -> Tuple[List[Path], Optional[str]]:
        """返回配置中选定且仍然有效的二级分类路径。"""
        selected = self._config.get("missing_metadata_categories") or []
        if isinstance(selected, str):
            selected = [line.strip() for line in selected.splitlines() if line.strip()]
        available = {
            item["value"]: item
            for item in self._discover_secondary_categories()
        }
        selected_paths = [
            Path(value)
            for value in selected
            if str(value) in available
        ]
        if not selected_paths:
            return [], "请先在插件配置中选择至少一个二级分类"
        return selected_paths, None

    def _discover_secondary_categories(self) -> List[Dict[str, str]]:
        """从配置的媒体库根目录识别电影、电视剧和动漫二级分类。"""
        organizer_config = config_from_dict(self._config)
        categories: Dict[str, Dict[str, str]] = {}
        for library_root in organizer_config.library_paths:
            root = library_root.expanduser().resolve()
            if not root.is_dir():
                continue
            library_type = organizer_config.library_types.get(root.as_posix(), "mixed")
            if library_type in ("movie", "tv", "anime"):
                category_parents = [(root, library_type, root.name)]
            else:
                category_parents = []
                try:
                    media_roots = sorted(
                        (path for path in root.iterdir() if path.is_dir()),
                        key=lambda path: path.name.casefold(),
                    )
                except OSError:
                    continue
                for media_root in media_roots:
                    detected_type = SECONDARY_CATEGORY_ROOT_TYPES.get(media_root.name)
                    if detected_type:
                        category_parents.append(
                            (media_root, detected_type, media_root.name)
                        )
            for category_parent, category_type, parent_label in category_parents:
                try:
                    category_paths = sorted(
                        (path for path in category_parent.iterdir() if path.is_dir()),
                        key=lambda path: path.name.casefold(),
                    )
                except OSError:
                    continue
                for category_path in category_paths:
                    resolved_path = category_path.resolve()
                    value = resolved_path.as_posix()
                    categories[value] = {
                        "title": f"{parent_label} / {category_path.name}",
                        "value": value,
                        "type": category_type,
                    }
        return sorted(categories.values(), key=lambda item: item["title"])

    @staticmethod
    def _category_library_type(path: Path) -> str:
        """根据分类路径推断媒体库类型。"""
        for part in reversed(path.parts):
            library_type = SECONDARY_CATEGORY_ROOT_TYPES.get(part)
            if library_type:
                return library_type
        return "mixed"

    @staticmethod
    def _path_is_within(path: Path, root: Path) -> bool:
        """判断路径是否位于指定媒体库根目录内。"""
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _manual_delete_action(
        task_id: str,
        path: Path,
        action_type: ActionType,
    ) -> PlanAction:
        """生成详情页手动清理动作并记录源文件快照。"""
        stat = path.stat()
        return PlanAction(
            action_id=(
                f"manual-{task_id}-"
                f"{hashlib.sha256(path.as_posix().encode('utf-8')).hexdigest()[:16]}"
            ),
            action_type=action_type,
            path=path.as_posix(),
            source_size=stat.st_size,
            source_modify_time=stat.st_mtime,
            source_sha1=hashlib.sha1(path.read_bytes()).hexdigest(),
            allowed=True,
            risk="medium",
            reason="用户在缺失元数据详情页手动选择清理",
        )

    def _execute_manual_cleanup(
        self,
        cleanup_paths: List[Path],
        organizer_config: OrganizerConfig,
        strm_count: int,
    ) -> Dict[str, Any]:
        """执行详情页手动清理并重新查询缺失元数据。"""
        task_id = datetime.now().strftime("%Y%m%d%H%M%S")
        actions = [
            self._manual_delete_action(
                task_id=task_id,
                path=cleanup_path,
                action_type=(
                    ActionType.DELETE_LOCAL_STRM
                    if cleanup_path.suffix.lower() == STRM_SUFFIX
                    else ActionType.DELETE_SIDECAR
                ),
            )
            for cleanup_path in cleanup_paths
        ]
        plan = OrganizerPlan(
            task_id=task_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            dry_run=organizer_config.dry_run,
            require_confirm=False,
            issues=[],
            duplicate_groups=[],
            actions=actions,
            summary={},
        )
        report = EmbyLibraryOrganizerEngine(organizer_config).execute_plan(
            plan=plan,
            data_path=self.get_data_path(),
            confirmed=True,
        )
        execution_data = execution_report_to_dict(report)
        self.save_data("latest_execution", execution_data)
        self._append_history("execution_history", execution_data)
        refresh_result = self._scan_and_save(missing_metadata_only=True)
        if report.dry_run:
            message = f"演练完成：匹配{strm_count}个STRM，未删除文件"
        else:
            message = f"清理完成：处理{strm_count}个STRM"
        return {
            "code": 0,
            "msg": message,
            "data": {
                "strm_count": strm_count,
                "execution": execution_data,
                "refresh": refresh_result,
            },
        }

    @staticmethod
    def _episode_name_template(stem: str) -> Optional[Tuple[str, str]]:
        """将单个剧集集号替换为占位符以比较同格式文件名。"""
        sxxexx_matches = list(SXXEXX_EPISODE_PATTERN.finditer(stem))
        if len(sxxexx_matches) == 1:
            normalized = SXXEXX_EPISODE_PATTERN.sub(
                lambda match: f"{match.group(1)}#",
                stem,
                count=1,
            )
            return "sxxexx", normalized.casefold()
        chinese_matches = list(CHINESE_EPISODE_PATTERN.finditer(stem))
        if len(chinese_matches) == 1:
            normalized = CHINESE_EPISODE_PATTERN.sub(
                lambda match: f"第#{match.group(2)}",
                stem,
                count=1,
            )
            return "chinese", normalized.casefold()
        return None

    def _load_latest_plan(self) -> Optional[OrganizerPlan]:
        """从插件数据中恢复最近一次整理计划。"""
        data = self.get_data("latest_plan")
        if not data:
            return None
        try:
            return plan_from_dict(data)
        except Exception as err:
            logger.warning(f"【{self.plugin_name}】恢复整理计划失败：{str(err)}")
            return None

    def _latest_plan_data(self) -> Dict[str, Any]:
        """读取持久化的最新计划并同步当前插件实例。"""
        data = self.get_data("latest_plan") or {}
        if data:
            try:
                self._latest_plan = plan_from_dict(data)
            except Exception as err:
                logger.warning(f"【{self.plugin_name}】读取最新整理计划失败：{str(err)}")
            return data
        if self._latest_plan:
            return plan_to_dict(self._latest_plan)
        return {}

    def _append_history(self, key: str, item: Dict[str, Any]) -> None:
        """追加并裁剪插件历史记录。"""
        history = self.get_data(key) or []
        history.insert(0, item)
        max_history = int(self._config.get("max_history") or 20)
        self.save_data(key, history[:max_history])

    def _filter_actions(
        self,
        action_type: Optional[str] = None,
        risk: Optional[str] = None,
        allowed: Optional[bool] = None,
        group_id: Optional[str] = None,
    ) -> List[Any]:
        """按查询参数过滤整理动作。"""
        if not self._latest_plan:
            return []
        actions = self._latest_plan.actions
        if action_type:
            actions = [
                action
                for action in actions
                if action.action_type.value == action_type
            ]
        if risk:
            actions = [action for action in actions if action.risk == risk]
        if allowed is not None:
            actions = [action for action in actions if action.allowed == allowed]
        if group_id:
            actions = [action for action in actions if action.group_id == group_id]
        return actions

    @staticmethod
    def _preflight_cloud_action(action: Any, cloud_verify_func: Any) -> Dict[str, Any]:
        """预检单个115云端删除动作。"""
        result = {
            "action_id": action.action_id,
            "path": action.path,
            "cloud_file_id": action.cloud_file_id or "",
            "cloud_path": action.cloud_path or "",
            "allowed": action.allowed,
            "skip_reason": action.skip_reason or "",
            "verify_status": action.cloud_verify_status.value,
            "message": "",
        }
        if not action.allowed:
            result["message"] = action.skip_reason or "动作未被允许执行"
            return result
        if not action.cloud_file_id:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = "缺少115 file_id"
            return result
        if not action.cloud_path:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = "缺少115云端路径"
            return result
        try:
            file_item = cloud_verify_func(STORAGE_115_NAME, Path(action.cloud_path))
        except Exception as err:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = f"115文件校验失败：{str(err)}"
            return result
        if not file_item:
            action.cloud_verify_status = CloudVerifyStatus.MISSING
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = "115文件不存在"
            return result
        if not file_item.fileid:
            action.cloud_verify_status = CloudVerifyStatus.FAILED
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = "115文件校验结果缺少file_id"
            return result
        if str(file_item.fileid) != str(action.cloud_file_id):
            action.cloud_verify_status = CloudVerifyStatus.MISMATCHED
            result["verify_status"] = action.cloud_verify_status.value
            result["message"] = "115文件ID与计划不一致"
            result["verified_file_id"] = str(file_item.fileid or "")
            result["verified_path"] = str(file_item.path or "")
            return result
        action.cloud_verify_status = CloudVerifyStatus.FOUND
        result["verify_status"] = action.cloud_verify_status.value
        result["message"] = "115文件校验通过"
        result["verified_file_id"] = str(file_item.fileid or "")
        result["verified_path"] = str(file_item.path or "")
        result["verified_name"] = str(file_item.name or "")
        return result

    def _select_actions_for_update(
        self,
        action_ids: Optional[List[str]] = None,
        action_type: Optional[str] = None,
        risk: Optional[str] = None,
        allowed: Optional[bool] = None,
        group_id: Optional[str] = None,
    ) -> List[Any]:
        """按动作ID或筛选条件选择待更新动作。"""
        if not self._latest_plan:
            return []
        if action_ids:
            action_id_set = set(action_ids)
            return [
                action
                for action in self._latest_plan.actions
                if action.action_id in action_id_set
            ]
        return self._filter_actions(
            action_type=action_type,
            risk=risk,
            allowed=allowed,
            group_id=group_id,
        )

    def _find_duplicate_group(self, group_id: str) -> Optional[Any]:
        """按分组ID查找重复分组。"""
        if not self._latest_plan:
            return None
        for group in self._latest_plan.duplicate_groups:
            if group.group_id == group_id:
                return group
        return None

    @staticmethod
    def _mark_group_score_keep(group: Any) -> None:
        """更新重复组评分明细中的保留标记。"""
        score_details = getattr(group, "score_details", None) or []
        for item in score_details:
            item["keep"] = item.get("path") == group.keep_path

    def _library_files_from_group(self, group: Any) -> List[LibraryFile]:
        """按重复分组路径构造动作重建所需文件记录。"""
        parser = StrmParser(config_from_dict(self._config).custom_identity_patterns)
        files = []
        for path_text in group.all_paths:
            path = Path(path_text)
            content = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
            identity = parser.parse(content) if content.strip() else None
            stat = path.stat() if path.exists() else None
            library_root = self._matching_library_root(path)
            files.append(
                LibraryFile(
                    path=path,
                    library_root=library_root,
                    relative_path=self._relative_path(path, library_root),
                    suffix=path.suffix.lower() or STRM_SUFFIX,
                    size=stat.st_size if stat else 0,
                    modify_time=stat.st_mtime if stat else 0,
                    content=content,
                    identity=identity,
                    media_key=group.key if group.key.startswith(("movie:", "episode:")) else None,
                )
            )
        return files

    def _matching_library_root(self, path: Path) -> Path:
        """返回路径所属媒体库根目录。"""
        config = config_from_dict(self._config)
        resolved = path.expanduser().resolve()
        for library_root in config.library_paths:
            root = library_root.expanduser().resolve()
            try:
                resolved.relative_to(root)
                return root
            except ValueError:
                continue
        return path.parent

    @staticmethod
    def _relative_path(path: Path, library_root: Path) -> str:
        """计算相对媒体库路径。"""
        try:
            return path.relative_to(library_root).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _refresh_plan_summary(plan: OrganizerPlan) -> Dict[str, Any]:
        """刷新人工调整后的整理计划摘要。"""
        summary = dict(plan.summary)
        summary.update(
            {
                "duplicate_group_count": len(plan.duplicate_groups),
                "reference_duplicate_count": len(
                    [
                        group
                        for group in plan.duplicate_groups
                        if group.duplicate_type.value == "reference"
                    ]
                ),
                "media_duplicate_count": len(
                    [
                        group
                        for group in plan.duplicate_groups
                        if group.duplicate_type.value == "media"
                    ]
                ),
                "action_count": len(plan.actions),
                "allowed_action_count": len(
                    [action for action in plan.actions if action.allowed]
                ),
                "blocked_action_count": len(
                    [action for action in plan.actions if not action.allowed]
                ),
                "high_risk_action_count": len(
                    [action for action in plan.actions if action.risk == "high"]
                ),
                "cloud_delete_count": len(
                    [
                        action
                        for action in plan.actions
                        if action.action_type == ActionType.DELETE_CLOUD_FILE
                    ]
                ),
            }
        )
        return summary

    @staticmethod
    def _set_action_enabled(action: Any, enabled: bool) -> Tuple[bool, str]:
        """设置动作启用状态并执行安全校验。"""
        if (
            enabled
            and action.action_type == ActionType.DELETE_CLOUD_FILE
            and action.skip_reason
        ):
            return False, f"该115删除动作被安全规则阻断，不能手动启用：{action.skip_reason}"
        action.allowed = bool(enabled)
        action.skip_reason = "" if enabled else "用户手动禁用"
        return True, "动作已更新"

    def _filter_issues(
        self,
        issue_code: Optional[str] = None,
        issue_level: Optional[str] = None,
    ) -> List[Any]:
        """按查询参数过滤巡检问题。"""
        if not self._latest_plan:
            return []
        issues = self._latest_plan.issues
        if issue_code:
            issues = [issue for issue in issues if issue.code == issue_code]
        if issue_level:
            issues = [
                issue
                for issue in issues
                if issue.level.value == issue_level
            ]
        return issues

    def _filter_groups(
        self,
        group_id: Optional[str] = None,
        risk: Optional[str] = None,
    ) -> List[Any]:
        """按查询参数过滤重复分组。"""
        if not self._latest_plan:
            return []
        groups = self._latest_plan.duplicate_groups
        if group_id:
            groups = [group for group in groups if group.group_id == group_id]
        if risk:
            groups = [group for group in groups if group.risk == risk]
        return groups

    @staticmethod
    def _filter_execution_results(
        results: List[Dict[str, Any]],
        status: Optional[str] = None,
        action_type: Optional[str] = None,
        has_cloud_snapshot: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """按查询参数过滤执行结果。"""
        filtered_results = results
        if status:
            filtered_results = [
                result
                for result in filtered_results
                if result.get("status") == status
            ]
        if action_type:
            filtered_results = [
                result
                for result in filtered_results
                if result.get("action_type") == action_type
            ]
        if has_cloud_snapshot is not None:
            filtered_results = [
                result
                for result in filtered_results
                if bool((result.get("details") or {}).get("cloud_snapshot"))
                == has_cloud_snapshot
            ]
        return filtered_results

    def _mediaserver_check_media_keys(self, scope: str = "all") -> List[Tuple[str, List[str]]]:
        """返回待媒体服务器缓存对照的媒体键。"""
        media_key_paths: Dict[str, List[str]] = {}
        if scope == "duplicates":
            duplicate_groups = self._latest_plan.duplicate_groups if self._latest_plan else []
            for group in duplicate_groups:
                if not group.key.startswith(("movie:", "episode:")):
                    continue
                media_key_paths.setdefault(group.key, []).extend(group.all_paths)
        else:
            media_key_items = (
                self._latest_plan.summary.get("media_keys") or []
                if self._latest_plan
                else []
            )
            for item in media_key_items:
                media_key = str(item.get("media_key") or "")
                if not media_key:
                    continue
                media_key_paths.setdefault(media_key, []).extend(item.get("paths") or [])
        return [
            (media_key, sorted(set(paths)))
            for media_key, paths in sorted(media_key_paths.items())
        ]

    @staticmethod
    def _export_filter_suffix(
        action_type: Optional[str],
        risk: Optional[str],
        allowed: Optional[bool],
        group_id: Optional[str] = None,
        issue_code: Optional[str] = None,
        issue_level: Optional[str] = None,
        report_scope: Optional[str] = None,
    ) -> str:
        """生成导出过滤条件文件名后缀。"""
        parts = []
        if report_scope and report_scope != "all":
            parts.append(report_scope)
        if action_type:
            parts.append(action_type)
        if risk:
            parts.append(risk)
        if allowed is not None:
            parts.append("allowed" if allowed else "blocked")
        if group_id:
            parts.append(group_id)
        if issue_code:
            parts.append(issue_code)
        if issue_level:
            parts.append(issue_level)
        return f"-{'-'.join(parts)}" if parts else ""

    def _post_execution_notice(self, report: Dict[str, Any]) -> None:
        """按配置发送执行结果通知。"""
        if not self._config.get("notify"):
            return
        summary = report.get("summary") or {}
        self.post_message(
            mtype=NotificationType.Plugin,
            title="Emby媒体库整理执行完成",
            text=(
                f"完成：{summary.get('done_count', 0)}，"
                f"跳过：{summary.get('skipped_count', 0)}，"
                f"失败：{summary.get('failed_count', 0)}"
            ),
        )

    @staticmethod
    def _plan_confirm_token(plan: OrganizerPlan) -> str:
        """生成整理计划高风险确认token。"""
        cloud_parts = [
            "|".join(
                [
                    action.action_id,
                    action.cloud_file_id or "",
                    action.cloud_path or "",
                ]
            )
            for action in plan.actions
            if action.allowed and action.action_type == ActionType.DELETE_CLOUD_FILE
        ]
        payload = "\n".join([plan.task_id, *sorted(cloud_parts)])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def _merge_defaults(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """合并默认配置。"""
        return {
            **cls._default_config(),
            **config,
        }

    @staticmethod
    def _validate_cron(config: Dict[str, Any]) -> List[ConfigValidationIssue]:
        """校验定时扫描Cron配置。"""
        cron = str(config.get("cron") or "").strip()
        if not cron:
            return []
        try:
            CronTrigger.from_crontab(cron)
        except ValueError as err:
            return [
                ConfigValidationIssue(
                    level=IssueLevel.ERROR,
                    code="invalid_cron",
                    message=f"定时扫描Cron表达式无效：{str(err)}",
                    suggestion="请使用标准5段Cron表达式，或留空关闭定时扫描",
                )
            ]
        return []

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """返回默认配置。"""
        return {
            "enabled": False,
            "library_paths": "",
            "movie_library_paths": "",
            "tv_library_paths": "",
            "anime_library_paths": "",
            "missing_metadata_categories": [],
            "library_types": {},
            "exclude_patterns": "",
            "protected_local_paths": "",
            "protected_115_paths": "",
            "preferred_library_paths": "",
            "custom_identity_patterns": "",
            "max_depth": 20,
            "follow_symlinks": False,
            "delete_duplicate_strm": True,
            "clean_trash_files": True,
            "delete_sidecar_files": False,
            "delete_orphan_sidecar_files": False,
            "delete_empty_dirs": False,
            "check_nfo_files": False,
            "check_image_files": False,
            "check_mediaserver_cache": False,
            "sync_delete_115": False,
            "dry_run": True,
            "require_confirm": True,
            "max_delete_count": 20,
            "max_history": 20,
            "quarantine_retention_days": 30,
            "notify": False,
            "local_delete_mode": "quarantine",
            "dedupe_keys": "file_id\npickcode\ncloud_path\nmedia_key",
            "keep_strategy": "quality_then_naming",
            "cron": "",
        }

    @staticmethod
    def _summary_row(label: str, value: Any) -> Dict[str, Any]:
        """生成摘要表格行。"""
        return {
            "component": "tr",
            "content": [
                {
                    "component": "td",
                    "text": label,
                },
                {
                    "component": "td",
                    "text": str(value),
                },
            ],
        }

    @classmethod
    def _page_panel(cls, title: str, rows: List[Tuple[str, Any]]) -> Dict[str, Any]:
        """生成详情页摘要面板。"""
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": 6},
            "content": [
                {
                    "component": "VCard",
                    "props": {"variant": "tonal"},
                    "content": [
                        {
                            "component": "VCardTitle",
                            "props": {"class": "text-subtitle-1"},
                            "text": title,
                        },
                        {
                            "component": "VTable",
                            "props": {"density": "compact"},
                            "content": [
                                {
                                    "component": "tbody",
                                    "content": [
                                        cls._summary_row(label, value)
                                        for label, value in rows
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }

    @staticmethod
    def _issue_distribution_rows(summary: Dict[str, Any]) -> List[Tuple[str, Any]]:
        """生成问题分布展示行。"""
        level_counts = summary.get("issue_level_counts") or {}
        code_counts = summary.get("issue_code_counts") or {}
        top_codes = sorted(
            code_counts.items(),
            key=lambda item: (-int(item[1]), item[0]),
        )[:3]
        rows = [
            ("错误", level_counts.get("error", 0)),
            ("警告", level_counts.get("warning", 0)),
            ("提示", level_counts.get("info", 0)),
        ]
        if top_codes:
            rows.append(
                (
                    "主要问题",
                    "，".join(f"{code}:{count}" for code, count in top_codes),
                )
            )
        return rows

    @staticmethod
    def _execution_summary_rows(report: Dict[str, Any]) -> List[Tuple[str, Any]]:
        """生成最近执行展示行。"""
        if not report:
            return [
                ("状态", "暂无执行记录"),
                ("完成", 0),
                ("跳过", 0),
                ("失败", 0),
            ]
        summary = report.get("summary") or {}
        return [
            ("任务ID", report.get("task_id") or ""),
            ("完成", summary.get("done_count", 0)),
            ("演练", summary.get("dry_run_count", 0)),
            ("跳过", summary.get("skipped_count", 0)),
            ("失败", summary.get("failed_count", 0)),
        ]

    @classmethod
    def _orphan_metadata_table(
        cls,
        plan: Dict[str, Any],
        execution_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成多余元数据文件及执行状态表格。"""
        issues = [
            issue
            for issue in plan.get("issues") or []
            if issue.get("code") == "orphan_sidecar"
        ]
        actions = {
            action.get("path"): action
            for action in plan.get("actions") or []
            if action.get("action_type") == ActionType.DELETE_SIDECAR.value
        }
        execution_matches = (
            execution_report.get("task_id")
            and execution_report.get("task_id") == plan.get("task_id")
        )
        results = {
            result.get("path"): result
            for result in execution_report.get("results") or []
        } if execution_matches else {}
        visible_issues = issues[: cls._OVERVIEW_SAMPLE_SIZE]
        rows = [
            cls._orphan_metadata_row(issue, actions, results)
            for issue in visible_issues
        ]
        if not rows:
            rows = [
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"colspan": 4},
                            "text": "暂无多余元数据，请先执行扫描。",
                        }
                    ],
                }
            ]
        title = f"多余元数据示例（共 {len(issues)} 条）"
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "text-subtitle-1"},
                    "text": title,
                },
                {
                    "component": "VTable",
                    "props": {"density": "compact"},
                    "content": [
                        {
                            "component": "thead",
                            "content": [
                                {
                                    "component": "tr",
                                    "content": [
                                        {"component": "th", "text": "类型"},
                                        {"component": "th", "text": "原文件路径"},
                                        {"component": "th", "text": "当前状态"},
                                        {"component": "th", "text": "隔离位置"},
                                    ],
                                }
                            ],
                        },
                        {"component": "tbody", "content": rows},
                    ],
                },
            ],
        }

    @staticmethod
    def _missing_metadata_strm_count(plan: Dict[str, Any]) -> int:
        """统计缺少 NFO 或 MediaInfo 的 STRM 数量。"""
        paths = {
            str(issue.get("path") or "")
            for issue in plan.get("issues") or []
            if issue.get("code") in ("missing_nfo", "missing_mediainfo")
        }
        paths.discard("")
        return len(paths)

    @classmethod
    def _missing_metadata_table(cls, plan: Dict[str, Any]) -> Dict[str, Any]:
        """生成 STRM 缺失元数据查询结果表格。"""
        missing_by_path: Dict[str, List[Dict[str, Any]]] = {}
        for issue in plan.get("issues") or []:
            if issue.get("code") not in ("missing_nfo", "missing_mediainfo"):
                continue
            path = str(issue.get("path") or "")
            if path:
                missing_by_path.setdefault(path, []).append(issue)
        visible_items = list(sorted(missing_by_path.items()))[
            : cls._OVERVIEW_SAMPLE_SIZE
        ]
        rows = [
            cls._missing_metadata_row(path, issues)
            for path, issues in visible_items
        ]
        if not rows:
            rows = [
                {
                    "component": "tr",
                    "content": [
                        {
                            "component": "td",
                            "props": {"colspan": 3},
                            "text": "暂无缺失元数据查询结果。",
                        }
                    ],
                }
            ]
        title = f"缺失元数据示例（共 {len(missing_by_path)} 个STRM）"
        return {
            "component": "VCard",
            "props": {"variant": "outlined", "class": "mt-4"},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "text-subtitle-1"},
                    "text": title,
                },
                {
                    "component": "VTable",
                    "props": {"density": "compact"},
                    "content": [
                        {
                            "component": "thead",
                            "content": [
                                {
                                    "component": "tr",
                                    "content": [
                                        {"component": "th", "text": "分类"},
                                        {"component": "th", "text": "文件"},
                                        {"component": "th", "text": "缺失类型"},
                                    ],
                                }
                            ],
                        },
                        {"component": "tbody", "content": rows},
                    ],
                },
            ],
        }

    @classmethod
    def _missing_metadata_row(
        cls,
        path: str,
        issues: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """生成单个 STRM 缺失元数据展示行。"""
        return {
            "component": "tr",
            "content": [
                {"component": "td", "text": cls._category_label_from_path(path)},
                {"component": "td", "text": Path(path).name},
                {
                    "component": "td",
                    "text": "、".join(cls._missing_metadata_types(issues)),
                },
            ],
        }

    @staticmethod
    def _missing_metadata_types(issues: List[Dict[str, Any]]) -> List[str]:
        """返回缺失元数据的简短类型名称。"""
        types = {
            "NFO" if issue.get("code") == "missing_nfo" else "JSON"
            for issue in issues
            if issue.get("code") in ("missing_nfo", "missing_mediainfo")
        }
        return sorted(types)

    @staticmethod
    def _category_label_from_path(path: str) -> str:
        """从媒体路径提取二级分类标签。"""
        parts = Path(path).parts
        for index, part in enumerate(parts[:-1]):
            if part in SECONDARY_CATEGORY_ROOT_TYPES and len(parts) > index + 1:
                return f"{part} / {parts[index + 1]}"
        return Path(path).parent.name

    def _missing_metadata_detail_page(self, page: int) -> List[Dict[str, Any]]:
        """生成缺失元数据完整结果分页页面。"""
        plan = self.get_data("latest_missing_plan") or self._latest_plan_data()
        groups = self._build_missing_metadata_groups(plan)
        page_count = max(
            (len(groups) + self._DETAIL_PAGE_SIZE - 1) // self._DETAIL_PAGE_SIZE,
            1,
        )
        current_page = min(max(page, 1), page_count)
        start = (current_page - 1) * self._DETAIL_PAGE_SIZE
        page_groups = groups[start : start + self._DETAIL_PAGE_SIZE]
        content: List[Dict[str, Any]] = [
            {
                "component": "VBtn",
                "props": {
                    "variant": "text",
                    "prepend-icon": "mdi-arrow-left",
                },
                "text": "返回概览",
                "events": {
                    "click": {
                        "api": "plugin/EmbyLibraryOrganizer/view?mode=overview&page=1",
                        "method": "post",
                    },
                },
            },
            {
                "component": "div",
                "props": {"class": "text-h6 mt-3"},
                "text": "缺失元数据完整结果",
            },
            {
                "component": "div",
                "props": {"class": "text-body-2 text-medium-emphasis mb-3"},
                "text": (
                    f"共 {len(groups)} 个影视条目，第 {current_page}/{page_count} 页；"
                    "点击条目可展开查看各季各集。"
                ),
            },
            self._missing_metadata_pagination(current_page, page_count),
        ]
        if page_groups:
            content.append(
                {
                    "component": "VExpansionPanels",
                    "props": {"class": "mt-3"},
                    "content": [
                        self._missing_metadata_group_panel(group)
                        for group in page_groups
                    ],
                }
            )
        else:
            content.append(
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "class": "mt-3",
                    },
                    "text": "暂无查询结果，请返回概览后选择分类并执行查询。",
                }
            )
        content.append(self._missing_metadata_pagination(current_page, page_count))
        return content

    @classmethod
    def _build_missing_metadata_groups(
        cls,
        plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """按电影目录或电视剧剧名目录归组缺失元数据结果。"""
        missing_by_path: Dict[str, List[Dict[str, Any]]] = {}
        for issue in plan.get("issues") or []:
            if issue.get("code") not in ("missing_nfo", "missing_mediainfo"):
                continue
            path = str(issue.get("path") or "")
            if path:
                missing_by_path.setdefault(path, []).append(issue)
        groups: Dict[str, Dict[str, Any]] = {}
        for path, issues in missing_by_path.items():
            strm_path = Path(path)
            if strm_path.parent.name.casefold().startswith("season "):
                media_directory = strm_path.parent.parent
            else:
                media_directory = strm_path.parent
            group_key = media_directory.as_posix()
            group = groups.setdefault(
                group_key,
                {
                    "title": media_directory.name,
                    "category": cls._category_label_from_path(path),
                    "items": [],
                },
            )
            group["items"].append(
                {
                    "season": (
                        strm_path.parent.name
                        if strm_path.parent.name.casefold().startswith("season ")
                        else "-"
                    ),
                    "name": strm_path.name,
                    "path": path,
                    "missing": cls._missing_metadata_types(issues),
                }
            )
        for group in groups.values():
            group["items"] = sorted(
                group["items"],
                key=lambda item: (item["season"], item["name"]),
            )
        return sorted(
            groups.values(),
            key=lambda group: (group["category"], group["title"]),
        )

    @staticmethod
    def _missing_metadata_group_panel(group: Dict[str, Any]) -> Dict[str, Any]:
        """生成单个影视条目的可展开缺失详情。"""
        items = group.get("items") or []
        rows = [
            {
                "component": "tr",
                "content": [
                    {"component": "td", "text": str(item.get("season") or "")},
                    {"component": "td", "text": str(item.get("name") or "")},
                    {
                        "component": "td",
                        "text": "、".join(item.get("missing") or []),
                    },
                    EmbyLibraryOrganizer._missing_metadata_action_cell(
                        str(item.get("path") or "")
                    ),
                ],
            }
            for item in items
        ]
        return {
            "component": "VExpansionPanel",
            "content": [
                {
                    "component": "VExpansionPanelTitle",
                    "text": (
                        f"{group.get('category') or ''} · {group.get('title') or ''} "
                        f"· {len(items)} 个STRM"
                    ),
                },
                {
                    "component": "VExpansionPanelText",
                    "content": [
                        {
                            "component": "VTable",
                            "props": {"density": "compact"},
                            "content": [
                                {
                                    "component": "thead",
                                    "content": [
                                        {
                                            "component": "tr",
                                            "content": [
                                                {"component": "th", "text": "季"},
                                                {"component": "th", "text": "文件"},
                                                {"component": "th", "text": "缺失类型"},
                                                {"component": "th", "text": "操作"},
                                            ],
                                        }
                                    ],
                                },
                                {"component": "tbody", "content": rows},
                            ],
                        }
                    ],
                },
            ],
        }

    @staticmethod
    def _missing_metadata_action_cell(path: str) -> Dict[str, Any]:
        """生成单个STRM的清理操作按钮。"""
        encoded_path = quote(path, safe="")
        buttons = [
            {
                "component": "VBtn",
                "props": {
                    "color": "warning",
                    "variant": "outlined",
                    "size": "small",
                    "class": "me-2",
                    "prepend-icon": "mdi-delete-outline",
                },
                "text": "删除STRM",
                "events": {
                    "click": {
                        "api": (
                            "plugin/EmbyLibraryOrganizer/delete_missing_strm?"
                            f"path={encoded_path}&include_sidecars=false"
                        ),
                        "method": "post",
                    },
                },
            },
            {
                "component": "VBtn",
                "props": {
                    "color": "error",
                    "size": "small",
                    "class": "me-2",
                    "prepend-icon": "mdi-delete-sweep-outline",
                },
                "text": "STRM+联动",
                "events": {
                    "click": {
                        "api": (
                            "plugin/EmbyLibraryOrganizer/delete_missing_strm?"
                            f"path={encoded_path}&include_sidecars=true"
                        ),
                        "method": "post",
                    },
                },
            },
        ]
        strm_path = Path(path)
        if (
            EmbyLibraryOrganizer._category_library_type(strm_path) == "tv"
            and strm_path.parent.name.casefold().startswith("season ")
            and EmbyLibraryOrganizer._episode_name_template(strm_path.stem)
        ):
            buttons.append(
                {
                    "component": "VBtn",
                    "props": {
                        "color": "error",
                        "variant": "tonal",
                        "size": "small",
                        "prepend-icon": "mdi-delete-alert-outline",
                    },
                    "text": "同格式整组",
                    "events": {
                        "click": {
                            "api": (
                                "plugin/EmbyLibraryOrganizer/delete_episode_group?"
                                f"path={encoded_path}"
                            ),
                            "method": "post",
                        },
                    },
                }
            )
        return {
            "component": "td",
            "props": {"style": "min-width: 390px;"},
            "content": buttons,
        }

    @staticmethod
    def _missing_metadata_pagination(page: int, page_count: int) -> Dict[str, Any]:
        """生成缺失元数据详情分页按钮。"""
        return {
            "component": "VRow",
            "props": {"class": "my-2", "justify": "space-between"},
            "content": [
                {
                    "component": "VCol",
                    "props": {"cols": 6},
                    "content": [
                        {
                            "component": "VBtn",
                            "props": {
                                "variant": "outlined",
                                "block": True,
                                "disabled": page <= 1,
                                "prepend-icon": "mdi-chevron-left",
                            },
                            "text": "上一页",
                            "events": {
                                "click": {
                                    "api": (
                                        "plugin/EmbyLibraryOrganizer/view?"
                                        f"mode=missing_metadata&page={max(page - 1, 1)}"
                                    ),
                                    "method": "post",
                                },
                            },
                        }
                    ],
                },
                {
                    "component": "VCol",
                    "props": {"cols": 6},
                    "content": [
                        {
                            "component": "VBtn",
                            "props": {
                                "variant": "outlined",
                                "block": True,
                                "disabled": page >= page_count,
                                "append-icon": "mdi-chevron-right",
                            },
                            "text": "下一页",
                            "events": {
                                "click": {
                                    "api": (
                                        "plugin/EmbyLibraryOrganizer/view?"
                                        f"mode=missing_metadata&page={min(page + 1, page_count)}"
                                    ),
                                    "method": "post",
                                },
                            },
                        }
                    ],
                },
            ],
        }

    @classmethod
    def _orphan_metadata_row(
        cls,
        issue: Dict[str, Any],
        actions: Dict[str, Dict[str, Any]],
        results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """生成单个多余元数据文件展示行。"""
        path = str(issue.get("path") or "")
        action = actions.get(path) or {}
        result = results.get(path) or {}
        if result:
            status = str(result.get("message") or result.get("status") or "已执行")
        elif action and not action.get("allowed", True):
            status = str(action.get("skip_reason") or "已被保护规则阻止")
        elif action:
            status = "待执行"
        else:
            status = "未生成清理动作"
        cell_props = {
            "style": "white-space: normal; overflow-wrap: anywhere; min-width: 120px;"
        }
        return {
            "component": "tr",
            "content": [
                {"component": "td", "text": cls._metadata_file_type(path)},
                {"component": "td", "props": cell_props, "text": path},
                {"component": "td", "props": cell_props, "text": status},
                {
                    "component": "td",
                    "props": cell_props,
                    "text": str(result.get("backup_path") or ""),
                },
            ],
        }

    @staticmethod
    def _metadata_file_type(path: str) -> str:
        """根据文件名返回元数据类型。"""
        name = Path(path).name.casefold()
        if name.endswith("-mediainfo.json"):
            return "MediaInfo"
        if "-thumb." in name:
            return "缩略图"
        if name.endswith(".nfo"):
            return "NFO"
        return "元数据"

    @staticmethod
    def _latest_quarantine_batch(items: List[Any]) -> str:
        """返回隔离区最近批次。"""
        batches = []
        for item in items:
            parts = Path(item.backup_path).parts
            if "quarantine" not in parts:
                continue
            index = parts.index("quarantine")
            if len(parts) > index + 1:
                batches.append(parts[index + 1])
        return sorted(set(batches))[-1] if batches else "无"

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小。"""
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f}{unit}"
            value = value / 1024
        return f"{value:.1f}TB"

    @staticmethod
    def _query_mediaserver_item_id(
        oper: MediaServerOper,
        parsed_media_key: Dict[str, Any],
    ) -> Optional[str]:
        """查询媒体服务器缓存中的媒体条目ID。"""
        if not parsed_media_key:
            return None
        if parsed_media_key.get("kind") == "movie":
            if parsed_media_key.get("tmdbid"):
                return oper.get_item_id(
                    tmdbid=int(parsed_media_key.get("tmdbid")),
                    mtype=MediaType.MOVIE.value,
                )
            return oper.get_item_id(
                title=parsed_media_key.get("title"),
                year=parsed_media_key.get("year"),
                mtype=MediaType.MOVIE.value,
            )
        if parsed_media_key.get("kind") == "episode":
            if parsed_media_key.get("tmdbid"):
                return oper.get_item_id(
                    tmdbid=int(parsed_media_key.get("tmdbid")),
                    mtype=MediaType.TV.value,
                    season=parsed_media_key.get("season"),
                )
            return oper.get_item_id(
                title=parsed_media_key.get("title"),
                mtype=MediaType.TV.value,
                season=parsed_media_key.get("season"),
            )
        return None

    @staticmethod
    def _dashboard_metric(label: str, value: Any) -> Dict[str, Any]:
        """生成仪表盘指标块。"""
        return {
            "component": "VCol",
            "props": {"cols": 4},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis"},
                    "text": label,
                },
                {
                    "component": "div",
                    "props": {"class": "text-h6 font-weight-bold"},
                    "text": str(value),
                },
            ],
        }

    def _form_schema(self) -> List[dict]:
        """返回 Vuetify 配置表单。"""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "dry_run",
                                            "label": "演练模式",
                                            "hint": "开启后不会执行实际删除",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "require_confirm",
                                            "label": "执行前确认",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_sidecar_files",
                                            "label": "重复伴随文件清理动作",
                                            "hint": "仅处理候选STRM独占的NFO、缩略图和MediaInfo",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_orphan_sidecar_files",
                                            "label": "孤儿伴随文件清理动作",
                                            "hint": "电影检查NFO、缩略图和MediaInfo，电视剧仅检查季目录集级文件",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_empty_dirs",
                                            "label": "生成空目录清理动作",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "sync_delete_115",
                                            "label": "同步删除115",
                                            "hint": "仅移入115回收站，默认建议关闭",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "执行后通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "check_mediaserver_cache",
                                            "label": "启用媒体服务器缓存对照",
                                            "hint": "对照MoviePilot已同步的媒体服务器缓存",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "library_paths",
                            "label": "混合媒体库路径",
                            "rows": 2,
                            "hint": "每行一个媒体库根目录，类型未知时使用",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "movie_library_paths",
                            "label": "电影媒体库路径",
                            "rows": 2,
                            "hint": "用于电影重复识别和命名检查",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "tv_library_paths",
                            "label": "剧集媒体库路径",
                            "rows": 2,
                            "hint": "用于 SxxExx 剧集重复识别",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "anime_library_paths",
                            "label": "动漫媒体库路径",
                            "rows": 2,
                            "hint": "按剧集规则处理动漫目录",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "missing_metadata_categories",
                            "label": "缺失元数据查询分类",
                            "items": self._discover_secondary_categories(),
                            "multiple": True,
                            "chips": True,
                            "closable-chips": True,
                            "class": "mt-6 mb-4",
                            "hint": "自动识别电影、电视剧和动漫目录下的二级分类，可多选",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "preferred_library_paths",
                            "label": "优先保留媒体库路径",
                            "rows": 2,
                            "hint": "重复时优先保留这些路径下的STRM",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "protected_local_paths",
                            "label": "本地保护路径",
                            "rows": 2,
                            "hint": "命中这些路径的本地文件不会被删除或隔离",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "protected_115_paths",
                            "label": "115保护路径",
                            "rows": 2,
                            "hint": "命中这些云端路径的文件不会被移入回收站",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "exclude_patterns",
                            "label": "排除正则",
                            "rows": 2,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "custom_identity_patterns",
                            "label": "自定义STRM身份解析正则",
                            "rows": 2,
                            "hint": "可使用命名分组 file_id、pickcode、cloud_path",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VTextarea",
                        "props": {
                            "model": "dedupe_keys",
                            "label": "去重身份键",
                            "rows": 4,
                            "hint": "每行一个：file_id、pickcode、cloud_path、media_key",
                            "persistent-hint": True,
                        },
                    },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "local_delete_mode",
                            "label": "本地删除模式",
                            "items": [
                                {"title": "移动到隔离区", "value": "quarantine"},
                                {"title": "直接删除", "value": "delete"},
                            ],
                        },
                    },
                    {
                        "component": "VSelect",
                        "props": {
                            "model": "keep_strategy",
                            "label": "重复保留策略",
                            "items": [
                                {"title": "质量和命名优先", "value": "quality_then_naming"},
                                {"title": "优先路径优先", "value": "preferred_path"},
                                {"title": "最新修改优先", "value": "newest"},
                                {"title": "文件体积优先", "value": "largest"},
                            ],
                        },
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_depth",
                                            "label": "最大扫描深度",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "quarantine_retention_days",
                                            "label": "隔离区保留天数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_delete_count",
                                            "label": "单次最大删除数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "max_history",
                                            "label": "历史保留数量",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "定时扫描Cron",
                                            "hint": "留空则不启用定时扫描",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
