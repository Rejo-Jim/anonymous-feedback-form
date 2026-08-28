import os
import secrets
import sqlite3
import string
import time
from contextlib import contextmanager
from functools import wraps

from flask import (
    Flask,
    request,
    render_template,
    session,
    abort,
    Response,
    flash,
)

app = Flask(__name__)

# ---------------- CONFIG ----------------

# Secret key for signing the session cookie (used for CSRF tokens and
# flash messages). In production, set this via an environment variable
# so it doesn't reset (and invalidate sessions) every time the app restarts.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Admin credentials. MUST be overridden via environment variables in
# any real deployment - these defaults are only here so the app can
# run out of the box in development.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")

if ADMIN_PASSWORD == "change-me":
    print(
        "WARNING: Using the default admin password. Set the "
        "ADMIN_USERNAME and ADMIN_PASSWORD environment variables "
        "before deploying this anywhere real."
    )

DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grievances.db")

VALID_CATEGORIES = [
    "Harassment",
    "Bullying",
    "Academic",
    "Hostel",
    "Infrastructure",
    "Other",
]

VALID_STATUSES = ["Received", "In Review", "Resolved"]

SENSITIVE_CATEGORIES = ["Harassment", "Bullying"]

TRACKING_ID_ALPHABET = string.ascii_uppercase + string.digits


# ---------------- DATABASE ----------------

@contextmanager
def get_db():
    """Yields a sqlite connection and guarantees it is closed even if
    an error is raised partway through a request."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS grievances (
                tracking_id TEXT PRIMARY KEY,
                category TEXT,
                description TEXT,
                status TEXT,
                severity INTEGER
            )
            """
        )
        conn.commit()


init_db()


# ---------------- TRACKING ID ----------------

def generate_tracking_id(conn):
    """Generates a cryptographically random tracking ID and guarantees
    it doesn't collide with an existing one."""
    while True:
        candidate = "GRV-" + "".join(
            secrets.choice(TRACKING_ID_ALPHABET) for _ in range(8)
        )
        existing = conn.execute(
            "SELECT 1 FROM grievances WHERE tracking_id = ?",
            (candidate,),
        ).fetchone()
        if not existing:
            return candidate


# ---------------- SEVERITY ----------------

def calculate_severity(category, description):

    score = 0

    high_severity_categories = [
        "Harassment",
        "Bullying"
    ]

    medium_severity_categories = [
        "Infrastructure",
        "Hostel"
    ]

    if category in high_severity_categories:
        score += 3

    elif category in medium_severity_categories:
        score += 2

    else:
        score += 1

    urgent_keywords = [
        "unsafe",
        "threat",
        "danger",
        "injury",
        "emergency",
        "assault",
        "abuse"
    ]

    description_lower = description.lower()

    for word in urgent_keywords:

        if word in description_lower:
            score += 2
            break

    return score


# ---------------- CSRF PROTECTION ----------------
# Lightweight, dependency-free CSRF protection: a random token is
# stored in the signed session cookie and must be echoed back by
# every POST form. Flask's session cookie is signed with secret_key,
# so an attacker cannot forge a valid token without it.

def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf():
    token = session.get("csrf_token")
    submitted = request.form.get("csrf_token")
    if not token or not submitted or not secrets.compare_digest(token, submitted):
        abort(400, description="Invalid or missing CSRF token.")


app.jinja_env.globals["csrf_token"] = get_csrf_token


# ---------------- RATE LIMITING (status lookups) ----------------
# Simple in-memory limiter to slow down brute-force guessing of
# tracking IDs on /status. Fine for a single-process deployment; use
# a shared store (e.g. Redis) if this app is ever scaled out.

_status_attempts = {}
STATUS_MAX_ATTEMPTS = 10
STATUS_WINDOW_SECONDS = 60


def status_rate_limited(ip):
    now = time.time()
    attempts = [t for t in _status_attempts.get(ip, []) if now - t < STATUS_WINDOW_SECONDS]
    attempts.append(now)
    _status_attempts[ip] = attempts
    return len(attempts) > STATUS_MAX_ATTEMPTS


