# Pinoy Henyo Online 🎉

A real-time, mobile-first guessing game built on the classic Filipino party game **Pinoy Henyo**. One player is the **Manghuhula (guesser)**, their team is the **Tagasagot (answerer)**, and the host runs the game — starting rounds, control the timer, and score words in real time over WebSockets.

Built as a single deployable app: a **Flask + Socket.IO** backend that serves a **vanilla HTML/CSS/JS** frontend and exposes a REST API + realtime event layer.

---

## ✨ Features

- **Host dashboard** — create a game, manage teams, assign gameplay roles, track scores/timer/penalties in real time.
- **Player page** — scan a QR or enter a game code, join/create a team, submit & manage words, and play rounds.
- **Realtime gameplay** — Socket.IO rooms keep host and players in sync (turn timer, word results, round/team/player events, presence).
- **QR code joining** — hosts and teams get scannable QR deep-links with safe, code-only payloads (no secrets leaked).
- **Word pool rules** — teams submit up to 5 words per category; a team can never receive a word it submitted itself; duplicate/normalized-word protection.
- **Live player leaderboard** — a Scores tab on the player page shows full public standings in real time (top-3 medals, your-team highlight), honoring the host's Show-scores toggle.
- **Resilience & maintenance** — host-inactivity expiry, stale-session cleanup, and reconnection for flaky mobile networks.
- **Roles & teams** — TEAM_LEADER / TEAM_MEMBER devices, Manghuhula / Tagasagot gameplay roles, fully real (backend-sourced) data end to end.

---

## 🧱 Tech Stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3, Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-SocketIO |
| Database | MySQL (via PyMySQL), PostgreSQL (via psycopg2), SQLite for tests |
| Frontend | Vanilla HTML/CSS/JS (no build step), served by Flask |
| Realtime | Socket.IO (WebSocket), vendored 4.8.1 client build (works offline) |
| Assets   | Fully vendored — Socket.IO, jsQR, Font Awesome, custom fonts; no CDN |
| Extras   | segno (QR generation), python-dotenv, pytest |

---

## 📁 Project Structure

```
pinoy_henyo_online/
├── README.md
├── .gitignore
├── backend/                      # Flask backend + API
│   ├── app/
│   │   ├── __init__.py           # app factory, blueprint registration
│   │   ├── constants/            # shared constants
│   │   ├── models/               # SQLAlchemy models (game, team, turn, …)
│   │   ├── routes/               # REST + frontend-servings blueprints
│   │   ├── schemas/              # (reserved) response shapes
│   │   ├── services/             # business logic (game, team, word, turn, …)
│   │   ├── sockets/              # Socket.IO event handlers
│   │   └── utils/                # auth, responses, rate-limit, time, qr codes
│   ├── migrations/               # Alembic/Flask-Migrate migrations
│   ├── test/                     # pytest suite
│   ├── config.py                 # env-driven configuration
│   ├── run.py                    # entry point (flask + socketio)
│   ├── requirements.txt
│   ├── .env.example              # template for local env (see Setup)
│   └── .env                      # ⚠️ LOCAL ONLY — gitignored, never commit
└── frontend/                     # static SPA served by the backend
    ├── index.html                # landing / lobby
    ├── pages/
    │   ├── host/host_dashboard.html, teams.html, words.html
    │   └── player/player.html
    ├── css/                      # global + per-page styles
    ├── js/
    │   ├── api/                  # REST API clients (game, team, word, …)
    │   ├── host/, player/        # page logic
    │   ├── core/                 # modal, session, config, utils
    │   └── components/           # header / sidebar
    ├── components/               # reusable HTML partials
    ├── templates/base.html       # layout template
    └── assets/                   # images, sounds, svgs, stickers
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+ (tested on 3.12/3.14)
- MySQL or PostgreSQL (or set `DATABASE_URL` to any SQLAlchemy-compatible DB; tests default to in-memory SQLite)
- No internet required — all frontend assets (Socket.IO, jsQR, Font Awesome, fonts) are vendored and served locally. Internet is only needed if you deploy the optional online mode.

### 1. Backend setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
```

Edit `backend/.env` (copy from `backend/.env.example` — the canonical template):

```
FLASK_CONFIG=development             # development | production
DEPLOY_MODE=local                    # local | lan | online (auto-derived from FLASK_CONFIG if unset)
SECRET_KEY=your-secret-key
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/pinoy_henyo
CORS_ORIGINS=*                       # comma-separated allowed browser origins
PORT=5000
QR_BASE_URL=                         # where players land after scanning a QR ('' = current request origin)
HOST_INACTIVITY_TIMEOUT=900          # 0 disables host-inactivity expiry
DEVICE_HEARTBEAT_TIMEOUT=60
DEVICE_HEARTBEAT_GRACE_MULTIPLIER=3  # stale threshold = timeout * multiplier
SWEEPER_INTERVAL=30
RATE_LIMIT_MULTIPLIER=1              # raise (e.g. 5) on LAN so a shared hotspot IP isn't throttled
WERKZEUG_RELOADER=true               # false for LAN/online deployments
```

> For local dev you can use SQLite instead of MySQL:
> `DATABASE_URL=sqlite:///pinoy_henyo.db`

### 2. Apply database migrations

```bash
python -m flask db upgrade
```

### 3. Run the app

```bash
python run.py
```

The Flask app serves **both** the REST API (`/api/*`) and the frontend, so open:

- Landing / lobby → http://localhost:5000/

