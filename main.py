from fastapi import FastAPI
from pydantic import BaseModel
import base64
import uuid
import re
import os
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions,
    ContentSettings
)

from dotenv import load_dotenv
from datetime import datetime, timedelta
load_dotenv()
app = FastAPI()


AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
ACCOUNT_NAME = os.getenv("ACCOUNT_NAME")
ACCOUNT_KEY = os.getenv("ACCOUNT_KEY")
CONTAINER_NAME = os.getenv("CONTAINER_NAME")
# =========================
# Blob Client
# =========================

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_CONNECTION_STRING
)

# =========================
# Request Model
# =========================

class ImagePayload(BaseModel):
    imageBase64: str

# =========================
# Upload API
# =========================

@app.post("/upload")
async def upload_image(payload: ImagePayload):
    try:
        base64_string = payload.imageBase64

        # 1. Strip data URI prefix
        if "," in base64_string:
            base64_string = base64_string.split(",", 1)[1]

        # 2. Strip all whitespace
        base64_string = re.sub(r"\s+", "", base64_string)

        # 3. Convert URL-safe base64 to standard
        base64_string = base64_string.replace("-", "+").replace("_", "/")

        # 4. Strip existing padding, then re-pad cleanly
        base64_string = base64_string.rstrip("=")
        missing_padding = len(base64_string) % 4
        if missing_padding:
            base64_string += "=" * (4 - missing_padding)

        # 5. Decode
        image_bytes = base64.b64decode(base64_string)

        # 6. Detect image type from magic bytes
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            ext, content_type = "png", "image/png"
        elif image_bytes[:3] == b"\xff\xd8\xff":
            ext, content_type = "jpg", "image/jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            ext, content_type = "webp", "image/webp"
        else:
            ext, content_type = "png", "image/png"  # fallback

        # 7. Generate unique blob path
        filename = f"{uuid.uuid4()}.{ext}"
        blob_path = f"images/{filename}"

        # 8. Upload to Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(
            container=CONTAINER_NAME,
            blob=blob_path
        )
        blob_client.upload_blob(
            image_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type)
        )

        # 9. Generate SAS token (10 years)
        sas_token = generate_blob_sas(
            account_name=ACCOUNT_NAME,
            container_name=CONTAINER_NAME,
            blob_name=blob_path,
            account_key=ACCOUNT_KEY,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(days=3650)
        )

        image_url = (
            f"https://{ACCOUNT_NAME}.blob.core.windows.net/"
            f"{CONTAINER_NAME}/{blob_path}?{sas_token}"
        )

        return {"success": True, "imageUrl": image_url}

    except base64.binascii.Error as e:
        return {"success": False, "error": f"Base64 decode failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}