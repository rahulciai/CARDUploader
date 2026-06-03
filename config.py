import os
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient

load_dotenv()

# ── Azure Config ──
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
ACCOUNT_NAME = os.getenv("ACCOUNT_NAME")
ACCOUNT_KEY = os.getenv("ACCOUNT_KEY")
CONTAINER_NAME = os.getenv("CONTAINER_NAME")

blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

# ── Font Dir ──
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# ── Card Defaults ──
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
    },
}