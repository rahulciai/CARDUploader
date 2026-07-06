import base64
import uuid
import re
import os
from html import unescape
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta

from fastapi import status
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont, ImageOps
from dotenv import load_dotenv
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions,
    ContentSettings,
)
import httpx

from models import ErrorResponse

load_dotenv()

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_blob_service_client = None


def error_json(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=message).model_dump(),
    )


def is_valid_http_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


async def fetch_url(url: str) -> httpx.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": url,
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        return await client.get(url, headers=headers)


def extract_image_url_from_html(html: str, base_url: str) -> Optional[str]:
    patterns = [
        r'<meta[^>]+(?:property|name)=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+(?:name|property)=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image(?::secure_url)?["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']twitter:image(?::src)?["\']',
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        r'<a[^>]+href=["\']([^"\']+\.(?:png|jpe?g|webp|gif|bmp)(?:\?[^"\']*)?)["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'(?:background-image|background)\s*:\s*url\(["\']?([^"\'()]+)["\']?\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            raw = unescape(match.group(1).strip())
            if raw and not raw.startswith("data:"):
                return urljoin(base_url, raw)
    return None


def decode_image_bytes(content: bytes) -> Optional[Image.Image]:
    try:
        img = Image.open(BytesIO(content))
        img.load()  
        img = ImageOps.exif_transpose(img)
        return img.convert("RGBA")
    except Exception:
        pass

    for signature in (b"\x89PNG", b"\xff\xd8", b"RIFF"):
        try:
            if signature in content:
                start = content.index(signature)
                img = Image.open(BytesIO(content[start:]))
                img.load()
                img = ImageOps.exif_transpose(img)
                return img.convert("RGBA")
        except Exception:
            pass

    return None



async def download_image(url: str, depth: int = 0) -> Image.Image:
    if not is_valid_http_url(url):
        raise ValueError("Invalid URL.")

    if depth > 3:
        raise ValueError("Could not resolve image URL.")

    resp = await fetch_url(url)

    if resp.status_code >= 400:
        raise ValueError(f"Failed to download. HTTP {resp.status_code}")

    content = resp.content

    img = decode_image_bytes(content)
    if img:
        return img

    # Try HTML fallback
    content_type = resp.headers.get("content-type", "").lower()
    text = resp.text
    if "html" in content_type or "<html" in text.lower() or "<img" in text.lower():
        extracted = extract_image_url_from_html(text, str(resp.url))
        if extracted:
            return await download_image(extracted, depth + 1)

    raise ValueError("Could not load image from URL.")


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} environment variable is required.")
    return value


def get_blob_service_client() -> BlobServiceClient:
    global _blob_service_client
    if _blob_service_client is None:
        connection_string = get_required_env("AZURE_CONNECTION_STRING")
        _blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
    return _blob_service_client


def upload_bytes_to_blob(
    image_bytes: bytes,
    ext: str = "png",
    content_type: str = "image/png",
) -> str:
    account_name = get_required_env("ACCOUNT_NAME")
    account_key = get_required_env("ACCOUNT_KEY")
    container_name = get_required_env("CONTAINER_NAME")

    filename = f"{uuid.uuid4()}.{ext}"
    blob_path = f"images/{filename}"

    blob_client = get_blob_service_client().get_blob_client(
        container=container_name, blob=blob_path
    )
    blob_client.upload_blob(
        image_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=3650),
    )

    return (
        f"https://{account_name}.blob.core.windows.net/"
        f"{container_name}/{blob_path}?{sas_token}"
    )



def cover_fit(photo: Image.Image, pw: int, ph: int) -> Image.Image:
    par = photo.width / photo.height
    far = pw / ph

    if par > far:
        dh = ph
        dw = int(dh * par)
    else:
        dw = pw
        dh = int(dw / par)

    photo = photo.resize((dw, dh), Image.LANCZOS)
    left = (dw - pw) // 2
    top = (dh - ph) // 2
    return photo.crop((left, top, left + pw, top + ph))


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(FONTS_DIR, name)
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return ImageFont.truetype(path, size)

    for fb in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size)

    return ImageFont.load_default()


def draw_centered_text(
    draw: ImageDraw.Draw,
    canvas: Image.Image,
    text: str,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    color: tuple,
    shadow: bool = True,
    italic: bool = False,
):
    if italic:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0] + 80
        th = bbox[3] - bbox[1] + 80
        pad = 40

        txt_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        txt_draw = ImageDraw.Draw(txt_img)

        cx = txt_img.width // 2
        if shadow:
            txt_draw.text(
                (cx + 2, pad + 2), text,
                font=font, fill=(0, 0, 0, 140), anchor="mt",
            )

        txt_draw.text(
            (cx, pad), text,
            font=font, fill=color + (255,), anchor="mt",
        )

        shear = 0.2
        txt_img = txt_img.transform(
            txt_img.size,
            Image.AFFINE,
            (1, shear, -shear * txt_img.height / 2, 0, 1, 0),
            resample=Image.BICUBIC,
        )

        content_bbox = txt_img.getbbox()
        if content_bbox:
            cropped = txt_img.crop(content_bbox)
            paste_x = x - cropped.width // 2
            paste_y = y - cropped.height
            canvas.paste(cropped, (paste_x, paste_y), cropped)
    else:
        if shadow:
            draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0), anchor="ms")
        draw.text((x, y), text, font=font, fill=color, anchor="ms")



def validate_base64_image(base64_string: str) -> Tuple[bytes, str, str]:
    if "," in base64_string:
        base64_string = base64_string.split(",", 1)[1]

    base64_string = re.sub(r"\s+", "", base64_string)
    base64_string = base64_string.replace("-", "+").replace("_", "/")
    base64_string = base64_string.rstrip("=")

    missing = len(base64_string) % 4
    if missing:
        base64_string += "=" * (4 - missing)

    try:
        image_bytes = base64.b64decode(base64_string)
    except Exception as e:
        raise ValueError(f"Base64 decode failed: {str(e)}")

    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()

        # Important fix: apply EXIF orientation before upload
        img = ImageOps.exif_transpose(img)

        # Save normalized image as PNG to remove EXIF orientation dependency
        buffer = BytesIO()
        img.convert("RGBA").save(buffer, format="PNG", optimize=True)

        return buffer.getvalue(), "png", "image/png"

    except Exception:
        raise ValueError("Invalid image payload.")
