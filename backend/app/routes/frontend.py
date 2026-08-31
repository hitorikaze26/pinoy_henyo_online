import os

from flask import Blueprint, send_from_directory

# Resolve the frontend directory relative to this file:
# backend/app/routes/ -> backend/app/ -> backend/ -> project root -> frontend/
_FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
)

frontend_bp = Blueprint("frontend", __name__)


@frontend_bp.get("/")
def index():
    """Serve the landing page."""
    return send_from_directory(_FRONTEND_DIR, "index.html")


@frontend_bp.get("/<path:filename>")
def static_files(filename):
    """Serve any other frontend asset (CSS, JS, images, pages, etc.)."""
    return send_from_directory(_FRONTEND_DIR, filename)
