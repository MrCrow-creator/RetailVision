import hashlib
import io
from pathlib import Path, PurePosixPath

from PIL import Image

from ..openfoodfacts.images import verify_image

MAX_IMAGE_BYTES = 5_242_880


def inspect_image(value: str, data_dir: Path) -> dict:
    result = {
        "image_available": False,
        "image_valid": False,
        "image_format": "",
        "image_width": None,
        "image_height": None,
        "image_size_bytes": None,
        "image_sha256": "",
        "image_validation_status": "no_path",
    }
    if not value:
        return result
    parts = value.split("/")
    if (
        "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(c) < 32 for c in value)
    ):
        return {**result, "image_validation_status": "unsafe_path"}
    root = data_dir.resolve()
    try:
        path = (root / value).resolve()
        if not path.is_relative_to(root):
            return {**result, "image_validation_status": "unsafe_path"}
        if not path.is_file():
            return {**result, "image_validation_status": "missing_file"}
        result.update(image_available=True, image_size_bytes=path.stat().st_size)
        if result["image_size_bytes"] > MAX_IMAGE_BYTES:
            return {**result, "image_validation_status": "oversize"}
        with path.open("rb") as stream:
            content = stream.read(MAX_IMAGE_BYTES + 1)
        if len(content) > MAX_IMAGE_BYTES:
            return {**result, "image_validation_status": "oversize"}
        result.update(
            image_size_bytes=len(content), image_sha256=hashlib.sha256(content).hexdigest()
        )
        with Image.open(io.BytesIO(content)) as image:
            result.update(
                image_format=image.format or "", image_width=image.width, image_height=image.height
            )
        verify_image(content)  # Reuse Milestone 2 format/dimension/pixel validation.
        return {**result, "image_valid": True, "image_validation_status": "valid"}
    except PermissionError:
        return {**result, "image_validation_status": "unreadable"}
    except ValueError as error:
        status = (
            "unsupported_format"
            if str(error) == "unsupported_image_format"
            else "invalid_dimensions"
        )
        return {**result, "image_validation_status": status}
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return {**result, "image_validation_status": "corrupt"}
