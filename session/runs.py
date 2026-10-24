"""单进程共享的按键互斥与可显式关闭的运行流。"""

from collections.abc import Iterator
from threading import Condition, RLock
from typing import Any


class SessionBusyError(RuntimeError):
    pass


class KeyedLocks:
    def __init__(self):
        self._condition = Condition()
        self._active: set[str] = set()

    def acquire(self, key: str, *, blocking: bool = False):
        with self._condition:
            while key in self._active:
                if not blocking:
                    raise SessionBusyError("正在生成，请结束后重试")
                self._condition.wait()
            self._active.add(key)
        return _Lease(self, key)


class _Lease:
    def __init__(self, owner: KeyedLocks, key: str):
        self._owner, self._key = owner, key
        self._released = False

    def release(self):
        with self._owner._condition:
            if not self._released:
                self._released = True
                self._owner._active.remove(self._key)
                self._owner._condition.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


class RunStream(Iterator[dict[str, Any]]):
    """close 即使在首次迭代前也有效；等待正在执行的 next 退出后才解锁。"""

    def __init__(self, events: Iterator[dict[str, Any]], lease: _Lease):
        self._events, self._lease = events, lease
        self._step = RLock()
        self._closed = False

    def __next__(self):
        with self._step:
            if self._closed:
                raise StopIteration
            try:
                return next(self._events)
            except BaseException:
                self.close()
                raise

    def close(self):
        with self._step:
            if not self._closed:
                self._closed = True
                try:
                    close = getattr(self._events, "close", None)
                    if close:
                        close()
                finally:
                    self._lease.release()


DEFAULT_RUNS = KeyedLocks()
