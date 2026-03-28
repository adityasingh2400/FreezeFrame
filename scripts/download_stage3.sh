#!/bin/bash
# Download Stage 3 PLY output from Hugging Face to local output/frames/
#
# USAGE (run locally, from repo root):
#   export HF_TOKEN=your_hf_token
#   bash scripts/download_stage3.sh

set -e

if [ -z "$HF_TOKEN" ]; then
    echo "ERROR: HF_TOKEN not set."
    echo "  export HF_TOKEN=your_token && bash scripts/download_stage3.sh"
    exit 1
fi

HF_REPO="adityasingh2400/replay-stage3-output"

echo "Downloading Stage 3 PLY files from Hugging Face..."
echo "Repo: $HF_REPO"
echo ""

# Use Python huggingface_hub to download
python3 - << PYEOF
import os
from huggingface_hub import snapshot_download

token = os.environ["HF_TOKEN"]
repo_id = "$HF_REPO"

local_dir = snapshot_download(
    repo_id=repo_id,
    repo_type="dataset",
    local_dir="output/hf_download",
    token=token,
)
print(f"Downloaded to: {local_dir}")

# Move frames into output/frames/
import shutil, glob
from pathlib import Path

frames_src = Path(local_dir) / "frames"
frames_dst = Path("output/frames")
frames_dst.mkdir(parents=True, exist_ok=True)

ply_files = sorted(frames_src.glob("frame_*.ply"))
print(f"Moving {len(ply_files)} PLY files to output/frames/...")
for f in ply_files:
    shutil.copy2(f, frames_dst / f.name)

print(f"Done: {len(ply_files)} files in output/frames/")
PYEOF

echo ""
echo "Validating Contract C..."
python3 scripts/validate_contracts.py c
