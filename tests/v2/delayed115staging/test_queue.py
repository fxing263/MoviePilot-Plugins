"""延迟暂存插件仅使用临时硬链接；不调用下载器或上传器。"""

import copy
import errno
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "plugins.v2"


@pytest.fixture
def plugin_module(monkeypatch):
    from app.sdk.events import eventmanager
    monkeypatch.setattr(eventmanager, "register", lambda *_args, **_kwargs: lambda function: function)
    monkeypatch.syspath_prepend(str(PLUGIN_ROOT))
    before = set(sys.modules)
    module = importlib.import_module("delayed115staging")
    yield module
    for name in set(sys.modules) - before:
        if name == "delayed115staging" or name.startswith("delayed115staging."):
            sys.modules.pop(name, None)


@pytest.fixture
def setup_queue(tmp_path, plugin_module):
    engine = importlib.import_module("delayed115staging.queue")
    library = tmp_path / "media"
    source = library / "国产电视剧/兰香如故 (2026)/Season 01/S01E01.mkv"
    source.parent.mkdir(parents=True)
    download = tmp_path / "qb/release.mkv"
    download.parent.mkdir()
    download.write_bytes(b"fake media")
    os.link(download, source)
    config = engine.validate_config({
        "enabled": True, "library_root": str(library), "staging_root": str(tmp_path / "115-staging"),
        "rules": [{"directory": "/国产电视剧", "delay_minutes": 15}],
        "cleanup_organized": True,
    })
    now = [1000.0]
    queue = engine.StagingQueue(tmp_path / "plugin-data", clock=lambda: now[0])
    return SimpleNamespace(engine=engine, queue=queue, config=config, source=source,
                           download=download, now=now, root=tmp_path, module=plugin_module)


def _enqueue(s):
    return s.queue.enqueue(s.config, str(s.source))


def _stage(s):
    task_id = _enqueue(s)
    s.now[0] += 901
    s.queue.tick(cleanup_organized=True)
    return task_id, Path(s.queue.tasks()[0]["staging_path"])


@pytest.mark.parametrize("directories", [["/电影", "/电影"], ["电影", "电影/动作"],
                                        ["电影/动作", "电影"], ["电影/", "/电影/."]])
def test_conflicting_rules_rejected(setup_queue, directories):
    s = setup_queue
    config = dict(s.config, rules=[{"directory": path, "delay_minutes": 1} for path in directories])
    with pytest.raises(ValueError, match="冲突"):
        s.engine.validate_config(config)


def test_rules_component_matching_and_size_edges(setup_queue):
    s = setup_queue
    config = s.engine.validate_config(dict(s.config, rules=[
        {"directory": "/动漫", "tiers": [{"below_gb": 5, "delay_minutes": 10},
                                            {"below_gb": 20, "delay_minutes": 30},
                                            {"below_gb": None, "delay_minutes": 60}]},
        {"directory": "/电影", "delay_minutes": 45},
    ]))
    for size, expected in [(0, 10), (5 * 10**9 - 1, 10), (5 * 10**9, 30),
                           (20 * 10**9 - 1, 30), (20 * 10**9, 60)]:
        assert s.engine.match_rule(config, Path("动漫/title/file.mkv"), size)[1] == expected
    assert s.engine.match_rule(config, Path("电影/file.mkv"), 0)[1] == 45
    assert s.engine.match_rule(config, Path("电影节/file.mkv"), 0) is None
    assert s.engine.match_rule(config, Path("其他/file.mkv"), 0) is None


@pytest.mark.parametrize("tiers", [[], [{"below_gb": 5, "delay_minutes": 1}],
                                  [{"below_gb": None, "delay_minutes": 1}, {"below_gb": None, "delay_minutes": 2}],
                                  [{"below_gb": 0, "delay_minutes": 1}, {"below_gb": None, "delay_minutes": 2}],
                                  [{"below_gb": None, "delay_minutes": -1}]])
def test_invalid_size_tiers_rejected(setup_queue, tiers):
    s = setup_queue
    with pytest.raises(ValueError):
        s.engine.validate_config(dict(s.config, rules=[{"directory": "动漫", "tiers": tiers}]))


def test_missing_final_upper_bound_normalized(setup_queue):
    s = setup_queue
    config = s.engine.validate_config(dict(s.config, rules=[{"directory": "动漫", "tiers": [{"delay_minutes": 10}]}]))
    assert s.engine.match_rule(config, Path("动漫/a.mkv"), 42)[1] == 10


@pytest.mark.parametrize("directory", ["/", "", "../qb", "电影/../../qb"])
def test_rule_escape_rejected(setup_queue, directory):
    s = setup_queue
    with pytest.raises(ValueError):
        s.engine.validate_config(dict(s.config, rules=[{"directory": directory, "delay_minutes": 1}]))


