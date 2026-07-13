import os
import time
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace
from typing import Dict, List

import pytest

from mediametadatasync import MediaMetadataSync
from mediametadatasync.core import (
    MetadataSyncConfig,
    MetadataSyncEngine,
    MissingMetadataItem,
    SyncReport,
    SyncStatus,
    config_from_dict,
    object_to_dict,
)


@pytest.fixture
def sync_config(tmp_path: Path) -> MetadataSyncConfig:
    """构造使用临时双目录的同步配置。"""
    source_dir = tmp_path / "9kg"
    target_dir = tmp_path / "番号系列"
    source_dir.mkdir()
    target_dir.mkdir()
    return MetadataSyncConfig(
        enabled=True,
        source_dir=source_dir,
        target_dir=target_dir,
        settle_seconds=1,
    )


def test_category_uses_first_ascii_letter(
    sync_config: MetadataSyncConfig,
) -> None:
    """番号目录应只按首字符分入 A-Z 或其他。"""
    engine = MetadataSyncEngine(sync_config)

    assert engine.get_category_name("abc-123") == "A"
    assert engine.get_category_name("Z-999") == "Z"
    assert engine.get_category_name("123-ABC") == "其他"
    assert engine.get_category_name("中文番号") == "其他"


def test_realtime_readiness_requires_matching_strm_and_nfo_stem(
    sync_config: MetadataSyncConfig,
) -> None:
    """任意 STRM 和任意 NFO 不应绕过同名配对门槛。"""
    directory = sync_config.source_dir / "演员" / "ABC-123"
    directory.mkdir(parents=True)
    (directory / "ABC-123.strm").write_text("video", encoding="utf-8")
    (directory / "OTHER.nfo").write_text("metadata", encoding="utf-8")
    engine = MetadataSyncEngine(sync_config)

    not_ready = engine.analyze_readiness(directory)
    (directory / "abc-123.nfo").write_text("metadata", encoding="utf-8")
    ready = engine.analyze_readiness(directory)

    assert not not_ready.ready
    assert not_ready.reason == "未满足同名 .strm + .nfo 条件"
    assert ready.ready
    assert ready.matched_stems == ["ABC-123"]


def test_full_forward_sync_copies_metadata_even_when_not_ready(
    sync_config: MetadataSyncConfig,
) -> None:
    """正向全量同步不应套用实时首次同步门槛。"""
    directory = sync_config.source_dir / "演员" / "ABC-123"
    directory.mkdir(parents=True)
    poster = directory / "poster.jpg"
    poster.write_bytes(b"poster")
    (directory / "ignored.mp4").write_bytes(b"video")
    engine = MetadataSyncEngine(sync_config)

    report = engine.full_forward_sync()
    target_directory = sync_config.target_dir / "A" / "ABC-123"

    assert (target_directory / "poster.jpg").read_bytes() == b"poster"
    assert not (target_directory / "ignored.mp4").exists()
    assert report.scanned_directories == 1
    assert report.copied_files == 1
    assert len(report.not_ready) == 1
    assert list(target_directory.glob(".*.tmp")) == []


def test_forward_sync_skips_unchanged_and_atomically_updates_changed_file(
    sync_config: MetadataSyncConfig,
) -> None:
    """未变化文件应跳过，更新文件应替换且不遗留临时文件。"""
    directory = sync_config.source_dir / "合集" / "ABC-123"
    directory.mkdir(parents=True)
    source_file = directory / "ABC-123.nfo"
    source_file.write_text("first", encoding="utf-8")
    initial_time = time.time_ns() - 5_000_000_000
    os.utime(source_file, ns=(initial_time, initial_time))
    engine = MetadataSyncEngine(sync_config)

    first_report = engine.forward_sync_directory(directory)
    second_report = engine.forward_sync_directory(directory)
    target_file = sync_config.target_dir / "A" / "ABC-123" / source_file.name
    updated_time = time.time_ns()
    source_file.write_text("second-version", encoding="utf-8")
    os.utime(source_file, ns=(updated_time, updated_time))
    third_report = engine.forward_sync_directory(directory)

    assert first_report.copied_files == 1
    assert second_report.skipped_files == 1
    assert second_report.files[0].status == SyncStatus.SKIPPED
    assert third_report.copied_files == 1
    assert target_file.read_text(encoding="utf-8") == "second-version"
    assert list(target_file.parent.glob(".*.tmp")) == []


