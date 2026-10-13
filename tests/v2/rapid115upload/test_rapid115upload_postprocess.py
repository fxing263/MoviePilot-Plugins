"""上传成功与后处理解耦、持久化恢复及合并行为；不连接外部服务。"""

import importlib
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from app.sdk.events import eventmanager
    monkeypatch.setattr(eventmanager, 'register', lambda *_a, **_k: lambda f: f)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[3] / 'plugins.v2'))
    before = set(sys.modules)
    plugin = importlib.import_module('rapid115upload')
    # 本测试不使用宿主Chain，避免为了实例化插件而启动整套运行服务。
    monkeypatch.setattr(plugin._PluginBase, '__init__', lambda self: None)
    queue_module = importlib.import_module('rapid115upload.queue')
    rules = importlib.import_module('rapid115upload.postprocess.rules')
    worker_module = importlib.import_module('rapid115upload.postprocess.worker')
    clock = [1000.0]
    queue = queue_module.UploadQueue(tmp_path / 'queue', clock=lambda: clock[0])
    config = rules.validate_config({'mode': 'strm', 'mappings': [{
        'source_root': '/影视库', 'strm_root': str(tmp_path / 'strm'),
        'playback_root': '/CloudNAS/CloudDrive/115open/影视库', 'cd2_root': '/115open/影视库'}]})
    library = tmp_path / 'library'
    library.mkdir()
    upload_config = {'mappings': [{'library_root': str(library), 'remote_root': '/影视库', 'retry_minutes': [1]}]}
    def enqueue(name='电影/示例.mkv', finish=True):
        source = library / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'video')
        key = queue.enqueue(upload_config, str(source), downloader='qb', download_hash='a' * 40)
        if finish:
            queue.complete(key, {'file_id': '1'}, config)
        return key
    result = SimpleNamespace(queue=queue, config=config, clock=clock, enqueue=enqueue, library=library,
                             plugin=plugin, worker_module=worker_module, queue_module=queue_module, stop=threading.Event())
    yield result
    for name in set(sys.modules) - before:
        if name == 'rapid115upload' or name.startswith('rapid115upload.'):
            sys.modules.pop(name, None)


def task(setup, key):
    return next(item for item in setup.queue.tasks() if item['id'] == key)


def test_success_atomically_records_plan_without_side_effects(setup):
    key = setup.enqueue()
    row = task(setup, key)
    assert row['state'] == 'uploaded' and row['postprocess']['state'] == 'pending'
    target = Path(row['postprocess']['target'])
    assert not target.exists()
    (setup.library / '电影/示例.mkv').unlink()
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop)
    worker.tick()
    assert target.read_text() == '/CloudNAS/CloudDrive/115open/影视库/电影/示例.mkv'
    assert task(setup, key)['state'] == 'uploaded'
    assert task(setup, key)['postprocess']['state'] == 'done'


def test_retry_backoff_persistence_and_manual_retry(setup):
    key = setup.enqueue()
    def fail(_):
        raise PermissionError('cannot write')
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop, writer=fail)
    worker.tick()
    row = task(setup, key)
    assert row['state'] == 'uploaded' and row['postprocess']['state'] == 'retry'
    assert row['postprocess']['ready_at'] == 1060
    worker.tick()
    assert task(setup, key)['postprocess']['attempts'] == 1
    setup.clock[0] = 1060
    worker.tick()
    assert task(setup, key)['postprocess']['ready_at'] == 1180
    worker.store.action(key, 'post_retry', setup.config)
    restarted = setup.worker_module.PostWorker(setup.queue_module.UploadQueue(setup.queue.directory), setup.config, setup.stop)
    restarted.tick()
    assert task(setup, key)['postprocess']['state'] == 'done'
    assert task(setup, key)['attempts'] == 0


def test_running_recovery_and_conflict_manual_retry(setup):
    key = setup.enqueue()
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop)
    claimed = worker.store.claim()[0]
    target = Path(claimed['postprocess']['target'])
    target.parent.mkdir(parents=True)
    target.write_text('existing different content')
    worker.tick()
    assert task(setup, key)['postprocess']['state'] == 'conflict'
    assert task(setup, key)['state'] == 'uploaded'
    target.unlink()
    worker.store.action(key, 'post_retry', setup.config)
    worker.tick()
    assert task(setup, key)['postprocess']['state'] == 'done'


