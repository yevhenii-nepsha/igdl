"""igdl - Simple Instagram media downloader CLI.

Download photos and videos from public Instagram profiles.
Files are named by post shortcode for easy URL reference.
"""

__version__ = "0.1.0"

from .archive import DownloadArchive
from .aria2 import Aria2Downloader
from .behavior import BehaviorSimulator
from .client import InstagramClient
from .downloader import ARIA2_BATCH_SIZE, Downloader
from .exceptions import (
    ApiError,
    AuthenticationError,
    DownloadError,
    IgdlError,
    PrivateProfileError,
    ProfileNotFoundError,
    RateLimitError,
)
from .models import MediaItem, Post, PostsPage, Profile
from .proxy import ProxyRotator
from .rate_limiter import RateLimiter

__all__ = [
    # Version
    "__version__",
    # Main classes
    "InstagramClient",
    "Downloader",
    "Aria2Downloader",
    "ARIA2_BATCH_SIZE",
    "RateLimiter",
    "BehaviorSimulator",
    "ProxyRotator",
    "DownloadArchive",
    # Models
    "Profile",
    "Post",
    "PostsPage",
    "MediaItem",
    # Exceptions
    "IgdlError",
    "ProfileNotFoundError",
    "PrivateProfileError",
    "RateLimitError",
    "AuthenticationError",
    "DownloadError",
    "ApiError",
]
