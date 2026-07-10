from pathlib import Path

from embylibraryorganizer import EmbyLibraryOrganizer
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


def test_api_paths_include_plugin_id() -> None:
    """插件API路径应显式包含插件ID。"""
    plugin = EmbyLibraryOrganizer.__new__(EmbyLibraryOrganizer)

    paths = [item["path"] for item in plugin.get_api()]

    assert "/EmbyLibraryOrganizer/scan" in paths
    assert all(path.startswith("/EmbyLibraryOrganizer/") for path in paths)


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
