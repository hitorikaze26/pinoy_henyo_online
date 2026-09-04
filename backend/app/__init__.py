import os

from flask import Flask

from config import config_by_name

from .extensions import cors, db, migrate, socketio
from .routes.categories import categories_bp
from .routes.devices import devices_bp
from .routes.games import games_bp
from .routes.gameplay import gameplay_bp
from .routes.health import health_bp
from .routes.teams import teams_bp
from .routes.words import words_bp
from .utils.response import error_response


def _register_blueprints(app):
    app.register_blueprint(health_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(words_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(gameplay_bp)
    # Frontend static serving — registered last so the catch-all /<path>
    # never shadows any /api/* route registered above.
    from .routes.frontend import frontend_bp
    app.register_blueprint(frontend_bp)


def _register_error_handlers(app):
    error_specs = {
        400: ("BAD_REQUEST", "The request could not be understood by the server."),
        404: ("NOT_FOUND", "The requested resource was not found."),
        405: ("METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this endpoint."),
        422: ("UNPROCESSABLE_ENTITY", "The request could not be processed."),
        500: ("INTERNAL_SERVER_ERROR", "An unexpected error occurred on the server."),
    }

    for status_code, (code, message) in error_specs.items():

        def handler(error, _code=code, _message=message, _status=status_code):
            if _status >= 500:
                app.logger.exception("Unhandled error: %s", error)
            if app.config.get("DEBUG") and _status >= 500:
                _message = "{} ({})".format(_message, error)
            return error_response(_message, code=_code, status=_status)

        app.register_error_handler(status_code, handler)

    # engineio raises ConnectionError when the WebSocket upgrade fails
    # on werkzeug (dev server). This is expected — the client falls back
    # to polling — but it must not surface as an opaque HTTP 500.
    app.register_error_handler(
        ConnectionError,
        lambda error: error_response(
            "WebSocket upgrade failed.", code="CONNECTION_ERROR", status=400,
        ),
    )


def _register_sockets():
    from .services import realtime as _realtime
    from .sockets import events as _events  # noqa: F401

    _realtime.reset_peers()
    _events.register()


def _maybe_start_sweeper(app):
    # Background host-disconnect reconciliation + stale-session expiry.
    # Disabled under tests so fixtures stay deterministic.
    if app.config.get("TESTING"):
        return
    from .services import maintenance as _maintenance

    _maintenance.start_sweeper(app)


def _register_models():
    from . import models  # noqa: F401


def _warn_production_cors(app):
    if app.config.get("DEBUG"):
        return
    origins = app.config.get("CORS_ORIGINS") or []
    if not origins:
        app.logger.warning(
            "Production CORS_ORIGINS is empty — the Vercel frontend cannot "
            "reach the API or Socket.IO. Set CORS_ORIGINS (comma-separated "
            "origins) in the Render environment."
        )
    elif "*" in origins:
        app.logger.warning(
            "Production CORS_ORIGINS contains '*' — restrict it to the Vercel "
            "frontend origin, e.g. https://<app>.vercel.app."
        )


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "development")
    if config_name not in config_by_name:
        raise ValueError("Unknown configuration: {!r}".format(config_name))

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "DATABASE_URL is not set. Copy backend/.env.example to backend/.env "
            "and set DATABASE_URL."
        )
    if config_name == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set for the production configuration.")

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(
        app, cors_allowed_origins=app.config.get("CORS_ORIGINS", "*")
    )
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}},
    )

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_models()
    _register_sockets()
    _maybe_start_sweeper(app)
    _warn_production_cors(app)

    return app