def test_root_overlap_and_symlinks_rejected(setup_queue):
    s = setup_queue
    for staging in [s.config["library_root"], str(s.source.parent), str(s.root)]:
        with pytest.raises(ValueError):
            s.engine.validate_config(dict(s.config, staging_root=staging))
    alias = s.root / "media/alias"
    alias.symlink_to(s.source.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        s.engine.validate_config(dict(s.config, rules=[{"directory": "alias", "delay_minutes": 1}]))


def test_delay_restart_idempotence_and_structure(setup_queue):
    s = setup_queue
    task_id = _enqueue(s)
    original = s.queue.tasks()[0]
    s.now[0] += 100
    assert _enqueue(s) == task_id
    assert s.queue.tasks()[0]["ready_at"] == original["ready_at"]
    s.queue.tick()
    destination = Path(original["staging_path"])
    assert not destination.exists()
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: original["ready_at"])
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == "staged"
    assert destination.relative_to(s.config["staging_root"]) == s.source.relative_to(s.config["library_root"])
    assert os.path.samefile(destination, s.source)
    assert destination.stat().st_nlink == 3
    s.queue.tick()
    assert destination.stat().st_nlink == 3


def test_cleanup_requires_confirmation_and_preserves_seeding(setup_queue):
    s = setup_queue
    task_id, destination = _stage(s)
    for verified, reference in [(False, "remote"), (True, "")]:
        with pytest.raises(ValueError):
            s.queue.action(task_id, "confirm", reference, verified)
    s.queue.tick(cleanup_organized=True)
    assert destination.exists() and s.source.exists()
    s.queue.action(task_id, "confirm", "115:file-id:42", True)
    s.queue = s.engine.StagingQueue(s.queue.directory)
    s.queue.tick(cleanup_organized=True)
    task = s.queue.tasks()[0]
    assert task["state"] == "done"
    assert task["upload_result"]["remote_reference"] == "115:file-id:42"
    assert not destination.exists() and not s.source.exists()
    assert s.download.read_bytes() == b"fake media"
    assert Path(s.config["library_root"]).is_dir()
    assert Path(s.config["staging_root"]).is_dir()
    assert not destination.parent.exists()
    s.queue.action(task_id, "confirm", "same", True)
    s.queue.tick(cleanup_organized=True)
    assert s.download.exists()


def test_missing_staging_is_not_upload_success(setup_queue):
    s = setup_queue
    task_id, destination = _stage(s)
    destination.unlink()
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()
    s.queue.action(task_id, "confirm", "verified remotely", True)
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "done" and s.download.exists()


@pytest.mark.parametrize("at_admission,current", [(False, True), (True, False), (False, False)])
def test_organized_cleanup_requires_both_options(setup_queue, at_admission, current):
    s = setup_queue
    s.config["cleanup_organized"] = at_admission
    task_id, destination = _stage(s)
    s.queue.action(task_id, "confirm", "remote", True)
    s.queue.tick(cleanup_organized=current)
    assert s.source.exists() and s.download.exists() and not destination.exists()


def test_cancel_preserves_staged_and_waiting_files(setup_queue):
    s = setup_queue
    task_id = _enqueue(s)
    s.queue.action(task_id, "cancel")
    s.now[0] += 1000
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == "cancelled"
    assert not Path(s.queue.tasks()[0]["staging_path"]).exists()
    with pytest.raises(ValueError):
        s.queue.action(task_id, "confirm", "remote", True)
    assert s.source.exists()


def test_cross_device_fails_without_copy_and_manual_retry(setup_queue, monkeypatch):
    s = setup_queue
    real_link = os.link
    def no_link(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "cross-device")
    monkeypatch.setattr(os, "link", no_link)
    task_id, destination = _stage(s)
    assert s.queue.tasks()[0]["state"] == "failed"
    assert not destination.exists() and s.source.exists()
    monkeypatch.setattr(os, "link", real_link)
    s.queue.action(task_id, "retry")
    s.queue.tick()
    assert os.path.samefile(s.source, destination)
    s.queue.action(task_id, "cancel")
    assert destination.exists()


def test_source_replaced_before_due_is_preserved(setup_queue):
    s = setup_queue
    _enqueue(s)
    s.source.unlink()
    s.source.write_bytes(b"new version")
    s.now[0] += 1000
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == "failed"
    assert not Path(s.queue.tasks()[0]["staging_path"]).exists()
    assert s.source.read_bytes() == b"new version"


@pytest.mark.parametrize("replace", ["staging", "source"])
def test_cleanup_uses_mapped_source_but_protects_staging_replacement(setup_queue, replace):
    s = setup_queue
    task_id, destination = _stage(s)
    path = destination if replace == "staging" else s.source
    path.unlink()
    path.write_bytes(b"replacement")
    s.queue.action(task_id, "confirm", "remote", True)
    s.queue.tick(cleanup_organized=True)
    if replace == "staging":
        assert s.queue.tasks()[0]["state"] == "cleanup_failed"
        assert path.read_bytes() == b"replacement"
    else:
        assert s.queue.tasks()[0]["state"] == "done"
        assert not path.exists()
    assert s.download.exists()


