from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock
from time import monotonic, time
from typing import Any, Callable, Optional


STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_FAILED = "failed"
STATUS_COMPLETED = "completed"
RETRY_DELAYS = (30, 60, 120)
FAILURE_COOLDOWN_SECONDS = 3600
CIRCUIT_FAILURE_THRESHOLD = 3
RECENT_RESULT_LIMIT = 100
VALID_STATUSES = {
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_FAILED,
    STATUS_COMPLETED,
}


def _wait_for_event(event: Event, timeout: Optional[float]) -> bool:
    """等待事件触发或超时。"""
    return event.wait(timeout)


@dataclass
class U115DeletionTask:
    """描述一项可持久化的 115 STRM 删除任务。"""

    task_id: str
    strm_path: str
    storage_type: str
    storage_path: str
    status: str = STATUS_PENDING
    attempts: int = 0
    next_run_at: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """把任务转换为插件数据可保存的字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "U115DeletionTask":
        """从持久化字典恢复并校验任务。"""
        task = cls(
            task_id=str(value["task_id"]),
            strm_path=str(value["strm_path"]),
            storage_type=str(value["storage_type"]),
            storage_path=str(value["storage_path"]),
            status=str(value.get("status") or STATUS_PENDING),
            attempts=int(value.get("attempts") or 0),
            next_run_at=float(value.get("next_run_at") or 0),
            created_at=float(value.get("created_at") or 0),
            updated_at=float(value.get("updated_at") or 0),
            last_error=str(value.get("last_error") or ""),
        )
        if not all(
            (task.task_id, task.strm_path, task.storage_type, task.storage_path)
        ):
            raise ValueError("删除任务缺少必填字段")
        if task.status not in VALID_STATUSES:
            raise ValueError(f"删除任务状态无效：{task.status}")
        return task


class U115DeletionQueue:
    """管理 115 删除任务的持久化、限速、重试和熔断。"""

    def __init__(
        self,
        execute_task: Callable[
            [U115DeletionTask], tuple[Optional[bool], str]
        ],
        persist_state: Optional[Callable[[dict[str, Any]], None]] = None,
        notify_paused: Optional[Callable[[str], None]] = None,
        interval: int = 30,
        now_func: Callable[[], float] = time,
        monotonic_func: Callable[[], float] = monotonic,
        wait_func: Callable[[Event, Optional[float]], bool] = _wait_for_event,
    ) -> None:
        """注入任务执行、持久化、通知、时钟和等待依赖。"""
        self._execute_task = execute_task
        self._persist_state = persist_state
        self._notify_paused = notify_paused
        self._interval = max(10, min(3600, int(interval)))
        self._now = now_func
        self._monotonic = monotonic_func
        self._wait = wait_func
        self._tasks: list[U115DeletionTask] = []
        self._recent: list[dict[str, Any]] = []
        self._lock = Lock()
        self._delete_lock = Lock()
        self._stop_event = Event()
        self._wake_event = Event()
        self._paused = False
        self._pause_reason = ""
        self._cooldown_until = 0.0
        self._consecutive_failures = 0
        self._last_delete_at = 0.0
        self._last_delete_monotonic: Optional[float] = None
        self._last_success_at = 0.0
        self._last_error = ""

    def restore(self, state: Optional[dict[str, Any]]) -> None:
        """从插件数据恢复队列，损坏任务会被安全跳过。"""
        state = state if isinstance(state, dict) else {}
        restored_tasks = []
        for value in state.get("tasks") or []:
            try:
                task = U115DeletionTask.from_dict(value)
            except (KeyError, TypeError, ValueError):
                continue
            if task.status == STATUS_PROCESSING:
                task.status = STATUS_PENDING
            if task.status != STATUS_COMPLETED:
                restored_tasks.append(task)
        with self._lock:
            self._tasks = restored_tasks
            self._recent = list(state.get("recent") or [])[:RECENT_RESULT_LIMIT]
            self._paused = bool(state.get("paused", False))
            self._pause_reason = str(state.get("pause_reason") or "")
            self._cooldown_until = float(state.get("cooldown_until") or 0)
            self._consecutive_failures = int(
                state.get("consecutive_failures") or 0
            )
            self._last_delete_at = float(state.get("last_delete_at") or 0)
            self._last_delete_monotonic = None
            self._last_success_at = float(state.get("last_success_at") or 0)
            self._last_error = str(state.get("last_error") or "")

    def snapshot(self) -> dict[str, Any]:
        """返回当前队列的可序列化状态副本。"""
        with self._lock:
            return self._snapshot_unlocked()

    def enqueue(
        self,
        strm_path: str,
        storage_type: str,
        storage_path: str,
    ) -> bool:
        """把未重复的 115 删除任务持久化加入队尾。"""
        normalized_storage = str(storage_type).strip().casefold()
        normalized_path = Path(str(storage_path)).as_posix()
        task_id = f"{normalized_storage}:{normalized_path}"
        now = self._now()
        with self._lock:
            if any(
                task.task_id == task_id
                and task.status in (STATUS_PENDING, STATUS_PROCESSING)
                for task in self._tasks
            ):
                return False
            task = U115DeletionTask(
                task_id=task_id,
                strm_path=Path(str(strm_path)).as_posix(),
                storage_type=normalized_storage,
                storage_path=normalized_path,
                created_at=now,
                updated_at=now,
            )
            self._tasks.append(task)
            if not self._persist_unlocked():
                self._tasks.remove(task)
                return False
        self._wake_event.set()
        return True

    def run_once(self) -> bool:
        """同步执行一项当前到期任务，供工作者和测试复用。"""
        with self._lock:
            if self._stop_event.is_set() or self._paused:
                return False
            now = self._now()
            if self._cooldown_until > now:
                return False
            task = next(
                (
                    item
                    for item in self._tasks
                    if item.status == STATUS_PENDING
                    and item.next_run_at <= now
                ),
                None,
            )
            if task is None:
                return False
            task.status = STATUS_PROCESSING
            task.updated_at = now
            if not self._persist_unlocked():
                task.status = STATUS_PENDING
                return False

        try:
            success, message = self._execute_task(task)
        except Exception as err:
            success, message = False, str(err)

        with self._lock:
            if success is None:
                task.status = STATUS_PENDING
                task.updated_at = self._now()
                self._persist_unlocked()
                return True
            if success:
                self._finish_success_unlocked(task, message)
            else:
                self._finish_failure_unlocked(task, message)
            self._persist_unlocked()
        return True

    def run(self) -> None:
        """持续串行处理到期任务，直到收到停止信号。"""
        while not self._stop_event.is_set():
            self._wake_event.clear()
            if self.run_once():
                continue
            timeout = self._next_wait_seconds()
            if self._wait(self._wake_event, timeout):
                continue

    def activate(self) -> None:
        """激活队列并允许后台消费者处理任务。"""
        self._stop_event.clear()
        self._wake_event.set()

    def stop(self) -> None:
        """停止消费者且保留尚未执行的任务。"""
        self._stop_event.set()
        self._wake_event.set()

    def resume(self) -> None:
        """清除手动熔断和冷却状态并唤醒消费者。"""
        with self._lock:
            self._paused = False
            self._pause_reason = ""
            self._cooldown_until = 0.0
            self._consecutive_failures = 0
            self._persist_unlocked()
        self._wake_event.set()

    def has_pending(self) -> bool:
        """判断队列是否存在尚待处理的任务。"""
        with self._lock:
            return any(
                task.status in (STATUS_PENDING, STATUS_PROCESSING)
                for task in self._tasks
            )

    def execute_delete(
        self,
        operation: Callable[[], Optional[bool]],
    ) -> Optional[bool]:
        """在统一删除槽中执行一次满足最小间隔的 115 删除。"""
        with self._delete_lock:
            if self._stop_event.is_set():
                return None
            wait_seconds = self._delete_wait_seconds()
            if wait_seconds > 0 and self._wait(
                self._stop_event, wait_seconds
            ):
                return None
            try:
                return operation()
            finally:
                self._last_delete_monotonic = self._monotonic()
                with self._lock:
                    self._last_delete_at = self._now()
                    self._persist_unlocked()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        """在持有状态锁时生成可序列化快照。"""
        return {
            "tasks": [task.to_dict() for task in self._tasks],
            "recent": [dict(item) for item in self._recent],
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "cooldown_until": self._cooldown_until,
            "consecutive_failures": self._consecutive_failures,
            "last_delete_at": self._last_delete_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
        }

    def _persist_unlocked(self) -> bool:
        """在持有状态锁时保存快照，失败则暂停消费者。"""
        if not self._persist_state:
            return True
        try:
            self._persist_state(self._snapshot_unlocked())
            return True
        except Exception as err:
            self._paused = True
            self._pause_reason = "115 删除队列持久化失败"
            self._last_error = str(err)
            return False

    def _finish_success_unlocked(
        self,
        task: U115DeletionTask,
        message: str,
    ) -> None:
        """记录成功任务摘要并清零连续失败计数。"""
        task.status = STATUS_COMPLETED
        task.updated_at = self._now()
        task.last_error = ""
        result = task.to_dict()
        result["message"] = str(message or "")
        self._recent.insert(0, result)
        self._recent = self._recent[:RECENT_RESULT_LIMIT]
        self._tasks.remove(task)
        self._consecutive_failures = 0
        self._last_success_at = task.updated_at
        self._last_error = ""

    def _finish_failure_unlocked(
        self,
        task: U115DeletionTask,
        message: str,
    ) -> None:
        """记录失败，并根据执行次数安排重试或触发冷却。"""
        task.attempts += 1
        task.last_error = str(message or "115 删除失败")
        task.updated_at = self._now()
        self._last_error = task.last_error
        if task.attempts <= len(RETRY_DELAYS):
            task.status = STATUS_PENDING
            task.next_run_at = self._now() + RETRY_DELAYS[task.attempts - 1]
            return
        task.status = STATUS_FAILED
        task.next_run_at = 0.0
        self._consecutive_failures += 1
        self._cooldown_until = self._now() + FAILURE_COOLDOWN_SECONDS
        if self._consecutive_failures == CIRCUIT_FAILURE_THRESHOLD:
            self._paused = True
            self._pause_reason = "连续 3 个 115 删除任务失败"
            if self._notify_paused:
                self._notify_paused(self._pause_reason)

    def _delete_wait_seconds(self) -> float:
        """计算下一次删除槽调用前需要等待的秒数。"""
        if self._last_delete_monotonic is not None:
            elapsed = self._monotonic() - self._last_delete_monotonic
            return max(0.0, self._interval - elapsed)
        if self._last_delete_at:
            elapsed = self._now() - self._last_delete_at
            return max(0.0, self._interval - elapsed)
        return 0.0

    def _next_wait_seconds(self) -> Optional[float]:
        """计算后台消费者距离下一项可执行状态的等待时间。"""
        with self._lock:
            if self._paused:
                return None
            now = self._now()
            if self._cooldown_until > now:
                return self._cooldown_until - now
            waits = [
                max(0.0, task.next_run_at - now)
                for task in self._tasks
                if task.status == STATUS_PENDING
            ]
            return min(waits) if waits else None
