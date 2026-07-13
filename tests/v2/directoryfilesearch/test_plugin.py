from pathlib import Path

import pytest

from directoryfilesearch import (
    DeleteBatchExecuteRequest,
    DeleteBatchPreviewRequest,
    DirectoryFileSearch,
)
from directoryfilesearch.core import (
    DirectoryFileEngine,
    DirectorySearchConfig,
    MAX_QUERY_LENGTH,
    config_from_dict,
    normalize_query,
)


@pytest.fixture
def search_root(tmp_path: Path) -> Path:
    """创建用于目录搜索的临时根目录。"""
    root_dir = tmp_path / "search-root"
    root_dir.mkdir()
    return root_dir


@pytest.fixture
def engine(search_root: Path) -> DirectoryFileEngine:
    """构造只访问临时目录的文件搜索引擎。"""
    return DirectoryFileEngine(
        DirectorySearchConfig(
            enabled=True,
            root_dir=search_root,
            max_results=100,
        )
    )


def test_validate_root_rejects_missing_relative_symlink_and_filesystem_root(
    tmp_path: Path,
) -> None:
    """搜索根目录必须存在、绝对、非符号链接且不能是文件系统根目录。"""
    missing_engine = DirectoryFileEngine(
        DirectorySearchConfig(enabled=True, root_dir=tmp_path / "missing")
    )
    relative_engine = DirectoryFileEngine(
        DirectorySearchConfig(enabled=True, root_dir=Path("relative"))
    )
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    symlink_engine = DirectoryFileEngine(
        DirectorySearchConfig(enabled=True, root_dir=linked_root)
    )
    filesystem_engine = DirectoryFileEngine(
        DirectorySearchConfig(enabled=True, root_dir=Path("/"))
    )

    with pytest.raises(ValueError, match="不存在或不可访问"):
        missing_engine.validate_root()
    with pytest.raises(ValueError, match="绝对路径"):
        relative_engine.validate_root()
    with pytest.raises(ValueError, match="符号链接"):
        symlink_engine.validate_root()
    with pytest.raises(ValueError, match="文件系统根目录"):
        filesystem_engine.validate_root()


def test_search_matches_name_or_relative_path_case_insensitively(
    search_root: Path,
    engine: DirectoryFileEngine,
) -> None:
    """搜索应忽略大小写，并同时匹配文件名和相对路径。"""
    first_dir = search_root / "普通目录"
    second_dir = search_root / "Needle合集"
    first_dir.mkdir()
    second_dir.mkdir()
    first_file = first_dir / "Needle.TXT"
    second_file = second_dir / "other.bin"
    ignored_file = first_dir / "ignored.txt"
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")
    ignored_file.write_text("ignored", encoding="utf-8")
    (search_root / "linked.txt").symlink_to(first_file)

    report = engine.search_files("needle")

    assert report.matched_files == 2
    assert report.scanned_files == 3
    assert not report.truncated
    assert [item.relative_path for item in report.items] == [
        "Needle合集/other.bin",
        "普通目录/Needle.TXT",
    ]
    assert all(item.absolute_path.startswith(search_root.as_posix()) for item in report.items)


def test_search_result_limit_marks_report_as_truncated(search_root: Path) -> None:
    """匹配数超过上限时应保留有限结果并明确标记截断。"""
    for index in range(4):
        (search_root / f"match-{index}.txt").write_text(str(index), encoding="utf-8")
    limited_engine = DirectoryFileEngine(
        DirectorySearchConfig(enabled=True, root_dir=search_root, max_results=2)
    )

    report = limited_engine.search_files("match")

    assert report.matched_files == 4
    assert len(report.items) == 2
    assert report.truncated
    assert "仅保留前 2 条" in report.message


@pytest.mark.parametrize("query", ["", "  ", "x" * (MAX_QUERY_LENGTH + 1)])
def test_search_query_must_be_non_empty_and_bounded(query: str) -> None:
    """空关键词和超长关键词不得触发目录扫描。"""
    with pytest.raises(ValueError):
        normalize_query(query)


def test_delete_file_requires_unchanged_snapshot_and_verifies_parent(
    search_root: Path,
    engine: DirectoryFileEngine,
) -> None:
    """未变化的普通文件应删除成功，并通过父目录重新枚举复核。"""
    target = search_root / "group" / "target.txt"
    target.parent.mkdir()
    target.write_text("target", encoding="utf-8")
    item = engine.search_files("target").items[0]

    plan = engine.build_delete_plan(item, "confirm-token")
    result = engine.delete_file(item)

    assert plan.confirm_token == "confirm-token"
    assert not plan.blocked_reasons
    assert result.deleted
    assert result.verified
    assert not target.exists()
    assert target.parent.is_dir()


