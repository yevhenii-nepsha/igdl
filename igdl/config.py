"""Configuration management for igdl."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Use tomllib (Python 3.11+) or tomli as fallback
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[import-not-found]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


CONFIG_DIR = Path.home() / ".config" / "igdl"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Config:
    """Application configuration."""

    proxy: str | None = None
    proxy_file: Path | None = None
    cookies: Path | None = None
    output: Path | None = None
    auto_archive: bool = False
    archive_dir: Path | None = None

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from file."""
        if not CONFIG_FILE.exists():
            return cls()

        if tomllib is None:
            # No TOML parser available, return defaults
            return cls()

        try:
            with CONFIG_FILE.open("rb") as f:
                data = tomllib.load(f)
            return cls.from_dict(data)
        except Exception:
            # Invalid config, return defaults
            return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        config = cls()

        if "proxy" in data:
            config.proxy = data["proxy"]

        if "proxy_file" in data:
            config.proxy_file = Path(data["proxy_file"]).expanduser()

        if "cookies" in data:
            config.cookies = Path(data["cookies"]).expanduser()

        if "output" in data:
            config.output = Path(data["output"]).expanduser()

        if "auto_archive" in data:
            config.auto_archive = bool(data["auto_archive"])

        if "archive_dir" in data:
            config.archive_dir = Path(data["archive_dir"]).expanduser()

        return config

    @staticmethod
    def get_config_path() -> Path:
        """Get path to config file."""
        return CONFIG_FILE

    @staticmethod
    def create_default_config() -> None:
        """Create default config file with comments."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        default_config = """\
# igdl configuration file
# Location: ~/.config/igdl/config.toml

# Proxy URL for Instagram API requests
# proxy = "http://user:pass@host:port"

# Or use a file with multiple proxies for rotation
# proxy_file = "~/.config/igdl/proxies.txt"

# Cookies file for authenticated access (18+ profiles)
# cookies = "~/.config/igdl/cookies.txt"

# Default output directory
# output = "~/Downloads/instagram"

# Automatically create archive file per username
# When true: igdl user → creates user.txt archive
auto_archive = true

# Directory for archive files (default: output directory)
# archive_dir = "~/.config/igdl/archives"
"""
        CONFIG_FILE.write_text(default_config)