def test_disabled_and_old_history_require_explicit_action(setup):
    setup.config['mode'] = 'off'
    key = setup.enqueue()
    setup.queue.update(key, postprocess={})
    setup.config['mode'] = 'strm'
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop)
    worker.tick()
    assert not task(setup, key)['postprocess']
    worker.store.action(key, 'post_enqueue', setup.config)
    worker.tick()
    assert task(setup, key)['postprocess']['state'] == 'done'
    with pytest.raises(ValueError):
        worker.store.action(key, 'post_enqueue', setup.config)


def test_plan_frozen_across_switch_and_stop(setup):
    key = setup.enqueue()
    old = task(setup, key)['postprocess']
    setup.config['mode'] = 'cd2'
    setup.config['mappings'][0]['strm_root'] = '/unused'
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop,
                                           adapter_factory=lambda *_: pytest.fail('must use frozen STRM plan'))
    setup.stop.set()
    worker.tick()
    assert task(setup, key)['postprocess']['state'] == 'pending'
    setup.stop.clear()
    worker.tick()
    assert Path(old['target']).exists()


def test_cd2_merges_directory_and_bounds_wait(setup):
    setup.config['mode'] = 'cd2'
    keys = []
    for i in range(5):
        setup.clock[0] = 1000 + i * 40
        keys.append(setup.enqueue(f'电影/系列/{i}.mkv'))
    calls = []
    def factory(instance, _stop, before):
        def refresh(directory, _cache):
            before()
            calls.append((instance, directory))
        return SimpleNamespace(refresh=refresh)
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop, adapter_factory=factory,
                                           writer=lambda _: pytest.fail('cd2 mode must not write STRM'))
    setup.clock[0] = 1179
    worker.tick()
    assert calls == []
    setup.clock[0] = 1180
    worker.tick()
    assert calls == [('CloudDriveDisk', '/115open/影视库/电影/系列')]
    assert all(task(setup, key)['postprocess']['state'] == 'done' for key in keys)
    assert worker.store.stats()['rpc_calls'] == 1
    assert worker.store.stats()['merged_directories'] == 4


def test_new_event_during_refresh_is_not_lost(setup):
    setup.config['mode'] = 'cd2'
    first = setup.enqueue('电影/a.mkv')
    setup.clock[0] += 45
    new = []
    calls = []
    def factory(*_):
        def refresh(directory, _cache):
            calls.append(directory)
            if not new:
                new.append(setup.enqueue('电影/b.mkv'))
        return SimpleNamespace(refresh=refresh)
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop, adapter_factory=factory)
    worker.tick()
    assert task(setup, first)['postprocess']['state'] == 'done'
    assert task(setup, new[0])['postprocess']['state'] == 'pending'
    setup.clock[0] += 45
    worker.tick()
    assert len(calls) == 2
    assert task(setup, new[0])['postprocess']['state'] == 'done'


@pytest.mark.parametrize('normal', [False, True])
def test_plugin_upload_success_independent_of_postprocess_failure(setup, monkeypatch, normal):
    key = setup.enqueue(finish=False)
    monkeypatch.setattr(setup.plugin, 'local_library_roots', lambda: {str(setup.library)})
    plugin = setup.plugin.Rapid115Upload()
    monkeypatch.setattr(plugin, 'get_data_path', lambda: setup.queue.directory)
    plugin.init_plugin({'enabled': True, 'delete_after_upload': True, 'postprocess': setup.config,
                        'mappings': [{'library_root': str(setup.library), 'remote_root': '/影视库',
                                      'max_attempts': 1, 'retry_minutes': [1]}]})
    plugin._queue = setup.queue
    calls = []
    def attempt(*_):
        calls.append('upload')
        return None if normal else {'file_id': '2'}
    monkeypatch.setattr(setup.plugin, 'RapidClient', lambda *_: SimpleNamespace(
        attempt=attempt, initialized={}, close=lambda: None))
    monkeypatch.setattr(setup.plugin, 'upload', lambda *_: {'file_id': '2'})
    setup.queue.update(key, max_attempts=1)
    plugin.process_tasks()
    def fail(_):
        raise OSError('disk full')
    plugin._postprocess.writer = fail
    plugin._postprocess.tick()
    plugin.process_tasks()
    row = task(setup, key)
    assert row['state'] == 'uploaded' and row['postprocess']['state'] == 'retry'
    assert calls == ['upload']
    assert not Path(row['organized_path']).exists()
    assert plugin.task_action({'task_id': key, 'action': 'post_retry'}).success
    plugin.stop_service()


