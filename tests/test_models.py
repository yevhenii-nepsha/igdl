"""Tests for igdl data models."""

from datetime import datetime, timezone

from igdl.models import Highlight, HighlightItem, slugify

# ------------------------------------------------------------------
# slugify
# ------------------------------------------------------------------


class TestSlugify:
    """Tests for the slugify helper function."""

    def test_basic_text(self) -> None:
        assert slugify("Sea 2025") == "sea-2025"

    def test_mixed_case(self) -> None:
        assert slugify("My Travel Blog") == "my-travel-blog"

    def test_accented_characters_preserved(self) -> None:
        assert slugify("Café & Bar") == "café-&-bar"
        assert slugify("Résumés") == "résumés"

    def test_emoji_preserved(self) -> None:
        assert slugify("Travel ✈️") == "travel-✈️"
        assert slugify("Sea 2025 🌊") == "sea-2025-🌊"

    def test_emoji_only(self) -> None:
        assert slugify("🔗") == "🔗"
        assert slugify("🌊✈️🏖️") == "🌊✈️🏖️"

    def test_special_characters(self) -> None:
        assert slugify("photo/video & more!") == "photo-video-&-more!"
        assert slugify("hello---world") == "hello-world"

    def test_slash_replaced(self) -> None:
        assert slugify("photo/video") == "photo-video"

    def test_leading_trailing_hyphens(self) -> None:
        assert slugify("  hello  ") == "hello"
        assert slugify("---hello---") == "hello"

    def test_leading_dot_stripped(self) -> None:
        assert slugify(".hidden") == "hidden"

    def test_empty_string_returns_untitled(self) -> None:
        assert slugify("") == "untitled"

    def test_unicode_normalization_nfc(self) -> None:
        # NFC keeps composed form (é stays as single char)
        assert slugify("café") == "café"

    def test_numbers_preserved(self) -> None:
        assert slugify("2024 Summer") == "2024-summer"

    def test_single_word(self) -> None:
        assert slugify("highlights") == "highlights"

    def test_cyrillic_preserved(self) -> None:
        assert slugify("Море") == "море"

    def test_mixed_cyrillic_latin(self) -> None:
        assert slugify("My Море Trip") == "my-море-trip"

    def test_control_chars_removed(self) -> None:
        assert slugify("hello\x00world") == "hello-world"
        assert slugify("test\x1fvalue") == "test-value"

    def test_whitespace_collapsed(self) -> None:
        assert slugify("hello   world") == "hello-world"
        assert slugify("a\t\nb") == "a-b"


# ------------------------------------------------------------------
# HighlightItem.from_rest_item
# ------------------------------------------------------------------


class TestHighlightItem:
    """Tests for HighlightItem parsing from REST API data."""

    def test_photo_item(self) -> None:
        data = {
            "pk": "3012345678901234567",
            "media_type": 1,
            "taken_at": 1700000000,
            "image_versions2": {
                "candidates": [
                    {"width": 1080, "height": 1920, "url": "https://cdn/photo_hq.jpg"},
                    {"width": 640, "height": 1138, "url": "https://cdn/photo_lq.jpg"},
                ],
            },
        }
        item = HighlightItem.from_rest_item(data)

        assert item.media_id == "3012345678901234567"
        assert item.is_video is False
        assert item.url == "https://cdn/photo_hq.jpg"
        assert item.extension == "jpg"
        assert item.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

    def test_video_item(self) -> None:
        data = {
            "pk": "3012345678901234568",
            "media_type": 2,
            "taken_at": 1700000001,
            "video_versions": [
                {"width": 720, "height": 1280, "url": "https://cdn/video_hq.mp4"},
                {"width": 480, "height": 852, "url": "https://cdn/video_lq.mp4"},
            ],
            "image_versions2": {
                "candidates": [
                    {"width": 1080, "height": 1920, "url": "https://cdn/thumb.jpg"},
                ],
            },
        }
        item = HighlightItem.from_rest_item(data)

        assert item.media_id == "3012345678901234568"
        assert item.is_video is True
        assert item.url == "https://cdn/video_hq.mp4"
        assert item.extension == "mp4"

    def test_missing_versions_returns_empty_url(self) -> None:
        data = {
            "pk": "123",
            "media_type": 1,
            "taken_at": 0,
        }
        item = HighlightItem.from_rest_item(data)

        assert item.url == ""

    def test_missing_pk_returns_empty_string(self) -> None:
        data = {
            "media_type": 1,
            "taken_at": 0,
            "image_versions2": {"candidates": [{"url": "https://cdn/x.jpg"}]},
        }
        item = HighlightItem.from_rest_item(data)

        assert item.media_id == ""


# ------------------------------------------------------------------
# Highlight.from_tray_item
# ------------------------------------------------------------------


class TestHighlight:
    """Tests for Highlight parsing and slug generation."""

    def test_from_tray_item(self) -> None:
        data = {
            "id": "highlight:17895485201104054",
            "title": "Sea 2025",
            "media_count": 5,
        }
        hl = Highlight.from_tray_item(data)

        assert hl.highlight_id == "17895485201104054"
        assert hl.title == "Sea 2025"
        assert hl.media_count == 5
        assert hl.items == []

    def test_from_tray_item_no_prefix(self) -> None:
        """Handle IDs that don't have the highlight: prefix."""
        data = {
            "id": "12345",
            "title": "Test",
            "media_count": 1,
        }
        hl = Highlight.from_tray_item(data)

        assert hl.highlight_id == "12345"

    def test_slug_property(self) -> None:
        hl = Highlight(highlight_id="1", title="My Summer Trip", media_count=3)
        assert hl.slug == "my-summer-trip"

    def test_slug_empty_title(self) -> None:
        hl = Highlight(highlight_id="1", title="", media_count=0)
        assert hl.slug == "untitled"

    def test_from_tray_item_missing_fields(self) -> None:
        data: dict[str, object] = {}
        hl = Highlight.from_tray_item(data)  # type: ignore[arg-type]

        assert hl.highlight_id == ""
        assert hl.title == ""
        assert hl.media_count == 0


# ------------------------------------------------------------------
# Downloader._deduplicate_slug
# ------------------------------------------------------------------


class TestDeduplicateSlug:
    """Tests for slug deduplication logic."""

    def test_no_collision(self) -> None:
        from igdl.downloader import Downloader

        used: set[str] = set()
        result = Downloader._deduplicate_slug("sea-2025", used)

        assert result == "sea-2025"
        assert "sea-2025" in used

    def test_single_collision(self) -> None:
        from igdl.downloader import Downloader

        used: set[str] = {"sea-2025"}
        result = Downloader._deduplicate_slug("sea-2025", used)

        assert result == "sea-2025_2"
        assert "sea-2025_2" in used

    def test_multiple_collisions(self) -> None:
        from igdl.downloader import Downloader

        used: set[str] = {"travel", "travel_2", "travel_3"}
        result = Downloader._deduplicate_slug("travel", used)

        assert result == "travel_4"

    def test_sequential_dedup(self) -> None:
        from igdl.downloader import Downloader

        used: set[str] = set()
        r1 = Downloader._deduplicate_slug("test", used)
        r2 = Downloader._deduplicate_slug("test", used)
        r3 = Downloader._deduplicate_slug("test", used)

        assert r1 == "test"
        assert r2 == "test_2"
        assert r3 == "test_3"