# ---------------- ADMIN AUTH ----------------

def check_auth(username, password):
    return (
        secrets.compare_digest(username, ADMIN_USERNAME)
        and secrets.compare_digest(password, ADMIN_PASSWORD)
    )


def authenticate():
    return Response(
        "Admin access requires authentication.",
        401,
        {"WWW-Authenticate": 'Basic realm="Admin Dashboard"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


# ---------------- HOME / SUBMIT ----------------

@app.route("/", methods=["GET", "POST"])
def submit():

    if request.method == "POST":

        validate_csrf()

        category = request.form.get("category", "")
        description = request.form.get("description", "").strip()

        if category not in VALID_CATEGORIES:
            abort(400, description="Invalid category.")

        if not description:
            abort(400, description="Description is required.")

        severity = calculate_severity(
            category,
            description
        )

        with get_db() as conn:
            tracking_id = generate_tracking_id(conn)

            conn.execute(
                """
                INSERT INTO grievances
                (tracking_id, category, description, status, severity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tracking_id,
                    category,
                    description,
                    "Received",
                    severity
                )
            )

            conn.commit()

        return render_template(
            "index.html",
            submitted=True,
            tracking_id=tracking_id,
            categories=VALID_CATEGORIES,
        )

    return render_template(
        "index.html",
        submitted=False,
        categories=VALID_CATEGORIES,
    )


# ---------------- STATUS ----------------

@app.route("/status", methods=["GET", "POST"])
def status():

    if request.method == "POST":

        validate_csrf()

        if status_rate_limited(request.remote_addr):
            abort(429, description="Too many attempts. Please try again later.")

        tracking_id = request.form.get("tracking_id", "").strip()

        with get_db() as conn:
            result = conn.execute(
                """
                SELECT category, status
                FROM grievances
                WHERE tracking_id = ?
                """,
                (tracking_id,)
            ).fetchone()

        if result:

            category, current_status = result

            return render_template(
                "status.html",
                found=True,
                tracking_id=tracking_id,
                category=category,
                status=current_status,
                statuses=VALID_STATUSES,
            )

        else:

            return render_template(
                "status.html",
                found=False
            )

    return render_template(
        "status.html",
        found=None
    )


# ---------------- ADMIN ----------------

@app.route("/admin", methods=["GET", "POST"])
@requires_auth
def admin():

    with get_db() as conn:

        if request.method == "POST":

            validate_csrf()

            tracking_id = request.form.get("tracking_id", "")
            new_status = request.form.get("new_status", "")

            if new_status not in VALID_STATUSES:
                abort(400, description="Invalid status.")

            cursor = conn.execute(
                """
                UPDATE grievances
                SET status = ?
                WHERE tracking_id = ?
                """,
                (new_status, tracking_id)
            )

            conn.commit()

            if cursor.rowcount:
                flash(f"{tracking_id} updated to \u201c{new_status}\u201d.", "success")
            else:
                flash(f"No grievance found with ID {tracking_id}.", "error")

        rows = conn.execute(
            """
            SELECT tracking_id,
                   category,
                   description,
                   status,
                   severity
            FROM grievances
            """
        ).fetchall()

    general_rows = [
        r for r in rows
        if r[1] not in SENSITIVE_CATEGORIES
    ]

    sensitive_rows = [
        r for r in rows
        if r[1] in SENSITIVE_CATEGORIES
    ]

    # Small, additive dashboard summary computed from data we already
    # fetched above - no schema or query changes required.
    stats = {
        "total": len(rows),
        "received": sum(1 for r in rows if r[3] == "Received"),
        "in_review": sum(1 for r in rows if r[3] == "In Review"),
        "resolved": sum(1 for r in rows if r[3] == "Resolved"),
        "sensitive": len(sensitive_rows),
    }

    return render_template(
        "admin.html",
        general_rows=general_rows,
        sensitive_rows=sensitive_rows,
        statuses=VALID_STATUSES,
        stats=stats,
    )


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=DEBUG)
