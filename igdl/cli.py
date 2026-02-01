"""Command-line interface for igdl."""

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .archive import DownloadArchive
from .behavior import BehaviorSimulator
from .client import InstagramClient
from .config import Config
from .downloader import Downloader
from .exceptions import (
    AuthenticationError,
    IgdlError,
    PrivateProfileError,
    ProfileNotFoundError,
)
from .proxy import ProxyRotator
from .rate_limiter import RateLimiter

console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="igdl",
        description="Download photos and videos from public Instagram profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  igdl username                     Download all posts from profile
  igdl user1 user2 user3            Download from multiple profiles
  igdl username -n 50               Download only last 50 posts
  igdl username -o ./downloads      Save to custom directory

Downloaded files are named by post shortcode (e.g., ABC123def.jpg)
so you can access the original post at: instagram.com/p/ABC123def/
        """,
    )

    parser.add_argument(
        "usernames",
        nargs="*",
        metavar="USERNAME",
        help="Instagram username(s) to download",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path.cwd(),
        metavar="DIR",
        help="Output directory (default: current directory)",
    )

    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        metavar="COUNT",
        help="Maximum number of posts to download per profile",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip files that already exist (default: enabled)",
    )

    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="Re-download files even if they exist",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Minimal output (errors only)",
    )

    parser.add_argument(
        "-a",
        "--archive",
        type=Path,
        default=None,
        metavar="FILE",
        help="Archive file to track downloaded posts (like yt-dlp)",
    )

    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        metavar="URL",
        help="Proxy URL (http://user:pass@host:port)",
    )

    parser.add_argument(
        "--cookies",
        type=Path,
        default=None,
        metavar="FILE",
        help="Cookies file for authenticated access (Netscape format, e.g. from browser extension)",
    )

    parser.add_argument(
        "--highlights",
        action="store_true",
        help="Download highlight reels (requires --cookies)",
    )

    parser.add_argument(
        "--proxy-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="File with proxy list for rotation (one URL per line)",
    )

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create default config file at ~/.config/igdl/config.toml",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI.

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Handle --init-config
    if args.init_config:
        config_path = Config.get_config_path()
        if config_path.exists():
            console.print(f"[yellow]Config already exists: {config_path}[/yellow]")
        else:
            Config.create_default_config()
            console.print(f"[green]Created config: {config_path}[/green]")
        return 0

    # Require at least one username
    if not args.usernames:
        parser.error("the following arguments are required: USERNAME")

    # Load config (CLI args override config values)
    config = Config.load()

    # Resolve settings: CLI args > config > defaults
    proxy = args.proxy or config.proxy
    proxy_file = args.proxy_file or config.proxy_file
    cookies_file = args.cookies or config.cookies
    output_dir = args.output if args.output != Path.cwd() else (config.output or Path.cwd())
    auto_archive = config.auto_archive
    archive_dir = config.archive_dir or output_dir

    # Cookies mode: disable proxy, use conservative delays
    use_cookies = cookies_file is not None

    if use_cookies:
        if proxy or proxy_file:
            console.print(
                "[yellow]Warning: Proxy disabled when using cookies "
                "(to avoid account flagging)[/yellow]"
            )
        # No proxy with cookies
        proxy_rotator = ProxyRotator(quiet=args.quiet)
        has_proxy = False
    else:
        proxy_rotator = ProxyRotator(
            proxy=proxy,
            proxy_file=proxy_file,
            quiet=args.quiet,
        )
        has_proxy = proxy_rotator.enabled

    rate_limiter = RateLimiter(quiet=args.quiet, has_proxy=has_proxy)
    behavior = BehaviorSimulator(quiet=args.quiet, has_proxy=has_proxy)

    try:
        with InstagramClient(
            rate_limiter=rate_limiter,
            behavior=behavior,
            proxy_rotator=proxy_rotator,
            cookies_file=cookies_file,
        ) as client:
            # Download each profile
            has_errors = False
            for username in args.usernames:
                # Determine archive for this username
                if args.archive:
                    # Explicit archive file provided
                    archive = DownloadArchive(args.archive)
                elif auto_archive:
                    # Auto-archive: {username}.txt in archive_dir
                    archive_path = archive_dir / f"{username}.txt"
                    archive = DownloadArchive(archive_path)
                else:
                    # No archive
                    archive = DownloadArchive(None)

                if archive.enabled and not args.quiet:
                    console.print(
                        f"[dim]Using archive: {archive.path} ({len(archive)} entries)[/dim]"
                    )

                downloader = Downloader(
                    client=client,
                    output_dir=output_dir,
                    skip_existing=args.skip_existing,
                    quiet=args.quiet,
                    archive=archive,
                )

                try:
                    downloader.download_profile(username, limit=args.limit)
                except ProfileNotFoundError:
                    console.print(f"[red]Profile not found: {username}[/red]")
                    has_errors = True
                    continue
                except PrivateProfileError:
                    console.print(f"[yellow]Profile is private: {username}[/yellow]")
                    has_errors = True
                    continue
                except IgdlError as e:
                    console.print(f"[red]Error: {e}[/red]")
                    has_errors = True
                    continue

                # Download highlights if requested
                if args.highlights:
                    try:
                        downloader.download_highlights(username)
                    except AuthenticationError as e:
                        console.print(f"[red]{e}[/red]")
                        has_errors = True
                    except IgdlError as e:
                        console.print(f"[red]Highlights error: {e}[/red]")
                        has_errors = True

            return 1 if has_errors else 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
