"""Proxy management and rotation for Instagram requests."""

import random
from pathlib import Path
from threading import Lock

from rich.console import Console

console = Console()


class ProxyRotator:
    """Manages proxy rotation for avoiding rate limits.

    Supports:
    - Single proxy mode (one proxy URL)
    - Rotation mode (list of proxies from file)
    - Rotation triggers: every N requests or on rate limit
    """

    ROTATE_EVERY_REQUESTS: int = 20

    def __init__(
        self,
        proxy: str | None = None,
        proxy_file: Path | None = None,
        quiet: bool = False,
    ) -> None:
        """Initialize proxy rotator.

        Args:
            proxy: Single proxy URL (http://user:pass@host:port)
            proxy_file: Path to file with proxy list (one per line)
            quiet: Suppress rotation messages
        """
        self._quiet = quiet
        self._lock = Lock()
        self._request_count = 0
        self._current_index = 0

        # Load proxies
        self._proxies: list[str] = []
        if proxy:
            self._proxies = [proxy]
        elif proxy_file:
            self._proxies = self._load_proxy_file(proxy_file)
            if self._proxies:
                random.shuffle(self._proxies)

    def _load_proxy_file(self, path: Path) -> list[str]:
        """Load proxies from file (one URL per line)."""
        if not path.exists():
            if not self._quiet:
                console.print(f"[yellow]Proxy file not found: {path}[/yellow]")
            return []

        proxies: list[str] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                proxy = line.strip()
                if proxy and not proxy.startswith("#"):
                    proxies.append(proxy)

        if not self._quiet and proxies:
            console.print(f"[dim]Loaded {len(proxies)} proxies[/dim]")

        return proxies

    @property
    def enabled(self) -> bool:
        """Check if proxy rotation is enabled."""
        return len(self._proxies) > 0

    @property
    def has_multiple(self) -> bool:
        """Check if multiple proxies are available for rotation."""
        return len(self._proxies) > 1

    def get_current(self) -> str | None:
        """Get current proxy URL."""
        if not self._proxies:
            return None
        with self._lock:
            return self._proxies[self._current_index]

    def get_proxies_dict(self) -> dict[str, str] | None:
        """Get proxy dict for requests library."""
        proxy = self.get_current()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def record_request(self) -> None:
        """Record a request and rotate if threshold reached."""
        if not self.has_multiple:
            return

        with self._lock:
            self._request_count += 1
            if self._request_count >= self.ROTATE_EVERY_REQUESTS:
                self._rotate()
                self._request_count = 0

    def rotate_on_error(self) -> None:
        """Force rotation due to rate limit or error."""
        if not self.has_multiple:
            return

        with self._lock:
            self._rotate()
            self._request_count = 0

    def _rotate(self) -> None:
        """Switch to next proxy in the list."""
        old_index = self._current_index
        self._current_index = (self._current_index + 1) % len(self._proxies)

        if not self._quiet:
            console.print(
                f"[dim]Rotating proxy: {old_index + 1} → {self._current_index + 1} "
                f"(of {len(self._proxies)})[/dim]"
            )
