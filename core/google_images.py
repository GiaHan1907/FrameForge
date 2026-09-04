"""
Google Images scraper — no API key required.

Scrapes Google Images search results using requests + BeautifulSoup.
Handles User-Agent rotation and rate limiting to avoid blocks.
"""

from __future__ import annotations

import io
import os
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
    license: str = ""
    author: str = ""
    page_url: str = ""


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

# Additional license-aware image sources (no API key required for the first two).
_WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_PEXELS_API = "https://api.pexels.com/v1/search"
_PIXABAY_API = "https://pixabay.com/api/"
_UNSPLASH_API = "https://api.unsplash.com/search/photos"

# env var names for optional API keys (Pexels / Pixabay / Unsplash / Openverse)
_API_KEY_ENV = {
    "pexels": "FRAMEFORGE_PEXELS_API_KEY",
    "pixabay": "FRAMEFORGE_PIXABAY_API_KEY",
    "unsplash": "FRAMEFORGE_UNSPLASH_ACCESS_KEY",
    "openverse": "FRAMEFORGE_OPENVERSE_TOKEN",
}

# display label used by the UI dropdown (kept here so core + ui agree)
IMAGE_SOURCES = [
    ("duckduckgo", "DuckDuckGo"),
    ("wikimedia", "Wikimedia Commons (CC, no key)"),
    ("openverse", "Openverse (CC)"),
    ("pexels", "Pexels"),
    ("pixabay", "Pixabay"),
    ("unsplash", "Unsplash"),
]
# sources that REQUIRE an api key to return anything
_KEY_REQUIRED_SOURCES = {"pexels", "pixabay", "unsplash"}

# aspect-ratio presets for optional center-crop on download
CROP_RATIOS = {
    "original": None,
    "1:1": (1, 1),
    "4:5": (4, 5),
    "3:2": (3, 2),
    "16:9": (16, 9),
    "9:16": (9, 16),
}


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

_DDG_URL = "https://duckduckgo.com/"
_DDG_IMAGES_URL = "https://duckduckgo.com/i.js"


def _ddg_search_images(query: str, num_results: int = 20, lang: str = "vi") -> list[dict]:
    """Search DuckDuckGo Images (no API key, no JavaScript required).

    Google Images now blocks plain-HTTP scrapers with a "please enable
    JavaScript" page, so the default engine is DuckDuckGo Images: its
    ``i.js`` endpoint returns JSON to a plain ``requests`` call.  Returns
    the same dict shape as ``_extract_image_urls_from_html`` so callers
    share one code path.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()

    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": f"{lang},en;q=0.5",
    })

    # Step 1: grab the vqd token from the image-search page.
    try:
        page = session.get(
            _DDG_URL,
            params={"q": query, "iax": "images", "ia": "images"},
            timeout=15,
        )
        page.raise_for_status()
        vqd_match = re.search(r"vqd=([0-9-]+)", page.text)
        if not vqd_match:
            return results
        vqd = vqd_match.group(1)
    except requests.RequestException:
        return results

    # Step 2: pull JSON results from i.js (Referer is required).
    params: dict[str, str] = {
        "q": query,
        "vqd": vqd,
        "o": "json",
        "p": "1",
        "f": ",,,",
    }
    if "-" in lang:
        params["l"] = lang
    headers = {
        "Referer": _DDG_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

    offset = 0
    while len(results) < num_results:
        params["s"] = str(offset)
        try:
            resp = session.get(_DDG_IMAGES_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            break

        items = data.get("results") or []
        if not items:
            break
        for item in items:
            url = item.get("image") or ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append({
                "url": url,
                "title": (item.get("title") or "").strip(),
                "thumbnail": item.get("thumbnail") or url,
                "source": item.get("url") or "",
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
            })

        next_url = data.get("next") or ""
        if "s=" not in next_url:
            break
        offset += 100
        time.sleep(random.uniform(0.8, 1.8))

    return results[:num_results]



def search_google_images(
    query: str,
    num_results: int = 20,
    lang: str = "vi",
    safe: str = "active",
) -> list[ImageResult]:
    """Search images by place name / address / coordinates (no API key).

    Google Images now blocks plain-HTTP scrapers (it returns a
    JavaScript-required page with no results), so the primary engine is
    DuckDuckGo Images, which serves JSON to a plain ``requests`` call.
    The Google HTML parser below is kept as a fallback for environments
    where Google still serves static results.
    """
    ddg_results = _ddg_search_images(query, num_results, lang)
    if ddg_results:
        return [
            ImageResult(
                url=r["url"],
                title=r["title"],
                source=r["source"],
                width=r["width"],
                height=r["height"],
                thumbnail=r["thumbnail"],
            )
            for r in ddg_results
        ]
    return _search_google_images_legacy(query, num_results, lang, safe)


def _search_google_images_legacy(
    query: str,
    num_results: int = 20,
    lang: str = "vi",
    safe: str = "active",
) -> list[ImageResult]:
    """Scrape Google Images for the given query (legacy fallback).

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
# Additional license-aware sources
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Remove HTML tags (Wikimedia returns artist/license as HTML)."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _dicts_to_results(dicts: list[dict]) -> list[ImageResult]:
    """Convert raw dict results (shared shape) to ImageResult objects."""
    return [
        ImageResult(
            url=r["url"],
            title=r.get("title", ""),
            source=r.get("source", ""),
            width=r.get("width") or 0,
            height=r.get("height") or 0,
            thumbnail=r.get("thumbnail") or r["url"],
            license=r.get("license", ""),
            author=r.get("author", ""),
            page_url=r.get("page_url", ""),
        )
        for r in dicts
    ]


