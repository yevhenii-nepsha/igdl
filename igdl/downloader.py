"""Download orchestration for Instagram media."""

from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from .archive import DownloadArchive
from .aria2 import Aria2Downloader
from .client import InstagramClient
from .exceptions import DownloadError, IgdlError
from .models import MediaItem, Post

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
