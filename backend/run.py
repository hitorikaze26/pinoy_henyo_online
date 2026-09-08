import os

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    debug_enabled = app.config.get("DEBUG", False)
    use_reloader = os.environ.get("WERKZEUG_RELOADER", "true").lower() in ("1", "true", "yes")
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=debug_enabled,
        use_reloader=use_reloader,
    )