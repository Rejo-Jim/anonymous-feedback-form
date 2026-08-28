# Campus Grievance Desk

An anonymous grievance-submission portal for a campus: students submit a
grievance and get a private tracking ID back; anyone with that ID can check
its status; admins triage everything from a dashboard.

This is a **restyle** of an existing working Flask app — the routes,
validation, CSRF protection, rate limiting, and database logic are unchanged.
What's new is the templates (now share a common `base.html`), the CSS design
system, a small vanilla-JS layer for toasts/loading states/copy-to-clipboard,
and a couple of small additive backend touches (flash messages on admin
updates, a dashboard stats summary computed from data already being fetched).

## Project structure

```
project/
├── app.py                 Flask app (routes, DB, auth, CSRF, rate limiting)
├── requirements.txt
├── grievances.db           SQLite database (created automatically if missing)
├── templates/
│   ├── base.html           Shared nav / toast area / footer
│   ├── index.html          Submit a grievance
│   ├── status.html         Track a grievance
│   └── admin.html          Admin dashboard
└── static/
    ├── style.css
    └── script.js
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Admin credentials

The admin dashboard at `/admin` uses HTTP Basic Auth. Set your own
credentials before running — **do not use the defaults outside of local
testing**:

```bash
export ADMIN_USERNAME="your_admin_name"
export ADMIN_PASSWORD="a-strong-password"
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

(On Windows PowerShell, use `$env:ADMIN_USERNAME = "..."` etc.)

If you skip this, the app falls back to `admin` / `change-me` for local
testing only, and prints a warning on startup.

## Run

```bash
python3 app.py
```

Then open:

- `http://127.0.0.1:5000/` — submit a grievance
- `http://127.0.0.1:5000/status` — track a grievance
- `http://127.0.0.1:5000/admin` — admin dashboard (prompts for the credentials above)

The SQLite database (`grievances.db`) is created automatically on first run
if it doesn't already exist.

## Notes on anonymity and security

- Submissions don't collect names, emails, or accounts — only category and
  description.
- The app never claims to be *perfectly* anonymous — people should still
  avoid writing identifying details they don't want shared.
- CSRF tokens are required on every POST form.
- `/status` is rate-limited per IP to slow down tracking-ID guessing.
- Admin routes require Basic Auth; set real credentials via environment
  variables before deploying anywhere beyond your own machine.
- For a real deployment, put this behind HTTPS so Basic Auth credentials
  and session cookies aren't sent in the clear.