def test_reverse_full_sync_writes_json_to_every_matching_source_directory(
    sync_config: MetadataSyncConfig,
) -> None:
    """同名番号存在多个源位置时应全部收到 JSON 回写。"""
    first_source = sync_config.source_dir / "演员甲" / "ABC-123"
    second_source = sync_config.source_dir / "演员乙" / "ABC-123"
    first_source.mkdir(parents=True)
    second_source.mkdir(parents=True)
    target_directory = sync_config.target_dir / "A" / "ABC-123"
    target_directory.mkdir(parents=True)
    json_file = target_directory / "ABC-123-mediainfo.json"
    json_file.write_text('{"video": "ok"}', encoding="utf-8")
    missing_directory = sync_config.target_dir / "Z" / "ZZZ-999"
    missing_directory.mkdir(parents=True)
    (missing_directory / "ZZZ-999.json").write_text("{}", encoding="utf-8")
    (target_directory / "poster.jpg").write_bytes(b"poster")
    engine = MetadataSyncEngine(sync_config)

    report = engine.full_reverse_sync()

    assert (first_source / json_file.name).read_text(encoding="utf-8") == '{"video": "ok"}'
    assert (second_source / json_file.name).read_text(encoding="utf-8") == '{"video": "ok"}'
    assert not (first_source / "poster.jpg").exists()
    assert report.copied_files == 2
    assert report.missing_targets == [
        (missing_directory / "ZZZ-999.json").as_posix()
    ]


def test_newer_destination_is_preserved(
    sync_config: MetadataSyncConfig,
) -> None:
    """目标文件修改时间更新时应避免被旧副本覆盖。"""
    directory = sync_config.source_dir / "演员" / "ABC-123"
    directory.mkdir(parents=True)
    source_file = directory / "ABC-123.json"
    source_file.write_text("old", encoding="utf-8")
    old_time = time.time_ns() - 10_000_000_000
    os.utime(source_file, ns=(old_time, old_time))
    target_file = sync_config.target_dir / "A" / "ABC-123" / source_file.name
    target_file.parent.mkdir(parents=True)
    target_file.write_text("new", encoding="utf-8")
    new_time = time.time_ns()
    os.utime(target_file, ns=(new_time, new_time))
    engine = MetadataSyncEngine(sync_config)

    report = engine.forward_sync_directory(directory)

    assert report.skipped_files == 1
    assert report.files[0].message == "目标文件较新，保留现有版本"
    assert target_file.read_text(encoding="utf-8") == "new"


def test_newer_non_json_destination_is_overwritten_by_forward_source(
    sync_config: MetadataSyncConfig,
) -> None:
    """正向 NFO 等元数据变化时应以 9kg 文件为准。"""
    directory = sync_config.source_dir / "演员" / "ABC-123"
    directory.mkdir(parents=True)
    source_file = directory / "ABC-123.nfo"
    source_file.write_text("source", encoding="utf-8")
    old_time = time.time_ns() - 10_000_000_000
    os.utime(source_file, ns=(old_time, old_time))
    target_file = sync_config.target_dir / "A" / "ABC-123" / source_file.name
    target_file.parent.mkdir(parents=True)
    target_file.write_text("target", encoding="utf-8")
    new_time = time.time_ns()
    os.utime(target_file, ns=(new_time, new_time))
    engine = MetadataSyncEngine(sync_config)

    report = engine.forward_sync_directory(directory)

    assert report.copied_files == 1
    assert target_file.read_text(encoding="utf-8") == "source"


def test_plugin_api_paths_are_relative_to_plugin_id() -> None:
    """插件 API 应由宿主统一添加插件 ID 前缀。"""
    plugin = MediaMetadataSync.__new__(MediaMetadataSync)

    paths = [item["path"] for item in plugin.get_api()]

    assert paths == [
        "/status",
        "/sync/all",
        "/sync/forward",
        "/sync/reverse",
        "/monitor/start",
        "/monitor/stop",
        "/missing/scan",
        "/missing/items",
        "/missing/delete-preview",
        "/missing/delete",
    ]
    assert all(not path.startswith("/MediaMetadataSync/") for path in paths)


