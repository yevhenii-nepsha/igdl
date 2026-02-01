"""Download orchestration for Instagram media."""

from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from .archive import DownloadArchive
from .aria2 import Aria2Downloader
from .client import InstagramClient
from .exceptions import DownloadError, IgdlError
from .models import Highlight, HighlightItem, MediaItem, Post

console = Console()

# Number of posts to collect before flushing to aria2c
ARIA2_BATCH_SIZE = 50


class Downloader:
    """High-level download orchestration.

    Handles downloading posts from profiles with progress tracking
    and file management. Uses aria2c for batch downloads if available.
    """

    def __init__(
        self,
        client: InstagramClient,
        output_dir: Path | None = None,
        skip_existing: bool = True,
        quiet: bool = False,
        archive: DownloadArchive | None = None,
    ) -> None:
        self.client = client
        self.output_dir = output_dir or Path.cwd()
        self.skip_existing = skip_existing
        self.quiet = quiet
        self.archive = archive or DownloadArchive(None)
        self._use_aria2 = Aria2Downloader.is_available()
        self._current_username: str = ""

        if self._use_aria2 and not quiet:
            console.print("[dim]Using aria2c for downloads[/dim]")

    def _get_filename(self, username: str, post: Post, media: MediaItem) -> str:
        """Generate filename for media item.

        Format: {username}_{shortcode}.{ext} or {username}_{shortcode}_{index}.{ext} for carousel
        """
        if media.index is not None:
            return f"{username}_{post.shortcode}_{media.index}.{media.extension}"
        return f"{username}_{post.shortcode}.{media.extension}"

    def _ensure_dir(self, path: Path) -> None:
        """Create directory if it doesn't exist."""
        path.mkdir(parents=True, exist_ok=True)

    def download_media_item(
        self,
        post: Post,
        media: MediaItem,
        target_dir: Path,
    ) -> Path | None:
        """Download a single media item.

        Returns:
            Path to downloaded file, or None if skipped
        """
        filename = self._get_filename(self._current_username, post, media)
        filepath = target_dir / filename

        if self.skip_existing and filepath.exists():
            return None

        self.client.download_media(media.url, filepath)
        return filepath

    def download_post(self, post: Post, target_dir: Path) -> list[Path]:
        """Download all media from a post.

        Returns:
            List of paths to downloaded files
        """
        self._ensure_dir(target_dir)
        downloaded: list[Path] = []
        media_items = post.get_media_items()

        for idx, media in enumerate(media_items):
            # Simulate carousel swiping delay (except first item)
            if idx > 0:
                self.client.behavior.carousel_delay()

            try:
                path = self.download_media_item(post, media, target_dir)
                if path:
                    downloaded.append(path)
            except DownloadError as e:
                if not self.quiet:
                    console.print(f"[red]Failed to download {post.shortcode}: {e}[/red]")

        return downloaded

    def _collect_post_media(
        self,
        post: Post,
        target_dir: Path,
        aria2: Aria2Downloader,
    ) -> int:
        """Collect media items from post for aria2c batch download.

        Returns:
            Number of items added to queue
        """
        added = 0
        media_items = post.get_media_items()

        for media in media_items:
            filename = self._get_filename(self._current_username, post, media)
            filepath = target_dir / filename

            if self.skip_existing and filepath.exists():
                continue

            aria2.add(url=media.url, filename=filename, shortcode=post.shortcode)
            added += 1

        return added

    def download_profile(
        self,
        username: str,
        limit: int | None = None,
        output_subdir: str | None = None,
    ) -> tuple[int, int]:
        """Download all posts from a profile.

        Args:
            username: Instagram username
            limit: Maximum number of posts to download
            output_subdir: Subdirectory name (defaults to username)

        Returns:
            Tuple of (downloaded_count, skipped_count)
        """
        # Get profile info
        if not self.quiet:
            console.print(f"[cyan]Fetching profile: {username}[/cyan]")

        profile = self.client.get_profile(username)

        if not self.quiet:
            console.print(f"[green]Found {profile.post_count} posts[/green]")

        # Prepare output directory
        subdir = output_subdir or username
        target_dir = self.output_dir / subdir
        self._ensure_dir(target_dir)
        self._current_username = username

        # Choose download method
        if self._use_aria2:
            return self._download_profile_aria2(
                username, profile.user_id, target_dir, limit, profile.post_count
            )
        else:
            return self._download_profile_requests(
                username, profile.user_id, target_dir, limit, profile.post_count
            )

    def _download_profile_requests(
        self,
        username: str,
        user_id: str,
        target_dir: Path,
        limit: int | None,
        post_count: int,
    ) -> tuple[int, int]:
        """Download profile using requests (fallback method)."""
        downloaded_count = 0
        skipped_count = 0
        total = min(limit, post_count) if limit else post_count

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
            disable=self.quiet,
        ) as progress:
            task = progress.add_task(f"[cyan]Downloading {username}", total=total)

            for post in self.client.iter_posts(user_id, limit=limit):
                # Skip if already in archive
                if post.shortcode in self.archive:
                    if not self.quiet:
                        console.print(f"[dim]Skipping {post.shortcode} (archived)[/dim]")
                    skipped_count += 1
                    progress.advance(task)
                    continue

                paths = self.download_post(post, target_dir)

                if paths:
                    downloaded_count += len(paths)
                    self.archive.add(post.shortcode)
                else:
                    skipped_count += 1

                progress.advance(task)
                self.client.behavior.record_post_processed()

        if not self.quiet:
            console.print(
                f"[green]Done![/green] Downloaded: {downloaded_count}, Skipped: {skipped_count}"
            )

        return downloaded_count, skipped_count

    def _download_profile_aria2(
        self,
        username: str,
        user_id: str,
        target_dir: Path,
        limit: int | None,
        post_count: int,
    ) -> tuple[int, int]:
        """Download profile using aria2c batch downloads."""
        aria2 = Aria2Downloader(output_dir=target_dir, quiet=self.quiet)

        # Try to resume incomplete download first
        resumed, _ = aria2.resume(username)
        if resumed > 0 and not self.quiet:
            console.print(f"[green]Resumed {resumed} files[/green]")

        downloaded_count = 0
        skipped_count = 0
        posts_in_batch: list[Post] = []
        total = min(limit, post_count) if limit else post_count

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
            disable=self.quiet,
        ) as progress:
            task = progress.add_task(f"[cyan]Fetching {username}", total=total)

            for post in self.client.iter_posts(user_id, limit=limit):
                # Skip if already in archive
                if post.shortcode in self.archive:
                    skipped_count += 1
                    progress.advance(task)
                    continue

                # Collect media for aria2c
                added = self._collect_post_media(post, target_dir, aria2)
                if added > 0:
                    posts_in_batch.append(post)
                else:
                    # All media already exists
                    skipped_count += 1

                progress.advance(task)
                self.client.behavior.record_post_processed()

                # Flush batch when reaching size limit
                if len(posts_in_batch) >= ARIA2_BATCH_SIZE:
                    successful_shortcodes, failed = aria2.flush(username)

                    # Update archive with successful downloads
                    for shortcode in successful_shortcodes:
                        self.archive.add(shortcode)
                        downloaded_count += 1

                    posts_in_batch.clear()

        # Flush remaining items
        if len(aria2) > 0:
            successful_shortcodes, failed = aria2.flush(username)

            for shortcode in successful_shortcodes:
                self.archive.add(shortcode)
                downloaded_count += 1

        if not self.quiet:
            console.print(
                f"[green]Done![/green] Downloaded: {downloaded_count}, Skipped: {skipped_count}"
            )

        return downloaded_count, skipped_count

    def download_profiles(
        self,
        usernames: list[str],
        limit: int | None = None,
    ) -> dict[str, tuple[int, int]]:
        """Download posts from multiple profiles.

        Returns:
            Dict mapping username to (downloaded, skipped) counts
        """
        results: dict[str, tuple[int, int]] = {}

        for username in usernames:
            try:
                results[username] = self.download_profile(username, limit=limit)
            except IgdlError as e:
                if not self.quiet:
                    console.print(f"[red]Error with {username}: {e}[/red]")
                results[username] = (0, 0)

        return results

    # ------------------------------------------------------------------
    # Highlights
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate_slug(slug: str, used: set[str]) -> str:
        """Return a unique slug, appending _2, _3, ... on collision.

        Args:
            slug: Base slug to deduplicate.
            used: Set of already-used slugs (mutated in-place).

        Returns:
            Unique slug that has been added to *used*.
        """
        candidate = slug
        counter = 2
        while candidate in used:
            candidate = f"{slug}_{counter}"
            counter += 1
        used.add(candidate)
        return candidate

    def _get_highlight_filename(
        self,
        username: str,
        item: HighlightItem,
    ) -> str:
        """Generate filename for a highlight item.

        Format: {username}_{media_id}.{ext}
        """
        return f"{username}_{item.media_id}.{item.extension}"

    def download_highlights(
        self,
        username: str,
    ) -> tuple[int, int]:
        """Download all highlight reels from a profile.

        Creates a directory structure::

            {output_dir}/{username}/highlights/{slug}/
                {username}_{media_id}.jpg
                {username}_{media_id}.mp4

        Duplicate highlight titles get a numeric suffix (_2, _3, ...).
        Requires cookies for API access.

        Args:
            username: Instagram username.

        Returns:
            Tuple of (downloaded_count, skipped_count).
        """
        # Fetch profile
        if not self.quiet:
            console.print(f"[cyan]Fetching profile: {username}[/cyan]")

        profile = self.client.get_profile(username)
        self._current_username = username

        # Simulate scrolling to highlights row
        self.client.behavior.highlight_tray_delay()

        # Fetch highlights list
        if not self.quiet:
            console.print("[cyan]Fetching highlights...[/cyan]")

        highlights = self.client.get_highlights(profile.user_id)

        if not highlights:
            if not self.quiet:
                console.print("[yellow]No highlights found[/yellow]")
            return 0, 0

        if not self.quiet:
            console.print(f"[green]Found {len(highlights)} highlights[/green]")

        # Choose download method
        if self._use_aria2:
            return self._download_highlights_aria2(username, highlights)
        return self._download_highlights_requests(username, highlights)

    def _download_highlights_requests(
        self,
        username: str,
        highlights: list[Highlight],
    ) -> tuple[int, int]:
        """Download highlights using requests (fallback method)."""
        downloaded_count = 0
        skipped_count = 0
        used_slugs: set[str] = set()

        total_items = sum(h.media_count for h in highlights)

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
            disable=self.quiet,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Highlights {username}",
                total=total_items,
            )

            for highlight in highlights:
                slug = self._deduplicate_slug(highlight.slug, used_slugs)
                target_dir = self.output_dir / username / "highlights" / slug
                self._ensure_dir(target_dir)

                if not self.quiet:
                    console.print(
                        f"[dim]Highlight: {highlight.title!r} -> {slug}/ "
                        f"({highlight.media_count} items)[/dim]"
                    )

                # Simulate tapping on a highlight
                self.client.behavior.highlight_switch_delay()

                # Fetch items for this highlight
                items = self.client.get_highlight_items(highlight.highlight_id)

                for item in items:
                    # Skip if in archive
                    if item.media_id in self.archive:
                        skipped_count += 1
                        progress.advance(task)
                        continue

                    filename = self._get_highlight_filename(username, item)
                    filepath = target_dir / filename

                    if self.skip_existing and filepath.exists():
                        skipped_count += 1
                        progress.advance(task)
                        continue

                    try:
                        self.client.download_media(item.url, filepath)
                        downloaded_count += 1
                        self.archive.add(item.media_id)
                    except DownloadError as e:
                        if not self.quiet:
                            console.print(f"[red]Failed to download {item.media_id}: {e}[/red]")

                    progress.advance(task)

        if not self.quiet:
            console.print(
                f"[green]Done![/green] Downloaded: {downloaded_count}, Skipped: {skipped_count}"
            )

        return downloaded_count, skipped_count

    def _download_highlights_aria2(
        self,
        username: str,
        highlights: list[Highlight],
    ) -> tuple[int, int]:
        """Download highlights using aria2c batch downloads."""
        downloaded_count = 0
        skipped_count = 0
        used_slugs: set[str] = set()

        # Map media_id -> target_dir so aria2 knows where to save each file
        # aria2 downloads all to one dir, so we use a staging approach:
        # collect all items, flush per highlight to its own target_dir.

        total_items = sum(h.media_count for h in highlights)

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
            disable=self.quiet,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Highlights {username}",
                total=total_items,
            )

            for highlight in highlights:
                slug = self._deduplicate_slug(highlight.slug, used_slugs)
                target_dir = self.output_dir / username / "highlights" / slug
                self._ensure_dir(target_dir)

                if not self.quiet:
                    console.print(
                        f"[dim]Highlight: {highlight.title!r} -> {slug}/ "
                        f"({highlight.media_count} items)[/dim]"
                    )

                # Simulate tapping on a highlight
                self.client.behavior.highlight_switch_delay()

                # Fetch items for this highlight
                items = self.client.get_highlight_items(highlight.highlight_id)

                aria2 = Aria2Downloader(output_dir=target_dir, quiet=self.quiet)

                for item in items:
                    if item.media_id in self.archive:
                        skipped_count += 1
                        progress.advance(task)
                        continue

                    filename = self._get_highlight_filename(username, item)
                    filepath = target_dir / filename

                    if self.skip_existing and filepath.exists():
                        skipped_count += 1
                        progress.advance(task)
                        continue

                    aria2.add(
                        url=item.url,
                        filename=filename,
                        shortcode=item.media_id,
                    )
                    progress.advance(task)

                # Flush this highlight's batch
                if len(aria2) > 0:
                    successful_ids, failed = aria2.flush(f"{username}_hl_{slug}")
                    for media_id in successful_ids:
                        self.archive.add(media_id)
                        downloaded_count += 1

        if not self.quiet:
            console.print(
                f"[green]Done![/green] Downloaded: {downloaded_count}, Skipped: {skipped_count}"
            )

        return downloaded_count, skipped_count
