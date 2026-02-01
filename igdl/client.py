"""Instagram API client for anonymous access."""

import http.cookiejar
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from .behavior import BehaviorSimulator
from .exceptions import (
    ApiError,
    AuthenticationError,
    DownloadError,
    PrivateProfileError,
    ProfileNotFoundError,
    RateLimitError,
)
from .models import Highlight, HighlightItem, Post, PostsPage, Profile
from .proxy import ProxyRotator
from .rate_limiter import RateLimiter

console = Console()

# GraphQL doc_id for fetching user posts (anonymous)
POSTS_DOC_ID = "7950326061742207"

# User-Agent string for requests
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Default headers mimicking Chrome browser
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "www.instagram.com",
    "Origin": "https://www.instagram.com",
    "Referer": "https://www.instagram.com/",
    "User-Agent": USER_AGENT,
    "X-Requested-With": "XMLHttpRequest",
    "X-IG-App-ID": "936619743392459",
}

# Headers for CDN media downloads (simpler, avoids Instagram-specific headers)
CDN_HEADERS = {
    "User-Agent": USER_AGENT,
}


def load_cookies_file(path: Path) -> http.cookiejar.CookieJar:
    """Load cookies from Netscape format file.

    This format is exported by browser extensions like "Get cookies.txt".
    """
    cookie_jar = http.cookiejar.MozillaCookieJar(str(path))
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    return cookie_jar