def _wikimedia_search_images(query: str, num_results: int = 20) -> list[dict]:
    """Search Wikimedia Commons via the MediaWiki API (no API key)."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": str(min(num_results, 50)),
        "gsrnamespace": "6",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "400",
    }
    try:
        resp = requests.get(
            _WIKIMEDIA_API,
            params=params,
            headers={"User-Agent": "FrameForge/0.1 (image search by location)"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results: list[dict] = []
    seen: set[str] = set()
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        imageinfo = (page.get("imageinfo") or [{}])[0]
        url = imageinfo.get("url") or ""
        if not url or url in seen or not (imageinfo.get("mime") or "").startswith("image/"):
            continue
        seen.add(url)
        meta = imageinfo.get("extmetadata") or {}
        results.append({
            "url": url,
            "title": (page.get("title") or "").replace("File:", "", 1),
            "thumbnail": imageinfo.get("thumburl") or url,
            "source": "commons.wikimedia.org",
            "width": int(imageinfo.get("width") or 0),
            "height": int(imageinfo.get("height") or 0),
            "license": _strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "author": _strip_html((meta.get("Artist") or {}).get("value", "")),
            "page_url": "https://commons.wikimedia.org/wiki/" + (page.get("title") or "").replace(" ", "_"),
        })
        if len(results) >= num_results:
            break
    return results[:num_results]


def _openverse_search_images(query: str, num_results: int = 20, token: str = "") -> list[dict]:
    """Search Openverse (CC-licensed aggregate) - anonymous or with token."""
    headers = {"User-Agent": "FrameForge/0.1 (image search by location)"}
    if token:
        headers["Authorization"] = "Token " + token
    try:
        resp = requests.get(
            _OPENVERSE_API,
            params={"q": query, "per_page": min(num_results, 20)},
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results: list[dict] = []
    for item in (data.get("results") or []):
        url = item.get("url") or ""
        if not url:
            continue
        lic = item.get("license") or ""
        if lic and item.get("license_version"):
            lic = lic + " " + str(item["license_version"])
        results.append({
            "url": url,
            "title": (item.get("title") or "").strip(),
            "thumbnail": item.get("thumbnail") or url,
            "source": item.get("source") or "openverse.org",
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "license": lic,
            "author": (item.get("creator") or "").strip(),
            "page_url": item.get("foreign_landing_url") or "",
        })
        if len(results) >= num_results:
            break
    return results[:num_results]


def _pexels_search_images(query: str, num_results: int = 20, api_key: str = "") -> list[dict]:
    """Search Pexels (requires API key)."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            _PEXELS_API,
            params={"query": query, "per_page": min(num_results, 80)},
            headers={"Authorization": api_key, "User-Agent": "FrameForge/0.1"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    results: list[dict] = []
    for photo in (data.get("photos") or []):
        src = photo.get("src") or {}
        url = src.get("original") or src.get("large2x") or ""
        if not url:
            continue
        results.append({
            "url": url,
            "title": (photo.get("alt") or "").strip(),
            "thumbnail": src.get("medium") or src.get("small") or url,
            "source": "pexels.com",
            "width": int(photo.get("width") or 0),
            "height": int(photo.get("height") or 0),
            "license": "Pexels License (free to use)",
            "author": (photo.get("photographer") or "").strip(),
            "page_url": photo.get("url") or "",
        })
        if len(results) >= num_results:
            break
    return results[:num_results]


def _pixabay_search_images(query: str, num_results: int = 20, api_key: str = "") -> list[dict]:
    """Search Pixabay (requires API key)."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            _PIXABAY_API,
            params={"key": api_key, "q": query, "per_page": min(num_results, 200)},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    results: list[dict] = []
    for hit in (data.get("hits") or []):
        url = hit.get("largeImageURL") or hit.get("webformatURL") or ""
        if not url:
            continue
        results.append({
            "url": url,
            "title": (hit.get("tags") or "").strip(),
            "thumbnail": hit.get("webformatURL") or url,
            "source": "pixabay.com",
            "width": int(hit.get("imageWidth") or 0),
            "height": int(hit.get("imageHeight") or 0),
            "license": "Pixabay Content License",
            "author": (hit.get("user") or "").strip(),
            "page_url": hit.get("pageURL") or "",
        })
        if len(results) >= num_results:
            break
    return results[:num_results]


def _unsplash_search_images(query: str, num_results: int = 20, api_key: str = "") -> list[dict]:
    """Search Unsplash (requires access key)."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            _UNSPLASH_API,
            params={"query": query, "per_page": min(num_results, 30)},
            headers={"Authorization": "Client-ID " + api_key, "User-Agent": "FrameForge/0.1"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    results: list[dict] = []
    for photo in (data.get("results") or []):
        urls = photo.get("urls") or {}
        url = urls.get("full") or urls.get("raw") or urls.get("regular") or ""
        if not url:
            continue
        results.append({
            "url": url,
            "title": (photo.get("alt_description") or photo.get("description") or "").strip(),
            "thumbnail": urls.get("thumb") or urls.get("small") or url,
            "source": "unsplash.com",
            "width": int(photo.get("width") or 0),
            "height": int(photo.get("height") or 0),
            "license": "Unsplash License (free to use)",
            "author": ((photo.get("user") or {}).get("name") or "").strip(),
            "page_url": photo.get("links", {}).get("html") or "",
        })
        if len(results) >= num_results:
            break
    return results[:num_results]


def search_images(
    query: str,
    num_results: int = 20,
    source: str = "duckduckgo",
    api_keys: dict[str, str] | None = None,
) -> list[ImageResult]:
    """Search images from a selectable source (DuckDuckGo, Wikimedia, ...).

    Sources that need an API key read it from api_keys (keyed by source name)
    or from the FRAMEFORGE_*_API_KEY environment variables.
    """
    api_keys = api_keys or {}
    source = (source or "duckduckgo").strip().lower()

    def _key(name: str) -> str:
        return api_keys.get(name) or os.environ.get(_API_KEY_ENV.get(name, ""), "")

    if source == "wikimedia":
        return _dicts_to_results(_wikimedia_search_images(query, num_results))
    if source == "openverse":
        return _dicts_to_results(_openverse_search_images(query, num_results, _key("openverse")))
    if source == "pexels":
        return _dicts_to_results(_pexels_search_images(query, num_results, _key("pexels")))
    if source == "pixabay":
        return _dicts_to_results(_pixabay_search_images(query, num_results, _key("pixabay")))
    if source == "unsplash":
        return _dicts_to_results(_unsplash_search_images(query, num_results, _key("unsplash")))
    # default: DuckDuckGo
    return search_google_images(query, num_results)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _resolve_crop(ratio):
    """Map a CROP_RATIOS key ("1:1", "16:9", ...) or a raw tuple to a ratio."""
    if ratio is None:
        return None
    if isinstance(ratio, tuple):
        return ratio
    return CROP_RATIOS.get(str(ratio).strip().lower())


def _crop_image_file(path: Path, ratio: tuple) -> None:
    """Center-crop an image file in place using Pillow (bundled with the app).

    Pillow ships inside the packaged exe (requirements.txt), but the raw dev
    environment may lack it - import lazily and keep the original file if
    Pillow is unavailable or the image cannot be decoded. Never destroys the
    source file on failure.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:
        return
    try:
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(img)
            img.load()
            width, height = img.size
            target = ratio[0] / ratio[1]
            current = width / height
            if current > target:
                new_width = int(height * target)
                left = (width - new_width) // 2
                box = (left, 0, left + new_width, height)
            else:
                new_height = int(width / target)
                top = (height - new_height) // 2
                box = (0, top, width, top + new_height)
            cropped = img.crop(box)
        suffix = path.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            cropped.save(path, format="JPEG", quality=92)
        else:
            cropped.save(path)
    except Exception:
        pass


def download_image(
    url: str,
    save_dir: str | Path,
    filename: str | None = None,
    crop_ratio: str | tuple | None = None,
    max_retries: int = 2,
    retry_delays: tuple[float, float] = (2.0, 5.0),
) -> Path:
    """Download a single image from URL and save to disk.

    Transient failures (HTTP 429 rate limit, HTTP 5xx, network errors) are
    retried with backoff - Wikimedia/Openverse are frequently rate-limited.
    Permanent HTTP errors (403, 404, ...) fail immediately.

    Args:
        url: Image URL to download
        save_dir: Directory to save the image
        filename: Optional custom filename. Auto-generated if not provided.
        crop_ratio: Optional aspect ratio ("1:1", "16:9", (4, 5), ...) -
            center-crops the saved file with Pillow when given.
        max_retries: Extra attempts after the first one (default 2 = 3 tries).
        retry_delays: Seconds to sleep before each retry; honours the
            server's Retry-After header when it is a number.

    Returns:
        Path to the saved file

    Raises:
        requests.RequestException: If download fails after all retries
        OSError: If file write fails
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        parsed = urlparse(url)
        basename = Path(parsed.path).name
        if not basename or basename == "/":
            basename = f"image_{abs(hash(url)) % 100000}.jpg"
        if not any(basename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS):
            basename += ".jpg"
        filename = basename

    save_path = save_dir / filename

    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Referer": "https://www.google.com/",
    }

    resp = None
    retry_after = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30, stream=True)
            resp.raise_for_status()
            break  # success
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            retryable = code == 429 or code >= 500
            if resp is not None:
                resp.close()
            if not retryable or attempt >= max_retries:
                raise
            if exc.response is not None:
                retry_after = exc.response.headers.get("Retry-After")
        except requests.RequestException:
            if resp is not None:
                resp.close()
            if attempt >= max_retries:
                raise

        wait = retry_delays[attempt] if attempt < len(retry_delays) else retry_delays[-1]
        if retry_after and retry_after.isdigit():
            wait = max(wait, min(int(retry_after), 30))
        retry_after = None
        time.sleep(wait)

    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    resp.close()

    crop = _resolve_crop(crop_ratio)
    if crop is not None and save_path.exists() and save_path.stat().st_size > 0:
        _crop_image_file(save_path, crop)

    return save_path