def test_collision_preserved(setup_queue):
    s = setup_queue
    task_id = _enqueue(s)
    destination = Path(s.queue.tasks()[0]["staging_path"])
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing unrelated")
    s.now[0] += 1000
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == "failed"
    assert destination.read_bytes() == b"existing unrelated"
    with pytest.raises(ValueError):
        s.queue.action(task_id, "confirm", "remote", True)


@pytest.mark.parametrize("exists", [True, False])
def test_crash_after_link_intent_recovers_conservatively(setup_queue, exists):
    s = setup_queue
    _enqueue(s)
    path = s.queue.directory / "queue.json"
    data = json.loads(path.read_text())
    task = next(iter(data["tasks"].values()))
    task["state"] = "linking"
    path.write_text(json.dumps(data))
    destination = Path(task["staging_path"])
    if exists:
        destination.parent.mkdir(parents=True)
        os.link(s.source, destination)
    s.queue = s.engine.StagingQueue(s.queue.directory)
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == ("staged" if exists else "failed")
    assert destination.exists() == exists


def test_intent_must_persist_before_link(setup_queue, monkeypatch):
    s = setup_queue
    _enqueue(s)
    s.now[0] += 1000
    def fail_write(_data):
        raise OSError("disk full")
    monkeypatch.setattr(s.queue, "_save", fail_write)
    with pytest.raises(OSError, match="disk full"):
        s.queue.tick()
    assert not Path(s.queue.tasks()[0]["staging_path"]).exists()
    assert s.queue.tasks()[0]["state"] == "waiting"


def test_corrupt_queue_not_overwritten(setup_queue):
    s = setup_queue
    _enqueue(s)
    path = s.queue.directory / "queue.json"
    path.write_text("{broken")
    with pytest.raises(ValueError):
        s.queue.tick()
    assert path.read_text() == "{broken"


def test_symlink_parent_after_enqueue_rejected(setup_queue):
    s = setup_queue
    _enqueue(s)
    staging = Path(s.config["staging_root"])
    staging.mkdir()
    outside = s.root / "outside"
    outside.mkdir()
    (staging / "国产电视剧").symlink_to(outside, target_is_directory=True)
    s.now[0] += 1000
    s.queue.tick()
    assert s.queue.tasks()[0]["state"] == "failed"
    assert list(outside.iterdir()) == []


def test_legacy_download_path_is_ignored_during_cleanup(setup_queue):
    s = setup_queue
    task_id = s.queue.enqueue(s.config, str(s.source))
    with s.queue._locked() as data:
        data['tasks'][task_id]['download_path'] = str(s.source)
        s.queue._save(data)
    s.now[0] += 1000
    s.queue.tick()
    task = s.queue.tasks()[0]
    s.queue.action(task["id"], "confirm", "remote", True)
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "done"
    assert not s.source.exists() and s.download.exists()


def test_plugin_event_lifecycle_and_invalid_config(setup_queue, monkeypatch):
    s = setup_queue
    cls = s.module.Delayed115Staging
    # 基类构造不触发链路、数据库或后台服务；测试仅替换插件外围持久化。
    monkeypatch.setattr(s.module._PluginBase, "__init__", lambda self: None)
    plugin = cls()
    saved = {}
    monkeypatch.setattr(plugin, "get_data_path", lambda: s.queue.directory)
    monkeypatch.setattr(plugin, "get_data", lambda key: saved.get(key))
    monkeypatch.setattr(plugin, "save_data", lambda key, value: saved.update({key: copy.deepcopy(value)}))
    monkeypatch.setattr(plugin, "update_config", lambda value: saved.update({"restored": value}))
    plugin.systemmessage = SimpleNamespace(put=lambda _message: None)
    plugin.init_plugin(s.config)
    payload = {"fileitem": {"storage": "local", "path": str(s.download)}, "transferinfo": {
        "success": True, "target_item": {"storage": "local", "path": str(s.source)},
        "file_list_new": [str(s.source)],
    }}
    plugin.on_transfer_complete(SimpleNamespace(event_data=payload))
    assert len(plugin.task_list().data["tasks"]) == 1
    assert plugin.get_service()[0]["kwargs"] == {"seconds": 15}
    assert plugin.get_state()
    assert not plugin.task_action({"task_id": [], "action": "cancel"}).success
    plugin.stop_service()
    assert not plugin.get_state() and plugin.get_service() == []
    plugin.init_plugin(dict(s.config, rules=s.config["rules"] * 2))
    assert not plugin.get_state()
    assert saved["restored"] == s.config
    assert not plugin.validate_settings(dict(s.config, rules=s.config["rules"] * 2)).success
    assert len(plugin.task_list().data["tasks"]) == 1


def test_api_requires_administrator(plugin_module):
    from fastapi import HTTPException
    from app.schemas.token import TokenPayload
    with pytest.raises(HTTPException) as error:
        plugin_module._admin(TokenPayload(super_user=False))
    assert error.value.status_code == 403
    plugin_module._admin(TokenPayload(super_user=True))