class InstagramClient:
    """Low-level Instagram API client for anonymous access.

    Handles HTTP communication, rate limiting, and response parsing.
    Designed to be extended for authenticated access in the future.
    """

    BASE_URL = "https://www.instagram.com"

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        behavior: BehaviorSimulator | None = None,
        proxy_rotator: ProxyRotator | None = None,
        cookies_file: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.rate_limiter = rate_limiter or RateLimiter()
        self.behavior = behavior or BehaviorSimulator()
        self.proxy_rotator = proxy_rotator or ProxyRotator()
        self.cookies_file = cookies_file
        self.timeout = timeout
        self._session = self._create_session()

        # Load cookies if provided
        if cookies_file:
            self._load_cookies(cookies_file)

    def _create_session(self) -> requests.Session:
        """Create configured requests session."""
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        # Set initial cookies
        session.cookies.set("ig_did", "", domain=".instagram.com")
        session.cookies.set("ig_nrcb", "1", domain=".instagram.com")

        return session

    def _load_cookies(self, path: Path) -> None:
        """Load cookies from file into session."""
        try:
            cookie_jar = load_cookies_file(path)
            # Copy cookies to session
            for cookie in cookie_jar:
                self._session.cookies.set_cookie(cookie)
            console.print(f"[dim]Loaded {len(cookie_jar)} cookies from {path.name}[/dim]")
        except (OSError, http.cookiejar.LoadError) as e:
            console.print(f"[yellow]Warning: Failed to load cookies: {e}[/yellow]")

    def refresh_session(self) -> None:
        """Refresh session after rate limit or errors.

        Creates a new session and reloads cookies if available.
        """
        console.print("[dim]Refreshing session...[/dim]")
        self._session.close()
        self._session = self._create_session()

        if self.cookies_file:
            self._load_cookies(self.cookies_file)

    def _request(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> requests.Response:
        """Make HTTP request with rate limiting, retries, and proxy support."""
        self.rate_limiter.wait_if_needed()

        for attempt in range(max_retries):
            try:
                # Apply current proxy if available
                proxies = self.proxy_rotator.get_proxies_dict()

                response = self._session.request(
                    method,
                    url,
                    timeout=self.timeout,
                    proxies=proxies,
                    **kwargs,
                )
                self.rate_limiter.record_request()
                self.proxy_rotator.record_request()

                # Handle rate limiting (429 or 401 with "wait" message)
                if response.status_code == 429 or (
                    response.status_code == 401 and "wait" in response.text.lower()
                ):
                    # Rotate proxy on rate limit
                    self.proxy_rotator.rotate_on_error()

                    retry_after = float(response.headers.get("Retry-After", 300))
                    # If we have multiple proxies, retry immediately with new proxy
                    if self.proxy_rotator.has_multiple:
                        retry_after = 1.0

                    if attempt < max_retries - 1:
                        console.print(
                            f"[yellow]Rate limited, waiting {retry_after:.0f}s "
                            f"(attempt {attempt + 1}/{max_retries})...[/yellow]"
                        )
                        time.sleep(retry_after)
                        # Refresh session after rate limit wait
                        self.refresh_session()
                        continue
                    raise RateLimitError(retry_after)

                if response.status_code == 404:
                    raise ProfileNotFoundError("unknown")

                if response.status_code >= 400:
                    raise ApiError(response.status_code, response.text[:200])

                return response

            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = 2**attempt
                    console.print(
                        f"[yellow]Network error: {e}, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})...[/yellow]"
                    )
                    time.sleep(wait_time)
                    continue
                raise ApiError(0, str(e)) from e

        raise ApiError(0, "Max retries exceeded")

    def get_profile(self, username: str) -> Profile:
        """Fetch profile information by username."""
        # Try API endpoint first
        profile = self._get_profile_api(username)
        if profile:
            return profile

        # Fallback to HTML parsing
        console.print("[dim]API returned no data, trying HTML fallback...[/dim]")
        profile = self._get_profile_html(username)
        if profile:
            return profile

        raise ProfileNotFoundError(username)

    def _get_profile_api(self, username: str) -> Profile | None:
        """Fetch profile via API endpoint."""
        url = f"{self.BASE_URL}/api/v1/users/web_profile_info/"
        params = {"username": username}

        response = self._request("GET", url, params=params)

        try:
            data = response.json()
        except json.JSONDecodeError:
            return None

        if data.get("status") != "ok":
            return None

        user_data = data.get("data", {}).get("user")
        if not user_data:
            return None

        profile = Profile.from_api_response(user_data)

        if profile.is_private:
            raise PrivateProfileError(username)

        return profile

    def _get_profile_html(self, username: str) -> Profile | None:
        """Fetch profile by parsing HTML page."""
        url = f"{self.BASE_URL}/{username}/"
        response = self._request("GET", url)

        # Look for user ID in meta tag or script
        html = response.text

        # Try to find user_id from various patterns
        patterns = [
            r'"user_id":"(\d+)"',
            r'"profilePage_(\d+)"',
            r'"owner":\{"id":"(\d+)"',
            r'data-id="(\d+)"',
        ]

        user_id = None
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                user_id = match.group(1)
                break

        if not user_id:
            return None

        # Try to get post count
        post_count = 0
        count_match = re.search(r'"edge_owner_to_timeline_media":\{"count":(\d+)', html)
        if count_match:
            post_count = int(count_match.group(1))

        # Check if private
        is_private = '"is_private":true' in html

        if is_private:
            raise PrivateProfileError(username)

        return Profile(
            user_id=user_id,
            username=username,
            full_name="",
            is_private=False,
            post_count=post_count,
        )

    def get_posts_page(
        self,
        user_id: str,
        first: int = 12,
        after: str | None = None,
    ) -> PostsPage:
        """Fetch a page of posts for a user."""
        # Try REST API first (works better with cookies)
        if self.cookies_file:
            return self._get_posts_page_rest(user_id, first, after)
        return self._get_posts_page_graphql(user_id, first, after)

    def _get_posts_page_graphql(
        self,
        user_id: str,
        first: int = 12,
        after: str | None = None,
    ) -> PostsPage:
        """Fetch posts via GraphQL (anonymous access)."""
        url = f"{self.BASE_URL}/graphql/query"

        variables = {
            "id": user_id,
            "first": first,
        }
        if after:
            variables["after"] = after

        params = {
            "doc_id": POSTS_DOC_ID,
            "variables": json.dumps(variables),
        }

        response = self._request("GET", url, params=params)

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise ApiError(response.status_code, "Invalid JSON response") from e

        user_data = data.get("data", {}).get("user")
        if not user_data:
            raise ApiError(response.status_code, "No user data in response")

        return PostsPage.from_api_response(user_data)

    def _get_posts_page_rest(
        self,
        user_id: str,
        first: int = 12,
        after: str | None = None,
    ) -> PostsPage:
        """Fetch posts via REST API (authenticated access)."""
        url = f"{self.BASE_URL}/api/v1/feed/user/{user_id}/"

        params = {"count": first}
        if after:
            params["max_id"] = after

        response = self._request("GET", url, params=params)

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise ApiError(response.status_code, "Invalid JSON response") from e

        return PostsPage.from_rest_response(data)

    def iter_posts(
        self,
        user_id: str,
        limit: int | None = None,
        max_page_retries: int = 3,
    ) -> Iterator[Post]:
        """Iterate over all posts for a user.

        Args:
            user_id: Instagram user ID
            limit: Maximum number of posts to fetch (None for all)
            max_page_retries: Max retries for each page on error

        Yields:
            Post objects
        """
        cursor: str | None = None
        count = 0
        consecutive_errors = 0

        while True:
            # Simulate scrolling delay between pages (except first)
            if cursor is not None:
                self.behavior.page_delay()

            # Try to get page with retries
            page = None
            for attempt in range(max_page_retries):
                try:
                    page = self.get_posts_page(user_id, after=cursor)
                    consecutive_errors = 0  # Reset on success
                    break
                except (ApiError, RateLimitError) as e:
                    consecutive_errors += 1
                    if attempt < max_page_retries - 1:
                        wait_time = 30 * (attempt + 1)  # 30s, 60s, 90s
                        console.print(
                            f"[yellow]Page fetch failed: {e}. "
                            f"Waiting {wait_time}s and retrying "
                            f"(attempt {attempt + 1}/{max_page_retries})...[/yellow]"
                        )
                        time.sleep(wait_time)
                        self.refresh_session()
                        continue
                    else:
                        # All retries failed, but we may have partial data
                        console.print(
                            f"[red]Failed to fetch page after {max_page_retries} attempts. "
                            f"Stopping iteration (downloaded {count} posts).[/red]"
                        )
                        return

            if page is None:
                return

            for post in page.posts:
                yield post
                count += 1

                if limit and count >= limit:
                    return

            if not page.has_next_page or not page.end_cursor:
                break

            cursor = page.end_cursor

    def _require_cookies(self, feature: str) -> None:
        """Raise AuthenticationError if no cookies are loaded."""
        if not self.cookies_file:
            raise AuthenticationError(f"{feature} requires cookies (use --cookies)")

    def get_highlights(self, user_id: str) -> list[Highlight]:
        """Fetch list of highlight reels for a user.

        Requires authentication (cookies). Returns highlights with metadata
        only — items must be fetched separately via get_highlight_items().

        Args:
            user_id: Instagram user ID.

        Returns:
            List of Highlight objects (without items populated).

        Raises:
            AuthenticationError: If no cookies are loaded.
        """
        self._require_cookies("Highlights")
        url = f"{self.BASE_URL}/api/v1/highlights/{user_id}/highlights_tray/"

        response = self._request("GET", url)

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise ApiError(response.status_code, "Invalid JSON in highlights tray") from e

        tray = data.get("tray", [])
        return [Highlight.from_tray_item(item) for item in tray]

    def get_highlight_items(self, highlight_id: str) -> list[HighlightItem]:
        """Fetch media items for a specific highlight reel.

        Requires authentication (cookies). Requests items for a single
        highlight reel and returns them sorted by timestamp.

        Args:
            highlight_id: Numeric highlight ID (without ``highlight:`` prefix).

        Returns:
            List of HighlightItem objects with best-quality URLs.

        Raises:
            AuthenticationError: If no cookies are loaded.
        """
        self._require_cookies("Highlights")
        url = f"{self.BASE_URL}/api/v1/feed/reels_media/"
        reel_id = f"highlight:{highlight_id}"

        response = self._request("GET", url, params={"reel_ids": reel_id})

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            raise ApiError(response.status_code, "Invalid JSON in highlight items") from e

        reel_data = data.get("reels", {}).get(reel_id, {})
        raw_items = reel_data.get("items", [])
        return [HighlightItem.from_rest_item(item) for item in raw_items]

    def download_media(
        self,
        url: str,
        filepath: Path,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        """Download media content from URL directly to file.

        Uses streaming to avoid loading large files into memory.

        Note: Media is served from CDN, not Instagram API.
        Uses minimal headers to avoid CDN rejecting the request.

        Args:
            url: Media URL to download
            filepath: Destination file path
            max_retries: Maximum retry attempts for failed downloads
            timeout: Timeout for download (longer than API requests)
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    stream=True,
                    headers=CDN_HEADERS,
                )
                response.raise_for_status()

                with filepath.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return  # Success

            except requests.RequestException as e:
                last_error = e
                # Clean up partial file
                if filepath.exists():
                    filepath.unlink()

                if attempt < max_retries - 1:
                    wait_time = 2**attempt
                    time.sleep(wait_time)
                    continue

        # All retries failed
        raise DownloadError(url, str(last_error)) from last_error

    def close(self) -> None:
        """Close the session."""
        self._session.close()

    def __enter__(self) -> "InstagramClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
