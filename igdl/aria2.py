"""Aria2c batch downloader for CDN media."""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

console = Console()


@dataclass
class DownloadItem:
    """Single item to download."""

    url: str
    filename: str
    shortcode: str


@dataclass
class Aria2Downloader:
    """Batch downloader using aria2c.

    Downloads in chunks to avoid URL expiration.
    Saves URL list to file for crash recovery.
    """

    output_dir: Path
    quiet: bool = False
    max_connections: int = 4
    max_concurrent: int = 16
    _items: list[DownloadItem] = field(default_factory=list)
    _input_file: Path | None = None

    @staticmethod
    def is_available() -> bool:
        """Check if aria2c is installed."""
        return shutil.which("aria2c") is not None

    def add(self, url: str, filename: str, shortcode: str) -> None:
        """Add item to download queue."""
        self._items.append(DownloadItem(url=url, filename=filename, shortcode=shortcode))

    def clear(self) -> None:
        """Clear download queue."""
        self._items.clear()

    def __len__(self) -> int:
        """Return number of items in queue."""
        return len(self._items)

    @property
    def shortcodes(self) -> set[str]:
        """Get unique shortcodes in queue."""
        return {item.shortcode for item in self._items}

    def _write_input_file(self, path: Path) -> None:
        """Write aria2c input file.

        Format:
            https://url1
              out=filename1.jpg
            https://url2
              out=filename2.mp4
        """
        lines: list[str] = []
        for item in self._items:
            lines.append(item.url)
            lines.append(f"  out={item.filename}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._input_file = path

    def _cleanup_input_file(self) -> None:
        """Remove input file after successful download."""
        if self._input_file and self._input_file.exists():
            self._input_file.unlink()
            self._input_file = None

    def _run_aria2c(self, input_file: Path) -> tuple[int, int]:
        """Run aria2c with input file.

        Returns:
            Tuple of (successful_count, failed_count)
        """
        cmd = [
            "aria2c",
            f"--input-file={input_file}",
            f"--dir={self.output_dir}",
            f"--max-connection-per-server={self.max_connections}",
            f"--max-concurrent-downloads={self.max_concurrent}",
            "--continue=true",
            "--auto-file-renaming=false",
            "--allow-overwrite=false",
            "--conditional-get=true",
            "--summary-interval=0",
        ]

        if self.quiet:
            cmd.append("--quiet=true")
        else:
            cmd.append("--console-log-level=warn")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return len(self._items), 0
            else:
                # Count existing files to determine success
                successful = sum(
                    1 for item in self._items if (self.output_dir / item.filename).exists()
                )
                return successful, len(self._items) - successful

        except FileNotFoundError:
            if not self.quiet:
                console.print("[red]aria2c not found[/red]")
            return 0, len(self._items)

    def flush(self, username: str) -> tuple[set[str], int]:
        """Download current queue and clear it.

        Args:
            username: Used for input file naming

        Returns:
            Tuple of (successful_shortcodes, failed_count)
        """
        if not self._items:
            return set(), 0

        input_file = self.output_dir / f".{username}.aria2.txt"
        self._write_input_file(input_file)

        if not self.quiet:
            console.print(f"[dim]Downloading batch: {len(self._items)} files...[/dim]")

        successful, failed = self._run_aria2c(input_file)

        # Determine which shortcodes succeeded
        successful_shortcodes: set[str] = set()
        for item in self._items:
            if (self.output_dir / item.filename).exists():
                successful_shortcodes.add(item.shortcode)

        if failed == 0:
            self._cleanup_input_file()
        elif not self.quiet:
            console.print(
                f"[yellow]{failed} downloads failed. Input file kept: {input_file}[/yellow]"
            )

        self.clear()
        return successful_shortcodes, failed

    def resume(self, username: str) -> tuple[int, int]:
        """Resume download from existing input file if present.

        Args:
            username: Used to find input file

        Returns:
            Tuple of (successful_count, failed_count)
        """
        input_file = self.output_dir / f".{username}.aria2.txt"

        if not input_file.exists():
            return 0, 0

        if not self.quiet:
            console.print("[cyan]Found incomplete download, resuming...[/cyan]")

        # Parse input file to reconstruct items
        self._items.clear()
        content = input_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("http"):
                url = line
                filename = ""
                # Look for out= on next line
                if i + 1 < len(lines) and "out=" in lines[i + 1]:
                    filename = lines[i + 1].strip().replace("out=", "")
                    i += 1
                # Extract shortcode from filename (before first . or _)
                shortcode = filename.split(".")[0].split("_")[0]
                self._items.append(DownloadItem(url=url, filename=filename, shortcode=shortcode))
            i += 1

        self._input_file = input_file
        successful, failed = self._run_aria2c(input_file)

        if failed == 0:
            self._cleanup_input_file()

        item_count = len(self._items)
        self.clear()
        return successful, item_count - successful
