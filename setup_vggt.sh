#!/bin/bash
set -euo pipefail

# ============================================================================
#  VGGT + Replay — Bulletproof RunPod Setup
#
#  Run on a fresh RunPod A100 instance (PyTorch 2.4 template).
#  Installs VGGT (Meta, CVPR 2025 Best Paper) for ~225x faster init vs MASt3R.
#
#  Usage:  bash setup_vggt.sh
#
#  After setup:
#    python3 pipeline_vggt.py --end 1          # test 1 frame
#    python3 pipeline_vggt.py --mode fast       # instant (no GS training)
#    python3 pipeline_vggt.py                   # full quality run
# ============================================================================

WORKSPACE="/workspace"
VGGT_DIR="$WORKSPACE/vggt"
INSTANTSPLAT_DIR="$WORKSPACE/InstantSplat"
REPLAY_DIR="$WORKSPACE/Replay"
SETUP_START=$(date +%s)

echo ""
echo "========================================"
echo "  VGGT + Replay — Full Setup"
echo "  Target: RunPod A100 80GB"
echo "========================================"

# ── 0. Pre-flight checks ────────────────────────────────────────────────
echo ""
echo "[0/8] Pre-flight checks..."

# GPU
python3 -c "import torch; assert torch.cuda.is_available()" 2>/dev/null || {
    echo "  [FATAL] No CUDA GPU detected. This script requires a GPU pod."
    exit 1
}
GPU_NAME=$(python3 -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null) || GPU_NAME="UNKNOWN"
GPU_MEM=$(python3 -c "import torch; m=torch.cuda.get_device_properties(0).total_mem; print(int(m/1e9))" 2>/dev/null) || GPU_MEM="?"
COMPUTE_CAP=$(python3 -c "import torch; print(torch.cuda.get_device_capability()[0])" 2>/dev/null) || COMPUTE_CAP="0"
echo "  GPU: $GPU_NAME (${GPU_MEM}GB VRAM, compute capability ${COMPUTE_CAP}.x)"

if [ "${COMPUTE_CAP:-0}" -lt 8 ] 2>/dev/null; then
    echo "  [WARN] Compute capability < 8.0 — bfloat16 not supported, will use float16 (slower)"
fi

# Disk space
AVAIL_GB=$(df -BG /workspace 2>/dev/null | tail -1 | awk '{print $4}' | tr -d 'G') || AVAIL_GB="0"
echo "  Disk: ${AVAIL_GB:-?}GB available on /workspace"
if [ "${AVAIL_GB:-0}" -lt 15 ] 2>/dev/null; then
    echo "  [WARN] Less than 15GB free. VGGT weights (~2GB) + repos (~5GB) + scene data may run tight."
fi

# PyTorch version
TORCH_VER=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null) || TORCH_VER="?"
CUDA_VER=$(python3 -c "import torch; print(torch.version.cuda)" 2>/dev/null) || CUDA_VER="?"
echo "  PyTorch: $TORCH_VER (CUDA $CUDA_VER)"
echo "  [OK] Pre-flight passed"


# ── 1. System deps ──────────────────────────────────────────────────────
echo ""
echo "[1/8] Installing system dependencies..."
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq \
    git wget unzip cmake build-essential ninja-build \
    libgl1-mesa-glx libglib2.0-0 > /dev/null 2>&1
echo "  [OK] git, cmake, ninja-build, build-essential installed"


# ── 2. Clone Replay ─────────────────────────────────────────────────────
echo ""
echo "[2/8] Setting up Replay repository..."
if [ ! -d "$REPLAY_DIR" ]; then
    cd "$WORKSPACE"
    git clone https://github.com/adityasingh2400/Replay.git
fi
cd "$REPLAY_DIR"
git fetch origin 2>/dev/null || true
git checkout instantsplat-pipeline 2>/dev/null || git checkout -b instantsplat-pipeline origin/instantsplat-pipeline
git pull origin instantsplat-pipeline 2>/dev/null || true
echo "  [OK] Replay at $REPLAY_DIR (branch: instantsplat-pipeline)"


# ── 3. Clone VGGT ──────────────────────────────────────────────────────
echo ""
echo "[3/8] Cloning VGGT (facebookresearch/vggt)..."
if [ ! -d "$VGGT_DIR" ]; then
    cd "$WORKSPACE"
    git clone https://github.com/facebookresearch/vggt.git