def test_cleanup_concurrent_replacement_restored_without_deletion(setup_queue, monkeypatch):
    s = setup_queue
    task_id, destination = _stage(s)
    s.queue.action(task_id, "confirm", "remote", True)
    rename = os.rename
    replaced = []
    def replace_before_rename(src, dst, **kwargs):
        if src == destination.name and not replaced:
            destination.unlink()
            destination.write_bytes(b"concurrent replacement")
            replaced.append(True)
        return rename(src, dst, **kwargs)
    monkeypatch.setattr(os, "rename", replace_before_rename)
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "cleanup_failed"
    assert destination.read_bytes() == b"concurrent replacement"
    assert s.source.exists() and s.download.exists()


def test_cleanup_recovers_after_quarantine_rename(setup_queue):
    s = setup_queue
    task_id, destination = _stage(s)
    s.queue.action(task_id, "confirm", "remote", True)
    hold = destination.parent / f".delayed115-cleanup-{task_id}-staging"
    hold.mkdir()
    destination.rename(hold / "payload")
    s.queue = s.engine.StagingQueue(s.queue.directory)
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "done"
    assert not hold.exists() and not s.source.exists() and s.download.exists()


def test_http_validation_and_admin_boundary(plugin_module, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.schemas.token import TokenPayload
    monkeypatch.setattr(plugin_module._PluginBase, "__init__", lambda self: None)
    plugin = plugin_module.Delayed115Staging()
    app = FastAPI()
    for definition in plugin.get_api():
        route = dict(definition)
        route.pop("auth")
        app.add_api_route(**route)
    principal = [TokenPayload(super_user=False)]
    app.dependency_overrides[plugin_module.verify_token] = lambda: principal[0]
    with TestClient(app) as client:
        assert client.get("/tasks").status_code == 403
        principal[0] = TokenPayload(super_user=True)
        response = client.post("/validate", json={})
        assert response.status_code == 200 and response.json()["success"] is True
        response = client.post("/validate", json={"enabled": True, "library_root": "/"})
        assert response.status_code == 200 and response.json()["success"] is False
        assert client.post("/validate", json=[]).status_code == 422
        assert client.get("/tasks").json()["data"]["tasks"] == []


def test_corrupt_confirmation_stops_before_any_deletion(setup_queue):
    s = setup_queue
    _task_id, destination = _stage(s)
    log = s.queue.directory / "queue.json"
    data = json.loads(log.read_text())
    task = next(iter(data["tasks"].values()))
    task["state"] = "confirmed"
    task["upload_result"] = None
    log.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="确认"):
        s.queue.tick(cleanup_organized=True)
    assert destination.exists() and s.source.exists() and s.download.exists()


def test_cleanup_crash_after_unlink_is_idempotent(setup_queue, monkeypatch):
    s = setup_queue
    task_id, destination = _stage(s)
    s.queue.action(task_id, "confirm", "remote", True)
    def fail_write(_data):
        raise OSError("crash before cleanup receipt")
    monkeypatch.setattr(s.queue, "_save", fail_write)
    with pytest.raises(OSError):
        s.queue.tick(cleanup_organized=True)
    assert not destination.exists() and s.source.exists()
    s.queue = s.engine.StagingQueue(s.queue.directory)
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "done" and s.download.exists()


def test_concurrent_queue_instances_deduplicate(setup_queue):
    from concurrent.futures import ThreadPoolExecutor
    s = setup_queue
    second = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(queue.enqueue, s.config, str(s.source))
                   for queue in (s.queue, second)]
        ids = [future.result() for future in pending]
    assert ids[0] == ids[1] and len(s.queue.tasks()) == 1
    s.now[0] += 1000
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = [executor.submit(queue.tick) for queue in (s.queue, second)]
        for future in pending:
            future.result()
    assert s.queue.tasks()[0]["state"] == "staged"
    assert s.source.stat().st_nlink == 3


@pytest.mark.parametrize("delay", [True, "10", float("nan"), float("inf"), 1e308, 10**400])
def test_delay_rejects_non_numeric_or_overflow_before_save(setup_queue, delay):
    s = setup_queue
    with pytest.raises(ValueError):
        s.engine.validate_config(dict(s.config, rules=[{"directory": "动漫", "delay_minutes": delay}]))


def _multi_config(s):
    return s.engine.validate_config({
        "enabled": True, "cleanup_organized": True, "cleanup_empty_dirs": True,
        "mappings": [
            {"library_root": str(s.root / "pt1"), "staging_root": str(s.root / "stage1"),
             "rules": [{"directory": "/", "delay_minutes": 10}]},
            {"library_root": str(s.root / "pt2"), "staging_root": str(s.root / "stage2"),
             "rules": [{"directory": "/", "tiers": [
                 {"below_gb": 5, "delay_minutes": 20}, {"below_gb": None, "delay_minutes": 60}]}]},
        ],
    })


