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
- **Resilience & maintenance** — host-inactivity expiry, stale-session cleanup, and reconnection for flaky mobile networks.
- **Roles & teams** — TEAM_LEADER / TEAM_MEMBER devices, Manghuhula / Tagasagot gameplay roles, fully real (backend-sourced) data end to end.

---

## 🧱 Tech Stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3, Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-SocketIO (simple-websocket) |
| Database | MySQL (via PyMySQL), SQLite for tests |
| Frontend | Vanilla HTML/CSS/JS (no build step), served by Flask |
| Realtime | Socket.IO (WebSocket), client uses the official CDN build |
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
- MySQL (or set `DATABASE_URL` to any SQLAlchemy-compatible DB; tests default to in-memory SQLite)
- Internet access for the Socket.IO client CDN (or self-host it)

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

Edit `backend/.env`:

```
FLASK_CONFIG=development
SECRET_KEY=your-secret-key
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/pinoy_henyo
CORS_ORIGINS=*
PORT=5000
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

### 4. Run the tests

```bash
cd backend
python -m pytest -q
```

> `pytest.ini` already points at the `test/` directory and `pythonpath=.`, so
> `flask db upgrade` is not required for the test suite (tests use in-memory SQLite).

---

## 🔄 Realtime Overview

- **Rooms** — each game, team, and the current turn have dedicated Socket.IO rooms.
- **Player mode** — devices connect with a session token + device id (heartbeat kept alive; stale sessions are expired).
- **Host mode** — hosts authenticate with a host session token.
- **Events** include `turn_started`, `turn_state`, `word_correct`, `word_passed`, `timer_updated`, `round_started/completed`, `game_completed`, and presence/roster events (`member_joined/left`, `team_connected/disconnected`, `role_updated`, `team_updated`, `member_updated`).

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
- **Generated artifacts** (`CONNECTION_AUDIT_REPORT.md`, `FINAL_E2E_REPORT.md`) are gitignored; `backend/e2e_test.py` is an end-to-end smoke harness you can run directly.

---

## 📄 License

This project is for educational / demonstration purposes. Use freely; attribute the original creators where appropriate.