fi
cd "$VGGT_DIR"
echo "  [OK] VGGT at $VGGT_DIR"


# ── 4. Install VGGT Python dependencies ────────────────────────────────
echo ""
echo "[4/8] Installing VGGT dependencies..."

# Core VGGT deps (DO NOT upgrade torch/torchvision — use pre-installed versions)
pip install -q \
    huggingface_hub \
    einops \
    safetensors \
    Pillow \
    numpy \
    plyfile \
    tqdm \
    scipy \
    opencv-python-headless \
    2>&1 | tail -3

# Dependencies that open3d / matplotlib / InstantSplat need at import time.
# Without these the training subprocess dies on `import open3d` or `import matplotlib`.
echo "  Installing runtime deps for InstantSplat trainer..."
pip install -q \
    colorama \
    plotly \
    scikit-learn \
    addict \
    pandas \
    cycler \
    contourpy \
    kiwisolver \
    fonttools \
    pyparsing \
    2>&1 | tail -3
# dash pulls in Flask/Werkzeug; blinker conflict requires --ignore-installed
pip install -q --ignore-installed blinker dash 2>&1 | tail -3
echo "  [OK] Runtime deps installed"

# Install VGGT as editable package (--no-deps to avoid torch version conflicts)
cd "$VGGT_DIR"
if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
    pip install -q --no-deps -e . 2>&1 | tail -1
    echo "  [OK] VGGT installed as pip package"
else
    echo "  [INFO] No pyproject.toml — will use sys.path import"
fi

# Verify VGGT is importable
python3 -c "
import sys
sys.path.insert(0, '$VGGT_DIR')
from vggt.models.vggt import VGGT
from vggt.utils.load_fn import load_and_preprocess_images
from vggt.utils.pose_enc import pose_encoding_to_extri_intri
from vggt.utils.geometry import unproject_depth_map_to_point_map
print('  [OK] All VGGT modules importable')
" || {
    echo "  [FATAL] Cannot import VGGT modules"
    exit 1
}


# ── 5. Flash Attention (optional but ~2x faster) ───────────────────────
echo ""
echo "[5/8] Installing Flash Attention 2 (optional, for speed)..."
python3 -c "import flash_attn; print('  [OK] flash-attn already installed: ' + flash_attn.__version__)" 2>/dev/null || {
    echo "  Installing flash-attn (may take a few minutes if building from source)..."
    pip install -q flash-attn --no-build-isolation 2>&1 | tail -2 && {
        FA_VER=$(python3 -c "import flash_attn; print(flash_attn.__version__)" 2>/dev/null)
        echo "  [OK] flash-attn $FA_VER installed"
    } || {
        echo "  [WARN] flash-attn install failed. VGGT will use standard attention (slower but works)."
        echo "  This is non-critical — the pipeline will still run correctly."
    }
}


# ── 6. Pre-download VGGT model weights ──────────────────────────────────
echo ""
echo "[6/8] Downloading VGGT-1B weights (~2GB from HuggingFace)..."

# Try HuggingFace hub download first (caches to ~/.cache/huggingface/)
python3 -c "
from huggingface_hub import hf_hub_download
import os
path = hf_hub_download('facebook/VGGT-1B', 'model.pt')
size_gb = os.path.getsize(path) / 1e9
print(f'  [OK] VGGT-1B weights cached ({size_gb:.1f}GB): {path}')
" 2>&1 || {
    echo "  HuggingFace download failed. Trying direct URL..."
    # Fallback: direct URL download
    VGGT_WEIGHTS="$WORKSPACE/.cache/vggt/model.pt"
    mkdir -p "$(dirname "$VGGT_WEIGHTS")"
    if [ ! -f "$VGGT_WEIGHTS" ]; then
        wget -q --show-progress \
            "https://huggingface.co/facebook/VGGT-1B/resolve/main/model.pt" \
            -O "$VGGT_WEIGHTS" && {
            echo "  [OK] VGGT-1B weights downloaded to $VGGT_WEIGHTS"
        } || {
            echo "  [FATAL] Cannot download VGGT weights. Check network."
            exit 1
        }
    else
        echo "  [OK] VGGT weights already cached at $VGGT_WEIGHTS"
    fi
}


# ── 7. InstantSplat (for Gaussian training in quality mode) ────────────
echo ""
echo "[7/8] Setting up InstantSplat (Gaussian Splatting trainer)..."

