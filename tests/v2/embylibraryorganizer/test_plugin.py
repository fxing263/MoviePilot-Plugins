import json
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import embylibraryorganizer as plugin_module
from embylibraryorganizer import (
    ALL_CATEGORIES_VALUE,
    BLURAY_CATEGORY_VALUE,
    EmbyLibraryOrganizer,
)
from embylibraryorganizer.core import (
    ActionStatus,
    ActionType,
    CloudVerifyStatus,
    EmbyLibraryOrganizerEngine,
    FileItem,
    OrganizerConfig,
    OrganizerPlan,
    PlanAction,
    PlanExecutor,
    QuarantineManager,
    StrmParser,
)


def _build_cloud_plan(tmp_path: Path):
    """构造包含本地与115删除动作的媒体重复计划。"""
    movie_dir = tmp_path / "Movie (2024)"
    movie_dir.mkdir()
    lower_file = movie_dir / "Movie (2024) 720p.strm"
    higher_file = movie_dir / "Movie (2024) 2160p.strm"
    lower_file.write_text(
        "https://115.example.com/play?file_id=81001&pickcode=pc81001&path=/Media/Movie.720p.mkv",
        encoding="utf-8",
    )
    higher_file.write_text(
        "https://115.example.com/play?file_id=81002&pickcode=pc81002&path=/Media/Movie.2160p.mkv",
        encoding="utf-8",
    )
    config = OrganizerConfig(
        library_paths=[tmp_path],
        sync_delete_115=True,
        dry_run=False,
        require_confirm=False,
    )
    plan = EmbyLibraryOrganizerEngine(config).create_plan()
    cloud_action = next(
        action
        for action in plan.actions
        if action.action_type == ActionType.DELETE_CLOUD_FILE
    )
    return config, plan, cloud_action


def test_api_paths_are_relative_to_plugin_prefix() -> None:
    """插件API路径应由MoviePilot统一拼接插件ID。"""
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)

    paths = [item["path"] for item in plugin.get_api()]

    assert "/scan" in paths
    assert "/ui_state" in paths
    assert "/delete_preview" in paths
    assert "/delete_orphan_metadata" in paths
    assert "/delete_all_orphan_metadata" in paths
    assert "/delete_orphan_metadata_batch" in paths
    assert all(not path.startswith("/EmbyLibraryOrganizer/") for path in paths)


def test_orphan_metadata_scan_requires_selected_category(tmp_path: Path) -> None:
    """多余元数据扫描未选择分类时应拒绝全库扫描。"""
    library_root = tmp_path / "media"
    (library_root / "电影" / "华语电影").mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": library_root.as_posix(),
        "orphan_metadata_categories": [],
    }

    result = plugin._scan_and_save(orphan_metadata_only=True)

    assert result["code"] == 1
    assert "多余元数据扫描分类" in result["msg"]


def test_orphan_scan_api_saves_submitted_categories(tmp_path: Path) -> None:
    """管理页提交的多余元数据分类应先保存再启动扫描。"""
    selected_category = tmp_path / "电影" / "华语电影"
    selected_category.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = plugin._default_config()
    plugin._discover_secondary_categories = lambda: [
        {
            "title": "电影 / 华语电影",
            "value": selected_category.as_posix(),
            "type": "movie",
        }
    ]
    saved_configs = []
    plugin.update_config = lambda config: saved_configs.append(config) or True
    plugin._start_scan_task = lambda **_kwargs: {
        "code": 0,
        "msg": "多余元数据扫描已排队",
    }

    result = plugin.api_scan_orphan_metadata(
        categories=json.dumps([selected_category.as_posix()]),
    )

    assert result["code"] == 0
    assert saved_configs[-1]["orphan_metadata_categories"] == [
        selected_category.as_posix()
    ]


def test_scan_starts_when_selected_categories_are_already_saved(
    tmp_path: Path,
) -> None:
    """分类配置无变化时也应继续启动扫描任务。"""
    selected_category = tmp_path / "电视剧" / "国产剧"
    selected_category.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "missing_metadata_categories": [selected_category.as_posix()],
    }
    plugin._discover_secondary_categories = lambda: [
        {
            "title": "电视剧 / 国产剧",
            "value": selected_category.as_posix(),
            "type": "tv",
        }
    ]
    plugin.update_config = lambda _config: None
    plugin._start_scan_task = lambda **_kwargs: {
        "code": 0,
        "msg": "缺失元数据查询已排队",
    }

    result = plugin.api_scan_missing_metadata(
        categories=json.dumps([selected_category.as_posix()]),
    )

    assert result["code"] == 0
    assert result["msg"] == "缺失元数据查询已排队"