def test_multiple_roots_keep_same_relative_names_separate(setup_queue):
    s = setup_queue
    config = _multi_config(s)
    relative = Path("电视剧/同名剧/Season 01/E01.mkv")
    files = []
    for index, mapping in enumerate(config["mappings"]):
        source = Path(mapping["library_root"]) / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(f"media-{index}".encode())
        files.append(source)
        s.queue.enqueue(config, str(source))
    tasks = s.queue.tasks()
    assert len(tasks) == 2 and tasks[0]["id"] != tasks[1]["id"]
    assert {task["relative_path"] for task in tasks} == {str(relative)}
    s.now[0] += 600
    s.queue.tick()
    first, second = (Path(mapping["staging_root"]) / relative for mapping in config["mappings"])
    assert first.read_bytes() == b"media-0" and not second.exists()
    s.now[0] += 600
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    s.queue.tick()
    assert second.read_bytes() == b"media-1"
    assert os.path.samefile(first, files[0]) and os.path.samefile(second, files[1])
    assert not os.path.samefile(first, second)
    first_task = next(task for task in s.queue.tasks() if task["source_path"] == str(files[0]))
    s.queue.action(first_task["id"], "confirm", "remote-first-file", True)
    s.queue.tick(cleanup_organized=True)
    assert not first.exists() and not files[0].exists()
    assert files[1].exists() and second.exists() and s.download.exists()
    assert all(Path(mapping["library_root"]).is_dir() for mapping in config["mappings"])
    assert all(Path(mapping["staging_root"]).is_dir() for mapping in config["mappings"])


@pytest.mark.parametrize("field,value", [
    ("library_root", "pt1"), ("library_root", "pt1/child"),
    ("staging_root", "stage1"), ("staging_root", "stage1/child"),
    ("library_root", "stage1"), ("library_root", "stage1/child"),
    ("staging_root", "pt1"), ("staging_root", "pt1/child"),
])
def test_mapping_overlap_rejected_in_both_orders(setup_queue, field, value):
    s = setup_queue
    config = _multi_config(s)
    config["mappings"][1][field] = str(s.root / value)
    for mappings in (config["mappings"], list(reversed(config["mappings"]))):
        with pytest.raises(ValueError):
            s.engine.validate_config(dict(config, mappings=mappings))


@pytest.mark.parametrize("rules", [
    [{"directory": "/", "delay_minutes": 1}, {"directory": "电影", "delay_minutes": 5}],
    [{"directory": "电影", "delay_minutes": 1}, {"directory": "电影/动作", "delay_minutes": 5}],
    [{"directory": "电影", "delay_minutes": 1}, {"directory": "/电影/", "delay_minutes": 5}],
])
def test_multi_mapping_rule_conflicts(setup_queue, rules):
    s = setup_queue
    config = _multi_config(s)
    config["mappings"][0]["rules"] = rules
    with pytest.raises(ValueError, match="冲突"):
        s.engine.validate_config(config)


def test_same_rule_category_is_valid_in_distinct_roots(setup_queue):
    s = setup_queue
    config = _multi_config(s)
    for mapping in config["mappings"]:
        mapping["rules"] = [{"directory": "电影", "delay_minutes": 1}]
    checked = s.engine.validate_config(config)
    assert len(checked["mappings"]) == 2
    assert s.engine.select_mapping(checked, s.root / "pt10/电影/a.mkv") is None
    assert s.engine.select_mapping(checked, s.root / "pt1/../pt2/电影/a.mkv") is None
    selected = s.engine.select_mapping(checked, s.root / "pt2/电影/a.mkv")
    assert selected["staging_root"] == str(s.root / "stage2")


def test_legacy_waiting_task_uses_original_paths_after_multi_config(setup_queue):
    s = setup_queue
    old_id = _enqueue(s)
    old_task = s.queue.tasks()[0]
    new_config = _multi_config(s)
    source = Path(new_config["mappings"][0]["library_root"]) / "电影/New.mkv"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new file")
    s.queue.enqueue(new_config, str(source))
    s.now[0] += 1000
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    s.queue.tick()
    old = next(task for task in s.queue.tasks() if task["id"] == old_id)
    assert old["ready_at"] == old_task["ready_at"]
    assert old["staging_path"] == old_task["staging_path"]
    assert os.path.samefile(old["staging_path"], s.source)
    assert os.path.samefile(Path(new_config["mappings"][0]["staging_root"]) / "电影/New.mkv", source)


@pytest.mark.parametrize("mappings", [None, {}, [None], [{}], [{"library_root": "/pt1"}]])
def test_invalid_mapping_shapes_fail_validation(setup_queue, mappings):
    with pytest.raises((ValueError, TypeError)):
        setup_queue.engine.validate_config({"mappings": mappings})


