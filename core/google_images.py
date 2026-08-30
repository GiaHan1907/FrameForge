"""
Google Images scraper — no API key required.

Scrapes Google Images search results using requests + BeautifulSoup.
Handles User-Agent rotation and rate limiting to avoid blocks.
"""

from __future__ import annotations

import re
import time
import random
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    """Single image result from Google Images."""

    url: str
    title: str = ""
    source: str = ""
    width: int = 0
    height: int = 0
    thumbnail: str = ""
    file_size: str = ""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

_GOOGLE_IMAGES_URL = "https://www.google.com/search"
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def _extract_image_urls_from_html(html: str) -> list[dict]:
    """Parse Google Images HTML and extract image URLs + metadata.

    Google embeds image data in several places:
    1. ``<img>`` tags with ``data-src`` or ``src`` attributes
    2. JSON-like data in ``<script>`` tags (AF_initDataCallback)
    3. ``<a>`` tags linking to full-size images

    Returns a list of dicts with keys: url, title, thumbnail, source.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen_urls: set[str] = set()

    # --- Strategy 1: Extract from <img> inside search result containers ---
    for img in soup.find_all("img"):
        # Skip tiny icons / logos
        width = int(img.get("width", "0") or "0")
        height = int(img.get("height", "0") or "0")
        if 0 < width < 50 or 0 < height < 50:
            continue

        # Get the image URL (prefer data-src over src for lazy-loaded images)
        src = img.get("data-src") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue

        # Google search results use encrypted URLs — keep them as-is
        # because they redirect to the actual image
        if not src.startswith("http"):
            continue

        # Extract title from alt text
        title = img.get("alt", "").strip()

        # Try to find the parent link for source info
        source = ""
        parent_a = img.find_parent("a")
        if parent_a:
            href = parent_a.get("href", "")
            # Google wraps actual URLs in redirect links
            if "/url?q=" in href:
                match = re.search(r"/url\?q=([^&]+)", href)
                if match:
                    source = match.group(1)

        if src not in seen_urls:
            seen_urls.add(src)
            results.append({
                "url": src,
                "title": title,
                "thumbnail": src,
                "source": source,
                "width": width,
                "height": height,
            })

    # --- Strategy 2: Extract full-size URLs from script tags ---
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for image URLs in script data
        urls_found = re.findall(
            r'"(https?://[^"]+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^"]*)?)"',
            text,
            re.IGNORECASE,
        )
        for url in urls_found:
            # Skip Google's own URLs
            if "google.com" in url or "gstatic.com" in url:
                continue
            if url not in seen_urls:
                seen_urls.add(url)
                results.append({
                    "url": url,
                    "title": "",
                    "thumbnail": url,
                    "source": url,
                    "width": 0,
                    "height": 0,
                })

    return results


def search_google_images(
    query: str,
    num_results: int = 20,
    lang: str = "vi",
    safe: str = "active",
) -> list[ImageResult]:
    """Scrape Google Images for the given query.

    Args:
        query: Search query (place name, address, coordinates, etc.)
        num_results: Target number of results (may return fewer)
        lang: Search language code
        safe: Safe search setting ("active", "moderate", "off")

    Returns:
        List of ImageResult objects
    """
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    # Google shows ~10 results per page, scroll for more
    pages = (num_results + 9) // 10

    for page in range(pages):
        start = page * 10
        params = {
            "q": query,
            "tbm": "isch",  # Image search
            "start": start,
            "hl": lang,
            "safe": safe,
        }

        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": f"{lang},en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            resp = requests.get(
                _GOOGLE_IMAGES_URL,
                params=params,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException:
            # If a page fails, continue with what we have
            break

        page_results = _extract_image_urls_from_html(resp.text)

        for r in page_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)

        if len(all_results) >= num_results:
            break

        # Rate limiting — random delay between pages
        if page < pages - 1:
            time.sleep(random.uniform(1.0, 2.5))

    # Convert to ImageResult objects
    return [
        ImageResult(
            url=r["url"],
            title=r["title"],
            source=r["source"],
            width=r["width"],
            height=r["height"],
            thumbnail=r["thumbnail"],
        )
        for r in all_results[:num_results]
    ]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_image(
    url: str,
    save_dir: str | Path,
    filename: str | None = None,
) -> Path:
    """Download a single image from URL and save to disk.

    Args:
        url: Image URL to download
        save_dir: Directory to save the image
        filename: Optional custom filename. Auto-generated if not provided.

    Returns:
        Path to the saved file

    Raises:
        requests.RequestException: If download fails
        OSError: If file write fails
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        # Generate filename from URL
        parsed = urlparse(url)
        basename = Path(parsed.path).name
        if not basename or basename == "/":
            basename = f"image_{abs(hash(url)) % 100000}.jpg"
        # Ensure valid extension
        if not any(basename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS):
            basename += ".jpg"
        filename = basename

    save_path = save_dir / filename

    # Download with retry
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Referer": "https://www.google.com/",
    }

    resp = requests.get(url, headers=headers, timeout=30, stream=True)
    resp.raise_for_status()

    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return save_path


def download_images(
    urls: list[str],
    save_dir: str | Path,
    delay: float = 0.5,
) -> list[Path]:
    """Download multiple images with rate limiting.

    Args:
        urls: List of image URLs
        save_dir: Directory to save images
        delay: Delay between downloads (seconds)

    Returns:
        List of successfully downloaded file paths
    """
    paths: list[Path] = []
    for i, url in enumerate(urls):
        try:
            path = download_image(url, save_dir)
            paths.append(path)
        except Exception:
            # Silently skip failed downloads
            pass

        if i < len(urls) - 1:
            time.sleep(delay)

    return paths
