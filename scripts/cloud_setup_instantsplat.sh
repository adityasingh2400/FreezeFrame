#!/bin/bash
# Fresh pod setup for Replay Stage 3 (InstantSplat)
#
# USAGE:
#   export RUNPOD_API_KEY=your_key_here
#   export HF_TOKEN=your_huggingface_token_here
#   bash cloud_setup_instantsplat.sh
#
# Expected pod: RunPod PyTorch template, A100 80GB, 50GB disk

set -e

WORKSPACE=/workspace
REPO_URL=https://github.com/adityasingh2400/Replay.git
BRANCH=divij
INSTANTSPLAT_DIR=$WORKSPACE/InstantSplat

# ── Validate required env vars ────────────────────────────────
if [ -z "$RUNPOD_API_KEY" ]; then
    echo "ERROR: RUNPOD_API_KEY not set."
    echo "  export RUNPOD_API_KEY=your_key && bash cloud_setup_instantsplat.sh"
    exit 1
fi
if [ -z "$HF_TOKEN" ]; then
    echo "ERROR: HF_TOKEN not set."
    echo "  export HF_TOKEN=your_hf_token && bash cloud_setup_instantsplat.sh"
    exit 1
fi

echo "=== Replay Stage 3 — InstantSplat Setup ==="
echo ""

# ── 1. Clone Replay (divij only) ─────────────────────────────
echo "[1/6] Cloning Replay repo (branch: $BRANCH)..."
cd $WORKSPACE
if [ -d "Replay" ]; then
    cd Replay && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH
else
    git clone --branch $BRANCH --single-branch $REPO_URL && cd Replay
fi

CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    echo "ERROR: On branch '$CURRENT_BRANCH', expected '$BRANCH'. Aborting."
    exit 1
fi
echo "  OK: $CURRENT_BRANCH @ $(git log --oneline -1)"

# ── 2. Install InstantSplat ───────────────────────────────────
echo ""
echo "[2/6] Installing InstantSplat..."
cd $WORKSPACE

if [ ! -d "$INSTANTSPLAT_DIR" ]; then
    git clone --recursive https://github.com/NVlabs/InstantSplat $INSTANTSPLAT_DIR
else
    echo "  Already cloned — updating..."
    cd $INSTANTSPLAT_DIR && git pull && git submodule update --init --recursive
fi

cd $INSTANTSPLAT_DIR
grep -v "^blinker" requirements.txt | pip install -q -r /dev/stdin
echo "  Building diff-gaussian-rasterization (CUDA, ~3 min)..."
pip install -q submodules/diff-gaussian-rasterization
echo "  Building simple-knn..."
pip install -q submodules/simple-knn
echo "  InstantSplat OK"

# ── 3. Download MASt3R checkpoint (~1GB) ─────────────────────
echo ""
echo "[3/6] Downloading MASt3R checkpoint..."
mkdir -p $INSTANTSPLAT_DIR/checkpoints
CKPT=$INSTANTSPLAT_DIR/checkpoints/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth

if [ ! -f "$CKPT" ]; then
    wget --show-progress -q \
        "https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth" \
        -O "$CKPT"
    echo "  Downloaded: $(du -sh $CKPT | cut -f1)"
else
    echo "  Already exists ($(du -sh $CKPT | cut -f1))"
fi

# ── 4. Install Hugging Face + runpodctl ──────────────────────
echo ""
echo "[4/6] Installing upload + pod management tools..."
pip install -q huggingface_hub pyyaml numpy pillow

# Install runpodctl for pod self-termination
curl -fsSL "https://github.com/runpod/runpodctl/releases/download/v1.14.3/runpodctl-linux-amd64" \
    -o /usr/local/bin/runpodctl
chmod +x /usr/local/bin/runpodctl
runpodctl config --apiKey "$RUNPOD_API_KEY"
echo "  runpodctl OK (pod id: ${RUNPOD_POD_ID:-not set})"

# ── 5. Save credentials to pod-local env file ────────────────
echo ""
echo "[5/6] Saving credentials..."
cat > $WORKSPACE/Replay/.env.pod << EOF
INSTANTSPLAT_DIR=$INSTANTSPLAT_DIR
RUNPOD_API_KEY=$RUNPOD_API_KEY
HF_TOKEN=$HF_TOKEN
EOF
chmod 600 $WORKSPACE/Replay/.env.pod
echo "  Credentials saved to .env.pod"

# ── 6. Smoke test ─────────────────────────────────────────────
echo ""
echo "[6/6] Smoke test..."
cd $INSTANTSPLAT_DIR
python -c "
import torch
print(f'  PyTorch {torch.__version__}')
print(f'  CUDA: {torch.cuda.is_available()}')
print(f'  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"none\"}')
"

CAM_COUNT=$(find $WORKSPACE/Replay/scene/images -maxdepth 1 -type d -name 'cam*' 2>/dev/null | wc -l)
FRAME_COUNT=$(ls $WORKSPACE/Replay/scene/images/cam01/ 2>/dev/null | wc -l || echo 0)
echo "  Scene: $CAM_COUNT cameras, $FRAME_COUNT frames"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Now run the training:"
echo "  cd $WORKSPACE/Replay && bash scripts/run_stage3.sh"
