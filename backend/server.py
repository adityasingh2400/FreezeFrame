"""
backend/server.py
Base: 3dReal server_to_nerf.py (https://github.com/alexkranias/3dReal)
Changes from 3dReal marked with # NEW
"""

import os
import time
import subprocess
import glob
import base64

from dotenv import load_dotenv
load_dotenv()  # loads .env from current directory

import firebase_admin
from firebase_admin import credentials, storage, firestore
from moviepy.editor import VideoFileClip, concatenate_videoclips

# NEW: Gemini
import google.generativeai as genai
import cv2


# ── Init ──────────────────────────────────────────────────────────────────────

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db     = firestore.client()
bucket = storage.bucket("replay-5ce56.firebasestorage.app")

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

original_dir = os.getcwd()


# ── NEW: Gemini peak moment detection ─────────────────────────────────────────

def detect_peak_moment(video_path: str) -> float:
    """Send 1fps frames to Gemini Flash, return timestamp of peak sports action."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_data = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % int(fps) == 0:
            _, buf = cv2.imencode(".jpg", frame)
            frame_data.append((frame_idx / fps, buf.tobytes()))
        frame_idx += 1
    cap.release()

    if not frame_data:
        return 0.0

    model = genai.GenerativeModel("gemini-2.0-flash")

    # Build parts: text label + inline image for each frame
    parts = ["These are frames from a sports video, one per second. "
             "Which timestamp (in seconds) shows the peak action moment — "
             "the dunk, catch, goal, or key play? Reply with only the number."]

    for ts, img_bytes in frame_data:
        parts.append(f"Frame at {ts:.1f}s:")
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode("utf-8"),
            }
        })

    response = model.generate_content(parts)

    try:
        return float(response.text.strip())
    except ValueError:
        return frame_data[len(frame_data) // 2][0]  # fallback: midpoint


def trim_video(input_path: str, output_path: str, center_ts: float, window: float = 3.0):
    """Trim video to [center_ts - window, center_ts + window] seconds."""
    cap = cv2.VideoCapture(input_path)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.release()

    start = max(0, center_ts - window)
    end   = min(duration, center_ts + window)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-c", "copy",
        output_path,
    ], check=True)


# ── Reconstruction ────────────────────────────────────────────────────────────

def run_nerfstudio(video_path: str, work_dir: str) -> str:
    """Run nerfstudio pipeline on video. Returns path to rendered orbit.mp4."""
    processed_dir = os.path.join(work_dir, "processed")
    output_dir    = os.path.join(work_dir, "output")
    orbit_path    = os.path.join(work_dir, "orbit.mp4")

    subprocess.run([
        "ns-process-data", "video",
        "--data", video_path,
        "--output-dir", processed_dir,
    ], check=True)

    subprocess.run([
        "ns-train", "nerfacto",
        "--data", processed_dir,
        "--output-dir", output_dir,
        "--max-num-iterations", "10000",
    ], check=True)

    # Find config.yml written by nerfstudio
    config_files = glob.glob(os.path.join(output_dir, "**", "config.yml"), recursive=True)
    if not config_files:
        raise RuntimeError("nerfstudio config.yml not found after training")
    config_path = sorted(config_files)[-1]  # latest if multiple

    subprocess.run([
        "ns-render", "interpolate",
        "--load-config", config_path,
        "--output-path", orbit_path,
        "--num-frames", "60",
    ], check=True)

    return orbit_path


# ── Main pipeline ─────────────────────────────────────────────────────────────

def process_session(session_id: str, video_dir: str):
    """Concatenate → Gemini peak → trim → nerfstudio → upload result."""

    mov_files = [f for f in os.listdir(video_dir) if f.lower().endswith(".mov")]
    if not mov_files:
        print(f"No .mov files in {video_dir}, skipping.")
        return

    print(f"Processing session {session_id} ({len(mov_files)} clips)...")

    clips = [VideoFileClip(os.path.join(video_dir, f)) for f in mov_files]
    combined_path = os.path.join(video_dir, "combined.mp4")
    concatenate_videoclips(clips, method="compose").write_videofile(combined_path, codec="libx264")
    for c in clips:
        c.close()

    print("Detecting peak moment with Gemini...")
    peak_ts = detect_peak_moment(combined_path)
    print(f"  Peak moment: {peak_ts:.1f}s")

    trimmed_path = os.path.join(video_dir, "trimmed.mp4")
    trim_video(combined_path, trimmed_path, peak_ts)

    print("Running nerfstudio reconstruction (~10-15 min on A100)...")
    orbit_path = run_nerfstudio(trimmed_path, video_dir)

    print("Uploading result...")
    result_blob = bucket.blob(f"results/{session_id}/orbit.mp4")
    result_blob.upload_from_filename(orbit_path, content_type="video/mp4")
    result_blob.make_public()
    result_url = result_blob.public_url

    db.collection("sessions").document(session_id).set({
        "status": "done",
        "result_url": result_url,
    })
    print(f"Done. Result: {result_url}")


def get_session_id(blob_name: str):
    """Extract session ID from blob path: videos/{sessionId}/{file} → sessionId"""
    parts = blob_name.split("/")
    if len(parts) >= 3 and parts[0] == "videos":
        try:
            int(parts[1])   # session IDs are numeric timestamps
            return parts[1]
        except ValueError:
            pass
    return None


def loop(blobs):
    """Find most recent session, download its videos, process."""
    sessions = {}
    for blob in blobs:
        sid = get_session_id(blob.name)
        if sid:
            sessions.setdefault(sid, []).append(blob)

    if not sessions:
        return

    session_id = max(sessions.keys())  # most recent timestamp
    video_dir  = os.path.join("data", session_id)
    os.makedirs(video_dir, exist_ok=True)

    for blob in sessions[session_id]:
        dest = os.path.join(video_dir, blob.name.split("/")[-1])
        if not os.path.exists(dest):
            blob.download_to_filename(dest)

    db.collection("sessions").document(session_id).set({"status": "processing"})
    process_session(session_id, video_dir)


# ── Polling loop ──────────────────────────────────────────────────────────────

blobs = list(bucket.list_blobs(prefix="videos/"))
print(f"Backend started. Watching for uploads ({len(blobs)} existing blobs)...")

while True:
    curr_blobs = list(bucket.list_blobs(prefix="videos/"))
    print(f"check: {len(curr_blobs)} blobs (was {len(blobs)})")

    if len(curr_blobs) > len(blobs):
        loop(curr_blobs)

    blobs = curr_blobs
    time.sleep(5)