def test_empty_mappings_only_allowed_when_disabled(setup_queue):
    s = setup_queue
    assert s.engine.validate_config({"mappings": []})["mappings"] == []
    with pytest.raises(ValueError):
        s.engine.validate_config({"enabled": True, "mappings": []})
    assert s.engine.select_mapping({"mappings": []}, s.source) is None


def test_mapping_symlink_alias_rejected(setup_queue):
    s = setup_queue
    config = _multi_config(s)
    (s.root / "pt1").mkdir()
    (s.root / "alias").symlink_to(s.root / "pt1", target_is_directory=True)
    config["mappings"][1]["library_root"] = str(s.root / "alias")
    with pytest.raises(ValueError, match="符号链接"):
        s.engine.validate_config(config)


def _auto_stage(s):
    s.config["confirmation_mode"] = "staging_deleted"
    return _stage(s)


def _tick_auto(s):
    s.queue.tick(cleanup_organized=True, confirmation_mode="staging_deleted")


def test_staging_deletion_confirms_after_two_checks_and_preserves_seeding(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()
    s.now[0] += 29
    _tick_auto(s)
    assert s.source.exists()
    s.now[0] += 1
    _tick_auto(s)
    task = s.queue.tasks()[0]
    assert task["state"] == "done" and not s.source.exists()
    assert s.download.read_bytes() == b"fake media"
    assert task["upload_result"]["method"] == "staging_deleted"
    assert task["upload_result"]["confirmed"] is True
    assert task["upload_result"]["remote_verified"] is False
    assert "remote_reference" not in task["upload_result"]


def test_deletion_detection_survives_restart(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 31
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "done" and s.download.exists()


def test_disappearance_then_reappearance_restarts_confirmation_delay(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 31
    os.link(s.source, destination)
    _tick_auto(s)
    assert "deletion_seen_at" not in s.queue.tasks()[0]
    destination.unlink()
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()
    s.now[0] += 30
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "done"


@pytest.mark.parametrize("target", ["root", "parent"])
@pytest.mark.parametrize("replacement", [False, True])
def test_missing_or_replaced_staging_directory_never_confirms(setup_queue, target, replacement):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    directory = Path(s.config["staging_root"]) if target == "root" else destination.parent
    moved = directory.with_name(directory.name + "-offline")
    directory.rename(moved)
    if replacement:
        directory.mkdir()
    s.now[0] += 31
    _tick_auto(s)
    task = s.queue.tasks()[0]
    assert task["state"] == "staged" and task["upload_result"] is None
    assert "deletion_seen_at" not in task and "自动确认暂停" in task["error"]
    assert s.source.exists() and s.download.exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_seen_replacement_then_deleted_requires_manual_confirmation(setup_queue, symlink):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    if symlink:
        destination.symlink_to(s.source)
    else:
        destination.write_bytes(b"replacement")
    _tick_auto(s)
    assert s.queue.tasks()[0]["deletion_confirmation_blocked"] is True
    destination.unlink()
    for _ in range(3):
        s.now[0] += 60
        _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


def test_missing_source_completes_automatic_confirmation(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    s.source.unlink()
    for _ in range(2):
        s.now[0] += 60
        _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "done" and s.download.exists()


def test_disabled_deletion_mode_clears_pending_observation(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 60
    s.queue.tick(cleanup_organized=True, confirmation_mode="manual")
    assert "deletion_seen_at" not in s.queue.tasks()[0]
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


@pytest.mark.parametrize("remove_fields", [("confirmation_mode",), ("staging_evidence",)])
def test_legacy_or_unproven_tasks_cannot_infer_upload_success(setup_queue, remove_fields):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    path = s.queue.directory / "queue.json"
    data = json.loads(path.read_text())
    for task in data["tasks"].values():
        for field in remove_fields:
            task.pop(field)
    path.write_text(json.dumps(data))
    destination.unlink()
    for _ in range(2):
        s.now[0] += 60
        _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


def test_manual_task_does_not_inherit_later_automatic_option(setup_queue):
    s = setup_queue
    _task_id, destination = _stage(s)
    destination.unlink()
    for _ in range(2):
        s.now[0] += 60
        _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


def test_sibling_deletions_keep_directory_evidence_until_last_confirmation(setup_queue):
    s = setup_queue
    s.config["confirmation_mode"] = "staging_deleted"
    second = s.source.with_name("S01E02.mkv")
    os.link(s.download, second)
    _enqueue(s)
    s.queue.enqueue(s.config, str(second))
    s.now[0] += 1000
    _tick_auto(s)
    destinations = [Path(task["staging_path"]) for task in s.queue.tasks()]
    assert len(destinations) == 2 and destinations[0].parent == destinations[1].parent
    for destination in destinations:
        destination.unlink()
    _tick_auto(s)
    s.now[0] += 30
    _tick_auto(s)
    assert all(task["state"] == "done" for task in s.queue.tasks())
    assert not s.source.exists() and not second.exists() and s.download.exists()
    assert not destinations[0].parent.exists()


def test_automatic_confirmation_must_persist_before_cleanup(setup_queue, monkeypatch):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 30
    def fail_save(_data):
        raise OSError("receipt disk full")
    monkeypatch.setattr(s.queue, "_save", fail_save)
    with pytest.raises(OSError, match="receipt disk full"):
        _tick_auto(s)
    assert s.source.exists() and s.queue.tasks()[0]["state"] == "staged"


def test_permission_error_is_not_deletion(setup_queue, monkeypatch):
    from contextlib import contextmanager
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    directory = s.engine._directory
    @contextmanager
    def denied(path, create=False):
        if path == destination.parent:
            raise PermissionError("cannot read directory")
        with directory(path, create=create) as descriptor:
            yield descriptor
    monkeypatch.setattr(s.engine, "_directory", denied)
    for _ in range(2):
        s.now[0] += 60
        _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


def test_automatic_confirmation_without_organized_cleanup_keeps_source(setup_queue):
    s = setup_queue
    s.config["cleanup_organized"] = False
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 30
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "done" and s.source.exists()


def test_confirmation_mode_validated_in_legacy_and_mapping_config(setup_queue):
    s = setup_queue
    for config in (s.config, _multi_config(s)):
        checked = s.engine.validate_config(dict(config, confirmation_mode="staging_deleted"))
        assert checked["confirmation_mode"] == "staging_deleted"
        with pytest.raises(ValueError, match="确认方式"):
            s.engine.validate_config(dict(config, confirmation_mode="anything"))


def test_parent_disappears_during_missing_file_check_is_not_confirmation(setup_queue, monkeypatch):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 30
    original_stat = os.stat
    changed = []
    def detach_parent(path, *args, **kwargs):
        if path == destination.name and kwargs.get("dir_fd") is not None and not changed:
            destination.parent.rename(destination.parent.with_name("detached"))
            changed.append(True)
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", detach_parent)
    _tick_auto(s)
    assert s.queue.tasks()[0]["state"] == "staged" and s.source.exists()


def test_malformed_staging_evidence_never_confirms(setup_queue):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    path = s.queue.directory / "queue.json"
    data = json.loads(path.read_text())
    next(iter(data["tasks"].values()))["staging_evidence"] = {"linked_at": 1}
    path.write_text(json.dumps(data))
    destination.unlink()
    for _ in range(2):
        s.now[0] += 60
        _tick_auto(s)
    task = s.queue.tasks()[0]
    assert task["state"] == "staged" and "目录证据" in task["error"] and s.source.exists()


@pytest.mark.parametrize("at_admission,current", [(False, False), (True, False), (False, True)])
def test_disabled_organized_cleanup_does_not_require_source_after_restart(setup_queue, at_admission, current):
    s = setup_queue
    s.config["cleanup_organized"] = at_admission
    _task_id, destination = _auto_stage(s)
    s.source.unlink()
    destination.unlink()
    s.queue.tick(cleanup_organized=current, confirmation_mode="staging_deleted")
    s.now[0] += 30
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    s.queue.tick(cleanup_organized=current, confirmation_mode="staging_deleted")
    task = s.queue.tasks()[0]
    assert task["state"] == "done"
    assert task["cleanup_result"]["organized"] == "retained"
    assert s.download.read_bytes() == b"fake media"


def test_cleanup_retry_can_enable_previously_retained_source(setup_queue, monkeypatch):
    s = setup_queue
    task_id, _destination = _stage(s)
    s.queue.action(task_id, "confirm", "115:/test", True)
    prune = s.queue._prune
    def fail_prune(*_args):
        raise OSError("temporary directory failure")
    monkeypatch.setattr(s.queue, "_prune", fail_prune)
    s.queue.tick(cleanup_organized=False)
    assert s.queue.tasks()[0]["state"] == "cleanup_failed"
    assert s.source.exists()
    monkeypatch.setattr(s.queue, "_prune", prune)
    s.queue.action(task_id, "retry")
    s.queue.tick(cleanup_organized=True)
    assert s.queue.tasks()[0]["state"] == "done"
    assert not s.source.exists()
    assert s.download.exists()


def test_automatic_cleanup_directly_unlinks_mapped_source(setup_queue, monkeypatch):
    s = setup_queue
    _task_id, destination = _auto_stage(s)
    destination.unlink()
    s.source.unlink()
    s.source.write_bytes(b"same path is authoritative")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("organized cleanup must not inspect identity or quarantine")
    monkeypatch.setattr(s.engine, "_file_identity", forbidden)
    monkeypatch.setattr(s.engine.os, "rename", forbidden)
    _tick_auto(s)
    s.now[0] += 30
    _tick_auto(s)
    task = s.queue.tasks()[0]
    assert task["state"] == "done"
    assert task["cleanup_result"]["organized"] == "removed"
    assert not s.source.exists()
    assert s.download.read_bytes() == b"fake media"


def test_restart_after_direct_organized_unlink_before_receipt(setup_queue, monkeypatch):
    s = setup_queue
    task_id, _destination = _stage(s)
    s.queue.action(task_id, "confirm", "remote", True)
    save = s.queue._save
    def interrupted(data):
        task = data["tasks"][task_id]
        if task["cleanup_result"].get("organized") == "removed":
            raise OSError("interrupted after organized unlink")
        save(data)
    monkeypatch.setattr(s.queue, "_save", interrupted)
    with pytest.raises(OSError):
        s.queue.tick(cleanup_organized=True)
    assert not s.source.exists()
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    s.queue.tick(cleanup_organized=True)
    task = s.queue.tasks()[0]
    assert task["state"] == "done"
    assert task["cleanup_result"]["organized"] == "already_absent"
    assert s.download.read_bytes() == b"fake media"


def test_full_scan_is_immediate_deduplicated_and_can_cleanup_without_download_path(setup_queue):
    s = setup_queue
    s.config['confirmation_mode'] = 'staging_deleted'
    outside = s.root / 'outside.mkv'
    outside.write_bytes(b'outside')
    (s.source.parent / 'symlink.mkv').symlink_to(outside)
    assert s.queue.scan_once(s.config) == 1
    task = s.queue.tasks()[0]
    assert task['ready_at'] == s.now[0] and 'download_path' not in task
    s.queue = s.engine.StagingQueue(s.queue.directory, clock=lambda: s.now[0])
    assert s.queue.scan_once(s.config) == 1
    assert len(s.queue.tasks()) == 1
    _tick_auto(s)
    destination = Path(task['staging_path'])
    assert destination.stat().st_ino == s.source.stat().st_ino
    destination.unlink()
    _tick_auto(s)
    s.now[0] += 30
    _tick_auto(s)
    assert s.queue.tasks()[0]['state'] == 'done'
    assert not s.source.exists() and outside.exists() and s.download.exists()


def test_history_purge_only_expires_completed_records(setup_queue):
    s = setup_queue
    s.config['cleanup_organized'] = False
    task_id, _destination = _stage(s)
    s.queue.action(task_id, 'confirm', 'remote', True)
    s.queue.tick()
    s.queue.purge_history(7)
    assert len(s.queue.tasks()) == 1
    another = s.source.with_name('S01E02.mkv')
    another.write_bytes(b'waiting')
    s.queue.enqueue(s.config, str(another))
    s.now[0] += 7 * 86400
    s.queue.purge_history(7)
    tasks = s.queue.tasks()
    assert len(tasks) == 1 and tasks[0]['state'] == 'waiting'
    assert s.source.exists() and another.exists() and s.download.exists()


@pytest.mark.parametrize('value', [0, -1, True, 1.5, 3651])
def test_history_days_validation(setup_queue, value):
    s = setup_queue
    with pytest.raises(ValueError, match='保留天数'):
        s.engine.validate_config(dict(s.config, history_days=value))


def test_full_scan_switch_resets_only_after_success(setup_queue, monkeypatch):
    s = setup_queue
    monkeypatch.setattr(s.module._PluginBase, '__init__', lambda self: None)
    plugin = s.module.Delayed115Staging()
    plugin._queue = s.queue
    plugin._config = dict(s.config, scan_once=True)
    plugin._enabled = True
    saved = {}
    monkeypatch.setattr(plugin, 'update_config', lambda value: saved.update(value))
    monkeypatch.setattr(plugin, 'save_data', lambda *_args: None)
    original_scan = s.queue.scan_once
    def fail_scan(_config):
        raise OSError('scan interrupted')
    monkeypatch.setattr(s.queue, 'scan_once', fail_scan)
    plugin.process_tasks()
    assert plugin._config['scan_once'] is True and not saved
    monkeypatch.setattr(s.queue, 'scan_once', original_scan)
    plugin.process_tasks()
    assert plugin._config['scan_once'] is False and saved['scan_once'] is False
    assert s.queue.tasks()[0]['state'] == 'staged'
    plugin.process_tasks()
    assert len(s.queue.tasks()) == 1


@pytest.mark.parametrize("missing", ["app.sdk.plugin", "app.sdk.plugin.base", "unrelated_dependency"])
def test_plugin_base_import_compatibility(plugin_module, monkeypatch, missing):
    import builtins
    original_import = builtins.__import__
    base = plugin_module._PluginBase
    calls = []
    def import_with_missing_sdk(name, *args, **kwargs):
        if name == "app.sdk.plugin.base":
            raise ModuleNotFoundError("simulated missing module", name=missing)
        if name == "app.plugins":
            calls.append(name)
            return SimpleNamespace(_PluginBase=base)
        return original_import(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", import_with_missing_sdk)
        if missing == "unrelated_dependency":
            with pytest.raises(ModuleNotFoundError):
                importlib.reload(plugin_module)
            assert not calls
        else:
            module = importlib.reload(plugin_module)
            assert issubclass(module.Delayed115Staging, base)
            assert calls == ["app.plugins"]
    importlib.reload(plugin_module)