if [ ! -d "$INSTANTSPLAT_DIR" ]; then
    cd "$WORKSPACE"
    git clone --recursive https://github.com/NVlabs/InstantSplat.git
fi
cd "$INSTANTSPLAT_DIR"

# Skip MASt3R checkpoint (replaced by VGGT, saves ~1.2GB)
echo "  Skipping MASt3R checkpoint download (replaced by VGGT)"

# Build CUDA extensions for Gaussian Splatting
echo "  Building CUDA extensions..."
CUDA_EXT_OK=true
for submod in submodules/simple-knn submodules/diff-gaussian-rasterization submodules/fused-ssim; do
    if [ -d "$submod" ]; then
        submod_name=$(basename "$submod")
        echo "    Building $submod_name..."
        pip install -q --no-build-isolation "$submod" 2>&1 | tail -1 && {
            echo "    [OK] $submod_name"
        } || {
            echo "    [WARN] $submod_name build failed"
            CUDA_EXT_OK=false
        }
    fi
done

# InstantSplat Python requirements
if [ -f "requirements.txt" ]; then
    # Install but don't let it mess with torch
    pip install -q --no-deps -r requirements.txt 2>&1 | tail -1 || true
fi

# Verify CUDA extensions
python3 -c "
try:
    import diff_gaussian_rasterization
    import simple_knn
    print('  [OK] CUDA extensions (diff-gaussian-rasterization, simple-knn)')
except ImportError as e:
    print(f'  [WARN] CUDA extension import failed: {e}')
    print('  Quality mode may not work. Fast mode will still work.')
" 2>/dev/null

echo "  [OK] InstantSplat at $INSTANTSPLAT_DIR (training only)"


# ── 8. Comprehensive smoke test ─────────────────────────────────────────
echo ""
echo "[8/8] Running smoke test..."

cd "$REPLAY_DIR"
python3 << 'SMOKE_TEST'
import sys, os, time, tempfile
import numpy as np

# Add VGGT to path
vggt_dir = "/workspace/vggt"
sys.path.insert(0, vggt_dir)

errors = []

# --- Test 1: VGGT imports ---
try:
    from vggt.models.vggt import VGGT
    from vggt.utils.load_fn import load_and_preprocess_images
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri
    from vggt.utils.geometry import unproject_depth_map_to_point_map
    print("  [OK] VGGT imports")
except ImportError as e:
    errors.append(f"VGGT import: {e}")
    print(f"  [FAIL] VGGT import: {e}")

# --- Test 2: Pipeline imports ---
try:
    from run_vggt_pipeline import (
        rotmat_to_qvec, write_cameras_bin, write_images_bin,
        write_points3D_bin, write_gaussian_ply, find_output_ply
    )
    print("  [OK] Pipeline imports")
except Exception as e:
    errors.append(f"Pipeline import: {e}")
    print(f"  [FAIL] Pipeline import: {e}")

# --- Test 3: COLMAP binary writers ---
try:
    with tempfile.TemporaryDirectory() as tmp:
        cams = [{"id": 1, "width": 1280, "height": 720, "fx": 800, "fy": 800, "cx": 640, "cy": 360}]
        imgs = [{"id": 1, "qvec": [1,0,0,0], "tvec": [0,0,0], "camera_id": 1, "name": "test.jpg"}]
        xyz = np.random.randn(1000, 3)
        rgb = np.random.randint(0, 255, (1000, 3), dtype=np.uint8)

        write_cameras_bin(os.path.join(tmp, "cameras.bin"), cams)
        write_images_bin(os.path.join(tmp, "images.bin"), imgs)
        write_points3D_bin(os.path.join(tmp, "points3D.bin"), xyz, rgb)

        rgb_f = rgb.astype(np.float32) / 255.0
        write_gaussian_ply(os.path.join(tmp, "test.ply"), xyz, rgb_f)

        for f in ["cameras.bin", "images.bin", "points3D.bin", "test.ply"]:
            assert os.path.getsize(os.path.join(tmp, f)) > 0, f"{f} is empty"
    print("  [OK] COLMAP + PLY writers")
except Exception as e:
    errors.append(f"Writers: {e}")
    print(f"  [FAIL] Writers: {e}")

