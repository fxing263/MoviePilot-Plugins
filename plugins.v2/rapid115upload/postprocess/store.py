"""与上传共用原子快照，后处理状态独立，不改变上传结果。"""

import copy
import fcntl
from contextlib import contextmanager
from typing import Iterator

from .rules import plan


class PostStore:
    """锁内只写后处理字段，执行STRM/CD2时不持上传队列锁。"""

    def __init__(self, queue) -> None:
        self.queue = queue

    @contextmanager
    def worker(self) -> Iterator[bool]:
        """旧重试及中断记录转为失败终态，不再次执行；上传消费者不受此锁影响。"""
        self.queue.directory.mkdir(parents=True, exist_ok=True)
        with (self.queue.directory / 'postprocess.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            with self.queue._locked() as snapshot:
                changed = False
                for task in snapshot['tasks'].values():
                    post = task.get('postprocess', {})
                    if post.get('state') in {'running', 'retry'}:
                        post.update(state='failed', ready_at=None, error=post.get('error') or '后处理已中断，不再重试')
                        changed = True
                if changed:
                    self.queue._save(snapshot)
            yield True

    def stats(self) -> dict:
        """统计CD2 RPC与合并量，不代表115底层请求次数。"""
        with self.queue._locked() as snapshot:
            return {"rpc_calls": 0, "merged_directories": 0,
                    **copy.deepcopy(snapshot.get('postprocess_stats', {}))}

    def rpc(self) -> None:
        """调用前持久化时间和计数，重启后仍遵守最小请求间隔。"""
        with self.queue._locked() as snapshot:
            stats = snapshot.setdefault('postprocess_stats', {})
            stats['rpc_calls'] = stats.get('rpc_calls', 0) + 1
            stats['last_rpc_at'] = self.queue.clock()
            self.queue._save(snapshot)

    def claim(self) -> list[dict]:
        """同实例同目录合并，领取固定ID，刷新期间到达的新事件保留下一轮。"""
        now = self.queue.clock()
        with self.queue._locked() as snapshot:
            groups = {}
            for task in snapshot['tasks'].values():
                post = task.get('postprocess', {})
                if task['state'] != 'uploaded' or post.get('state') != 'pending':
                    continue
                key = (('cd2', post['cd2_plugin_id'], post['target']) if post['mode'] == 'cd2'
                       else ('strm', task['id']))
                groups.setdefault(key, []).append(task)
            for key, tasks in groups.items():
                pending = [task for task in tasks if task['postprocess']['state'] == 'pending']
                ready = []
                if pending:
                    posts = [task['postprocess'] for task in pending]
                    due = (min(max(post['created_at'] + post['merge_delay'] for post in posts),
                               min(post['created_at'] + post['max_wait'] for post in posts))
                           if key[0] == 'cd2' else min(post['ready_at'] for post in posts))
                    if due <= now:
                        ready.extend(pending)
                if not ready:
                    continue
                stats = snapshot.setdefault('postprocess_stats', {})
                for task in ready:
                    post = task['postprocess']
                    post.update(state='running', attempts=post['attempts'] + 1, error='')
                if key[0] == 'cd2':
                    stats['merged_directories'] = stats.get('merged_directories', 0) + len(ready) - 1
                self.queue._save(snapshot)
                return copy.deepcopy(ready)
        return []

    def finish(self, task_id: str, state: str, message: str = '') -> None:
        """仅记录最终处理结果，不安排重试；上传成功状态及种子关联始终保持不变。"""
        with self.queue._locked() as snapshot:
            post = snapshot['tasks'][task_id]['postprocess']
            if post['state'] != 'running':
                return
            post.update(state=state, error=message, updated_at=self.queue.clock(),
                        ready_at=None)
            self.queue._save(snapshot)

    def action(self, task_id: str, action: str, config: dict) -> None:
        """仅未处理历史可显式补处理；失败或中断的后处理不再重试。"""
        with self.queue._locked() as snapshot:
            task = snapshot['tasks'].get(task_id)
            if not task or task['state'] != 'uploaded':
                raise ValueError('仅已上传任务可操作后处理')
            post = task.get('postprocess', {})
            if action == 'post_enqueue':
                if config['mode'] == 'off':
                    raise ValueError('请先启用并配置上传后处理')
                if post and post.get('state') != 'disabled' and not (
                        post.get('state') == 'failed' and post.get('attempts') == 0):
                    raise ValueError('此任务已有后处理结果，不再重复执行')
                task['postprocess'] = plan(task, config, self.queue.clock())
            else:
                raise ValueError('不支持的后处理操作')
            self.queue._save(snapshot)