def test_scan_starts_when_category_persistence_fails(tmp_path: Path) -> None:
    """分类持久化失败时仍应使用本次选择启动扫描。"""
    selected_category = tmp_path / "电视剧" / "国产剧"
    selected_category.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = plugin._default_config()
    plugin._discover_secondary_categories = lambda: [
        {
            "title": "电视剧 / 国产剧",
            "value": selected_category.as_posix(),
            "type": "tv",
        }
    ]
    plugin.update_config = lambda _config: False
    plugin._start_scan_task = lambda **_kwargs: {
        "code": 0,
        "msg": "缺失元数据查询已排队",
    }

    result = plugin.api_scan_missing_metadata(
        categories=json.dumps([selected_category.as_posix()]),
    )

    assert result["code"] == 0
    assert result["msg"] == "缺失元数据查询已排队"


def test_all_category_selection_uses_every_library_root(tmp_path: Path) -> None:
    """选择全部时应同时使用混合和蓝光媒体库根目录。"""
    mixed_root = tmp_path / "mixed"
    bluray_root = tmp_path / "bluray"
    mixed_root.mkdir()
    bluray_root.mkdir()
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": mixed_root.as_posix(),
        "bluray_library_paths": bluray_root.as_posix(),
        "orphan_metadata_categories": [ALL_CATEGORIES_VALUE],
    }

    paths, error = plugin._selected_category_paths(
        config_key="orphan_metadata_categories",
        scan_label="多余元数据扫描",
    )

    assert error is None
    assert paths == [mixed_root, bluray_root]


def test_all_category_scan_includes_bluray_library(tmp_path: Path) -> None:
    """全量扫描应检查不参与分类识别的蓝光媒体库。"""
    bluray_root = tmp_path / "bluray"
    movie_dir = bluray_root / "Selected (2026)"
    movie_dir.mkdir(parents=True)
    orphan = movie_dir / "Selected (2026).nfo"
    orphan.write_text("metadata", encoding="utf-8")
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "bluray_library_paths": bluray_root.as_posix(),
        "orphan_metadata_categories": [ALL_CATEGORIES_VALUE],
    }
    plugin.save_data = lambda _key, _value: None
    plugin._append_history = lambda _key, _value: None

    result = plugin._scan_and_save(orphan_metadata_only=True)
    issue_paths = {
        issue["path"]
        for issue in (result.get("data") or {}).get("issues") or []
    }

    assert result["code"] == 0
    assert orphan.as_posix() in issue_paths


def test_bluray_library_is_single_standalone_category(tmp_path: Path) -> None:
    """蓝光媒体库应显示为单一分类且不识别其子目录。"""
    mixed_root = tmp_path / "mixed"
    mixed_category = mixed_root / "电影" / "华语电影"
    bluray_root = tmp_path / "bluray"
    (bluray_root / "原盘" / "电影A").mkdir(parents=True)
    mixed_category.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": mixed_root.as_posix(),
        "bluray_library_paths": bluray_root.as_posix(),
        "missing_metadata_categories": [BLURAY_CATEGORY_VALUE],
    }

    options = plugin._category_options()
    paths, error = plugin._selected_category_paths(
        config_key="missing_metadata_categories",
        scan_label="缺失元数据查询",
    )

    assert options == [
        {"title": "全部（全量）", "value": ALL_CATEGORIES_VALUE, "type": "all"},
        {
            "title": "电影 / 华语电影",
            "value": mixed_category.resolve().as_posix(),
            "type": "movie",
        },
        {"title": "蓝光", "value": BLURAY_CATEGORY_VALUE, "type": "movie"},
    ]
    assert error is None
    assert paths == [bluray_root]
    assert plugin._category_label_from_path(
        (bluray_root / "原盘" / "电影A" / "电影A.strm").as_posix()
    ) == "蓝光"


