"""Archive file for tracking downloaded posts.

Similar to yt-dlp's --download-archive feature.
Format: one shortcode per line.
"""

from pathlib import Path


class DownloadArchive:
    """Tracks downloaded posts in a text file.

    File format: one shortcode per line.
    Example:
        ABC123def
        XYZ789ghi
        ...
    """

    def __init__(self, path: Path | str | None) -> None:
        """Initialize archive.

        Args:
            path: Path to archive file. If None, archive is disabled.
        """
        self._path = Path(path) if path else None
        self._downloaded: set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load existing archive from file."""
        if not self._path or not self._path.exists():
            return

        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                shortcode = line.strip()
                if shortcode:
                    self._downloaded.add(shortcode)

    def contains(self, shortcode: str) -> bool:
        """Check if shortcode is in archive."""
        return shortcode in self._downloaded

    def add(self, shortcode: str) -> None:
        """Add shortcode to archive.

        Writes immediately to file for crash-safety.
        """
        if shortcode in self._downloaded:
            return

        self._downloaded.add(shortcode)

        if self._path:
            # Ensure parent directory exists
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Append to file immediately (crash-safe)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(f"{shortcode}\n")

    def __len__(self) -> int:
        """Return number of archived shortcodes."""
        return len(self._downloaded)

    def __bool__(self) -> bool:
        """Archive is always truthy when it exists."""
        return True

    def __contains__(self, shortcode: str) -> bool:
        """Check if shortcode is in archive."""
        return self.contains(shortcode)

    @property
    def enabled(self) -> bool:
        """Check if archive is enabled."""
        return self._path is not None

    @property
    def path(self) -> Path | None:
        """Get archive file path."""
        return self._path
