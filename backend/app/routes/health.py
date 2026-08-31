from flask import Blueprint

from sqlalchemy import text

from ..extensions import db
from ..utils.response import error_response, success_response

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.get("/health")
def health():
    return success_response(message="Pinoy Henyo Online API is running")


@health_bp.get("/health/db")
def health_db():
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        return error_response(
            message="Database connection is unavailable",
            code="DATABASE_UNAVAILABLE",
            status=503,
        )
    return success_response(message="Database connection is healthy")