def test_bluray_category_is_visible_before_path_is_configured() -> None:
    """未配置蓝光路径时仍应展示蓝光分类并在扫描前明确提示。"""
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "missing_metadata_categories": [BLURAY_CATEGORY_VALUE],
    }

    options = plugin._category_options()
    paths, error = plugin._selected_category_paths(
        config_key="missing_metadata_categories",
        scan_label="缺失元数据查询",
    )

    assert options[-1] == {
        "title": "蓝光",
        "value": BLURAY_CATEGORY_VALUE,
        "type": "movie",
    }
    assert paths == []
    assert error == "请先配置蓝光媒体库路径"


def test_custom_category_root_name_discovers_tv_categories(tmp_path: Path) -> None:
    """自定义电视剧文件夹名应参与二级分类识别和类型判断。"""
    library_root = tmp_path / "media"
    category_path = library_root / "Series" / "国产剧"
    episode_path = category_path / "Example" / "Season 1" / "Example.S01E01.strm"
    episode_path.parent.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": library_root.as_posix(),
        "tv_category_root_names": "Series\nTV Shows",
    }

    categories = plugin._discover_secondary_categories()
    groups = plugin._build_missing_metadata_groups(
        {
            "issues": [
                {"code": "missing_nfo", "path": episode_path.as_posix()},
            ]
        }
    )

    assert categories == [
        {
            "title": "Series / 国产剧",
            "value": category_path.resolve().as_posix(),
            "type": "tv",
        }
    ]
    assert plugin._category_library_type(episode_path) == "tv"
    assert groups[0]["category"] == "Series / 国产剧"
    assert groups[0]["library_type"] == "tv"


def test_category_preview_uses_unsaved_page_config(tmp_path: Path) -> None:
    """分类预览应使用页面提交但尚未保存的路径和文件夹名。"""
    library_root = tmp_path / "media"
    category_path = library_root / "Shows" / "华语剧"
    category_path.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = plugin._default_config()

    result = plugin.api_preview_categories(
        config_json=json.dumps(
            {
                "library_paths": library_root.as_posix(),
                "tv_category_root_names": "Shows",
            }
        )
    )

    assert result["code"] == 0
    assert result["data"][1] == {
        "title": "Shows / 华语剧",
        "value": category_path.resolve().as_posix(),
        "type": "tv",
    }


def test_all_category_removes_other_submitted_categories(tmp_path: Path) -> None:
    """全部与普通分类同时提交时应只保存全部。"""
    selected_category = tmp_path / "电影" / "华语电影"
    selected_category.mkdir(parents=True)
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = plugin._default_config()
    plugin._discover_secondary_categories = lambda: [
        {
            "title": "电影 / 华语电影",
            "value": selected_category.as_posix(),
            "type": "movie",
        }
    ]
    saved_configs = []
    plugin.update_config = lambda config: saved_configs.append(config) or True

    error = plugin._update_selected_categories(
        config_key="orphan_metadata_categories",
        categories=json.dumps(
            [selected_category.as_posix(), ALL_CATEGORIES_VALUE]
        ),
        scan_label="多余元数据扫描",
    )

    assert error is None
    assert saved_configs[-1]["orphan_metadata_categories"] == [
        ALL_CATEGORIES_VALUE
    ]


def test_orphan_metadata_scan_only_uses_selected_category(tmp_path: Path) -> None:
    """多余元数据扫描应只检查选中的二级分类。"""
    library_root = tmp_path / "media"
    selected_category = library_root / "电影" / "华语电影"
    excluded_category = library_root / "电影" / "欧美电影"
    selected_movie = selected_category / "Selected (2026)"
    excluded_movie = excluded_category / "Excluded (2026)"
    selected_movie.mkdir(parents=True)
    excluded_movie.mkdir(parents=True)
    selected_orphan = selected_movie / "Selected (2026).nfo"
    excluded_orphan = excluded_movie / "Excluded (2026).nfo"
    selected_orphan.write_text("metadata", encoding="utf-8")
    excluded_orphan.write_text("metadata", encoding="utf-8")
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": library_root.as_posix(),
        "orphan_metadata_categories": [selected_category.as_posix()],
    }
    plugin.save_data = lambda _key, _value: None
    plugin._append_history = lambda _key, _value: None

    result = plugin._scan_and_save(orphan_metadata_only=True)
    issue_paths = {
        issue["path"]
        for issue in (result.get("data") or {}).get("issues") or []
    }

    assert result["code"] == 0
    assert selected_orphan.as_posix() in issue_paths
    assert excluded_orphan.as_posix() not in issue_paths