def test_vue_render_path_is_versioned() -> None:
    """Vue 联邦资源目录应随插件版本变化，避免浏览器复用旧模块。"""
    mode, render_path = MediaMetadataSync.get_render_mode()

    assert MediaMetadataSync.plugin_version == "1.1.2"
    assert mode == "vue"
    assert render_path == "dist/assets-1.1.2"


def test_string_false_config_values_are_normalized() -> None:
    """字符串 false 不应被错误解析成启用状态。"""
    config = config_from_dict(
        {
            "enabled": "false",
            "monitor_enabled": "0",
            "reverse_sync_enabled": "off",
            "sync_extensions": ["strm", ".nfo", "JSON"],
            "cloud_mount_paths": "/mnt/cloud-a\n/mnt/cloud-b",
            "max_delete_files": "80",
        }
    )

    assert not config.enabled
    assert not config.monitor_enabled
    assert not config.reverse_sync_enabled
    assert config.sync_extensions == (".strm", ".nfo", ".json")
    assert config.cloud_mount_paths == (
        Path("/mnt/cloud-a"),
        Path("/mnt/cloud-b"),
    )
    assert config.max_delete_files == 80


def test_status_api_uses_standard_response_schema() -> None:
    """状态接口应返回宿主标准 Response 模型。"""
    plugin = MediaMetadataSync()

    response = plugin.api_status()

    assert response.success
    assert response.data["task_status"] == "idle"
    assert response.data["config"]["source_dir"] == "/media/9kg"
    assert response.data["config"]["cloud_mount_paths"] == [
        "/CloudNAS/CloudDrive"
    ]
    plugin.stop_service()


def test_non_trigger_metadata_waits_until_directory_is_activated(
    sync_config: MetadataSyncConfig,
) -> None:
    """图片和 JSON 不应触发未激活目录的首次实时同步。"""
    directory = sync_config.source_dir / "演员" / "ABC-123"
    directory.mkdir(parents=True)
    image_file = directory / "poster.jpg"
    image_file.write_bytes(b"poster")
    nfo_file = directory / "ABC-123.nfo"
    nfo_file.write_text("metadata", encoding="utf-8")
    plugin = MediaMetadataSync.__new__(MediaMetadataSync)
    plugin._state_lock = RLock()
    plugin._sync_config = sync_config
    plugin._engine = MetadataSyncEngine(sync_config)
    plugin._activated_directories = set()
    plugin._pending_source = {}
    plugin._suppressed_paths = {}

    plugin.queue_source_event(image_file, False)
    assert plugin._pending_source == {}

    plugin.queue_source_event(nfo_file, False)
    assert list(plugin._pending_source) == [directory.as_posix()]

    plugin._pending_source.clear()
    plugin._activated_directories.add("演员/ABC-123")
    plugin.queue_source_event(image_file, False)
    assert list(plugin._pending_source) == [directory.as_posix()]

    plugin._pending_source.clear()
    plugin._mark_suppressed(image_file)
    plugin.queue_source_event(image_file, False)
    assert plugin._pending_source == {}


def test_combined_sync_runs_forward_before_reverse() -> None:
    """启动双向任务必须先正向全量，再执行 JSON 回写。"""
    call_order: List[str] = []

    class _EngineStub:
        """记录双向同步调用顺序的引擎桩。"""

        @staticmethod
        def full_forward_sync() -> SyncReport:
            """记录正向全量调用。"""
            call_order.append("forward")
            return SyncReport(kind="forward_full", copied_files=1)

        @staticmethod
        def full_reverse_sync() -> SyncReport:
            """记录 JSON 回写调用。"""
            call_order.append("reverse")
            return SyncReport(kind="reverse_full", copied_files=2)

        @staticmethod
        def get_stats() -> Dict[str, int]:
            """返回空分类统计。"""
            return {}

    plugin = MediaMetadataSync.__new__(MediaMetadataSync)
    plugin._engine = _EngineStub()
    plugin._sync_lock = RLock()
    plugin._lifecycle_stop_event = Event()
    plugin._stats = {}
    plugin._prepare_directories = lambda: None
    plugin._refresh_readiness_state = lambda: None

    result = plugin._run_combined_sync()

    assert call_order == ["forward", "reverse"]
    assert result["forward"]["copied_files"] == 1
    assert result["reverse"]["copied_files"] == 2


