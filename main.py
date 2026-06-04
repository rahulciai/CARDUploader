from fastapi import FastAPI, status
from io import BytesIO
from PIL import ImageDraw
import httpx

from models import (
    ErrorResponse,
    UploadRequest,
    UploadResponse,
    GenerateRequest,
    GenerateResponse,
)
from card_defaults import CARD_DEFAULTS
from helpers import (
    error_json,
    download_image,
    upload_bytes_to_blob,
    validate_base64_image,
    cover_fit,
    load_font,
    draw_centered_text,
)

app = FastAPI(title="Card Generator API")


@app.post(
    "/upload",
    response_model=UploadResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def upload_image(payload: UploadRequest):
    try:
        image_bytes, ext, ct = validate_base64_image(payload.imageBase64)
        image_url = upload_bytes_to_blob(image_bytes, ext, ct)
        return UploadResponse(imageUrl=image_url)

    except ValueError as e:
        return error_json(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        return error_json(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@app.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def generate_card(payload: GenerateRequest):
    try:
        d = CARD_DEFAULTS[payload.type]

        if payload.type == "birthday" and not payload.dob:
            return error_json(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "dob is required for birthday card.",
            )

        if payload.type == "anniversary" and not payload.years:
            return error_json(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "years is required for anniversary card.",
            )

        try:
            template = await download_image(payload.templateUrl)
            photo = await download_image(payload.photoUrl)
        except ValueError as e:
            return error_json(status.HTTP_400_BAD_REQUEST, str(e))
        except httpx.HTTPError as e:
            return error_json(
                status.HTTP_502_BAD_GATEWAY,
                f"Image download failed: {str(e)}",
            )

        fitted = cover_fit(photo, d["pw"], d["ph"])

        template.paste(
            fitted,
            (d["px"], d["py"]),
            fitted if fitted.mode == "RGBA" else None,
        )

        draw = ImageDraw.Draw(template)

        if payload.type == "birthday":
            font_name = load_font(d["name_font"], d["ns"])
            draw_centered_text(
                draw=draw, canvas=template,
                text=payload.name,
                x=d["nx"], y=d["ny"],
                font=font_name, color=d["name_color"],
                italic=True,
            )

            if payload.dob:
                font_dob = load_font(d["dob_font"], d["ds"])
                draw_centered_text(
                    draw=draw, canvas=template,
                    text=payload.dob,
                    x=d["dx"], y=d["dy"],
                    font=font_dob, color=d["dob_color"],
                    italic=True,
                )
        else:
            font_name = load_font(d["name_font"], d["ns"])
            draw_centered_text(
                draw=draw, canvas=template,
                text=payload.name.upper(),
                x=d["nx"], y=d["ny"],
                font=font_name, color=d["name_color"],
                italic=False,
            )

            if payload.years:
                font_years = load_font(d["years_font"], d["ys"])
                draw_centered_text(
                    draw=draw, canvas=template,
                    text=payload.years,
                    x=d["yx"], y=d["yy"],
                    font=font_years, color=d["years_color"],
                    italic=False,
                )

        buffer = BytesIO()
        template.convert("RGB").save(buffer, format="PNG", optimize=True)
        image_bytes = buffer.getvalue()

        image_url = upload_bytes_to_blob(image_bytes, "png", "image/png")
        return GenerateResponse(imageUrl=image_url)

    except Exception as e:
        return error_json(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
