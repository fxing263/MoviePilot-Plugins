"""独立执行STRM生成或CD2目录刷新，不重传媒体或通知其他服务。"""

import threading
from typing import Callable, Optional

from app.sdk.logging import logger

from .cd2 import RefreshAdapter
from .store import PostStore
from .strm import StrmConflictError, write_strm


class PostWorker:
    """独立调度的单消费者；失败只重试后处理，不重新上传视频。"""

    def __init__(self, queue, config: dict, stop: threading.Event, writer: Callable = write_strm,
                 adapter_factory: Optional[Callable] = None) -> None:
        self.store = PostStore(queue)
        self.config = config
        self.stop = stop
        self.writer = writer
        self.adapter_factory = adapter_factory or RefreshAdapter
        self._execution = threading.Lock()

    def close(self) -> None:
        """插件先置停止标记，再等待当前原子写入或有超时的CD2刷新结束。"""
        with self._execution:
            pass

    def tick(self) -> None:
        """关闭时暂停既有意图；重新启用沿用原路径，每次最多处理100个文件。"""
        if self.stop.is_set() or self.config['mode'] == 'off' or not self._execution.acquire(blocking=False):
            return
        try:
            with self.store.worker() as acquired:
                if not acquired:
                    return
                cache = {}
                for _ in range(100):
                    if self.stop.is_set():
                        break
                    task = self.store.claim()
                    if not task:
                        break
                    self._process(task, cache)
        except Exception as error:
            logger.error(f'上传后处理队列异常（{type(error).__name__}），上传成功记录保持不变')
        finally:
            self._execution.release()

    def _before_rpc(self, interval: float) -> None:
        elapsed = self.store.queue.clock() - self.store.stats().get('last_rpc_at', 0)
        if self.stop.wait(max(0, interval - elapsed)):
            raise InterruptedError('后处理已停止')
        self.store.rpc()

    def _process(self, tasks: list[dict], cache: dict) -> None:
        post = tasks[0]['postprocess']
        try:
            if post['mode'] == 'strm':
                self.writer(post)
            else:
                interval = max(task['postprocess']['min_interval'] for task in tasks)
                adapter = self.adapter_factory(post['cd2_plugin_id'], self.stop,
                                               lambda: self._before_rpc(interval))
                adapter.refresh(post['target'], cache.setdefault(post['cd2_plugin_id'], {}))
            for task in tasks:
                self.store.finish(task['id'], 'done')
        except StrmConflictError as error:
            for task in tasks:
                self.store.finish(task['id'], 'conflict', str(error))
        except Exception as error:
            from ..bdmv_cd2 import BdmvCd2Error
            message = (str(error) if isinstance(error, (BdmvCd2Error, InterruptedError))
                       else f'后处理失败（{type(error).__name__}），等待重试')
            for task in tasks:
                self.store.finish(task['id'], 'retry', message)
