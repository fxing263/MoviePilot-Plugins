"""后处理映射与 STRM 原子写入离线测试，仅使用临时目录。"""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    from app.sdk.events import eventmanager
    monkeypatch.setattr(eventmanager, "register", lambda *_args, **_kwargs: lambda function: function)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[3] / "plugins.v2"))
    before = set(sys.modules)
    yield (importlib.import_module("rapid115upload.postprocess.rules"),
           importlib.import_module("rapid115upload.postprocess.strm"))
    for name in set(sys.modules) - before:
        if name == "rapid115upload" or name.startswith("rapid115upload."):
            sys.modules.pop(name, None)


def config(**changes):
    value = {"mode": "strm", "mappings": [{"source_root": "/影视库", "strm_root": "/media/strm",
             "playback_root": "/CloudNAS/CloudDrive/115open/影视库", "cd2_root": "/115open/影视库"}]}
    value.update(changes)
    return value


@pytest.mark.parametrize("relative", [
    "电影/华语电影/力王 (1991) {tmdb-17467}/力王 (1991) - 1080p.SDR.H.265.10-bit.24fps.DTS 5.1.mkv",
    "电视剧/儿童动漫/变形金刚：超能勇士 (1996) {tmdb-958}/Season 3/变形金刚：超能勇士.1996.S03E06.480p.SDR.H.264.mkv",
])
def test_real_samples(modules, relative):
    rules, _ = modules
    record = rules.plan({"remote_path": f"/影视库/{relative}"}, config(), 100)
    assert record["target"] == str((Path("/media/strm") / relative).with_suffix(".strm"))
    assert record["content"] == f"/CloudNAS/CloudDrive/115open/影视库/{relative}"
    assert record["state"] == "pending"


def test_longest_boundary_and_frozen_mapping(modules):
    rules, _ = modules
    value = config()
    value["mappings"].append({"source_root": "/影视库/电影", "strm_root": "/special", "playback_root": "/play"})
    record = rules.plan({"remote_path": "/影视库/电影/片.mkv"}, value, 1)
    assert record["target"] == "/special/片.strm"
    assert rules.plan({"remote_path": "/影视库/电影节/片.mkv"}, value, 1)["target"] == "/media/strm/电影节/片.strm"
    assert rules.plan({"remote_path": "/影视库2/片.mkv"}, value, 1)["state"] == "failed"
    value["mappings"][1]["playback_root"] = "/changed"
    assert record["content"] == "/play/片.mkv"


@pytest.mark.parametrize("path", ["/", "relative", "/a/../b", "/a/./b", "/a\\b", "/a\nb", "//a", "/a//b"])
def test_invalid_paths(modules, path):
    with pytest.raises(ValueError):
        modules[0].absolute_path(path)


def test_duplicate_and_inactive_settings(modules):
    rules, _ = modules
    value = config()
    value["mappings"].append(dict(value["mappings"][0]))
    with pytest.raises(ValueError, match="重复"):
        rules.validate_config(value)
    value = config()
    value["mappings"][0]["cd2_root"] = "bad"
    assert rules.validate_config(value)["mappings"][0]["cd2_root"] == "bad"
    value["mode"] = "cd2"
    with pytest.raises(ValueError):
        rules.validate_config(value)


@pytest.mark.parametrize("changes", [{"mode": "both"}, {"retry_base": 0}, {"retry_base": float("nan")},
                                      {"retry_max": 86401}, {"retry_max": 2}, {"retry_base": True}, {"merge_delay": float("nan")}, {"max_wait": 1}, {"min_interval": 0}])
def test_configuration_limits(modules, changes):
    with pytest.raises(ValueError):
        modules[0].validate_config(config(**changes))


def test_modes_are_exclusive(modules):
    rules, _ = modules
    task = {"remote_path": "/影视库/电影/片.mkv"}
    assert rules.plan(task, {"mode": "off"}, 1)["state"] == "disabled"
    record = rules.plan(task, config(mode="cd2"), 1)
    assert record["target"] == "/115open/影视库/电影"
    assert record["state"] == "pending"
    assert "content" not in record and "strm_root" not in record
    assert "cd2_plugin_id" not in rules.plan(task, config(), 1)


@pytest.mark.parametrize("path", ["/影视库/a.nfo", "/影视库/a.jpg", "/影视库/a.srt", "/影视库/BDMV/STREAM/1.m2ts", "/影视库/video_ts/1.vob"])
def test_non_media_and_disc_skip(modules, path):
    assert modules[0].plan({"remote_path": path}, config(), 1)["state"] == "skipped"


@pytest.fixture
def record(tmp_path):
    return {"strm_root": str(tmp_path / "strm"), "target": str(tmp_path / "strm" / "中文 a" / "a.b.strm"),
            "content": "/CloudNAS/CloudDrive/115open/影视库/中文 a/a.b.mkv"}


def test_write_idempotent_and_conflict(modules, record):
    writer = modules[1]
    writer.write_strm(record)
    path = Path(record["target"])
    assert path.read_text() == record["content"]
    inode = path.stat().st_ino
    writer.write_strm(record)
    assert path.stat().st_ino == inode
    with pytest.raises(writer.StrmConflictError):
        writer.write_strm({**record, "content": "/different/a.mkv"})
    assert path.read_text() == record["content"]


def test_failure_leaves_no_target(modules, record, monkeypatch):
    writer = modules[1]
    def fail(_):
        raise OSError("disk full")
    monkeypatch.setattr(writer.os, "fsync", fail)
    with pytest.raises(OSError, match="disk full"):
        writer.write_strm(record)
    assert not Path(record["target"]).exists()
    assert list(Path(record["target"]).parent.iterdir()) == []


def test_symlink_parent_and_target_rejected(modules, record, tmp_path):
    writer = modules[1]
    outside = tmp_path / "outside"
    outside.mkdir()
    Path(record["strm_root"]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        writer.write_strm(record)
    Path(record["strm_root"]).unlink()
    Path(record["target"]).parent.mkdir(parents=True)
    sentinel = outside / "file"
    sentinel.write_text("keep")
    Path(record["target"]).symlink_to(sentinel)
    with pytest.raises(writer.StrmConflictError):
        writer.write_strm(record)
    assert sentinel.read_text() == "keep"


def test_racing_existing_file_not_overwritten(modules, record, monkeypatch):
    writer = modules[1]
    original = writer.os.link
    def race(source, destination, **kwargs):
        Path(record["target"]).write_text("other writer")
        return original(source, destination, **kwargs)
    monkeypatch.setattr(writer.os, "link", race)
    with pytest.raises(writer.StrmConflictError):
        writer.write_strm(record)
    assert Path(record["target"]).read_text() == "other writer"


def test_target_escape_rejected(modules, record, tmp_path):
    with pytest.raises(ValueError):
        modules[1].write_strm({**record, "target": str(tmp_path / "outside.strm")})


def test_directory_target_rejected(modules, record):
    Path(record["target"]).mkdir(parents=True)
    with pytest.raises(modules[1].StrmConflictError):
        modules[1].write_strm(record)


def test_vanishing_racing_target_retries(modules, record, monkeypatch):
    writer = modules[1]
    def race(*_args, **_kwargs):
        raise FileExistsError("raced, then removed")
    monkeypatch.setattr(writer.os, "link", race)
    with pytest.raises(FileNotFoundError, match="已消失"):
        writer.write_strm(record)
    assert not Path(record["target"]).exists()
