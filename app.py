from flask import Flask, request, jsonify, render_template, send_file, abort, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, UnidentifiedImageError, ImageFile
import pillow_heif
import os
import json
from datetime import datetime
import uuid
import fcntl

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 75_000_000  # ~12k x 6k; adjust if you expect larger

pillow_heif.register_heif_opener()

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Public (served by Nginx):
PUBLIC_STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(PUBLIC_STATIC_DIR, "uploads")        # WebP output here

# Private (NOT served by Nginx):
ORIGINALS_DIR = os.path.join(BASE_DIR, "storage", "originals") # Raw originals here

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ORIGINALS_DIR, exist_ok=True)

PHOTOS_JSON = os.path.join(BASE_DIR, "photos.json")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "heic", "heif"}

# -------- Helpers --------

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def _read_photos_unlocked() -> list:
    if not os.path.exists(PHOTOS_JSON):
        return []
    try:
        with open(PHOTOS_JSON, "r", encoding="utf-8") as f:
            data = f.read().strip()
            return json.loads(data) if data else []
    except Exception:
        return []

def _uploads_today_count(photos: list, client_ip: str, today_prefix: str) -> int:
    """
    Count entries uploaded today by this client_ip.
    today_prefix is 'YYYY-MM-DD' (matches start of ISO datetime).
    """
    cnt = 0
    for p in photos:
        if p.get("client_ip") == client_ip:
            ts = p.get("uploaded_at", "")
            if ts.startswith(today_prefix):
                cnt += 1
    return cnt

def _append_photo_locked_with_quota(entry: dict, client_ip: str, daily_limit: int = 20) -> bool:
    """
    Re-check quota under lock and append if still under limit.
    Returns True if appended, False if quota exceeded.
    """
    today_prefix = datetime.now().isoformat(timespec="seconds")[:10]  # 'YYYY-MM-DD'
    with open(PHOTOS_JSON, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read().strip()
            photos = json.loads(raw) if raw else []
            # Count again inside the lock to avoid races
            if _uploads_today_count(photos, client_ip, today_prefix) >= daily_limit:
                return False
            photos.append(entry)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(photos, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
            return True
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def _resize_to_720p_box(img: Image.Image) -> Image.Image:
    """
    Resize to fit within ~720p for fast delivery:
    - Fits inside 1280x720 while keeping aspect ratio.
    - Never upscales smaller images.
    """
    img = ImageOps.exif_transpose(img)  # normalize orientation
    max_w, max_h = 1280, 720
    w, h = img.size
    scale = min(max_w / w, max_h / h, 1.0)  # <=1.0 prevents upscaling
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
    return img

def _save_webp(src_path: str, dest_path: str) -> None:
    with Image.open(src_path) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        im = _resize_to_720p_box(im)  # <- updated
        im.save(dest_path, "WEBP", quality=75, method=4)

def _client_ip() -> str:
    """
    Best-effort client IP behind reverse proxy.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # format: "client, proxy1, proxy2"
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.remote_addr or "0.0.0.0"

# -------- Routes --------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    DAILY_LIMIT = 20
    client_ip = _client_ip()
    today_prefix = datetime.now().isoformat(timespec="seconds")[:10]  # 'YYYY-MM-DD'

    # --- quick quota pre-check (no lock) ---
    photos_snapshot = _read_photos_unlocked()
    if _uploads_today_count(photos_snapshot, client_ip, today_prefix) >= DAILY_LIMIT:
        return jsonify(success=False, error="Tageslimit erreicht (max. 20 Uploads pro Tag)."), 429

    # --- size limit (20 MB) ---
    max_bytes = 20 * 1024 * 1024
    clen = request.content_length or 0
    if clen > max_bytes:
        return jsonify(success=False, error="Datei zu groß (max 20 MB)"), 413

    # get file
    file = request.files.get("file")
    mission_number = (request.form.get("mission_number") or "").strip()
    mission_desc = (request.form.get("mission_desc") or "").strip()

    if not file or file.filename == "":
        return jsonify(success=False, error="Keine Datei übermittelt"), 400
    if not allowed_file(file.filename):
        return jsonify(success=False, error="Nicht unterstützter Dateityp"), 400

    photo_id = uuid.uuid4().hex
    original_name = secure_filename(file.filename)
    orig_ext = os.path.splitext(original_name)[1].lower() or ".jpg"

    # Save original first (private) — but we will enforce quota again before recording
    original_filename = f"{photo_id}{orig_ext}"
    original_path = os.path.join(ORIGINALS_DIR, original_filename)
    file.save(original_path)

    # Validate as real image, check dimensions >= 100x100, fix orientation in memory
    try:
        with Image.open(original_path) as im:
            im = ImageOps.exif_transpose(im)  # normalize orientation
            w, h = im.size
            if w < 100 or h < 100:
                os.remove(original_path)
                return jsonify(success=False, error="Bild zu klein (mind. 100x100 px)"), 400
    except UnidentifiedImageError:
        try: os.remove(original_path)
        except Exception: pass
        return jsonify(success=False, error="Ungültige Bilddatei"), 400
    except Exception as e:
        try: os.remove(original_path)
        except Exception: pass
        return jsonify(success=False, error=f"Bildvalidierung fehlgeschlagen: {e}"), 400

    # Create WebP (public)
    webp_filename = f"{photo_id}.webp"
    webp_path = os.path.join(UPLOAD_DIR, webp_filename)
    try:
        _save_webp(original_path, webp_path)
    except Exception as e:
        try: os.remove(original_path)
        except Exception: pass
        return jsonify(success=False, error=f"Bildverarbeitung fehlgeschlagen: {e}"), 500

    now = datetime.now().isoformat(timespec="seconds")
    has_mission = bool(mission_desc)
    entry = {
        "id": photo_id,
        "url": f"/static/uploads/{webp_filename}",
        "download_url": f"/download/{photo_id}",
        "name": original_name,
        "original_ext": orig_ext,
        "mission_number": mission_number,
        "mission_desc": mission_desc,
        "has_mission": has_mission,
        "uploaded_at": now,
        "client_ip": client_ip,           # <-- record who uploaded
    }

    # --- final quota enforcement under lock ---
    appended = _append_photo_locked_with_quota(entry, client_ip, daily_limit=DAILY_LIMIT)
    if not appended:
        # Quota was reached between pre-check and now; clean up saved files
        try: os.remove(original_path)
        except Exception: pass
        try: os.remove(webp_path)
        except Exception: pass
        return jsonify(success=False, error="Tageslimit erreicht (max. 20 Uploads pro Tag)."), 429

    return jsonify(success=True, photo=entry)

@app.route("/photos")
def photos():
    items = _read_photos_unlocked()
    items.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
    return jsonify(items)

@app.route("/download/<photo_id>")
def download(photo_id):
    # Try to find the original; if entry recorded original_ext we can prefer that.
    entry = next((p for p in _read_photos_unlocked() if p.get("id") == photo_id), None)
    if entry:
        cand = os.path.join(ORIGINALS_DIR, f"{photo_id}{entry.get('original_ext', '')}")
        if os.path.exists(cand):
            return send_file(cand, as_attachment=True, download_name=entry.get("name") or os.path.basename(cand))

    # Fallback: probe common extensions
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"):
        p = os.path.join(ORIGINALS_DIR, f"{photo_id}{ext}")
        if os.path.exists(p):
            return send_file(p, as_attachment=True, download_name=os.path.basename(p))
    abort(404)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
