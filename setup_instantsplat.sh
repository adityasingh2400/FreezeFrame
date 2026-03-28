#!/bin/bash
set -euo pipefail

# ============================================================================
#  InstantSplat + Replay — RunPod Setup Script
#
#  Run this on a fresh RunPod instance (A100 recommended).
#  Installs InstantSplat (NVIDIA) with MASt3R for pose-free 3D reconstruction.
#
#  Usage:  bash setup_instantsplat.sh
#
#  After setup, run the pipeline:
#    python3 organize_timesteps.py --copy
#    python3 run_instantsplat.py --end 1        # test on 1 frame
#    python3 run_instantsplat.py                 # run all 80
#    python3 collect_for_viewer.py
# ============================================================================

WORKSPACE="/workspace"
INSTANTSPLAT_DIR="$WORKSPACE/InstantSplat"
REPLAY_DIR="$WORKSPACE/Replay"

echo ""
echo "========================================"
echo "  InstantSplat + Replay Setup"
echo "========================================"

# ── 1. System deps ───────────────────────────────────────────────────────
echo ""
echo "[1/6] Installing system dependencies..."
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq git wget unzip cmake build-essential \
    libgl1-mesa-glx libglib2.0-0 > /dev/null 2>&1
echo "  [OK] System deps installed"

# ── 2. Clone Replay ─────────────────────────────────────────────────────
echo ""
echo "[2/6] Setting up Replay repository..."
if [ ! -d "$REPLAY_DIR" ]; then
    cd "$WORKSPACE"
    git clone https://github.com/adityasingh2400/Replay.git
fi
cd "$REPLAY_DIR"
git fetch origin 2>/dev/null || true
git checkout instantsplat-pipeline 2>/dev/null || git checkout -b instantsplat-pipeline origin/instantsplat-pipeline
git pull origin instantsplat-pipeline 2>/dev/null || true
echo "  [OK] Replay repo at $REPLAY_DIR (branch: instantsplat-pipeline)"

# ── 3. Clone InstantSplat ───────────────────────────────────────────────
echo ""
echo "[3/6] Cloning InstantSplat..."
if [ ! -d "$INSTANTSPLAT_DIR" ]; then
    cd "$WORKSPACE"
    git clone --recursive https://github.com/NVlabs/InstantSplat.git
fi
cd "$INSTANTSPLAT_DIR"
echo "  [OK] InstantSplat at $INSTANTSPLAT_DIR"

# ── 4. Download MASt3R checkpoint ────────────────────────────────────────
echo ""
echo "[4/6] Downloading MASt3R checkpoint..."
mkdir -p mast3r/checkpoints
CKPT="mast3r/checkpoints/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth"
if [ ! -f "$CKPT" ]; then
    wget -q --show-progress \
        "https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth" \
        -O "$CKPT"
fi
echo "  [OK] MASt3R checkpoint ready ($(du -h "$CKPT" | cut -f1))"

# ── 5. Install Python dependencies ──────────────────────────────────────
echo ""
echo "[5/6] Installing Python dependencies..."

# PyTorch (skip if already installed with CUDA)
python3 -c "import torch; assert torch.cuda.is_available()" 2>/dev/null || {
    echo "  Installing PyTorch with CUDA..."
    pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu121
}

# InstantSplat requirements
if [ -f "$INSTANTSPLAT_DIR/requirements.txt" ]; then
    pip install -q -r "$INSTANTSPLAT_DIR/requirements.txt" 2>&1 | tail -1
fi

# CUDA submodules — these are critical
echo "  Building CUDA extensions (simple-knn, diff-gaussian-rasterization, fused-ssim)..."
cd "$INSTANTSPLAT_DIR"

for submod in submodules/simple-knn submodules/diff-gaussian-rasterization submodules/fused-ssim; do
    if [ -d "$submod" ]; then
        echo "    Installing $submod..."
        pip install -q "$submod" 2>&1 | tail -1 || echo "    [WARN] Failed to install $submod"
    fi
done

# RoPE CUDA kernels (optional but recommended for speed)
ROPE_DIR="mast3r/dust3r/croco/models/curope"
if [ -d "$ROPE_DIR" ] && [ ! -f "$ROPE_DIR/curope.so" ]; then
    echo "  Compiling RoPE CUDA kernels..."
    cd "$ROPE_DIR"
    python3 setup.py build_ext --inplace 2>/dev/null && echo "    [OK] RoPE compiled" || echo "    [WARN] RoPE compilation failed (non-critical)"
    cd "$INSTANTSPLAT_DIR"
fi

echo "  [OK] Python dependencies installed"

# ── 6. Validate ─────────────────────────────────────────────────────────
echo ""
echo "[6/6] Validating setup..."

GPU_NAME=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null || echo "UNKNOWN")
GPU_MEM=$(python3 -c "import torch; print(f'{torch.cuda.get_device_properties(0).total_mem / 1e9:.0f} GB')" 2>/dev/null || echo "?")
echo "  GPU: $GPU_NAME ($GPU_MEM)"

CHECKS_OK=true
for f in init_geo.py train.py render.py; do
    if [ -f "$INSTANTSPLAT_DIR/$f" ]; then
        echo "  [OK] $f"
    else
        echo "  [FAIL] $f not found"
        CHECKS_OK=false
    fi
done

if [ -f "$CKPT" ]; then
    echo "  [OK] MASt3R checkpoint"
else
    echo "  [FAIL] MASt3R checkpoint missing"
    CHECKS_OK=false
fi

# Check frame images
IMAGES_DIR="$REPLAY_DIR/scene/images"
if [ -d "$IMAGES_DIR/cam01" ]; then
    CAM_COUNT=$(ls -d "$IMAGES_DIR"/cam*/ 2>/dev/null | wc -l)
    FRAME_COUNT=$(ls "$IMAGES_DIR/cam01"/frame_*.jpg 2>/dev/null | wc -l)
    echo "  [OK] Frame images: $CAM_COUNT cameras, $FRAME_COUNT frames each"
else
    echo ""
    echo "  [ACTION NEEDED] Frame images not found!"
    echo "  Upload from your local machine:"
    echo "    scp -r scene/images/ root@<pod-ip>:<port>:$REPLAY_DIR/scene/images/"
fi

echo ""
if [ "$CHECKS_OK" = true ]; then
    echo "========================================"
    echo "  SETUP COMPLETE"
    echo "========================================"
    echo ""
    echo "  Run the pipeline:"
    echo "  ─────────────────"
    echo "  cd $REPLAY_DIR"
    echo ""
    echo "  # Step 1: Organize frames"
    echo "  python3 organize_timesteps.py --copy"
    echo ""
    echo "  # Step 2: Test on 1 timestep"
    echo "  python3 run_instantsplat.py --instantsplat-dir $INSTANTSPLAT_DIR --end 1"
    echo ""
    echo "  # Step 3: If test works, run all 80"
    echo "  python3 run_instantsplat.py --instantsplat-dir $INSTANTSPLAT_DIR"
    echo ""
    echo "  # Step 4: Collect for viewer"
    echo "  python3 collect_for_viewer.py"
    echo ""
    echo "========================================"
else
    echo "========================================"
    echo "  SETUP INCOMPLETE — fix issues above"
    echo "========================================"
fi
