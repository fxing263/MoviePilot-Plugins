"""定向刷新使用模拟 RPC；不访问网盘及真实插件管理器。"""

import importlib.util
import sys
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace as NS

import pytest


@pytest.fixture
def refresh(monkeypatch):
    root = Path(__file__).resolve().parents[3] / 'plugins.v2/rapid115upload'
    for name, directory in [('refresh_fixture', root), ('refresh_fixture.postprocess', root / 'postprocess')]:
        package = ModuleType(name)
        package.__path__ = [str(directory)]
        monkeypatch.setitem(sys.modules, name, package)
    for name, path in [('refresh_fixture.bdmv_cd2', root / 'bdmv_cd2.py'),
                       ('refresh_fixture.postprocess.cd2', root / 'postprocess/cd2.py')]:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    calls = []
    existing = {'/115open', '/115open/影视库'}
    discovered = {}
    state = NS(error=None, stream_factory=None, before=0)
    stop = Event()

    def find(request, **kwargs):
        calls.append(('find', request.path, kwargs))
        if state.error:
            raise state.error
        return NS(fullPathName=request.path if request.path in existing else '', isDirectory=True)

    def listing(request, **kwargs):
        calls.append(('list', request.path, kwargs))
        assert request.forceRefresh is True
        existing.update(discovered.get(request.path, []))
        if state.stream_factory:
            return state.stream_factory()
        return iter([NS(subFiles=[]), NS(subFiles=[])])

    client = NS(jwt_token='test-only', stub=NS(FindFileByPath=find, GetSubFiles=listing))
    protocol = NS(FindFileByPathRequest=NS, ListSubFileRequest=NS)
    monkeypatch.setattr(module.RefreshAdapter, '_connection', lambda self: (client, protocol, None))

    def before():
        state.before += 1

    adapter = module.RefreshAdapter('CloudDriveDisk', stop, before)
    return NS(module=module, adapter=adapter, calls=calls, existing=existing,
              discovered=discovered, state=state, stop=stop)


def test_existing_parent_only_and_deadline(refresh):
    refresh.adapter.refresh('/115open/影视库', {})
    assert [(kind, path) for kind, path, _ in refresh.calls] == [
        ('find', '/115open/影视库'), ('list', '/115open/影视库')]
    assert refresh.state.before == 2
    assert all(kwargs['timeout'] == 30 for _, _, kwargs in refresh.calls)


def test_discover_new_levels_only_along_requested_path(refresh):
    refresh.discovered['/115open/影视库'] = ['/115open/影视库/电视剧']
    refresh.discovered['/115open/影视库/电视剧'] = ['/115open/影视库/电视剧/剧名']
    cache = {}
    refresh.adapter.refresh('/115open/影视库/电视剧/剧名', cache)
    assert list(cache) == ['/115open/影视库', '/115open/影视库/电视剧', '/115open/影视库/电视剧/剧名']
    assert all(path != '/' for _, path, _ in refresh.calls)


def test_shared_parent_deduplicated_but_new_leaf_event_always_refreshes(refresh):
    refresh.discovered['/115open/影视库'] = ['/115open/影视库/A', '/115open/影视库/B']
    cache = {}
    refresh.adapter.refresh('/115open/影视库/A', cache)
    refresh.adapter.refresh('/115open/影视库/B', cache)
    refresh.adapter.refresh('/115open/影视库/A', cache)
    assert [path for method, path, _ in refresh.calls if method == 'list'] == [
        '/115open/影视库', '/115open/影视库/A', '/115open/影视库/B', '/115open/影视库/A']


@pytest.mark.parametrize('error_name', ['UNAVAILABLE', 'DEADLINE_EXCEEDED', 'PERMISSION_DENIED'])
def test_transport_failure_does_not_probe_ancestors(refresh, error_name):
    class RpcError(Exception):
        def code(self):
            return NS(name=error_name)
    refresh.state.error = RpcError('credential-must-not-be-shown')
    with pytest.raises(refresh.module.RefreshError, match='未继续探测祖先') as caught:
        refresh.adapter.refresh('/115open/影视库/child', {})
    assert 'credential' not in str(caught.value)
    assert len(refresh.calls) == 1


def test_not_found_may_ascend_but_never_above_mount(refresh):
    class Missing(Exception):
        def code(self):
            return NS(name='NOT_FOUND')
    refresh.state.error = Missing()
    with pytest.raises(refresh.module.RefreshError, match='挂载根不可访问'):
        refresh.adapter.refresh('/115open/影视库', {})
    assert [path for _, path, _ in refresh.calls] == ['/115open/影视库', '/115open']


@pytest.mark.parametrize('mode', ['failure', 'stop', 'timeout'])
def test_partial_stream_never_success_and_is_cancelled(refresh, monkeypatch, mode):
    state = NS(cancelled=False)
    class Stream:
        def __iter__(self):
            yield NS(subFiles=[])
            if mode == 'failure':
                raise RuntimeError('stream broken')
            if mode == 'stop':
                refresh.stop.set()
            if mode == 'timeout':
                monkeypatch.setattr(refresh.module, 'monotonic', lambda: 1000)
            yield NS(subFiles=[])

        def cancel(self):
            state.cancelled = True
    monkeypatch.setattr(refresh.module, 'monotonic', lambda: 0)
    refresh.state.stream_factory = Stream
    cache = {}
    expected = InterruptedError if mode == 'stop' else refresh.module.RefreshError
    with pytest.raises(expected):
        refresh.adapter.refresh('/115open/影视库', cache)
    assert state.cancelled and not cache


def test_stopped_or_rate_limiter_interrupted_does_not_call_rpc(refresh):
    refresh.stop.set()
    with pytest.raises(InterruptedError):
        refresh.adapter.refresh('/115open/影视库', {})
    assert not refresh.calls
    refresh.stop.clear()

    def interrupted():
        raise InterruptedError()
    refresh.adapter.before_rpc = interrupted
    with pytest.raises(InterruptedError):
        refresh.adapter.refresh('/115open/影视库', {})
    assert not refresh.calls


@pytest.mark.parametrize('path', ['/', 'relative', '//115open/a', '/115open/../a', '/115open/./a', '/115open/\\a'])
def test_invalid_paths_no_rpc(refresh, path):
    with pytest.raises(refresh.module.RefreshError):
        refresh.adapter.refresh(path, {})
    assert not refresh.calls