def test_planning_failure_still_commits_success(setup, monkeypatch):
    key = setup.enqueue(finish=False)
    monkeypatch.setattr(setup.queue_module, 'plan', lambda *_: (_ for _ in ()).throw(ValueError('bad plan')))
    setup.queue.complete(key, {'file_id': '1'}, setup.config)
    row = task(setup, key)
    assert row['state'] == 'uploaded' and row['postprocess']['state'] == 'failed'


def test_cd2_failure_retries_without_reupload_and_preserves_rate_limit(setup):
    setup.config['mode'] = 'cd2'
    key = setup.enqueue()
    setup.clock[0] += 45
    waits = []
    class Stop:
        def is_set(self):
            return False
        def wait(self, seconds):
            waits.append(seconds)
            setup.clock[0] += seconds
            return False
    def factory(_instance, _stop, before):
        def refresh(_directory, _cache):
            before()
            before()
            raise setup.plugin.RetryLaterError('fake stream failure')
        return SimpleNamespace(refresh=refresh)
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, Stop(), adapter_factory=factory)
    worker.tick()
    row = task(setup, key)
    assert row['state'] == 'uploaded' and row['postprocess']['state'] == 'retry'
    assert waits[-1] == 3
    assert worker.store.stats()['rpc_calls'] == 2
    setup.clock[0] = row['postprocess']['ready_at']
    restarted = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop,
        adapter_factory=lambda *_: SimpleNamespace(refresh=lambda *_: None))
    restarted.tick()
    assert task(setup, key)['postprocess']['state'] == 'done'
    assert restarted.store.stats()['retries'] == 1
    assert task(setup, key)['attempts'] == 0


def test_off_pauses_pending_and_non_uploaded_cannot_request_postprocess(setup):
    key = setup.enqueue()
    setup.config['mode'] = 'off'
    worker = setup.worker_module.PostWorker(setup.queue, setup.config, setup.stop,
                                           writer=lambda _: pytest.fail('off must not write'))
    worker.tick()
    assert task(setup, key)['postprocess']['state'] == 'pending'
    other = setup.enqueue('电影/other.mkv', finish=False)
    with pytest.raises(ValueError):
        worker.store.action(other, 'post_enqueue', setup.config)


def test_broken_cleanup_never_returns_upload_to_queue(setup, monkeypatch):
    key = setup.enqueue(finish=False)
    monkeypatch.setattr(setup.plugin, 'local_library_roots', lambda: {str(setup.library)})
    plugin = setup.plugin.Rapid115Upload()
    monkeypatch.setattr(plugin, 'get_data_path', lambda: setup.queue.directory)
    plugin.init_plugin({'enabled': True, 'postprocess': setup.config,
                        'mappings': [{'library_root': str(setup.library), 'remote_root': '/影视库'}]})
    plugin._queue = setup.queue
    monkeypatch.setattr(setup.plugin, 'RapidClient', lambda *_: SimpleNamespace(
        attempt=lambda *_: {'file_id': '1'}, close=lambda: None))
    def fail(_):
        raise RuntimeError('cleanup failed')
    monkeypatch.setattr(plugin, '_remove_uploaded_file', fail)
    plugin.process_tasks()
    assert task(setup, key)['state'] == 'uploaded'
    assert task(setup, key)['postprocess']['state'] == 'pending'
    plugin.stop_service()
