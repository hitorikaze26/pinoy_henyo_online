from app import create_app
from app.extensions import socketio

app = create_app()

# --- Render (production) ---
# Expose the Socket.IO-wrapped WSGI app for gunicorn. Real-time events would
# not work if gunicorn served the bare `app` instead. Uncomment for Render.
# Keep `socketio.run(app, ...)` below for local development.
# socketio_app = socketio.WSGIApp(socketio, app)

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=app.config.get("PORT", 5000),
        debug=app.config.get("DEBUG", False),
    )
    