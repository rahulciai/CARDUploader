from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import base64, uuid, re, os
from io import BytesIO

from azure.storage.blob import (
    BlobServiceClient, generate_blob_sas,
    BlobSasPermissions, ContentSettings
)
from dotenv import load_dotenv
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import httpx

load_dotenv()
app = FastAPI()

# ── Azure Config ──
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
ACCOUNT_NAME = os.getenv("ACCOUNT_NAME")
ACCOUNT_KEY = os.getenv("ACCOUNT_KEY")
CONTAINER_NAME = os.getenv("CONTAINER_NAME")

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

# ── Font & Card Config ──
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

CARD_DEFAULTS = {
    "birthday": {
        "px": 802, "py": 229, "pw": 408, "ph": 454,
        "nx": 1006, "ny": 742, "ns": 38,
        "dx": 1006, "dy": 780, "ds": 28,
        "name_color": (254, 174, 56),
        "dob_color": (255, 255, 255),
        "name_font": "Inter-Bold.ttf",
        "dob_font": "Inter-Bold.ttf",
    },
    "anniversary": {
        "px": 160, "py": 558, "pw": 373, "ph": 437,
        "nx": 657, "ny": 456, "ns": 50,
        "yx": 952, "yy": 886, "ys": 331,
        "name_color": (254, 174, 56),
        "years_color": (254, 174, 56),
        "name_font": "Montserrat-Bold.ttf",
        "years_font": "PlayfairDisplay-Regular.ttf",
    }
}


# ══════════════════════════
#  HELPERS
# ══════════════════════════

def upload_bytes_to_blob(image_bytes: bytes, ext: str = "png",
                         content_type: str = "image/png") -> str:
    """Upload raw bytes to Azure Blob → return public SAS URL (10 yr)"""
    filename = f"{uuid.uuid4()}.{ext}"
    blob_path = f"images/{filename}"

    blob_client = blob_service_client.get_blob_client(
        container=CONTAINER_NAME, blob=blob_path
    )
    blob_client.upload_blob(
        image_bytes, overwrite=True,
        content_settings=ContentSettings(content_type=content_type)
    )

    sas_token = generate_blob_sas(
        account_name=ACCOUNT_NAME,
        container_name=CONTAINER_NAME,
        blob_name=blob_path,
        account_key=ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=3650)
    )

    return (
        f"https://{ACCOUNT_NAME}.blob.core.windows.net/"
        f"{CONTAINER_NAME}/{blob_path}?{sas_token}"
    )


def download_image(url: str) -> Image.Image:
    """Download image from URL → return PIL Image (RGBA)"""
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGBA")


def cover_fit(photo: Image.Image, pw: int, ph: int) -> Image.Image:
    """Resize + center-crop photo to fill frame (like CSS object-fit:cover)"""
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
    """Load font from /app/fonts → fallback to DejaVu → fallback to default"""
    path = os.path.join(FONTS_DIR, name)
    if os.path.exists(path) and os.path.getsize(path) > 100:
        return ImageFont.truetype(path, size)
    # Fallback chain
    for fb in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size)
    return ImageFont.load_default(size)


def draw_centered_text(draw: ImageDraw.Draw, canvas: Image.Image,
                       text: str, x: int, y: int,
                       font: ImageFont.FreeTypeFont, color: tuple,
                       shadow: bool = True, italic: bool = False):
    """Draw text centered at (x, y) — with optional italic shear"""
    if italic:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0] + 80
        th = bbox[3] - bbox[1] + 80
        pad = 40

        txt_img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        txt_draw = ImageDraw.Draw(txt_img)

        # Draw text centered horizontally in temp image
        cx = txt_img.width // 2
        if shadow:
            txt_draw.text((cx + 2, pad + 2), text, font=font,
                          fill=(0, 0, 0, 140), anchor="mt")
        txt_draw.text((cx, pad), text, font=font,
                      fill=color + (255,), anchor="mt")

        # Shear transform → italic
        shear = 0.2
        txt_img = txt_img.transform(
            txt_img.size, Image.AFFINE,
            (1, shear, -shear * txt_img.height / 2, 0, 1, 0),
            resample=Image.BICUBIC
        )

        # Crop to actual content → perfect centering
        content_bbox = txt_img.getbbox()
        if content_bbox:
            cropped = txt_img.crop(content_bbox)
            paste_x = x - cropped.width // 2
            paste_y = y - cropped.height
            canvas.paste(cropped, (paste_x, paste_y), cropped)
    else:
        if shadow:
            draw.text((x + 2, y + 2), text, font=font,
                      fill=(0, 0, 0), anchor="ms")
        draw.text((x, y), text, font=font, fill=color, anchor="ms")


