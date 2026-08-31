import time
from functools import wraps
from threading import Lock

from flask import current_app, request

from .response import error_response


def _store():
    """Per-app sliding window store. Fresh per Flask app (per test server)."""
    if not hasattr(current_app, "_rate_store"):
        current_app._rate_store = {}
        current_app._rate_store_lock = Lock()
    return current_app._rate_store, current_app._rate_store_lock


def check_rate_limit(key, limit, window_seconds):
    """Return (ok, retry_after). Sliding window keyed by (key, client_ip)."""
    store, lock = _store()
    ip = request.remote_addr or "unknown"
    window_key = "{}:{}".format(key, ip)
    now = time.monotonic()
    with lock:
        events = store.get(window_key, [])
        events = [t for t in events if now - t < window_seconds]
        if len(events) >= limit:
            store[window_key] = events
            oldest = events[0] if events else now
            retry_after = max(1, int(window_seconds - (now - oldest)))
            return False, retry_after
        events.append(now)
        store[window_key] = events
        return True, 0


def rate_limit(key, limit, window_seconds=60, _retry_code="RATE_LIMITED"):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ok, retry_after = check_rate_limit(key, limit, window_seconds)
            if not ok:
                resp, status = error_response(
                    "Too many requests. Try again shortly.",
                    code=_retry_code,
                    status=429,
                    retry_after=retry_after,
                )
                resp.headers["Retry-After"] = str(retry_after)
                return resp, status
            return fn(*args, **kwargs)

        return wrapper

    return decorator