def test_batch_delete_verifies_same_parent_once(tmp_path: Path) -> None:
    """同目录批量删除应合并父目录复核。"""
    first = tmp_path / "Episode S01E01.strm"
    second = tmp_path / "Episode S01E01.nfo"
    first.write_text("/CloudNAS/CloudDrive/Episode S01E01.mkv", encoding="utf-8")
    second.write_text("metadata", encoding="utf-8")

    class _StorageChainStub:
        """记录本地删除和目录列举次数。"""

        def __init__(self) -> None:
            self.list_count = 0

        @staticmethod
        def get_file_item(
            storage: str,
            path: Path,
        ) -> Optional[SimpleNamespace]:
            """按当前文件系统状态返回简化文件项。"""
            if not path.exists():
                return None
            return SimpleNamespace(
                storage=storage,
                type="file" if path.is_file() else "dir",
                path=path.as_posix(),
            )

        @staticmethod
        def delete_file(file_item: SimpleNamespace) -> bool:
            """删除简化文件项。"""
            Path(file_item.path).unlink()
            return True

        def list_files(self, file_item: SimpleNamespace) -> List[SimpleNamespace]:
            """列举目录并记录调用次数。"""
            self.list_count += 1
            return [
                SimpleNamespace(path=path.as_posix())
                for path in Path(file_item.path).iterdir()
            ]

    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    storage_chain = _StorageChainStub()

    results = plugin._delete_paths_and_verify([first, second], storage_chain)

    assert storage_chain.list_count == 1
    assert all(result["verified"] for result in results)
    assert not first.exists()
    assert not second.exists()


def test_delete_all_orphan_metadata_requires_confirmation_and_updates_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """一键删除应要求确认，并在批量复核后更新扫描结果。"""
    first = tmp_path / "Movie.nfo"
    second = tmp_path / "Movie-thumb.jpg"
    first.write_text("metadata", encoding="utf-8")
    second.write_text("image", encoding="utf-8")
    data_store = {
        "latest_orphan_plan": {
            "issues": [
                {"code": "orphan_sidecar", "path": first.as_posix()},
                {"code": "orphan_sidecar", "path": second.as_posix()},
            ],
            "summary": {"issue_count": 2},
        }
    }

    class _StorageChainStub:
        """使用临时目录模拟MP本地存储链。"""

        @staticmethod
        def get_file_item(storage: str, path: Path) -> Optional[SimpleNamespace]:
            """按临时文件系统状态返回文件项。"""
            if not path.exists():
                return None
            return SimpleNamespace(
                storage=storage,
                type="file" if path.is_file() else "dir",
                path=path.as_posix(),
            )

        @staticmethod
        def delete_file(file_item: SimpleNamespace) -> bool:
            """删除临时文件。"""
            Path(file_item.path).unlink()
            return True

        @staticmethod
        def list_files(file_item: SimpleNamespace) -> List[SimpleNamespace]:
            """列举临时父目录。"""
            return [
                SimpleNamespace(path=path.as_posix())
                for path in Path(file_item.path).iterdir()
            ]

    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin._config = {
        **plugin._default_config(),
        "library_paths": tmp_path.as_posix(),
    }
    plugin.get_data = lambda key: data_store.get(key)
    plugin.save_data = lambda key, value: data_store.__setitem__(key, value)
    plugin._append_history = lambda _key, _value: None
    monkeypatch.setattr(plugin_module, "StorageChain", _StorageChainStub)

    rejected = plugin.api_delete_all_orphan_metadata()
    result = plugin.api_delete_all_orphan_metadata(confirmed=True)

    assert rejected["code"] == 1
    assert result["code"] == 0
    assert result["data"]["total_count"] == 2
    assert result["data"]["deleted_count"] == 2
    assert result["data"]["failed_count"] == 0
    assert data_store["latest_orphan_plan"]["issues"] == []
    assert not first.exists()
    assert not second.exists()


def test_delete_selected_orphan_metadata_only_uses_requested_paths(
    tmp_path: Path,
) -> None:
    """多选删除应只处理当前结果中明确勾选的路径。"""
    first = tmp_path / "Movie.nfo"
    second = tmp_path / "Movie-thumb.jpg"
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    plugin.get_data = lambda _key: {
        "issues": [
            {"code": "orphan_sidecar", "path": first.as_posix()},
            {"code": "orphan_sidecar", "path": second.as_posix()},
        ]
    }
    selected = []
    plugin._delete_orphan_metadata_paths = (
        lambda paths: selected.extend(paths) or {"code": 0, "msg": "完成"}
    )

    result = plugin.api_delete_orphan_metadata_batch(
        paths=json.dumps([second.as_posix()]),
        confirmed=True,
    )

    assert result["code"] == 0
    assert selected == [second.as_posix()]


