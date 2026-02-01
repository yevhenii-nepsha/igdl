# igdl

Download photos and videos from Instagram profiles.

## Installation

```bash
pip install igdl
```

## Quick Start

```bash
# Download all posts from a profile
igdl username

# Download from multiple profiles
igdl user1 user2 user3
```

## Setup (Recommended)

Create a config file for easier usage:

```bash
igdl --init-config
```

Edit `~/.config/igdl/config.toml`:

```toml
# Your proxy (recommended to avoid blocks)
proxy = "http://user:pass@host:port"

# Or use multiple proxies for rotation
# proxy_file = "~/.config/igdl/proxies.txt"

# Cookies for 18+ profiles
# cookies = "~/.config/igdl/cookies.txt"

# Where to save downloads
output = "~/Downloads/instagram"

# Remember downloaded posts (skip on re-run)
auto_archive = true

# Where to store archive files (default: output directory)
# archive_dir = "~/.config/igdl/archives"
```

Now just run:

```bash
igdl username
```

## Common Tasks

### Download specific number of posts

```bash
igdl username -n 50
```

### Save to a specific folder

```bash
igdl username -o ./my-folder
```

### Use a proxy

```bash
igdl username --proxy "http://user:pass@host:port"
```

### Download highlights

Highlight reels require your Instagram cookies:

1. Install [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) browser extension
2. Log into Instagram
3. Export cookies to a file
4. Run:

```bash
igdl username --highlights --cookies cookies.txt
```

Each highlight is saved in its own directory named after the highlight title:

```
./username/highlights/
  sea-2025/
    username_3012345678901234567.jpg
    username_3012345678901234568.mp4
  travel/
    username_3012345678901234569.jpg
```

Emoji and unicode titles are preserved (`🔗`, `море`, etc.).

### Download posts and highlights together

```bash
igdl username -n 50 --highlights --cookies cookies.txt
```

### Download 18+ profile

Age-restricted profiles require your Instagram cookies (same setup as highlights):

```bash
igdl username --cookies cookies.txt
```

## Options

```
igdl username [OPTIONS]

  -o, --output DIR        Where to save files
  -n, --limit COUNT       Max posts to download
  -a, --archive FILE      Track downloaded posts
  -q, --quiet             Show errors only
  --proxy URL             Use proxy
  --proxy-file FILE       Use rotating proxies from file
  --cookies FILE          Use cookies for highlights and 18+ profiles
  --highlights            Download highlight reels (requires --cookies)
  --init-config           Create config file
  -V, --version           Show version
```

## Downloaded Files

Files are saved in a folder named after the username:

```
./username/
  username_ABC123.jpg        # Photo
  username_XYZ789.mp4        # Video
  username_DEF456_1.jpg      # Carousel photo 1
  username_DEF456_2.jpg      # Carousel photo 2
  highlights/                # Highlight reels (--highlights)
    sea-2025/
      username_3012345678901234567.jpg
    travel/
      username_3012345678901234569.mp4
```

Post filenames contain the shortcode. Find the original post at:
`instagram.com/p/ABC123/`

## Troubleshooting

### "Rate limited, waiting..."

Instagram temporarily blocked requests. Solutions:
- Wait (automatic retry)
- Use a proxy: `--proxy "http://..."`

### "Profile not found"

- Check the username spelling
- Profile may be 18+ restricted - use `--cookies`
- Try using a proxy

### "Profile is private"

Private profiles cannot be downloaded.

## Faster Downloads with aria2c

Install [aria2](https://aria2.github.io/) for faster parallel downloads:

```bash
# macOS
brew install aria2

# Ubuntu/Debian
apt install aria2
```

igdl automatically uses aria2c when available. No extra configuration needed.

## Limitations

- Public profiles only (or 18+ with cookies)
- No stories or reels (highlights are supported)
- No private profiles

---

## For Developers

### Installation from Source

```bash
git clone <repo>
cd igdl
pip install -e .
```

### Project Structure

```
igdl/
├── __init__.py      # Public exports, version
├── __main__.py      # python -m igdl entry
├── cli.py           # CLI argument parsing
├── client.py        # Instagram API client
├── models.py        # Data classes (Profile, Post, MediaItem, Highlight)
├── downloader.py    # Download orchestration
├── aria2.py         # Aria2c batch downloader
├── rate_limiter.py  # Sliding window rate limiting
├── archive.py       # Download tracking
├── proxy.py         # Proxy rotation
├── behavior.py      # Human-like behavior simulation
├── config.py        # Configuration management
└── exceptions.py    # Custom exceptions
```

### Python API

```python
from igdl import InstagramClient, Downloader, DownloadArchive, ProxyRotator
from pathlib import Path

# Basic usage
with InstagramClient() as client:
    downloader = Downloader(client, output_dir=Path("./downloads"))
    downloader.download_profile("username", limit=50)

# With archive and proxy
archive = DownloadArchive(Path("archive.txt"))
proxy = ProxyRotator(proxy="http://user:pass@host:port")

with InstagramClient(proxy_rotator=proxy) as client:
    downloader = Downloader(client, archive=archive)
    downloader.download_profile("username")

# With cookies (18+ profiles)
with InstagramClient(cookies_file=Path("cookies.txt")) as client:
    downloader = Downloader(client)
    downloader.download_profile("restricted_username")

# Download highlights (requires cookies)
with InstagramClient(cookies_file=Path("cookies.txt")) as client:
    downloader = Downloader(client, output_dir=Path("./downloads"))
    downloader.download_highlights("username")
```

### Rate Limiting

Built-in protection against Instagram blocks:

- Sliding window: 75 requests per 11 minutes
- Random delays between requests
- Human-like behavior simulation
- Auto-retry with exponential backoff

When using proxy, delays are minimal since requests come from different IPs.

### Aria2c Integration

If `aria2c` is installed, igdl automatically uses it for faster batch downloads:

- Downloads media in batches of 50 posts
- Parallel downloads (up to 16 concurrent)
- Automatic resume on interruption
- Falls back to requests if aria2c not available

Install aria2c:
```bash
# macOS
brew install aria2

# Ubuntu/Debian
apt install aria2

# Windows
choco install aria2
```

### Archive Format

Simple text file with one shortcode per line:

```
ABC123def
XYZ789ghi
```

### Proxy Rotation

Create `proxies.txt`:

```
http://user1:pass1@proxy1.example.com:8080
http://user2:pass2@proxy2.example.com:8080
# comments are ignored
```

Rotation triggers:
- Every 20 requests (preventive)
- On rate limit error (immediate)

Supported formats: `http://`, `https://`, `socks5://`

### Documentation

- `.claude/reference/architecture.md` - Architecture details
- `.claude/reference/api.md` - API reference

## License

MIT
