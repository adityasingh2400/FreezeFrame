#!/bin/bash
# Cloud box setup script — run once after SSH-ing in
# Usage: bash cloud_setup.sh
# Expected env: Ubuntu + CUDA, fresh RunPod/Lambda/Vast instance

set -e

WORKSPACE=/workspace
REPO_URL=https://github.com/adityasingh2400/Replay.git
BRANCH=divij

echo "=== Replay Cloud Setup ==="

# ── System deps ──────────────────────────────────────────────
echo "[1/5] Installing system deps..."
apt-get update -qq
apt-get install -y -qq colmap ffmpeg git python3-pip python3-venv

colmap -h 2>&1 | head -1
echo "  colmap ok"

# ── Repo ─────────────────────────────────────────────────────
echo "[2/5] Cloning repo..."
cd $WORKSPACE
if [ -d "Replay" ]; then
    echo "  Repo already exists, pulling latest..."
    cd Replay && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH
else
    git clone --branch $BRANCH $REPO_URL
    cd Replay
fi

# ── Python env ───────────────────────────────────────────────
echo "[3/5] Setting up Python environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q pycolmap numpy scipy opencv-python Pillow pyyaml

python3 -c "import pycolmap; print('  pycolmap', pycolmap.__version__)"

# ── Workspace dirs ───────────────────────────────────────────
echo "[4/5] Creating workspace dirs..."
mkdir -p scene/images scene/sparse/0 scene/dense output

# ── Verify scene data ────────────────────────────────────────
echo "[5/5] Checking for scene data..."
CAM_COUNT=$(find scene/images -maxdepth 1 -type d -name 'cam*' | wc -l)
if [ "$CAM_COUNT" -eq 0 ]; then
    echo "  WARNING: scene/images/ is empty — Arshia needs to drop frames here first."
    echo "  Path: $WORKSPACE/Replay/scene/images/"
else
    echo "  Found $CAM_COUNT camera dirs in scene/images/"
fi

echo ""
echo "=== Setup complete ==="
echo "  Activate env:  source $WORKSPACE/Replay/.venv/bin/activate"
echo "  Run COLMAP:    cd $WORKSPACE/Replay && python3 scripts/stage2_colmap.py"
echo "  (full pipeline with dense reconstruction — no --sparse-only needed here)"