def test_absent_cloud_file_requires_accessible_parent(tmp_path: Path) -> None:
    """CD2目标原本不存在时必须成功列举父目录。"""
    missing_file = tmp_path / "offline" / "Movie.mkv"

    class _UnavailableStorageChainStub:
        """模拟CD2目标和父目录均不可访问。"""

        @staticmethod
        def get_file_item(storage: str, path: Path) -> None:
            """始终返回路径不可访问。"""
            return None

        @staticmethod
        def delete_file(file_item: SimpleNamespace) -> bool:
            """记录不应被调用的删除接口。"""
            raise AssertionError("目标不存在时不应调用删除")

        @staticmethod
        def list_files(file_item: SimpleNamespace) -> List[SimpleNamespace]:
            """记录不应在父目录缺失时调用的列举接口。"""
            raise AssertionError("父目录不存在时不应调用列举")

    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)
    results = plugin._delete_paths_and_verify(
        [missing_file],
        _UnavailableStorageChainStub(),
        verify_absent_parent=True,
    )

    assert results[0]["verified"] is False
    assert results[0]["status"] == "failed"


def test_absolute_media_path_is_valid_strm_identity() -> None:
    """绝对媒体路径应作为有效STRM身份参与去重。"""
    media_path = (
        "/CloudNAS/CloudDrive/115open/影视库/电影/示例 (2026)/示例 (2026).mkv"
    )

    identity = StrmParser().parse(media_path)

    assert identity.is_absolute_path
    assert not identity.is_url
    assert identity.is_115
    assert identity.cloud_path == media_path
    assert identity.primary_key() == f"cloud_path:{media_path}"


def test_cloud_delete_runs_after_local_prerequisite(tmp_path: Path) -> None:
    """115删除应在对应本地STRM成功隔离后执行。"""
    config, plan, cloud_action = _build_cloud_plan(tmp_path)
    deleted = []
    executor = PlanExecutor(
        config=config,
        data_path=tmp_path / "data",
        cloud_delete_func=lambda file_item: deleted.append(file_item) or True,
        cloud_verify_func=lambda _storage, _path: FileItem(
            storage="115网盘Plus",
            fileid=cloud_action.cloud_file_id,
            path=cloud_action.cloud_path,
            type="file",
        ),
    )

    report = executor.execute(
        plan,
        confirmed=True,
        confirm_token="token",
        expected_confirm_token="token",
    )
    results = {item.action_id: item for item in report.results}

    assert cloud_action.prerequisite_action_id
    assert results[cloud_action.prerequisite_action_id].status == ActionStatus.DONE
    assert results[cloud_action.action_id].status == ActionStatus.DONE
    assert len(deleted) == 1
    assert not Path(cloud_action.path).exists()


def test_cloud_delete_skips_when_local_prerequisite_disabled(
    tmp_path: Path,
) -> None:
    """本地STRM动作被禁用时不得删除对应115文件。"""
    config, plan, cloud_action = _build_cloud_plan(tmp_path)
    local_action = next(
        action
        for action in plan.actions
        if action.action_id == cloud_action.prerequisite_action_id
    )
    local_action.allowed = False
    local_action.skip_reason = "用户手动禁用"
    deleted = []
    executor = PlanExecutor(
        config=config,
        data_path=tmp_path / "data",
        cloud_delete_func=lambda file_item: deleted.append(file_item) or True,
        cloud_verify_func=lambda _storage, _path: FileItem(
            fileid=cloud_action.cloud_file_id,
            path=cloud_action.cloud_path,
            type="file",
        ),
    )

    report = executor.execute(
        plan,
        confirmed=True,
        confirm_token="token",
        expected_confirm_token="token",
    )
    result = next(
        item for item in report.results if item.action_id == cloud_action.action_id
    )

    assert not deleted
    assert Path(cloud_action.path).exists()
    assert result.status == ActionStatus.SKIPPED


