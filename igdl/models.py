"""Data models for Instagram content."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Profile:
    """Instagram user profile."""

    user_id: str
    username: str
    full_name: str
    is_private: bool
    post_count: int
    biography: str = ""
    profile_pic_url: str = ""

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "Profile":
        """Create Profile from Instagram API response."""
        user = data.get("user", data)
        return cls(
            user_id=str(user.get("pk") or user.get("id", "")),
            username=user.get("username", ""),
            full_name=user.get("full_name", ""),
            is_private=user.get("is_private", False),
            post_count=user.get("edge_owner_to_timeline_media", {}).get("count", 0),
            biography=user.get("biography", ""),
            profile_pic_url=user.get("profile_pic_url_hd", user.get("profile_pic_url", "")),
        )


@dataclass
class MediaItem:
    """Single media item (image or video)."""

    url: str
    is_video: bool
    index: int | None = None  # For carousel items

    @property
    def extension(self) -> str:
        """Get file extension based on media type."""
        return "mp4" if self.is_video else "jpg"


@dataclass
class Post:
    """Instagram post with media."""

    shortcode: str
    typename: str  # GraphImage, GraphVideo, GraphSidecar
    display_url: str
    video_url: str | None
    is_video: bool
    timestamp: datetime
    caption: str = ""
    like_count: int = 0
    comment_count: int = 0
    media_items: list[MediaItem] = field(default_factory=list)

    @property
    def url(self) -> str:
        """Get Instagram URL for this post."""
        return f"https://www.instagram.com/p/{self.shortcode}/"

    @property
    def is_carousel(self) -> bool:
        """Check if post is a carousel (multiple media items)."""
        return self.typename == "GraphSidecar"

    def get_media_items(self) -> list[MediaItem]:
        """Get all media items for download."""
        if self.media_items:
            return self.media_items

        # Single media post
        url = self.video_url if self.is_video else self.display_url
        if not url:
            return []

        return [
            MediaItem(
                url=url,
                is_video=self.is_video,
                index=None,
            )
        ]

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> "Post":
        """Create Post from GraphQL node."""
        # Parse timestamp (Instagram returns Unix timestamp in UTC)
        timestamp_raw = node.get("taken_at_timestamp") or node.get("date", 0)
        timestamp = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)

        # Parse caption
        caption = ""
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        if caption_edges:
            caption = caption_edges[0].get("node", {}).get("text", "")

        # Parse media items for carousel
        media_items: list[MediaItem] = []
        sidecar_edges = node.get("edge_sidecar_to_children", {}).get("edges", [])
        for idx, edge in enumerate(sidecar_edges):
            child = edge.get("node", {})
            is_video = child.get("is_video", False)
            media_items.append(
                MediaItem(
                    url=child.get("video_url") if is_video else child.get("display_url", ""),
                    is_video=is_video,
                    index=idx + 1,
                )
            )

        return cls(
            shortcode=node.get("shortcode", ""),
            typename=node.get("__typename", "GraphImage"),
            display_url=node.get("display_url", ""),
            video_url=node.get("video_url"),
            is_video=node.get("is_video", False),
            timestamp=timestamp,
            caption=caption,
            like_count=node.get("edge_media_preview_like", {}).get("count", 0),
            comment_count=node.get("edge_media_to_comment", {}).get("count", 0),
            media_items=media_items,
        )

    @classmethod
    def from_rest_item(cls, item: dict[str, Any]) -> "Post":
        """Create Post from REST API item (/api/v1/feed/user/)."""
        # Parse timestamp
        timestamp_raw = item.get("taken_at", 0)
        timestamp = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)

        # Parse caption
        caption_data = item.get("caption") or {}
        caption = caption_data.get("text", "") if isinstance(caption_data, dict) else ""

        # Media type: 1=photo, 2=video, 8=carousel
        media_type = item.get("media_type", 1)
        is_video = media_type == 2
        is_carousel = media_type == 8

        # Map media_type to typename
        typename = "GraphImage"
        if is_video:
            typename = "GraphVideo"
        elif is_carousel:
            typename = "GraphSidecar"

        # Get display URL
        display_url = ""
        image_versions = item.get("image_versions2", {}).get("candidates", [])
        if image_versions:
            display_url = image_versions[0].get("url", "")

        # Get video URL
        video_url = None
        if is_video:
            video_versions = item.get("video_versions", [])
            if video_versions:
                video_url = video_versions[0].get("url")

        # Parse carousel items
        media_items: list[MediaItem] = []
        carousel_media = item.get("carousel_media", [])
        for idx, child in enumerate(carousel_media):
            child_is_video = child.get("media_type") == 2
            child_url = ""

            if child_is_video:
                video_vers = child.get("video_versions", [])
                if video_vers:
                    child_url = video_vers[0].get("url", "")
            else:
                img_vers = child.get("image_versions2", {}).get("candidates", [])
                if img_vers:
                    child_url = img_vers[0].get("url", "")

            if child_url:
                media_items.append(
                    MediaItem(
                        url=child_url,
                        is_video=child_is_video,
                        index=idx + 1,
                    )
                )

        return cls(
            shortcode=item.get("code", ""),
            typename=typename,
            display_url=display_url,
            video_url=video_url,
            is_video=is_video,
            timestamp=timestamp,
            caption=caption,
            like_count=item.get("like_count", 0),
            comment_count=item.get("comment_count", 0),
            media_items=media_items,
        )


@dataclass
class PostsPage:
    """Paginated response of posts."""

    posts: list[Post]
    has_next_page: bool
    end_cursor: str | None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "PostsPage":
        """Create PostsPage from Instagram API response."""
        media = data.get("edge_owner_to_timeline_media", {})
        edges = media.get("edges", [])
        page_info = media.get("page_info", {})

        posts = [Post.from_node(edge.get("node", {})) for edge in edges]

        return cls(
            posts=posts,
            has_next_page=page_info.get("has_next_page", False),
            end_cursor=page_info.get("end_cursor"),
        )

    @classmethod
    def from_rest_response(cls, data: dict[str, Any]) -> "PostsPage":
        """Create PostsPage from REST API response (/api/v1/feed/user/)."""
        items = data.get("items", [])
        posts = [Post.from_rest_item(item) for item in items]

        return cls(
            posts=posts,
            has_next_page=data.get("more_available", False),
            end_cursor=data.get("next_max_id"),
        )


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe directory name.

    Preserves unicode characters (emoji, accents, cyrillic, etc.) while
    removing only characters that are unsafe for filesystems. Lowercases
    ASCII letters, replaces whitespace and unsafe chars with hyphens,
    and collapses consecutive hyphens.

    Examples:
        "Sea 2025" -> "sea-2025"
        "My Trip 🌊" -> "my-trip-🌊"
        "Café & Bar" -> "café-&-bar"
        "🔗" -> "🔗"
        "Море" -> "море"
    """
    # Normalize unicode to NFC (composed form, consistent representation)
    text = unicodedata.normalize("NFC", text)
    # Lowercase (only affects cased characters, emoji/symbols unchanged)
    text = text.lower()
    # Replace filesystem-unsafe characters and whitespace with hyphens
    # Unsafe: / \ NUL and control characters (0x00-0x1F, 0x7F)
    text = re.sub(r"[\x00-\x1f\x7f/\\]+", "-", text)
    # Replace whitespace with hyphens
    text = re.sub(r"\s+", "-", text)
    # Collapse consecutive hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens and dots (avoid hidden dirs)
    text = text.strip("-.")
    return text or "untitled"


