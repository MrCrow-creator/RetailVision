import io
import threading
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .config import IMAGE_HOSTS, Settings, safe_url
from .models import Product
from .network import FetchError, RateLimiter, fetch_bytes
from .storage import atomic_bytes, atomic_json, digest, event, now, read_json


def verify_image(content: bytes) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("unsupported_image_format")
            if image.width * image.height > 20_000_000 or min(image.size) < 32:
                raise ValueError("invalid_image_dimensions")
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[image.format]
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()  # Verify decoded pixels too; truncated files sometimes pass verify().
    return extension


class ImageDownloader:
    def __init__(self, settings: Settings, client: httpx.Client, retry_failed: bool = False):
        self.settings = settings
        self.client = client
        self.retry_failed = retry_failed
        self.directory = settings.data_dir / "raw" / "openfoodfacts" / "images"
        self.limiter = RateLimiter(settings.image_requests_per_second)
        self.off_limiter = RateLimiter(1)
        self.off_lock = threading.Lock()

    def one(self, product: Product) -> tuple[dict, bool]:
        state_path = self.directory / f"{product.product_id}.json"
        if state_path.exists():
            state = read_json(state_path)
            if state["url"] == product.image_url:
                if state["status"] == "downloaded":
                    path = self.directory / state["filename"]
                    if (
                        path.parent == self.directory
                        and path.exists()
                        and digest(path) == state["sha256"]
                    ):
                        return state, True
                elif state["status"] == "failed" and not self.retry_failed:
                    return state, True
        state = {"url": product.image_url, "checked_at": now(), "status": "failed"}
        if not safe_url(product.image_url, IMAGE_HOSTS):
            state["error"] = "invalid_image_url"
            atomic_json(state_path, state)
            return state, False
        try:
            if urlsplit(product.image_url).hostname == "images.openfoodfacts.org":
                # The primary OFF image server explicitly asks clients to download serially.
                with self.off_lock:
                    content, headers, resolved, _ = self.fetch(product.image_url, self.off_limiter)
            else:
                content, headers, resolved, _ = self.fetch(product.image_url, self.limiter)
            mime = headers.get("content-type", "").split(";")[0].lower()
            if mime not in {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}:
                raise ValueError("unsupported_content_type")
            extension = verify_image(content)
            path = self.directory / f"{product.product_id}{extension}"
            atomic_bytes(path, content)
            state.update(
                status="downloaded",
                filename=path.name,
                sha256=digest(path),
                resolved_url=resolved,
                size_bytes=len(content),
            )
        except FetchError as error:
            state["error"] = str(error)
        except (
            ValueError,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            state["error"] = "invalid_image_content"
        atomic_json(state_path, state)
        return state, False

    def fetch(self, url: str, limiter: RateLimiter):
        return fetch_bytes(
            self.client,
            url,
            limit=self.settings.max_image_bytes,
            retries=self.settings.max_retries,
            limiter=limiter,
            allowed_url=lambda target: safe_url(target, IMAGE_HOSTS),
        )

    def run(self, products: list[Product]) -> dict:
        stats = {"downloaded_this_run": 0, "failed_this_run": 0, "cached_images": 0}
        failures = Counter()
        candidates = []
        for product in products:
            product.image_path = ""
            product.image_status = "not_checked" if product.image_url else "missing"
            if self.settings.download_images and product.image_url:
                candidates.append(product)
            product.data_quality_score = product.score(False)
        if not candidates:
            return stats
        with ThreadPoolExecutor(max_workers=self.settings.image_workers) as executor:
            futures = {executor.submit(self.one, product): product for product in candidates}
            for index, future in enumerate(as_completed(futures), 1):
                product = futures[future]
                state, cached = future.result()
                product.image_status = state["status"]
                if state["status"] == "failed":
                    failures[state["error"]] += 1
                if cached:
                    stats["cached_images"] += 1
                else:
                    stats[f"{state['status']}_this_run"] += 1
                if state["status"] == "downloaded":
                    path = self.directory / state["filename"]
                    product.image_path = path.relative_to(self.settings.data_dir).as_posix()
                product.data_quality_score = product.score(state["status"] == "downloaded")
                if index % 100 == 0 or index == len(candidates):
                    event("images_progress", completed=index, total=len(candidates), **stats)
        return {**stats, "failure_reasons": dict(sorted(failures.items()))}