def test_cloud_verify_requires_file_id(tmp_path: Path) -> None:
    """115校验结果缺少file_id时应失败关闭。"""
    deleted = []
    action = PlanAction(
        action_id="cloud1",
        action_type=ActionType.DELETE_CLOUD_FILE,
        path="/media/a.strm",
        cloud_file_id="100",
        cloud_path="/Media/a.mkv",
    )
    plan = OrganizerPlan(
        task_id="task",
        created_at="now",
        dry_run=False,
        require_confirm=False,
        issues=[],
        duplicate_groups=[],
        actions=[action],
        summary={},
    )
    executor = PlanExecutor(
        config=OrganizerConfig(),
        data_path=tmp_path / "data",
        cloud_delete_func=lambda file_item: deleted.append(file_item) or True,
        cloud_verify_func=lambda _storage, _path: FileItem(
            path="/Media/a.mkv",
            type="file",
        ),
    )

    missing_token_report = executor.execute(plan, confirmed=True)
    report = executor.execute(
        plan,
        confirmed=True,
        confirm_token="token",
        expected_confirm_token="token",
    )
    preflight = EmbyLibraryOrganizer._preflight_cloud_action(
        action,
        lambda _storage, _path: FileItem(path="/Media/a.mkv", type="file"),
    )

    assert not deleted
    assert missing_token_report.results[0].status == ActionStatus.SKIPPED
    assert "确认token" in missing_token_report.results[0].message
    assert report.results[0].status == ActionStatus.SKIPPED
    assert action.cloud_verify_status == CloudVerifyStatus.FAILED
    assert preflight["verify_status"] == CloudVerifyStatus.FAILED.value


def test_issue_action_skips_file_replaced_after_scan(tmp_path: Path) -> None:
    """扫描后被替换的垃圾文件不应按旧计划清理。"""
    movie_dir = tmp_path / "Movie (2024)"
    movie_dir.mkdir()
    trash_file = movie_dir / ".DS_Store"
    trash_file.write_text("trash", encoding="utf-8")
    config = OrganizerConfig(
        library_paths=[tmp_path],
        dry_run=False,
        require_confirm=False,
    )
    plan = EmbyLibraryOrganizerEngine(config).create_plan()
    action = next(item for item in plan.actions if item.path == trash_file.as_posix())
    trash_file.write_text("replacement", encoding="utf-8")

    report = PlanExecutor(config, tmp_path / "data").execute(
        plan,
        confirmed=True,
    )
    result = next(item for item in report.results if item.action_id == action.action_id)

    assert trash_file.exists()
    assert result.status == ActionStatus.SKIPPED


def test_scan_skips_symlink_target_outside_library(tmp_path: Path) -> None:
    """开启符号链接扫描时仍不得遍历媒体库外部目标。"""
    library_root = tmp_path / "library"
    outside_root = tmp_path / "outside"
    library_root.mkdir()
    outside_root.mkdir()
    outside_trash = outside_root / ".DS_Store"
    outside_trash.write_text("outside", encoding="utf-8")
    (library_root / "escape").symlink_to(outside_root, target_is_directory=True)

    plan = EmbyLibraryOrganizerEngine(
        OrganizerConfig(library_paths=[library_root], follow_symlinks=True)
    ).create_plan()

    assert all(Path(action.path).name != outside_trash.name for action in plan.actions)
    assert all(Path(issue.path).name != outside_trash.name for issue in plan.issues)


def test_restore_refuses_to_overwrite_directory(tmp_path: Path) -> None:
    """覆盖恢复不得递归删除与原文件同名的现有目录。"""
    data_path = tmp_path / "data"
    original = tmp_path / "media" / "Movie.strm"
    original.mkdir(parents=True)
    child = original / "keep.txt"
    child.write_text("keep", encoding="utf-8")
    safe_parts = [
        part for part in original.parts if part not in (original.anchor, "/")
    ]
    backup = data_path / "quarantine" / "task" / Path(*safe_parts)
    backup.parent.mkdir(parents=True)
    backup.write_text("url", encoding="utf-8")

    state, message = QuarantineManager(data_path).restore(backup, overwrite=True)

    assert not state
    assert "拒绝递归覆盖" in message
    assert backup.exists()
    assert child.exists()


