"""Request identity and provider metadata captured at the point a log is emitted."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

request_state = ContextVar("log_request_state", default=None)
user_id = ContextVar("log_user_id", default=None)
purpose = ContextVar("log_call_purpose", default=None)
model_name = ContextVar("log_model_name", default=None)


@contextmanager
def bind(variable, value):
    token = variable.set(value)
    try:
        yield
    finally:
        variable.reset(token)


def identity():
    state = request_state.get()
    actor = user_id.get() or (state.get("audit_actor") if state is not None else None)
    if actor:
        return actor, "user"
    return None, "anonymous" if state is not None else "system"


def model_method(label=None):
    def decorate(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            with bind(purpose, label or purpose.get() or "问答"), bind(model_name, self.model):
                return method(self, *args, **kwargs)
        return wrapper
    return decorate


def model_stream(stream, model):
    # Starlette can advance and close one generator in different thread contexts.
    label = purpose.get() or "问答"
    try:
        while True:
            with bind(model_name, model), bind(purpose, label):
                event = next(stream, None)
            if event is None:
                return
            yield event
    finally:
        with bind(model_name, model), bind(purpose, label):
            stream.close()
