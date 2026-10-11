"""上传实时进度仅驻留内存，避免高频回调重写持久化队列。"""

import threading
import time


class UploadProgress:
    """按任务隔离阶段与速率；停止更新五秒后速率归零，不保存重启前进度。"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._tasks = {}

    def update(self, task_id: str, stage: str, completed: int = 0, total: int = 0) -> None:
        """接收累计文件字节数，允许分片重传时回退；每秒更新速率采样。"""
        now = self._clock()
        with self._lock:
            old = self._tasks.get(task_id)
            if old is None or old["stage"] != stage or completed < old["completed"]:
                old = {"sample_time": now, "sample_bytes": completed, "speed": 0}
            elapsed = now - old["sample_time"]
            if elapsed >= 1:
                old["speed"] = max(0, completed - old["sample_bytes"]) / elapsed
                old.update(sample_time=now, sample_bytes=completed)
            old.update(stage=stage, completed=completed, total=total, updated=now)
            self._tasks[task_id] = old

    def snapshot(self, task_id: str) -> dict:
        """输出供页面轮询的快照，完成上传前的百分比不代表远端校验成功。"""
        with self._lock:
            item = self._tasks.get(task_id)
            if item is None:
                return {}
            return {"stage": item["stage"], "completed_bytes": item["completed"],
                    "total_bytes": item["total"],
                    "bytes_per_second": item["speed"] if item["stage"] == "uploading"
                    and self._clock() - item["updated"] < 5 else 0}

    def remove(self, task_id: str) -> None:
        """任务退出后释放进度，失败重试从新的一轮开始。"""
        with self._lock:
            self._tasks.pop(task_id, None)