def download_images(
    urls: list[str],
    save_dir: str | Path,
    delay: float = 0.5,
    crop_ratio: str | tuple | None = None,
) -> list[Path]:
    """Download multiple image URLs with rate limiting (retry-free, silent skip).

    Args:
        urls: List of image URLs
        save_dir: Directory to save images
        delay: Delay between downloads (seconds)
        crop_ratio: Optional aspect ratio applied to every saved file

    Returns:
        List of successfully downloaded file paths
    """
    paths: list[Path] = []
    for i, url in enumerate(urls):
        try:
            path = download_image(url, save_dir, crop_ratio=crop_ratio)
            paths.append(path)
        except Exception:
            pass  # silently skip failed downloads (legacy behaviour)
        if i < len(urls) - 1:
            time.sleep(delay)
    return paths


def download_results(
    results: list[ImageResult],
    save_dir: str | Path,
    crop_ratio: str | tuple | None = None,
    delay: float = 0.5,
) -> dict:
    """Download ImageResult objects and write a sources.tsv sidecar.

    Useful for license-aware sources (Wikimedia, Openverse, Pexels, Pixabay,
    Unsplash): each saved file is recorded with its license, author, page
    and original URL so attribution is easy. Files without metadata produce
    no sidecar.

    Returns a dict with keys: paths (saved files), failed (download errors),
    sources_file (Path or None), total (requested count).
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    failed: list[str] = []
    for i, result in enumerate(results):
        try:
            path = download_image(result.url, save_dir, crop_ratio=crop_ratio)
            saved_paths.append(path)
        except Exception as exc:
            failed.append(f"{result.url} ({exc})")
        if i < len(results) - 1:
            time.sleep(delay)

    has_meta = any(r.license or r.author or r.page_url for r in results)
    sources_file: Path | None = None
    if has_meta and saved_paths:
        sep = chr(9)
        header = sep.join(["file", "license", "author", "page_url", "source_url"])
        rows = [header]
        for result, path in zip(results, saved_paths):
            rows.append(sep.join([
                path.name,
                result.license,
                result.author,
                result.page_url,
                result.url,
            ]))
        sources_file = save_dir / "sources.tsv"
        sources_file.write_text(chr(10).join(rows) + chr(10), encoding="utf-8")

    return {
        "paths": saved_paths,
        "failed": failed,
        "sources_file": sources_file,
        "total": len(results),
    }
