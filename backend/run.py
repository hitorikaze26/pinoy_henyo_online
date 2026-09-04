import os

from app import create_app
from app.extensions import socketio

# Flask application + Socket.IO server, used for local dev AND production.
# Flask-SocketIO installs its Socket.IO middleware into app.wsgi_app during
# init_app, so the exported Flask `app` is already Socket.IO-capable and is
# the ONLY WSGI entry point. Do not wrap it manually with socketio.WSGIApp.
#
# Render start command:
#   flask db upgrade && python run.py
#
# Gunicorn's eventlet worker (`gunicorn -k eventlet`/`run:gunicorn_app`) is
# NOT supported by Gunicorn 26 and must not be used.
app = create_app()

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=app.config.get("DEBUG", False),
    )