def test_missing_metadata_scan_groups_duplicate_source_locations(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
) -> None:
    """同番号同名 STRM 的多个 9kg 位置应聚合成一条缺失记录。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    cloud_file = cloud_root / "ABC-123.mp4"
    cloud_file.write_bytes(b"video")
    sync_config.cloud_mount_paths = (cloud_root,)
    first_directory = sync_config.source_dir / "演员甲" / "ABC-123"
    second_directory = sync_config.source_dir / "演员乙" / "ABC-123"
    first_directory.mkdir(parents=True)
    second_directory.mkdir(parents=True)
    for directory in (first_directory, second_directory):
        (directory / "ABC-123.strm").write_text(
            cloud_file.as_posix(),
            encoding="utf-8",
        )
    (second_directory / "ABC-123.nfo").write_text("nfo", encoding="utf-8")
    engine = MetadataSyncEngine(sync_config)

    report = engine.scan_missing_metadata()

    assert report.scanned_directories == 2
    assert report.scanned_strm_files == 2
    assert report.missing_items == 1
    item = report.items[0]
    assert item.number == "ABC-123"
    assert item.missing_types == ["MediaInfo", "NFO"]
    assert item.source_paths == sorted(
        [
            (first_directory / "ABC-123.strm").as_posix(),
            (second_directory / "ABC-123.strm").as_posix(),
        ]
    )
    assert item.owner_names == ["演员乙", "演员甲"]
    assert item.cloud_ready
    assert item.cloud_paths == [cloud_file.as_posix()]


def test_missing_delete_preview_covers_three_locations_and_detects_changes(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
) -> None:
    """删除预览应列出三端文件，并在文件集合变化后生成新令牌。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    cloud_file = cloud_root / "ABC-123.mp4"
    cloud_file.write_bytes(b"video")
    sync_config.cloud_mount_paths = (cloud_root,)
    sync_config.sync_extensions = (".json",)
    source_directory = sync_config.source_dir / "演员" / "ABC-123"
    source_directory.mkdir(parents=True)
    source_strm = source_directory / "ABC-123.strm"
    source_strm.write_text(cloud_file.as_posix(), encoding="utf-8")
    (source_directory / "poster.jpg").write_bytes(b"poster")
    target_directory = sync_config.target_dir / "A" / "ABC-123"
    target_directory.mkdir(parents=True)
    (target_directory / "ABC-123.strm").write_text(
        cloud_file.as_posix(),
        encoding="utf-8",
    )
    engine = MetadataSyncEngine(sync_config)
    item = engine.scan_missing_metadata().items[0]

    first_plan = engine.build_missing_delete_plan(item)
    (target_directory / "fanart.jpg").write_bytes(b"fanart")
    second_plan = engine.build_missing_delete_plan(item)

    assert first_plan.blocked_reasons == []
    assert first_plan.cloud_files == [cloud_file.as_posix()]
    assert source_strm.as_posix() in first_plan.source_files
    assert (source_directory / "poster.jpg").as_posix() in first_plan.source_files
    assert (target_directory / "ABC-123.strm").as_posix() in first_plan.target_files
    assert first_plan.confirm_token != second_plan.confirm_token
    assert (target_directory / "fanart.jpg").as_posix() in second_plan.target_files