@dataclass
class HighlightItem:
    """Single item (photo or video) from a highlight reel."""

    media_id: str
    is_video: bool
    url: str
    timestamp: datetime

    @property
    def extension(self) -> str:
        """Get file extension based on media type."""
        return "mp4" if self.is_video else "jpg"

    @classmethod
    def from_rest_item(cls, item: dict[str, Any]) -> "HighlightItem":
        """Create HighlightItem from REST API item (/api/v1/feed/reels_media/).

        Args:
            item: Single item dict from the highlight reel response.

        Returns:
            Parsed HighlightItem with best-quality media URL.
        """
        media_id = str(item.get("pk", ""))
        media_type = item.get("media_type", 1)
        is_video = media_type == 2
        timestamp_raw = item.get("taken_at", 0)
        timestamp = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)

        # Select best quality URL
        url = ""
        if is_video:
            video_versions = item.get("video_versions", [])
            if video_versions:
                url = video_versions[0].get("url", "")
        else:
            image_versions = item.get("image_versions2", {}).get("candidates", [])
            if image_versions:
                url = image_versions[0].get("url", "")

        return cls(
            media_id=media_id,
            is_video=is_video,
            url=url,
            timestamp=timestamp,
        )


@dataclass
class Highlight:
    """Instagram highlight reel.

    Represents a single highlight collection on a user's profile.
    Contains metadata and optionally the list of media items.
    """

    highlight_id: str
    title: str
    media_count: int
    items: list[HighlightItem] = field(default_factory=list)

    @property
    def slug(self) -> str:
        """Slugified title for use as directory name.

        Examples:
            "Sea 2025" -> "sea-2025"
            "Travel ✈️" -> "travel"
        """
        return slugify(self.title)

    @classmethod
    def from_tray_item(cls, data: dict[str, Any]) -> "Highlight":
        """Create Highlight from highlights tray API response.

        Args:
            data: Single item from the ``tray`` array in
                ``/api/v1/highlights/{user_id}/highlights_tray/``.

        Returns:
            Highlight with metadata (items are fetched separately).
        """
        # ID comes as "highlight:17895485201104054" — strip prefix
        raw_id = str(data.get("id", ""))
        highlight_id = raw_id.removeprefix("highlight:")

        return cls(
            highlight_id=highlight_id,
            title=data.get("title", ""),
            media_count=data.get("media_count", 0),
        )