def test_delete_rejects_file_changed_after_search(
    search_root: Path,
    engine: DirectoryFileEngine,
) -> None:
    """搜索后发生变化的文件必须重新搜索，旧快照不得删除。"""
    target = search_root / "target.txt"
    target.write_text("old", encoding="utf-8")
    item = engine.search_files("target").items[0]
    target.write_text("new-content", encoding="utf-8")

    plan = engine.build_delete_plan(item, "confirm-token")
    result = engine.delete_file(item)

    assert not plan.confirm_token
    assert plan.blocked_reasons == ("文件状态已变化，请重新搜索后再删除",)
    assert not result.deleted
    assert not result.verified
    assert target.exists()


def test_delete_rejects_result_replaced_by_symlink(
    search_root: Path,
    engine: DirectoryFileEngine,
) -> None:
    """普通文件被替换成符号链接后不得沿链接删除目标。"""
    target = search_root / "target.txt"
    outside = search_root.parent / "outside.txt"
    target.write_text("target", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    item = engine.search_files("target").items[0]
    target.unlink()
    target.symlink_to(outside)

    result = engine.delete_file(item)

    assert not result.deleted
    assert not result.verified
    assert result.message == "不允许删除符号链接"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_string_false_config_value_is_not_treated_as_enabled() -> None:
    """字符串 false 不应被错误解析为启用状态。"""
    config = config_from_dict({"enabled": "false", "root_dir": "/media"})

    assert not config.enabled
    assert config.root_dir == Path("/media")


def test_plugin_api_paths_and_versioned_render_path() -> None:
    """插件 API 应保持相对路径，Vue 资源目录应绑定版本。"""
    plugin = DirectoryFileSearch.__new__(DirectoryFileSearch)

    paths = [item["path"] for item in plugin.get_api()]
    render_mode, render_path = plugin.get_render_mode()

    assert paths == [
        "/status",
        "/search",
        "/results",
        "/delete-preview",
        "/delete-batch-preview",
        "/delete",
        "/delete-batch",
    ]
    assert all(not path.startswith("/DirectoryFileSearch/") for path in paths)
    assert DirectoryFileSearch.plugin_version == "1.1.1"
    assert render_mode == "vue"
    assert render_path == "dist/assets-1.1.1"


def test_plugin_background_search_delete_and_verification(search_root: Path) -> None:
    """插件应后台完成搜索、令牌确认、删除和结果移除。"""
    target = search_root / "target.txt"
    target.write_text("target", encoding="utf-8")
    plugin = DirectoryFileSearch()
    plugin.init_plugin({"enabled": True, "root_dir": search_root.as_posix()})

    search_response = plugin.api_search("target")
    assert search_response.success
    plugin._task_future.result(timeout=5)
    results = plugin.api_results().data
    item = results["items"][0]

    preview = plugin.api_delete_preview(item["item_id"])
    assert preview.success
    token = preview.data["confirm_token"]
    delete_response = plugin.api_delete(
        item_id=item["item_id"],
        confirmed=True,
        confirm_token=token,
    )
    assert delete_response.success
    plugin._task_future.result(timeout=5)

    status = plugin.api_status().data
    remaining = plugin.api_results().data
    assert status["task_status"] == "succeeded"
    assert status["last_report"]["verified"]
    assert remaining["total"] == 0
    assert not target.exists()
    plugin.stop_service()


def test_plugin_rejects_delete_when_file_changes_after_preview(search_root: Path) -> None:
    """预览后文件发生变化时，插件必须拒绝消费旧确认令牌。"""
    target = search_root / "target.txt"
    target.write_text("target", encoding="utf-8")
    plugin = DirectoryFileSearch()
    plugin.init_plugin({"enabled": True, "root_dir": search_root.as_posix()})
    assert plugin.api_search("target").success
    plugin._task_future.result(timeout=5)
    item = plugin.api_results().data["items"][0]
    preview = plugin.api_delete_preview(item["item_id"])
    target.write_text("changed-content", encoding="utf-8")

    response = plugin.api_delete(
        item_id=item["item_id"],
        confirmed=True,
        confirm_token=preview.data["confirm_token"],
    )

    assert not response.success
    assert "文件状态已变化" in response.message
    assert target.exists()
    plugin.stop_service()


def test_plugin_batch_delete_removes_only_selected_source_files(
    search_root: Path,
) -> None:
    """多选删除只应永久删除确认令牌绑定的真实源文件。"""
    first = search_root / "batch-first.txt"
    second = search_root / "batch-second.txt"
    kept = search_root / "batch-kept.txt"
    for target in (first, second, kept):
        target.write_text(target.name, encoding="utf-8")
    plugin = DirectoryFileSearch()
    plugin.init_plugin({"enabled": True, "root_dir": search_root.as_posix()})
    assert plugin.api_search("batch-").success
    plugin._task_future.result(timeout=5)
    items = {
        item["name"]: item
        for item in plugin.api_results(page_size=100).data["items"]
    }

    preview = plugin.api_delete_batch_preview(
        DeleteBatchPreviewRequest(
            item_ids=[
                items[first.name]["item_id"],
                items[second.name]["item_id"],
            ]
        )
    )
    assert preview.success
    assert preview.data["selected_count"] == 2
    assert preview.data["ready_count"] == 2
    response = plugin.api_delete_batch(
        DeleteBatchExecuteRequest(
            confirmed=True,
            confirm_token=preview.data["confirm_token"],
        )
    )
    assert response.success
    plugin._task_future.result(timeout=5)

    report = plugin.api_status().data["last_report"]
    remaining = plugin.api_results(page_size=100).data["items"]
    assert report["kind"] == "delete_batch"
    assert report["verified"]
    assert report["verified_count"] == 2
    assert not first.exists()
    assert not second.exists()
    assert kept.exists()
    assert [item["name"] for item in remaining] == [kept.name]
    plugin.stop_service()


def test_plugin_select_all_delete_honors_excluded_results(search_root: Path) -> None:
    """全选删除应覆盖全部当前结果，同时保留用户明确排除的文件。"""
    targets = [search_root / f"select-all-{index}.txt" for index in range(3)]
    for target in targets:
        target.write_text(target.name, encoding="utf-8")
    plugin = DirectoryFileSearch()
    plugin.init_plugin({"enabled": True, "root_dir": search_root.as_posix()})
    assert plugin.api_search("select-all-").success
    plugin._task_future.result(timeout=5)
    items = plugin.api_results(page_size=100).data["items"]
    excluded = items[1]

    preview = plugin.api_delete_batch_preview(
        DeleteBatchPreviewRequest(
            select_all=True,
            excluded_item_ids=[excluded["item_id"]],
        )
    )
    assert preview.success
    assert preview.data["selected_count"] == 2
    response = plugin.api_delete_batch(
        DeleteBatchExecuteRequest(
            confirmed=True,
            confirm_token=preview.data["confirm_token"],
        )
    )
    assert response.success
    plugin._task_future.result(timeout=5)

    remaining = plugin.api_results(page_size=100).data["items"]
    assert [item["item_id"] for item in remaining] == [excluded["item_id"]]
    assert Path(excluded["absolute_path"]).exists()
    assert sum(target.exists() for target in targets) == 1
    plugin.stop_service()


def test_plugin_batch_delete_aborts_before_first_delete_when_snapshot_changes(
    search_root: Path,
) -> None:
    """整批预览后任一快照变化时必须在删除首个文件前取消任务。"""
    first = search_root / "guard-first.txt"
    changed = search_root / "guard-changed.txt"
    first.write_text("first", encoding="utf-8")
    changed.write_text("before", encoding="utf-8")
    plugin = DirectoryFileSearch()
    plugin.init_plugin({"enabled": True, "root_dir": search_root.as_posix()})
    assert plugin.api_search("guard-").success
    plugin._task_future.result(timeout=5)

    preview = plugin.api_delete_batch_preview(
        DeleteBatchPreviewRequest(select_all=True)
    )
    changed.write_text("changed-after-preview", encoding="utf-8")
    response = plugin.api_delete_batch(
        DeleteBatchExecuteRequest(
            confirmed=True,
            confirm_token=preview.data["confirm_token"],
        )
    )
    assert response.success
    plugin._task_future.result(timeout=5)

    status = plugin.api_status().data
    assert status["task_status"] == "failed"
    assert status["last_report"]["processed_count"] == 0
    assert "本批次未删除任何文件" in status["last_report"]["message"]
    assert first.exists()
    assert changed.exists()
    plugin.stop_service()
