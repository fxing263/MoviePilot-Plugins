import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    OrganizerPlan,
    PlanBuilder,
    QuarantineManager,
    ReportExporter,
    STRM_SUFFIX,
    STORAGE_115_NAME,
    StrmParser,
    config_from_dict,
    execution_report_to_dict,
    plan_from_dict,
    plan_to_dict,
    validate_config,
)


class EmbyLibraryOrganizer(_PluginBase):
    """Emby媒体库整理插件。"""

    plugin_name = "Emby媒体库整理"
    plugin_desc = (
        "巡检基于115 STRM方案建立的Emby媒体库，识别重复、生成整理计划，"
        "并在确认后安全清理本地与115文件。"
    )
    plugin_icon = (
        "https://raw.githubusercontent.com/jxxghp/MoviePilot-Frontend/"
        "refs/heads/v2/src/assets/images/misc/emby.png"
    )
    plugin_version = "1.0.1"
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
                "path": f"/{self.__class__.__name__}/scan",
                "endpoint": self.api_scan,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "扫描媒体库并生成整理计划",
                "description": "扫描配置的Emby媒体库，返回重复识别结果和整理计划。",
            },
            {
                "path": f"/{self.__class__.__name__}/validate",
                "endpoint": self.api_validate,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "校验插件配置",
                "description": "校验媒体库路径、删除保护和删除数量等关键配置。",
            },
            {
                "path": f"/{self.__class__.__name__}/plan",
                "endpoint": self.api_get_plan,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取最近整理计划",
                "description": "返回最近一次扫描生成的整理计划。",
            },
            {
                "path": f"/{self.__class__.__name__}/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取插件任务状态",
                "description": "返回当前扫描或执行状态。",
            },
            {
                "path": f"/{self.__class__.__name__}/execute",
                "endpoint": self.api_execute,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "执行最近整理计划",
                "description": "在确认后执行最近一次整理计划。",
            },
            {
                "path": f"/{self.__class__.__name__}/confirm_token",
                "endpoint": self.api_confirm_token,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取高风险确认token",
                "description": "为最近整理计划生成115云端删除确认token。",
            },
            {
                "path": f"/{self.__class__.__name__}/preflight",
                "endpoint": self.api_preflight,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "预检115删除动作",
                "description": "只读校验最近计划中的115云端删除动作，不执行删除。",
            },
            {
                "path": f"/{self.__class__.__name__}/actions",
                "endpoint": self.api_actions,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询整理动作",
                "description": "按类型、风险和状态过滤最近整理计划中的动作。",
            },
            {
                "path": f"/{self.__class__.__name__}/groups",
                "endpoint": self.api_groups,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询重复分组",
                "description": "返回重复分组及其关联整理动作，供人工审查。",
            },
            {
                "path": f"/{self.__class__.__name__}/group/keep",
                "endpoint": self.api_set_group_keep,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "设置重复分组保留项",
                "description": "按重复分组指定保留路径，并重新生成该组整理动作。",
            },
            {
                "path": f"/{self.__class__.__name__}/issues",
                "endpoint": self.api_issues,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询巡检问题",
                "description": "按问题代码和级别过滤最近整理计划中的巡检问题。",
            },
            {
                "path": f"/{self.__class__.__name__}/mediaserver_check",
                "endpoint": self.api_mediaserver_check,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "媒体服务器缓存对照",
                "description": "使用MoviePilot本地媒体服务器缓存对照最近扫描计划。",
            },
            {
                "path": f"/{self.__class__.__name__}/action",
                "endpoint": self.api_update_action,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "更新整理动作状态",
                "description": "根据 action_id 启用或禁用整理动作。",
            },
            {
                "path": f"/{self.__class__.__name__}/actions/update",
                "endpoint": self.api_update_actions,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "批量更新整理动作状态",
                "description": "按动作ID或筛选条件批量启用或禁用整理动作。",
            },
            {
                "path": f"/{self.__class__.__name__}/quarantine",
                "endpoint": self.api_quarantine,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询隔离区",
                "description": "列出本插件隔离区中的可恢复文件。",
            },
            {
                "path": f"/{self.__class__.__name__}/restore",
                "endpoint": self.api_restore,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "恢复隔离文件",
                "description": "将隔离区文件恢复到原始路径。",
            },
            {
                "path": f"/{self.__class__.__name__}/restore_batch",
                "endpoint": self.api_restore_batch,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "按批次恢复隔离文件",
                "description": "将同一执行批次的隔离文件恢复到原始路径。",
            },
            {
                "path": f"/{self.__class__.__name__}/clean_quarantine",
                "endpoint": self.api_clean_quarantine,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理过期隔离文件",
                "description": "按保留天数删除插件隔离区中的过期文件。",
            },
            {
                "path": f"/{self.__class__.__name__}/history",
                "endpoint": self.api_history,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取整理历史",
                "description": "返回最近的扫描和执行历史。",
            },
            {
                "path": f"/{self.__class__.__name__}/execution",
                "endpoint": self.api_execution,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询最近执行结果",
                "description": "按状态、动作类型和云端快照过滤最近执行结果。",
            },
            {
                "path": f"/{self.__class__.__name__}/clear_history",
                "endpoint": self.api_clear_history,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理整理历史",
                "description": "清理扫描历史、执行历史和最近计划。",
            },
            {
                "path": f"/{self.__class__.__name__}/clear_reports",
                "endpoint": self.api_clear_reports,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理导出报告",
                "description": "删除插件数据目录下的导出报告文件。",
            },
            {
                "path": f"/{self.__class__.__name__}/export",
                "endpoint": self.api_export,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "导出最近整理计划",
                "description": "导出最近一次整理计划，支持 json、csv、markdown。",
            },
            {
                "path": f"/{self.__class__.__name__}/export_execution",
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
        latest = plan_to_dict(self._latest_plan) if self._latest_plan else {}
        summary = latest.get("summary") or {}
        latest_execution = self.get_data("latest_execution") or {}
        quarantine_items = QuarantineManager(self.get_data_path()).list_items()
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "此页面展示最近一次扫描、执行和隔离区摘要。高风险动作执行前请先导出报告审查。",
                },
            },
            {
                "component": "VTable",
                "content": [
                    {
                        "component": "tbody",
                        "content": [
                            self._summary_row("STRM数量", summary.get("strm_count", 0)),
                            self._summary_row("问题数量", summary.get("issue_count", 0)),
                            self._summary_row("重复分组", summary.get("duplicate_group_count", 0)),
                            self._summary_row("待执行动作", summary.get("action_count", 0)),
                            self._summary_row("115删除动作", summary.get("cloud_delete_count", 0)),
                        ],
                    }
                ],
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4"},
                "content": [
                    self._page_panel(
                        title="问题分布",
                        rows=self._issue_distribution_rows(summary),
                    ),
                    self._page_panel(
                        title="重复与动作",
                        rows=[
                            ("引用重复", summary.get("reference_duplicate_count", 0)),
                            ("媒体重复", summary.get("media_duplicate_count", 0)),
                            ("允许动作", summary.get("allowed_action_count", 0)),
                            ("阻断动作", summary.get("blocked_action_count", 0)),
                            ("高风险动作", summary.get("high_risk_action_count", 0)),
                        ],
                    ),
                ],
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4"},
                "content": [
                    self._page_panel(
                        title="最近执行",
                        rows=self._execution_summary_rows(latest_execution),
                    ),
                    self._page_panel(
                        title="隔离区",
                        rows=[
                            ("文件数量", len(quarantine_items)),
                            (
                                "占用空间",
                                self._format_size(
                                    sum(item.size for item in quarantine_items)
                                ),
                            ),
                            (
                                "最近批次",
                                self._latest_quarantine_batch(quarantine_items),
                            ),
                        ],
                    ),
                ],
            },
            {
                "component": "VRow",
                "props": {"class": "mt-4"},
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "primary",
                                    "block": True,
                                    "prepend-icon": "mdi-magnify-scan",
                                },
                                "text": "开始扫描",
                                "events": {
                                    "click": {
                                        "api": "plugin/EmbyLibraryOrganizer/scan",
                                        "method": "post",
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 4},
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
                        "props": {"cols": 12, "md": 4},
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
        latest = plan_to_dict(self._latest_plan) if self._latest_plan else {}
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
        if self._latest_plan:
            data = plan_to_dict(self._latest_plan)
        else:
            data = self.get_data("latest_plan") or {}
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
        self._task_status = "scanning"
        self._last_error = ""
        try:
            organizer_config = config_from_dict(self._config)
            validation_issues = validate_config(organizer_config)
            errors = [
                issue
                for issue in validation_issues
                if issue.level == IssueLevel.ERROR
            ]
            if errors:
                self._task_status = "failed"
                self._last_error = errors[0].message
                return {
                    "code": 1,
                    "msg": errors[0].message,
                    "data": [plan_to_dict(issue) for issue in validation_issues],
                }
            engine = EmbyLibraryOrganizerEngine(organizer_config)
            self._latest_plan = engine.create_plan()
            data = plan_to_dict(self._latest_plan)
            self.save_data("latest_plan", data)
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

    @staticmethod
    def _form_schema() -> List[dict]:
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
                                            "hint": "仅处理重复STRM候选旁边的伴随文件",
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
                                            "hint": "仅处理没有对应STRM的NFO、图片和字幕",
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
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "delete_duplicate_strm",
                                            "label": "生成重复STRM清理动作",
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
                                            "model": "clean_trash_files",
                                            "label": "生成垃圾文件清理动作",
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
                                            "model": "check_nfo_files",
                                            "label": "检查NFO缺失",
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
                                            "model": "check_image_files",
                                            "label": "检查图片缺失",
                                        },
                                    }
                                ],
                            },
                        ],
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
