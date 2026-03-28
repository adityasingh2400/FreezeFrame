#!/bin/bash
# Run Stage 3 InstantSplat training, upload results, terminate pod
#
# USAGE (on the RunPod):
#   cd /workspace/Replay
#   bash scripts/run_stage3.sh
#
# Runs in foreground with live progress. Safe to Ctrl+C and re-run — resumes
# automatically because stage3_instantsplat.py skips completed frames.
#
# What it does:
#   1. Trains InstantSplat on all 80 timesteps (~55 min on A100)
#   2. Uploads output/frames/*.ply to Hugging Face
#   3. Pushes output_meta.json + HF dataset URL to git
#   4. Terminates the pod (saves money)

set -e
WORKSPACE=/workspace
REPLAY_DIR=$WORKSPACE/Replay

# Load credentials from .env.pod
if [ -f "$REPLAY_DIR/.env.pod" ]; then
    source "$REPLAY_DIR/.env.pod"
else
    echo "ERROR: .env.pod not found. Run cloud_setup_instantsplat.sh first."
    exit 1
fi

# Branch safety check — never run on wrong branch
cd $REPLAY_DIR
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "divij" ]; then
    echo "ERROR: On branch '$CURRENT_BRANCH', expected 'divij'. Aborting."
    exit 1
fi
echo "Branch: $CURRENT_BRANCH @ $(git log --oneline -1)"
echo ""

# ── Step 1: Train ─────────────────────────────────────────────
echo "=== Step 1/3: Training (80 frames) ==="
echo "Started: $(date)"
echo "Log: /tmp/stage3.log"
echo ""

export INSTANTSPLAT_DIR
python scripts/stage3_instantsplat.py 2>&1 | tee /tmp/stage3.log

FRAME_COUNT=$(ls output/frames/frame_*.ply 2>/dev/null | wc -l)
echo ""
echo "Training done: $FRAME_COUNT PLY files in output/frames/"

if [ "$FRAME_COUNT" -eq 0 ]; then
    echo "ERROR: No PLY files produced. Check /tmp/stage3.log"
    exit 1
fi

# ── Step 2: Upload to Hugging Face ───────────────────────────
echo ""
echo "=== Step 2/3: Uploading $FRAME_COUNT PLY files to Hugging Face ==="
echo "Started: $(date)"

HF_REPO="adityasingh2400/replay-stage3-output"

python - << PYEOF
import os, json
from huggingface_hub import HfApi, create_repo

token = os.environ["HF_TOKEN"]
repo_id = "$HF_REPO"
api = HfApi()

# Create repo if it doesn't exist
try:
    create_repo(repo_id, repo_type="dataset", private=True, token=token)
    print(f"  Created HF dataset: {repo_id}")
except Exception:
    print(f"  Using existing HF dataset: {repo_id}")

# Upload all PLY files
import glob
ply_files = sorted(glob.glob("output/frames/frame_*.ply"))
print(f"  Uploading {len(ply_files)} files...")

api.upload_folder(
    folder_path="output/frames",
    repo_id=repo_id,
    repo_type="dataset",
    path_in_repo="frames",
    token=token,
)
print(f"  Upload complete")

# Update output_meta.json with HF URL
meta_path = "output/output_meta.json"
if os.path.exists(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)
else:
    meta = {}

meta["hf_dataset"] = repo_id
meta["hf_frames_path"] = "frames"
with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)
print(f"  Updated output_meta.json with HF dataset URL")
PYEOF

# ── Step 3: Push metadata to git ─────────────────────────────
echo ""
echo "=== Step 3/3: Pushing metadata to git ==="

git config user.email "pod@runpod.io"
git config user.name "RunPod Stage3"

# output_meta.json is gitignored — untrack the ignore for this one file
git add -f output/output_meta.json

FRAME_COUNT=$(ls output/frames/frame_*.ply 2>/dev/null | wc -l)
git commit -m "Add Stage 3 InstantSplat output_meta.json ($FRAME_COUNT frames, HF dataset: adityasingh2400/replay-stage3-output)"

# Push using token
REPO_WITH_TOKEN=$(git remote get-url origin | sed "s|https://|https://x-access-token:${GITHUB_TOKEN:-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}@|")
git push "$REPO_WITH_TOKEN" divij
echo "  Pushed to GitHub"

# ── Done — terminate pod ──────────────────────────────────────
echo ""
echo "=== All done at $(date) ==="
echo "  $FRAME_COUNT PLY files on Hugging Face: https://huggingface.co/datasets/$HF_REPO"
echo "  Metadata pushed to git (divij branch)"
echo ""
echo "Terminating pod in 30 seconds... Ctrl+C to cancel."
sleep 30

POD_ID="${RUNPOD_POD_ID}"
if [ -n "$POD_ID" ]; then
    echo "Terminating pod $POD_ID..."
    runpodctl remove pod "$POD_ID"
else
    echo "RUNPOD_POD_ID not set — stop the pod manually in RunPod UI."
fi
