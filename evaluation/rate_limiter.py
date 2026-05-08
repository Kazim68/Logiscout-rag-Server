"""Global rolling-window rate limiter for Gemini API calls.

Gemini free tier: ~10 requests/minute per API key. The whole evaluation pipeline
(LogiScout RAG server intent + answer, baseline LLM call, two judge calls per
scenario) shares a single GEMINI_KEY, so without a global limiter we burst far
past 10/min and trip 429s.

Usage:
    from evaluation.rate_limiter import gemini_acquire
    gemini_acquire()    # blocks until a slot is available
    httpx.post(GEMINI_URL, ...)
"""

import os
import threading
import time
from collections import deque

# Conservative: 8 req/min instead of the documented 10 to leave headroom for
# the RAG server's own Gemini calls which happen outside this limiter.
_GEMINI_MAX_REQUESTS_PER_MINUTE = int(os.environ.get("GEMINI_RPM_BUDGET", "5"))
_WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_timestamps: deque[float] = deque()


def gemini_acquire() -> None:
    """Block until a Gemini request slot is available within the rolling 60s window."""
    while True:
        with _lock:
            now = time.time()
            # Drop timestamps older than the window.
            while _timestamps and now - _timestamps[0] >= _WINDOW_SECONDS:
                _timestamps.popleft()
            if len(_timestamps) < _GEMINI_MAX_REQUESTS_PER_MINUTE:
                _timestamps.append(now)
                return
            wait = _WINDOW_SECONDS - (now - _timestamps[0]) + 0.1
        if wait > 0:
            print(f"  [RateLimit] Gemini slot full ({len(_timestamps)}/"
                  f"{_GEMINI_MAX_REQUESTS_PER_MINUTE} per {int(_WINDOW_SECONDS)}s); "
                  f"waiting {wait:.1f}s")
            time.sleep(wait)
