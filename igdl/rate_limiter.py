"""Rate limiting for Instagram API requests."""

import random
import time
from collections import deque
from threading import Lock

from rich.console import Console

console = Console()


class RateLimiter:
    """Sliding window rate limiter for Instagram API.

    Based on instaloader's research:
    - 75 requests per 11 minutes for anonymous users (conservative)
    - Random delay between requests using exponential distribution
    """

    WINDOW_SECONDS: float = 660.0  # 11 minutes
    MAX_REQUESTS: int = 75  # Limit for anonymous (more relaxed with proxy)
    MIN_DELAY: float = 0.5  # Minimum delay between requests
    MAX_DELAY: float = 5.0  # Maximum random delay

    # Aggressive mode (with proxy) - minimal delays
    AGGRESSIVE_MIN_DELAY: float = 0.1
    AGGRESSIVE_MAX_DELAY: float = 0.3

    def __init__(self, quiet: bool = False, has_proxy: bool = False) -> None:
        self._timestamps: deque[float] = deque()
        self._lock = Lock()
        self._quiet = quiet
        self._has_proxy = has_proxy

    def _clean_old_timestamps(self, current_time: float) -> None:
        """Remove timestamps outside the sliding window."""
        cutoff = current_time - self.WINDOW_SECONDS
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _random_delay(self) -> float:
        """Generate random delay using exponential distribution."""
        if self._has_proxy:
            # With proxy: minimal delay
            return random.uniform(self.AGGRESSIVE_MIN_DELAY, self.AGGRESSIVE_MAX_DELAY)
        # Lambda = 0.3 gives mean delay of ~3.3s (more conservative)
        delay = min(random.expovariate(0.3), self.MAX_DELAY)
        return max(delay, self.MIN_DELAY)

    def wait_if_needed(self) -> None:
        """Wait if approaching rate limit, then add random delay."""
        with self._lock:
            # With proxy, skip sliding window check (IP rotates)
            if not self._has_proxy:
                current_time = time.monotonic()
                self._clean_old_timestamps(current_time)

                requests_in_window = len(self._timestamps)

                # If at limit, wait until oldest request expires
                if requests_in_window >= self.MAX_REQUESTS:
                    oldest = self._timestamps[0]
                    wait_time = oldest + self.WINDOW_SECONDS - current_time + 6.0
                    if wait_time > 0:
                        if not self._quiet:
                            msg = f"Rate limit approaching, waiting {wait_time:.1f}s..."
                            console.print(f"[yellow]{msg}[/yellow]")
                        time.sleep(wait_time)

            # Add random delay to avoid detection
            delay = self._random_delay()
            time.sleep(delay)

    def record_request(self) -> None:
        """Record that a request was made."""
        with self._lock:
            self._timestamps.append(time.monotonic())

    def get_stats(self) -> dict[str, int | float]:
        """Get current rate limiter statistics."""
        with self._lock:
            current_time = time.monotonic()
            self._clean_old_timestamps(current_time)
            return {
                "requests_in_window": len(self._timestamps),
                "max_requests": self.MAX_REQUESTS,
                "window_seconds": self.WINDOW_SECONDS,
            }
