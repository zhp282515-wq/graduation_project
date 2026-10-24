import anyio
from fastapi.responses import StreamingResponse


class ChatStreamingResponse(StreamingResponse):
    """包括发送响应头失败、断连、尚未消费流在内，均显式关闭运行。"""

    def __init__(self, content, *, run, cleanup=None, **kwargs):
        super().__init__(content, **kwargs)
        self._run = run
        self._cleanup = cleanup

    def _close(self):
        try:
            self._run.close()
        finally:
            if self._cleanup:
                self._cleanup()

    async def __call__(self, scope, receive, send):
        background, self.background = self.background, None
        try:
            await super().__call__(scope, receive, send)
        finally:
            # 线程中的同步模型调用不可强杀；等 next 结束后再归还运行资格。
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self._close)
        # 先归还请求连接，再执行需要重新借连接的后台记忆任务。
        if background is not None:
            await background()