def test_missing_delete_api_requires_preview_confirmation(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺失记录删除接口应拒绝未确认或缺少预览令牌的请求。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    cloud_file = cloud_root / "ABC-123.mp4"
    cloud_file.write_bytes(b"video")
    sync_config.cloud_mount_paths = (cloud_root,)
    source_directory = sync_config.source_dir / "演员" / "ABC-123"
    source_directory.mkdir(parents=True)
    (source_directory / "ABC-123.strm").write_text(
        cloud_file.as_posix(),
        encoding="utf-8",
    )
    engine = MetadataSyncEngine(sync_config)
    report = object_to_dict(engine.scan_missing_metadata())
    item_id = report["items"][0]["item_id"]
    plugin = MediaMetadataSync()
    plugin._enabled = True
    plugin._sync_config = sync_config
    plugin._engine = engine
    plugin._missing_metadata_report = report
    monkeypatch.setattr(plugin, "save_data", lambda *args, **kwargs: None)

    preview = plugin.api_missing_delete_preview(item_id)
    unconfirmed = plugin.api_delete_missing_metadata(item_id=item_id)
    missing_token = plugin.api_delete_missing_metadata(
        item_id=item_id,
        confirmed=True,
    )

    assert preview.success
    assert preview.data["confirm_token"]
    assert not unconfirmed.success
    assert unconfirmed.message == "请先预览并确认删除目标"
    assert not missing_token.success
    assert missing_token.message == "请先预览并确认删除目标"
    plugin.stop_service()


def test_missing_delete_plan_preserves_shared_and_other_strm_files(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
) -> None:
    """同目录存在多个 STRM 时不得删除共享图片或其他条目的文件。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    selected_cloud = cloud_root / "ABC-123-CD1.mp4"
    other_cloud = cloud_root / "ABC-123-CD2.mp4"
    selected_cloud.write_bytes(b"cd1")
    other_cloud.write_bytes(b"cd2")
    sync_config.cloud_mount_paths = (cloud_root,)
    source_directory = sync_config.source_dir / "合集" / "ABC-123"
    source_directory.mkdir(parents=True)
    selected_strm = source_directory / "ABC-123-CD1.strm"
    other_strm = source_directory / "ABC-123-CD2.strm"
    selected_strm.write_text(selected_cloud.as_posix(), encoding="utf-8")
    other_strm.write_text(other_cloud.as_posix(), encoding="utf-8")
    (source_directory / "ABC-123-CD1.nfo").write_text("nfo", encoding="utf-8")
    shared_poster = source_directory / "poster.jpg"
    shared_poster.write_bytes(b"poster")
    engine = MetadataSyncEngine(sync_config)
    selected_item = next(
        item
        for item in engine.scan_missing_metadata().items
        if item.file_name == selected_strm.name
    )

    plan = engine.build_missing_delete_plan(selected_item)

    assert selected_strm.as_posix() in plan.source_files
    assert (source_directory / "ABC-123-CD1.nfo").as_posix() in plan.source_files
    assert other_strm.as_posix() not in plan.source_files
    assert shared_poster.as_posix() not in plan.source_files
    assert plan.cloud_files == [selected_cloud.as_posix()]


def test_missing_delete_executes_cloud_target_source_and_verifies(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认删除后应依次清理网盘、番号系列和 9kg，并保留目录。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    cloud_file = cloud_root / "ABC-123.mp4"
    cloud_file.write_bytes(b"video")
    sync_config.cloud_mount_paths = (cloud_root,)
    source_directory = sync_config.source_dir / "演员" / "ABC-123"
    source_directory.mkdir(parents=True)
    source_strm = source_directory / "ABC-123.strm"
    source_strm.write_text(cloud_file.as_posix(), encoding="utf-8")
    (source_directory / "poster.jpg").write_bytes(b"poster")
    target_directory = sync_config.target_dir / "A" / "ABC-123"
    target_directory.mkdir(parents=True)
    target_strm = target_directory / "ABC-123.strm"
    target_strm.write_text(cloud_file.as_posix(), encoding="utf-8")
    engine = MetadataSyncEngine(sync_config)
    missing_report = object_to_dict(engine.scan_missing_metadata())
    item = MissingMetadataItem.from_dict(missing_report["items"][0])
    preview = engine.build_missing_delete_plan(item)
    delete_order: List[str] = []

    class _StorageStub:
        @staticmethod
        def get_file_item(storage: str, path: Path):
            """返回本地测试路径对应的文件项。"""
            del storage
            if not path.exists():
                return None
            return SimpleNamespace(
                type="file" if path.is_file() else "dir",
                path=path.as_posix(),
            )

        @staticmethod
        def delete_file(file_item) -> bool:
            """删除测试文件并记录调用顺序。"""
            path = Path(file_item.path)
            delete_order.append(path.as_posix())
            path.unlink()
            return True

        @staticmethod
        def list_files(parent_item):
            """返回测试父目录的当前子项。"""
            return [
                SimpleNamespace(path=path.as_posix())
                for path in Path(parent_item.path).iterdir()
            ]

    monkeypatch.setattr("mediametadatasync.StorageChain", _StorageStub)
    plugin = MediaMetadataSync()
    plugin._enabled = True
    plugin._sync_config = sync_config
    plugin._engine = engine
    plugin._missing_metadata_report = missing_report
    plugin._DELETE_VERIFY_DELAYS = (0.0,)
    monkeypatch.setattr(plugin, "save_data", lambda *args, **kwargs: None)

    result = plugin._run_missing_metadata_delete(
        item.item_id,
        preview.confirm_token,
    )

    assert result["success"]
    assert result["verified"]
    assert delete_order[0] == cloud_file.as_posix()
    assert delete_order.index(target_strm.as_posix()) < delete_order.index(
        source_strm.as_posix()
    )
    assert not cloud_file.exists()
    assert list(source_directory.iterdir()) == []
    assert list(target_directory.iterdir()) == []
    assert source_directory.is_dir()
    assert target_directory.is_dir()
    assert plugin._missing_metadata_report["items"] == []
    plugin.stop_service()


def test_missing_delete_stops_when_cloud_verification_fails(
    sync_config: MetadataSyncConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网盘源文件仍存在时不得继续删除番号系列和 9kg。"""
    cloud_root = tmp_path / "cloud"
    cloud_root.mkdir()
    cloud_file = cloud_root / "ABC-123.mp4"
    cloud_file.write_bytes(b"video")
    sync_config.cloud_mount_paths = (cloud_root,)
    source_directory = sync_config.source_dir / "演员" / "ABC-123"
    source_directory.mkdir(parents=True)
    source_strm = source_directory / "ABC-123.strm"
    source_strm.write_text(cloud_file.as_posix(), encoding="utf-8")
    target_directory = sync_config.target_dir / "A" / "ABC-123"
    target_directory.mkdir(parents=True)
    target_strm = target_directory / "ABC-123.strm"
    target_strm.write_text(cloud_file.as_posix(), encoding="utf-8")
    engine = MetadataSyncEngine(sync_config)
    missing_report = object_to_dict(engine.scan_missing_metadata())
    item = MissingMetadataItem.from_dict(missing_report["items"][0])
    preview = engine.build_missing_delete_plan(item)

    class _FailingStorageStub:
        @staticmethod
        def get_file_item(storage: str, path: Path):
            """返回仍然存在的测试文件项。"""
            del storage
            if not path.exists():
                return None
            return SimpleNamespace(
                type="file" if path.is_file() else "dir",
                path=path.as_posix(),
            )

        @staticmethod
        def delete_file(file_item) -> bool:
            """模拟网盘删除调用失败。"""
            del file_item
            return False

        @staticmethod
        def list_files(parent_item):
            """返回仍包含源文件的父目录列表。"""
            return [
                SimpleNamespace(path=path.as_posix())
                for path in Path(parent_item.path).iterdir()
            ]

    monkeypatch.setattr("mediametadatasync.StorageChain", _FailingStorageStub)
    plugin = MediaMetadataSync()
    plugin._enabled = True
    plugin._sync_config = sync_config
    plugin._engine = engine
    plugin._missing_metadata_report = missing_report
    plugin._DELETE_VERIFY_DELAYS = (0.0,)
    monkeypatch.setattr(plugin, "save_data", lambda *args, **kwargs: None)

    result = plugin._run_missing_metadata_delete(
        item.item_id,
        preview.confirm_token,
    )

    assert not result["success"]
    assert cloud_file.exists()
    assert source_strm.exists()
    assert target_strm.exists()
    assert all(
        item_result["status"] == "skipped"
        for item_result in [
            *result["target_results"],
            *result["source_results"],
        ]
    )
    plugin.stop_service()