# --- Test 4: Load VGGT model ---
try:
    import torch
    t0 = time.time()
    device = "cuda"
    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    model = VGGT.from_pretrained("facebook/VGGT-1B").to(device)
    model.eval()
    load_time = time.time() - t0
    print(f"  [OK] VGGT model loaded in {load_time:.1f}s (dtype={dtype})")

    # Quick inference on tiny dummy images to verify forward pass
    t0 = time.time()
    dummy = torch.randn(1, 2, 3, 518, 518, device=device)  # 2 fake images
    with torch.no_grad():
        with torch.cuda.amp.autocast(dtype=dtype):
            agg, ps_idx = model.aggregator(dummy)
        pose_enc = model.camera_head(agg)[-1]
        ext, intr = pose_encoding_to_extri_intri(pose_enc, dummy.shape[-2:])
    infer_time = time.time() - t0
    print(f"  [OK] VGGT inference test passed in {infer_time:.2f}s")
    print(f"       Extrinsic shape: {ext.shape}, Intrinsic shape: {intr.shape}")

    # Free GPU memory
    del model, dummy, agg, ps_idx, pose_enc, ext, intr
    torch.cuda.empty_cache()

except Exception as e:
    errors.append(f"VGGT model: {e}")
    print(f"  [FAIL] VGGT model: {e}")

# --- Test 5: InstantSplat train.py exists ---
trainer_path = "/workspace/InstantSplat/train.py"
if os.path.exists(trainer_path):
    print(f"  [OK] InstantSplat train.py found")
else:
    print(f"  [WARN] InstantSplat train.py not found (quality mode won't work, fast mode OK)")

# --- Summary ---
if errors:
    print(f"\n  SMOKE TEST: {len(errors)} FAILURE(S)")
    for e in errors:
        print(f"    - {e}")
    sys.exit(1)
else:
    print(f"\n  SMOKE TEST: ALL PASSED")
SMOKE_TEST

SMOKE_OK=$?

# ── Check for scene images ──────────────────────────────────────────────
IMAGES_DIR="$REPLAY_DIR/scene/images"
if [ -d "$IMAGES_DIR/cam01" ]; then
    CAM_COUNT=$(ls -d "$IMAGES_DIR"/cam*/ 2>/dev/null | wc -l | tr -d ' ')
    FRAME_COUNT=$(ls "$IMAGES_DIR/cam01"/frame_*.jpg 2>/dev/null | wc -l | tr -d ' ')
    echo ""
    echo "  [OK] Scene images found: $CAM_COUNT cameras, $FRAME_COUNT frames each"
else
    echo ""
    echo "  [ACTION NEEDED] Scene images not uploaded yet."
    echo "  Upload from your local machine:"
    echo "    scp -r scene/images/ root@<pod-ip>:<port>:$REPLAY_DIR/scene/images/"
fi

# ── Final summary ───────────────────────────────────────────────────────
SETUP_END=$(date +%s)
SETUP_TIME=$((SETUP_END - SETUP_START))

echo ""
if [ "$SMOKE_OK" -eq 0 ]; then
    echo "========================================"
    echo "  SETUP COMPLETE (${SETUP_TIME}s)"
    echo "========================================"
    echo ""
    echo "  Components installed:"
    echo "    VGGT-1B ............. camera poses + point clouds (~0.15s for 4 views)"
    echo "    InstantSplat ........ Gaussian Splatting training"
    echo "    Flash Attention ..... optional speed boost for VGGT"
    echo ""
    echo "  Optimizations built in:"
    echo "    Warm-starting ....... init from previous frame (100 iter vs 200)"
    echo "    Keyframe system ..... full re-init every 10 frames"
    echo "    Multi-GPU ........... --multi-gpu flag for parallel processing"
    echo ""
    echo "  Run the pipeline:"
    echo "  ─────────────────"
    echo "  cd $REPLAY_DIR"
    echo ""
    echo "  # 1. Test on 1 frame"
    echo "  python3 pipeline_vggt.py --end 1"
    echo ""
    echo "  # 2. Fast mode (VGGT-only, instant)"
    echo "  python3 pipeline_vggt.py --mode fast"
    echo ""
    echo "  # 3. Full quality — single GPU (~9 min)"
    echo "  python3 pipeline_vggt.py"
    echo ""
    echo "  # 4. Full quality — multi-GPU (~2 min on 4xA100)"
    echo "  python3 pipeline_vggt.py --multi-gpu"
    echo ""
    echo "========================================"
else
    echo "========================================"
    echo "  SETUP FAILED — see errors above"
    echo "========================================"
    exit 1
fi