# ══════════════════════════
#  MODELS
# ══════════════════════════

class ImagePayload(BaseModel):
    imageBase64: str


class GeneratePayload(BaseModel):
    type: str                       # "birthday" or "anniversary"
    templateUrl: str                # template image URL
    photoUrl: str                   # employee photo URL
    name: str                       # employee full name
    dob: Optional[str] = None       # e.g. "15 March" (birthday only)
    years: Optional[str] = None     # e.g. "5" (anniversary only)


# ══════════════════════════
#  ENDPOINTS
# ══════════════════════════

@app.post("/upload")
async def upload_image(payload: ImagePayload):
    """Existing endpoint — accepts base64, uploads to Azure Blob"""
    try:
        base64_string = payload.imageBase64

        if "," in base64_string:
            base64_string = base64_string.split(",", 1)[1]
        base64_string = re.sub(r"\s+", "", base64_string)
        base64_string = base64_string.replace("-", "+").replace("_", "/")
        base64_string = base64_string.rstrip("=")
        missing = len(base64_string) % 4
        if missing:
            base64_string += "=" * (4 - missing)

        image_bytes = base64.b64decode(base64_string)

        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            ext, ct = "png", "image/png"
        elif image_bytes[:3] == b"\xff\xd8\xff":
            ext, ct = "jpg", "image/jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            ext, ct = "webp", "image/webp"
        else:
            ext, ct = "png", "image/png"

        image_url = upload_bytes_to_blob(image_bytes, ext, ct)
        return {"success": True, "imageUrl": image_url}

    except base64.binascii.Error as e:
        return {"success": False, "error": f"Base64 decode failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/generate")
async def generate_card(payload: GeneratePayload):
    """NEW — generates birthday/anniversary card image server-side"""
    try:
        if payload.type not in CARD_DEFAULTS:
            return {"success": False, "error": f"Unknown type: {payload.type}"}

        d = CARD_DEFAULTS[payload.type]

        # ① Download template + employee photo
        template = download_image(payload.templateUrl)
        photo = download_image(payload.photoUrl)

        # ② Cover-fit photo into frame area
        fitted = cover_fit(photo, d["pw"], d["ph"])

        # ③ Paste photo onto template
        template.paste(
            fitted, (d["px"], d["py"]),
            fitted if fitted.mode == "RGBA" else None
        )

        # ④ Draw text
        draw = ImageDraw.Draw(template)

        if payload.type == "birthday":
            # Name (Inter Bold + Italic shear, gold)
            name = payload.name
            font_name = load_font(d["name_font"], d["ns"])
            draw_centered_text(draw, template, name, d["nx"], d["ny"],
                               font_name, d["name_color"], italic=True)

            # DOB (Inter Bold + Italic shear, white)
            if payload.dob:
                font_dob = load_font(d["dob_font"], d["ds"])
                draw_centered_text(draw, template, payload.dob, d["dx"], d["dy"],
                                   font_dob, d["dob_color"], italic=True)

        else:  # anniversary
            # Name (Montserrat Bold, gold, UPPERCASE)
            name = payload.name.upper()
            font_name = load_font(d["name_font"], d["ns"])
            draw_centered_text(draw, template, name, d["nx"], d["ny"],
                               font_name, d["name_color"], italic=False)

            # Years (Playfair Display, gold, big)
            if payload.years:
                font_years = load_font(d["years_font"], d["ys"])
                draw_centered_text(draw, template, payload.years, d["yx"], d["yy"],
                                   font_years, d["years_color"], italic=False)

        # ⑤ Export to PNG bytes
        buffer = BytesIO()
        template.convert("RGB").save(buffer, format="PNG", optimize=True)
        image_bytes = buffer.getvalue()

        # ⑥ Upload to Azure Blob (reuses existing logic)
        image_url = upload_bytes_to_blob(image_bytes, "png", "image/png")

        return {"success": True, "imageUrl": image_url}

    except httpx.HTTPError as e:
        return {"success": False, "error": f"Image download failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}