In development, the Socket.IO server and Flask share the same process (port 5000 by default).

> Single-origin installs need **no edits** to `frontend/js/core/runtime-config.js` —
> `js/core/config.js` auto-detects the same-origin backend on localhost/LAN, and
> QR deep-links resolve to the same origin players are already on.

### 4. Run the tests

```bash
cd backend
python -m pytest -q
```

> `pytest.ini` already points at the `test/` directory and `pythonpath=.`, so
> `flask db upgrade` is not required for the test suite (tests use in-memory SQLite).

---

## 🌐 Deployment Modes

The app is a **single-origin monolith**: Flask serves the frontend, REST API, and Socket.IO from **one** process (`python run.py`). Pick a mode via `DEPLOY_MODE` (or it's derived from `FLASK_CONFIG` — `production` → `online`, anything else → `local`).

### 🖥️ localhost (single device)

```bash
FLASK_CONFIG=development
DEPLOY_MODE=local
CORS_ORIGINS=*
```

Open `http://localhost:5000/`. Everything runs on your machine; QR codes resolve to `http://localhost:5000`.

### 📡 LAN / offline party (laptop + phones, no internet)

Share your laptop's Wi-Fi/hotspot and run:

```bash
DEPLOY_MODE=lan
CORS_ORIGINS=*          # or list LAN origins explicitly
HOST_INACTIVITY_TIMEOUT=0   # long local session, no auto-expiry
RATE_LIMIT_MULTIPLIER=5     # phones share one hotspot IP
WERKZEUG_RELOADER=false
```

Open the **host dashboard via the LAN address** — `http://<YOUR-LAN-IP>:5000/` — so the QR codes embed that origin. Phones on the same network scan/join and play normally, with **no internet connection required**.

### ☁️ Online (Cloudflare)

Deploy the single process behind Cloudflare (Tunnel or proxy, **WebSockets enabled**), one origin end to end:

```bash
FLASK_CONFIG=production
DEPLOY_MODE=online
SECRET_KEY=<long random string>             # REQUIRED in production
DATABASE_URL=postgresql+psycopg2://<user>:<pass>@<host>:5432/<db>
CORS_ORIGINS=https://game.yourdomain.com    # your public origin
QR_BASE_URL=https://game.yourdomain.com     # where QR codes land players
WERKZEUG_RELOADER=false
```

Build & run: `pip install -r requirements.txt`, `flask db upgrade`, then `python run.py` (Socket.IO included — no separate WSGI/gunicorn layer, so the WebSocket route works through the Cloudflare tunnel). `CORS_ORIGINS` and `QR_BASE_URL` must be your public domain — never empty in this mode.

---

## 🔄 Realtime Overview

- **Rooms** — each game, team, and the current turn have dedicated Socket.IO rooms.
- **Player mode** — devices connect with a session token + device id (heartbeat kept alive; stale sessions are expired).
- **Host mode** — hosts authenticate with a host session token.
- **Events** include `turn_started`, `turn_state`, `word_correct`, `word_passed`, `timer_updated`, `round_started/completed`, `game_completed`, `leaderboard_updated`, and presence/roster events (`member_joined/left`, `team_connected/disconnected`, `role_updated`, `team_updated`, `member_updated`).

---

## 🧪 API Highlights

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/games` | Create a game (returns host session token + code) |
| `GET`  | `/api/games/<id>` | Game status |
| `POST` | `/api/games/<id>/teams` | Create a team (leader becomes a member) |
| `GET`  | `/api/games/<id>/teams` | List teams + real rosters (host) |
| `GET`  | `/api/teams/<id>` | Own-team roster via session (or host) |
| `POST` | `/api/games/<id>/join` | Join a game by team name or code |
| `POST` | `/api/teams/<id>/roles` | Assign Manghuhula/Tagasagot roles |
| `POST` | `/api/games/<id>/categories` | Create a word category |
| `POST` | `/api/games/<id>/words` | Submit a word (host or player session) |
| `GET`  | `/api/games/<id>/words/my` | Player’s own team words (session) |
| `PATCH`| `/api/teams/<id>` / `/api/members/<id>` | Update team name / username |
| `GET`  | `/api/games/<id>/qr` | Host QR join link |
| `GET`  | `/api/games/<id>/leaderboard` | Live standings (host or any connected player session) |
| `POST` | `/api/devices/connect` | Establish a device session |

---

## 🗄️ Database

- Schema is managed with **Flask-Migrate / Alembic**.
- Migrations live in `backend/migrations/versions/`.
- Apply new migrations with `python -m flask db upgrade`.

Key entities: `Game`, `Team`, `TeamMember`, `DeviceSession`, `Category`, `Word`, `Match`, `Round`, `RoundCategory`, `Turn`, `Score`, `Penalty`, `GameEvent`.

---

## 🧹 Notes & Housekeeping

- **Secrets**: `backend/.env` is gitignored. Only `.env.example` is committed — never commit real credentials.
- **Offline-first assets**: everything the frontend needs (Socket.IO client, jsQR, Font Awesome, custom fonts) lives in `frontend/vendor/` — no external CDNs are referenced.
- **Generated artifacts** (`CONNECTION_AUDIT_REPORT.md`, `FINAL_E2E_REPORT.md`) are gitignored; `backend/e2e_test.py` is an end-to-end smoke harness you can run directly.

---

## 📄 License

This project is for educational / demonstration purposes. Use freely; attribute the original creators where appropriate.
