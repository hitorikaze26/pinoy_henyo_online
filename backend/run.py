from app import create_app
from app.extensions import socketio

app = create_app()

# --- Render (production) ---
# Gunicorn entrypoint for Flask-SocketIO. Socket.IO traffic must go through the
# WSGI middleware rather than the bare Flask app or real-time events break.
# The factory is evaluated lazily so local dev (`python run.py`, threading
# async mode) never constructs the wrapper at import time.
# Render start command:
#   gunicorn -k eventlet -w 1 run:gunicorn_app
def gunicorn_app(environ, start_response):
    return socketio.WSGIApp(socketio, app)(environ, start_response)

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=app.config.get("PORT", 5000),
        debug=app.config.get("DEBUG", False),
    )
    