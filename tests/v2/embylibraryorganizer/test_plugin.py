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
    assert all(not path.startswith("/EmbyLibraryOrganizer/") for path in paths)


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