def test_empty_directory_action_cannot_delete_library_root(tmp_path: Path) -> None:
    """空目录动作不得删除媒体库根目录本身。"""
    library_root = tmp_path / "library"
    library_root.mkdir()
    action = PlanAction(
        action_id="a1",
        action_type=ActionType.DELETE_EMPTY_DIR,
        path=library_root.as_posix(),
    )
    plan = OrganizerPlan(
        task_id="task",
        created_at="now",
        dry_run=False,
        require_confirm=False,
        issues=[],
        duplicate_groups=[],
        actions=[action],
        summary={},
    )

    report = PlanExecutor(
        OrganizerConfig(library_paths=[library_root]),
        tmp_path / "data",
    ).execute(plan, confirmed=True)

    assert library_root.exists()
    assert report.results[0].status == ActionStatus.SKIPPED


def test_orphan_sidecars_follow_movie_and_season_scope(
    tmp_path: Path,
) -> None:
    """孤儿检查应区分电影、季级文件、剧级文件和字幕。"""
    movie_root = tmp_path / "movies"
    movie_dir = movie_root / "Movie (2024)"
    movie_dir.mkdir(parents=True)
    movie_name = "Movie (2024) - 2160p"
    (movie_dir / f"{movie_name}.strm").write_text(
        "https://115.example.com/play?file_id=1001&path=/Movie.mkv",
        encoding="utf-8",
    )
    movie_valid_files = [
        movie_dir / f"{movie_name}.nfo",
        movie_dir / f"{movie_name}-thumb.jpg",
        movie_dir / f"{movie_name}-mediainfo.json",
    ]
    movie_orphan_files = [
        movie_dir / "Removed Movie.nfo",
        movie_dir / "Removed Movie-thumb.jpg",
        movie_dir / "Removed Movie-mediainfo.json",
    ]
    movie_ignored_subtitle = movie_dir / "Removed Movie.zh-CN.srt"

    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Show (2024)"
    season_dir = show_dir / "Season 01"
    season_dir.mkdir(parents=True)
    episode_name = "Show - S01E01"
    (season_dir / f"{episode_name}.strm").write_text(
        "https://115.example.com/play?file_id=2001&path=/Show/S01E01.mkv",
        encoding="utf-8",
    )
    episode_valid_files = [
        season_dir / f"{episode_name}.nfo",
        season_dir / f"{episode_name}-thumb.jpg",
        season_dir / f"{episode_name}-mediainfo.json",
        season_dir / "season.nfo",
    ]
    episode_orphan_files = [
        season_dir / "Show - S01E02.nfo",
        season_dir / "Show - S01E02-thumb.jpg",
        season_dir / "Show - S01E02-mediainfo.json",
    ]
    ignored_files = [
        movie_ignored_subtitle,
        season_dir / "Show - S01E02.zh-CN.srt",
        show_dir / "poster.jpg",
        show_dir / "tvshow.nfo",
        show_dir / "season01-poster.jpg",
        show_dir / "Detached Episode.nfo",
    ]
    for path in (
        movie_valid_files
        + movie_orphan_files
        + episode_valid_files
        + episode_orphan_files
        + ignored_files
    ):
        path.write_text("metadata", encoding="utf-8")

    plan = EmbyLibraryOrganizerEngine(
        OrganizerConfig(
            library_paths=[movie_root, tv_root],
            library_types={
                movie_root.as_posix(): "movie",
                tv_root.as_posix(): "tv",
            },
            delete_orphan_sidecar_files=True,
            check_image_files=True,
        )
    ).create_plan()
    orphan_issue_paths = {
        issue.path for issue in plan.issues if issue.code == "orphan_sidecar"
    }
    orphan_action_paths = {
        action.path
        for action in plan.actions
        if action.action_type == ActionType.DELETE_SIDECAR
    }

    expected_orphans = {
        path.as_posix() for path in movie_orphan_files + episode_orphan_files
    }
    assert orphan_issue_paths == expected_orphans
    assert orphan_action_paths == expected_orphans
    assert all(path.as_posix() not in orphan_issue_paths for path in ignored_files)
    assert all(issue.code != "missing_image" for issue in plan.issues)


