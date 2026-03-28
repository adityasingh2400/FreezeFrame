"""
backend/server.py
Base: 3dReal server_to_nerf.py (https://github.com/alexkranias/3dReal)
Changes from 3dReal marked with # NEW
"""

import os
import time
import subprocess
import glob

import firebase_admin
from firebase_admin import credentials, storage, firestore
from moviepy.editor import VideoFileClip, concatenate_videoclips

# NEW: Gemini
import google.generativeai as genai
import cv2


# ── Init ──────────────────────────────────────────────────────────────────────

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()                        # NEW: Firestore client for writing results
bucket = storage.bucket("replay-5ce56.firebasestorage.app")

genai.configure(api_key=os.environ["GEMINI_API_KEY"])  # NEW

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
        if frame_idx % int(fps) == 0:  # one frame per second
            _, buf = cv2.imencode(".jpg", frame)
            frame_data.append((frame_idx / fps, buf.tobytes()))
        frame_idx += 1
    cap.release()

    if not frame_data:
        return 0.0

    model = genai.GenerativeModel("gemini-2.0-flash")
    parts = []
    for ts, img_bytes in frame_data:
        parts.append(f"Frame at {ts:.1f}s:")
        parts.append({"mime_type": "image/jpeg", "data": img_bytes})

    response = model.generate_content([
        "These are frames from a sports video, one per second. "
        "Which timestamp (in seconds) shows the peak action moment — the dunk, catch, goal, or key play? "
        "Reply with only the number.",
        *parts
    ])

    try:
        return float(response.text.strip())
    except ValueError:
        return len(frame_data) / 2  # fallback: midpoint


def trim_video(input_path: str, output_path: str, center_ts: float, window: float = 3.0):
    """Trim video to [center_ts - window, center_ts + window] seconds."""
    cap = cv2.VideoCapture(input_path)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    cap.release()

    start = max(0, center_ts - window)
    end = min(duration, center_ts + window)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-c", "copy",
        output_path
    ], check=True)


# ── Reconstruction (replaces instant-ngp.exe call from 3dReal) ────────────────

def run_nerfstudio(video_path: str, work_dir: str) -> str:
    """
    Run nerfstudio pipeline on video. Returns path to rendered orbit.mp4.
    Replaces 3dReal's colmap2nerf.py + instant-ngp.exe calls.
    Install once on RunPod: pip install nerfstudio
    """
    processed_dir = os.path.join(work_dir, "processed")
    output_dir = os.path.join(work_dir, "output")
    orbit_path = os.path.join(work_dir, "orbit.mp4")

    # COLMAP + data processing (nerfstudio handles this internally)
    subprocess.run([
        "ns-process-data", "video",
        "--data", video_path,
        "--output-dir", processed_dir,
    ], check=True)

    # Train nerfacto (~10-15 min on A100)
    subprocess.run([
        "ns-train", "nerfacto",
        "--data", processed_dir,
        "--output-dir", output_dir,
        "--max-num-iterations", "10000",
    ], check=True)

    # Find the config file nerfstudio wrote
    config_files = glob.glob(os.path.join(output_dir, "**", "config.yml"), recursive=True)
    if not config_files:
        raise RuntimeError("nerfstudio config.yml not found after training")
    config_path = config_files[0]

    # Render orbit flyaround video
    subprocess.run([
        "ns-render", "interpolate",
        "--load-config", config_path,
        "--output-path", orbit_path,
        "--num-frames", "60",
    ], check=True)

    return orbit_path


# ── Main loop (from 3dReal, updated for Linux + result upload) ────────────────

def process_session(session_id: str, video_dir: str):
    """Download videos, run Gemini + nerfstudio, upload result."""

    # Concatenate clips — from 3dReal
    mov_files = [f for f in os.listdir(video_dir) if f.lower().endswith(".mov")]
    clips = [VideoFileClip(os.path.join(video_dir, f)).rotate(90) for f in mov_files]
    combined_path = os.path.join(video_dir, "combined.mp4")
    concatenate_videoclips(clips, method="compose").write_videofile(combined_path, codec="libx264")
    for c in clips:
        c.close()

    # NEW: Gemini peak moment → trim
    print("Detecting peak moment with Gemini...")
    peak_ts = detect_peak_moment(combined_path)
    print(f"  Peak moment at {peak_ts:.1f}s")
    trimmed_path = os.path.join(video_dir, "trimmed.mp4")
    trim_video(combined_path, trimmed_path, peak_ts)

    # NEW: nerfstudio (replaces instant-ngp.exe)
    print("Running nerfstudio reconstruction...")
    orbit_path = run_nerfstudio(trimmed_path, video_dir)

    # NEW: upload orbit.mp4 to Firebase Storage
    print("Uploading result...")
    result_blob = bucket.blob(f"results/{session_id}/orbit.mp4")
    result_blob.upload_from_filename(orbit_path, content_type="video/mp4")
    result_blob.make_public()
    result_url = result_blob.public_url

    # NEW: write result to Firestore so iOS app picks it up
    db.collection("sessions").document(session_id).set({
        "status": "done",
        "result_url": result_url,
    })
    print(f"Done. Result: {result_url}")


def loop(blobs):
    """From 3dReal — find most recent upload directory, download videos."""
    blobs = [b for b in blobs if len(b.name) == 62]
    most_recent = max((int(b.name[7:21]) for b in blobs), default=0)
    session_id = str(most_recent)

    video_dir = os.path.join("data", session_id)
    os.makedirs(video_dir, exist_ok=True)

    for blob in blobs:
        if session_id in blob.name:
            dest = os.path.join(video_dir, blob.name.split("/")[-1])
            blob.download_to_filename(dest)

    # NEW: write processing status before starting
    db.collection("sessions").document(session_id).set({"status": "processing"})

    process_session(session_id, video_dir)


# ── Polling loop — from 3dReal ────────────────────────────────────────────────

blobs = list(bucket.list_blobs(prefix="videos/"))

while True:
    curr_blobs = list(bucket.list_blobs(prefix="videos/"))
    print(f"check: {len(curr_blobs)} blobs (was {len(blobs)})")

    if len(curr_blobs) > len(blobs):
        loop(bucket.list_blobs(prefix="videos/"))

    blobs = list(bucket.list_blobs(prefix="videos/"))
    time.sleep(5)
