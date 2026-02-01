"""User behavior simulation for natural browsing patterns."""

import random
import time

from rich.console import Console

console = Console()


class BehaviorSimulator:
    """Simulates human-like browsing behavior.

    Provides delays that mimic natural user interaction patterns
    to avoid detection by Instagram's anti-bot systems.
    """

    # Page scrolling delay (between API pages of 12 posts)
    PAGE_DELAY_MIN: float = 1.0
    PAGE_DELAY_MAX: float = 3.0

    # Carousel swipe delay (between media items in a post)
    CAROUSEL_DELAY_MIN: float = 0.2
    CAROUSEL_DELAY_MAX: float = 0.5

    # Periodic break settings
    BREAK_POSTS_MIN: int = 50
    BREAK_POSTS_MAX: int = 80
    BREAK_DURATION_MIN: float = 10.0
    BREAK_DURATION_MAX: float = 30.0

    # Highlight viewing delays (simulates tapping through highlights)
    HIGHLIGHT_TRAY_DELAY_MIN: float = 1.5
    HIGHLIGHT_TRAY_DELAY_MAX: float = 4.0
    HIGHLIGHT_SWITCH_DELAY_MIN: float = 2.0
    HIGHLIGHT_SWITCH_DELAY_MAX: float = 5.0

    # Aggressive mode (with proxy) - minimal delays
    AGGRESSIVE_PAGE_DELAY: float = 0.1
    AGGRESSIVE_CAROUSEL_DELAY: float = 0.05

    def __init__(self, quiet: bool = False, has_proxy: bool = False) -> None:
        self._quiet = quiet
        self._has_proxy = has_proxy
        self._posts_since_break = 0
        self._next_break_at = self._random_break_interval()

    def _random_break_interval(self) -> int:
        """Generate random number of posts before next break."""
        return random.randint(self.BREAK_POSTS_MIN, self.BREAK_POSTS_MAX)

    def page_delay(self) -> None:
        """Delay between API page fetches (simulates scrolling)."""
        if self._has_proxy:
            time.sleep(self.AGGRESSIVE_PAGE_DELAY)
        else:
            delay = random.uniform(self.PAGE_DELAY_MIN, self.PAGE_DELAY_MAX)
            time.sleep(delay)

    def carousel_delay(self) -> None:
        """Delay between carousel items (simulates swiping)."""
        if self._has_proxy:
            time.sleep(self.AGGRESSIVE_CAROUSEL_DELAY)
        else:
            delay = random.uniform(self.CAROUSEL_DELAY_MIN, self.CAROUSEL_DELAY_MAX)
            time.sleep(delay)

    def highlight_tray_delay(self) -> None:
        """Delay before fetching highlights tray (simulates scrolling to highlights row)."""
        if self._has_proxy:
            time.sleep(self.AGGRESSIVE_PAGE_DELAY)
        else:
            delay = random.uniform(self.HIGHLIGHT_TRAY_DELAY_MIN, self.HIGHLIGHT_TRAY_DELAY_MAX)
            time.sleep(delay)

    def highlight_switch_delay(self) -> None:
        """Delay between viewing different highlights (simulates tapping next highlight)."""
        if self._has_proxy:
            time.sleep(self.AGGRESSIVE_PAGE_DELAY)
        else:
            delay = random.uniform(self.HIGHLIGHT_SWITCH_DELAY_MIN, self.HIGHLIGHT_SWITCH_DELAY_MAX)
            time.sleep(delay)

    def record_post_processed(self) -> None:
        """Record that a post was processed, may trigger break."""
        # Skip breaks with proxy
        if self._has_proxy:
            return

        self._posts_since_break += 1

        if self._posts_since_break >= self._next_break_at:
            self._take_break()
            self._posts_since_break = 0
            self._next_break_at = self._random_break_interval()

    def _take_break(self) -> None:
        """Take a periodic break to simulate user resting."""
        delay = random.uniform(self.BREAK_DURATION_MIN, self.BREAK_DURATION_MAX)

        if not self._quiet:
            console.print(f"[dim]Pausing for {delay:.0f}s...[/dim]")

        time.sleep(delay)