def test_duplicate_episode_cleanup_ignores_subtitles_and_shared_metadata(
    tmp_path: Path,
) -> None:
    """重复集清理只应包含该 STRM 独占的非字幕伴随文件。"""
    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Show (2024) {tmdb-1234}"
    season_dir = show_dir / "Season 1"
    season_dir.mkdir(parents=True)
    lower_name = "Show.2024.S01E01.720p"
    higher_name = "Show.2024.S01E01.2160p"
    (season_dir / f"{lower_name}.strm").write_text(
        "https://115.example.com/play?file_id=3001&path=/Show.720p.mkv",
        encoding="utf-8",
    )
    (season_dir / f"{higher_name}.strm").write_text(
        "https://115.example.com/play?file_id=3002&path=/Show.2160p.mkv",
        encoding="utf-8",
    )
    owned_sidecars = [
        season_dir / f"{lower_name}.nfo",
        season_dir / f"{lower_name}-thumb.jpg",
        season_dir / f"{lower_name}-mediainfo.json",
    ]
    ignored_files = [
        season_dir / f"{lower_name}.zh-CN.srt",
        season_dir / "season.nfo",
        show_dir / "poster.jpg",
        show_dir / "tvshow.nfo",
    ]
    for path in owned_sidecars + ignored_files:
        path.write_text("metadata", encoding="utf-8")

    plan = EmbyLibraryOrganizerEngine(
        OrganizerConfig(
            library_paths=[tv_root],
            library_types={tv_root.as_posix(): "tv"},
            delete_sidecar_files=True,
        )
    ).create_plan()
    sidecar_action_paths = {
        action.path
        for action in plan.actions
        if action.action_type == ActionType.DELETE_SIDECAR
    }

    assert sidecar_action_paths == {path.as_posix() for path in owned_sidecars}
    assert all(path.as_posix() not in sidecar_action_paths for path in ignored_files)


def test_tv_empty_directory_cleanup_only_targets_seasons(tmp_path: Path) -> None:
    """电视剧空目录清理应忽略剧级目录，只处理季目录。"""
    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Show (2024)"
    season_dir = show_dir / "Season 1"
    season_dir.mkdir(parents=True)

    plan = EmbyLibraryOrganizerEngine(
        OrganizerConfig(
            library_paths=[tv_root],
            library_types={tv_root.as_posix(): "tv"},
            delete_empty_dirs=True,
        )
    ).create_plan()
    empty_issue_paths = {
        issue.path for issue in plan.issues if issue.code == "empty_directory"
    }
    empty_action_paths = {
        action.path
        for action in plan.actions
        if action.action_type == ActionType.DELETE_EMPTY_DIR
    }

    assert empty_issue_paths == {season_dir.as_posix()}
    assert empty_action_paths == {season_dir.as_posix()}


def test_executor_rejects_stale_ignored_sidecar_actions(tmp_path: Path) -> None:
    """执行器应拒绝旧计划中的字幕和剧级动作，并允许电影缩略图。"""
    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Show (2024)"
    season_dir = show_dir / "Season 1"
    season_dir.mkdir(parents=True)
    ignored_paths = [
        season_dir / "Show.S01E01.zh-CN.srt",
        show_dir / "tvshow.nfo",
        show_dir / "poster.jpg",
    ]
    for path in ignored_paths:
        path.write_text("metadata", encoding="utf-8")

    movie_root = tmp_path / "movies"
    movie_dir = movie_root / "Movie (2024)"
    movie_dir.mkdir(parents=True)
    movie_thumb = movie_dir / "Movie (2024)-thumb.jpg"
    movie_thumb.write_text("thumb", encoding="utf-8")
    actions = [
        PlanAction(
            action_id=f"ignored-{index}",
            action_type=ActionType.DELETE_SIDECAR,
            path=path.as_posix(),
        )
        for index, path in enumerate(ignored_paths, start=1)
    ]
    actions.append(
        PlanAction(
            action_id="movie-thumb",
            action_type=ActionType.DELETE_SIDECAR,
            path=movie_thumb.as_posix(),
        )
    )
    plan = OrganizerPlan(
        task_id="stale-plan",
        created_at="now",
        dry_run=False,
        require_confirm=False,
        issues=[],
        duplicate_groups=[],
        actions=actions,
        summary={},
    )
    config = OrganizerConfig(
        library_paths=[tv_root, movie_root],
        library_types={
            tv_root.as_posix(): "tv",
            movie_root.as_posix(): "movie",
        },
        local_delete_mode="delete",
    )

    report = PlanExecutor(config, tmp_path / "data").execute(
        plan,
        confirmed=True,
    )
    results = {result.action_id: result for result in report.results}

    assert all(path.exists() for path in ignored_paths)
    assert all(
        results[f"ignored-{index}"].status == ActionStatus.SKIPPED
        for index in range(1, len(ignored_paths) + 1)
    )
    assert not movie_thumb.exists()
    assert results["movie-thumb"].status == ActionStatus.DONE
