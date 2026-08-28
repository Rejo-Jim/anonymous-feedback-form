import os
import secrets
import sqlite3
import string
import subprocess
import time
from contextlib import contextmanager
from difflib import SequenceMatcher
from functools import wraps

from flask import (
    Flask,
    request,
    render_template,
    session,
    abort,
    Response,
    flash,
    send_from_directory,
    url_for,
)
from PIL import Image, ImageOps

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

VALID_RATINGS = {1, 2, 3, 4, 5}

# Anonymous-safe complaint linking (see find_similar_complaint below).
# difflib.SequenceMatcher ratio at/above this is treated as "possibly the
# same underlying issue".
SIMILARITY_THRESHOLD = 0.5

SENSITIVE_CATEGORIES = ["Harassment", "Bullying"]

TRACKING_ID_ALPHABET = string.ascii_uppercase + string.digits

# ---------------- ATTACHMENTS ----------------

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}

# 25 MB cap on the whole request body, not just the file - keeps large
# uploads from tying up memory/disk. Flask turns this into a 413 automatically.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


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
                severity INTEGER,
                attachment TEXT
            )
            """
        )
        # Migrate older databases created before the attachment column existed.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(grievances)")}
        if "attachment" not in existing_cols:
            conn.execute("ALTER TABLE grievances ADD COLUMN attachment TEXT")

        # Migrate older databases created before anonymous-safe complaint
        # linking existed. similar_tracking_id points at the closest
        # matching prior grievance (same category); similarity_score is
        # the difflib ratio (0-1) that produced that match. Neither column
        # stores or implies anything about who submitted either grievance.
        if "similar_tracking_id" not in existing_cols:
            conn.execute("ALTER TABLE grievances ADD COLUMN similar_tracking_id TEXT")
        if "similarity_score" not in existing_cols:
            conn.execute("ALTER TABLE grievances ADD COLUMN similarity_score REAL")

        # General site feedback is intentionally a separate, simpler table:
        # no tracking ID, no status, nothing that ties it back to a person
        # or a specific grievance.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rating INTEGER,
                message TEXT,
                submitted_at TEXT
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


# ---------------- COMPLAINT LINKING (anonymous-safe) ----------------
# Flags when a new grievance's description looks like it might describe
# the same underlying issue as an existing one, so admins can notice
# related reports. The comparison uses ONLY description text and
# category - nothing that could identify who filed either grievance
# (this app never collects that data in the first place).

def find_similar_complaint(conn, category, description):
    """Compares `description` against existing grievances in the same
    `category` using difflib's SequenceMatcher. Returns
    (tracking_id, score) for the closest match at or above
    SIMILARITY_THRESHOLD, or (None, None) if nothing matches closely
    enough."""
    existing = conn.execute(
        "SELECT tracking_id, description FROM grievances WHERE category = ?",
        (category,)
    ).fetchall()

    new_description = description.lower()

    best_tracking_id = None
    best_score = 0.0

    for tracking_id, existing_description in existing:
        score = SequenceMatcher(
            None,
            new_description,
            (existing_description or "").lower()
        ).ratio()

        if score >= SIMILARITY_THRESHOLD and score > best_score:
            best_score = score
            best_tracking_id = tracking_id

    if best_tracking_id:
        return best_tracking_id, best_score
    return None, None


# ---------------- ATTACHMENT HANDLING ----------------
# Uploading a photo/video is optional. Whatever is uploaded is re-saved
# with its metadata stripped before it ever touches disk, since phone
# photos/videos routinely embed GPS coordinates, device model, and
# timestamps in EXIF/container metadata - exactly the kind of detail
# that could de-anonymize a submitter.

def attachment_kind(filename):
    """Returns ('image'|'video', extension) for an allowed filename, or
    (None, None) if the extension isn't recognized."""
    if "." not in filename:
        return None, None
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image", ext
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video", ext
    return None, None


def strip_image_metadata(file_storage, dest_path):
    """Rebuilds the image from raw pixel data only, so EXIF (including
    GPS), ICC, and XMP metadata never reaches the saved copy."""
    with Image.open(file_storage) as img:
        img.load()
        # Bake in any rotation encoded in the EXIF orientation tag before
        # that tag is discarded, so the stripped image still looks right.
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        clean = Image.frombytes(img.mode, img.size, img.tobytes())
        save_kwargs = {"quality": 90} if dest_path.lower().endswith((".jpg", ".jpeg")) else {}
        clean.save(dest_path, **save_kwargs)


