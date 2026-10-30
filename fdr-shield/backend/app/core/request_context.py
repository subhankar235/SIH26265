"""Request-scoped metadata propagated to same-transaction audit records."""
from contextvars import ContextVar

request_id_context: ContextVar[str | None] = ContextVar('request_id', default=None)
