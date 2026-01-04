"""Custom exceptions for igdl."""


class IgdlError(Exception):
    """Base exception for all igdl errors."""

    pass


class ProfileNotFoundError(IgdlError):
    """Raised when a profile does not exist."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Profile not found: {username}")


class PrivateProfileError(IgdlError):
    """Raised when trying to access a private profile without authentication."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(f"Profile is private: {username}")


class RateLimitError(IgdlError):
    """Raised when Instagram rate limits requests."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        msg = "Rate limited by Instagram"
        if retry_after:
            msg += f", retry after {retry_after:.1f}s"
        super().__init__(msg)


class AuthenticationError(IgdlError):
    """Raised when authentication fails or is required."""

    pass


class DownloadError(IgdlError):
    """Raised when a media download fails."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Download failed: {reason}")


class ApiError(IgdlError):
    """Raised when Instagram API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")