def strip_video_metadata(src_path, dest_path):
    """Uses ffmpeg to drop container/stream metadata (device model, GPS,
    creation time, etc.) without re-encoding the audio/video streams."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src_path,
            "-map_metadata", "-1",
            "-c", "copy",
            "-movflags", "+faststart",
            dest_path,
        ],
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0 or not os.path.exists(dest_path):
        raise RuntimeError("ffmpeg failed to process video")


def save_attachment(file_storage):
    """Validates, strips metadata from, and stores an uploaded image or
    video. Returns (stored_filename, kind), or (None, None) if no file
    was provided. Raises ValueError on an invalid/unsupported upload."""
    if not file_storage or not file_storage.filename:
        return None, None

    kind, ext = attachment_kind(file_storage.filename)
    if kind is None:
        raise ValueError(
            "Unsupported file type. Please upload an image (PNG, JPG, "
            "WEBP) or video (MP4, MOV, WEBM)."
        )

    stored_name = f"{secrets.token_hex(16)}.{ext}"
    dest_path = os.path.join(UPLOAD_FOLDER, stored_name)

    if kind == "image":
        try:
            strip_image_metadata(file_storage, dest_path)
        except Exception:
            raise ValueError("That image couldn't be processed. Please try a different file.")
    else:
        tmp_path = os.path.join(UPLOAD_FOLDER, f".tmp-{secrets.token_hex(16)}.{ext}")
        try:
            file_storage.save(tmp_path)
            strip_video_metadata(tmp_path, dest_path)
        except Exception:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise ValueError("That video couldn't be processed. Please try a different file.")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return stored_name, kind


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

        try:
            attachment_name, attachment_kind_ = save_attachment(request.files.get("attachment"))
        except ValueError as e:
            abort(400, description=str(e))

        severity = calculate_severity(
            category,
            description
        )

        with get_db() as conn:
            tracking_id = generate_tracking_id(conn)

            # Anonymous-safe: compares only category + description against
            # existing grievances, before this one is inserted (so it can
            # never match itself). Never touches identity/IP/session data.
            similar_tracking_id, similarity_score = find_similar_complaint(
                conn, category, description
            )

            conn.execute(
                """
                INSERT INTO grievances
                (tracking_id, category, description, status, severity, attachment,
                 similar_tracking_id, similarity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tracking_id,
                    category,
                    description,
                    "Received",
                    severity,
                    attachment_name,
                    similar_tracking_id,
                    similarity_score
                )
            )

            conn.commit()

        return render_template(
            "index.html",
            submitted=True,
            tracking_id=tracking_id,
            categories=VALID_CATEGORIES,
            attachment=attachment_name,
            attachment_kind=attachment_kind_,
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


# ---------------- FEEDBACK ----------------
# General feedback about the portal itself (not a specific grievance).
# Deliberately has no tracking ID and no status - it's not meant to be
# followed up on individually, just read by admins in aggregate.

@app.route("/feedback", methods=["GET", "POST"])
def feedback():

    if request.method == "POST":

        validate_csrf()

        rating_raw = request.form.get("rating", "").strip()
        message = request.form.get("message", "").strip()

        rating = None
        if rating_raw:
            if not rating_raw.isdigit() or int(rating_raw) not in VALID_RATINGS:
                abort(400, description="Invalid rating.")
            rating = int(rating_raw)

        if not message and rating is None:
            abort(400, description="Please add a message or a rating.")

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO feedback (rating, message, submitted_at)
                VALUES (?, ?, ?)
                """,
                (
                    rating,
                    message or None,
                    time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
                )
            )
            conn.commit()

        return render_template("feedback.html", submitted=True)

    return render_template("feedback.html", submitted=False)


# ---------------- UNRESOLVED-BY-CATEGORY CHART (admin dashboard) ----------------
# Pie/donut of current unresolved caseload, grouped by category. Resolved
# grievances are excluded by the SQL query itself (WHERE status != 'Resolved'),
# not filtered out afterwards - see the query in the admin() route below.
# Drawn with a single CSS conic-gradient, so no charting library is needed.

CATEGORY_CHART_COLORS = {
    "Harassment": "var(--brick)",
    "Bullying": "var(--brick-light)",
    "Academic": "var(--navy)",
    "Hostel": "var(--amber)",
    "Infrastructure": "var(--slate)",
    "Other": "var(--sage)",
}


def build_unresolved_category_chart(category_counts):
    """category_counts is the result of a query already filtered to
    unresolved statuses only: [(category, count), ...]. Returns chart
    data covering every known category (zero-filled if absent) so the
    legend is stable even as categories go in and out of use."""
    counts = {cat: 0 for cat in VALID_CATEGORIES}
    for category, count in category_counts:
        if category in counts:
            counts[category] = count

    total = sum(counts.values())
    stops = []
    slices = []
    cumulative = 0

    for cat in VALID_CATEGORIES:
        count = counts[cat]
        color = CATEGORY_CHART_COLORS.get(cat, "var(--slate)")
        if count:
            start_deg = (cumulative / total) * 360 if total else 0
            cumulative += count
            end_deg = (cumulative / total) * 360 if total else 0
            stops.append(f"{color} {start_deg:.2f}deg {end_deg:.2f}deg")
        slices.append({"label": cat, "count": count, "color": color})

    gradient_css = ", ".join(stops) if stops else "var(--line) 0deg 360deg"

    return {
        "slices": slices,
        "total": total,
        "gradient_css": gradient_css,
    }


# ---------------- ATTACHMENT SERVING ----------------

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Stored filenames are always server-generated random tokens (see
    # save_attachment) - the path is never built from user input, so this
    # can't be used to traverse or guess other files on disk.
    return send_from_directory(UPLOAD_FOLDER, filename)


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
                   severity,
                   attachment,
                   similar_tracking_id,
                   similarity_score
            FROM grievances
            """
        ).fetchall()

        feedback_rows = conn.execute(
            """
            SELECT rating, message, submitted_at
            FROM feedback
            ORDER BY id DESC
            """
        ).fetchall()

        # Unresolved-only, grouped by category, straight from SQL - not
        # filtered client-side and not filtered after the fact in Python.
        unresolved_category_counts = conn.execute(
            """
            SELECT category, COUNT(*)
            FROM grievances
            WHERE status != 'Resolved'
            GROUP BY category
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

    category_chart = build_unresolved_category_chart(unresolved_category_counts)

    return render_template(
        "admin.html",
        general_rows=general_rows,
        sensitive_rows=sensitive_rows,
        statuses=VALID_STATUSES,
        stats=stats,
        category_chart=category_chart,
        feedback_rows=feedback_rows,
    )


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=DEBUG)