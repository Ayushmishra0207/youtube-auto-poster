"""
Retry decorator with exponential back-off + jitter.

Usage:
    from pipeline.retry import with_retry

    @with_retry(max_attempts=3, base_delay=2.0)
    def call_api():
        ...

    # Retry only on specific exception types:
    @with_retry(max_attempts=4, base_delay=5.0, exceptions=(requests.exceptions.RequestException,))
    def fetch_image():
        ...
"""
import functools
import random
import time

from pipeline.logger import log


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    exceptions: tuple = (Exception,),
):
    """
    Decorator that retries the wrapped function on failure.

    Args:
        max_attempts: Total attempts (including the first try).
        base_delay:   Seconds to wait before the first retry.
                      Each subsequent retry doubles the delay (+ random jitter ≤ 1 s).
        exceptions:   Exception types that trigger a retry.
                      Any other exception propagates immediately.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        log.error(
                            "[retry] %s failed after %d attempts: %s",
                            fn.__name__, max_attempts, exc,
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    log.warning(
                        "[retry] %s attempt %d/%d failed: %s — retrying in %.1fs",
                        fn.__name__, attempt, max_attempts, exc, delay,
                    )
                    time.sleep(delay)
            raise last_exc  # unreachable, but satisfies type checkers
        return wrapper
    return decorator
