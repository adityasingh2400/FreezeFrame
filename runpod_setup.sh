#!/bin/bash
set -euo pipefail

# ┌──────────────────────────────────────────────────────────────────┐
# │  Replay — One-Shot RunPod Training Script (v2)                  │
# │                                                                  │
# │  Tested on: A100 SXM (PyTorch 2.4 template, CUDA 12.4)         │
# │  Requires: NVIDIA Ampere+ GPU, PyTorch pre-installed            │
# │                                                                  │
# │  Usage:                                                          │
# │    git clone -b aditya/training \                                │
# │      https://github.com/adityasingh2400/Replay.git \            │
# │      /workspace/Replay                                           │
# │    cd /workspace/Replay && bash runpod_setup.sh                  │
# └──────────────────────────────────────────────────────────────────┘

WORKSPACE="/workspace"
REPO_DIR="$WORKSPACE/Replay"
FOURDGS_DIR="$REPO_DIR/4DGaussians"
DATA_DIR="$FOURDGS_DIR/data/multipleview/replay"
FOURDGS_REPO="https://github.com/hustvl/4DGaussians.git"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
timer_start() { TIMER_START=$(date +%s); }
timer_end()   { echo -e "${GREEN}[DONE]${NC} $1 in $(( ($(date +%s)-TIMER_START)/60 ))m $(( ($(date +%s)-TIMER_START)%60 ))s"; }

PIP="pip install --break-system-packages --root-user-action=ignore -q"
SCRIPT_START=$(date +%s)

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: ENVIRONMENT VALIDATION
# ═══════════════════════════════════════════════════════════════════

log "Checking GPU..."
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null) || fail "No GPU"
GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null)
ok "$GPU_NAME ($GPU_MEM)"

log "Checking PyTorch..."
TORCH_VER=$(python3 -c "import torch; print(torch.__version__)")
CUDA_OK=$(python3 -c "import torch; print(torch.cuda.is_available())")
[ "$CUDA_OK" = "True" ] || fail "PyTorch CUDA not available"
ok "PyTorch $TORCH_VER, CUDA OK"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: CLONE & PATCH
# ═══════════════════════════════════════════════════════════════════

cd "$REPO_DIR"

if [ -d "$FOURDGS_DIR/.git" ]; then
    log "4DGaussians already cloned"
else
    log "Cloning 4DGaussians..."
    git clone --recursive "$FOURDGS_REPO" "$FOURDGS_DIR"
fi
ok "4DGaussians at $FOURDGS_DIR"

log "Copying custom configs..."
cp configs/replay.py "$FOURDGS_DIR/arguments/multipleview/replay.py"
cp configs/replay_fast.py "$FOURDGS_DIR/arguments/multipleview/replay_fast.py"
ok "Configs copied"

log "Patching 4DGS for headless container..."
python3 patch_4dgs.py "$FOURDGS_DIR"
ok "Patches applied"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: INSTALL DEPENDENCIES (all at once, torch-safe)
# ═══════════════════════════════════════════════════════════════════

log "Recording torch version: $TORCH_VER"

log "Installing Python packages (--no-deps to protect torch)..."
$PIP --no-deps \
    plyfile \
    lpips \
    pytorch_msssim \
    "imageio[ffmpeg]" \
    tqdm \
    opencv-python-headless \
    tensorboard 2>&1 | grep -v "already satisfied" | tail -5

log "Installing packages with deps (torch-safe)..."
$PIP --ignore-installed \
    pyparsing cycler kiwisolver fonttools contourpy \
    matplotlib 2>&1 | grep -v "already satisfied" | tail -3
$PIP scipy 2>&1 | tail -2
$PIP scikit-image 2>&1 | tail -2

log "Installing open3d + its deps..."
$PIP --no-deps open3d 2>&1 | tail -2
$PIP plotly dash pandas scikit-learn 2>&1 | tail -3

# Verify torch wasn't clobbered
TORCH_AFTER=$(python3 -c "import torch; print(torch.__version__)")
if [ "$TORCH_VER" != "$TORCH_AFTER" ]; then
    warn "Torch changed $TORCH_VER → $TORCH_AFTER, restoring..."
    CUDA_TAG=$(python3 -c "v='$TORCH_VER'; print(v.split('+')[1] if '+' in v else 'cu124')")
    $PIP "torch==$TORCH_VER" --index-url "https://download.pytorch.org/whl/$CUDA_TAG" 2>&1 | tail -2
fi
ok "Python packages installed, torch: $(python3 -c 'import torch; print(torch.__version__)')"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 4: BUILD CUDA EXTENSIONS
# ═══════════════════════════════════════════════════════════════════

log "Building CUDA extensions..."
cd "$FOURDGS_DIR"
git submodule update --init --recursive 2>/dev/null || true

log "  Building diff-gaussian-rasterization..."
cd submodules/depth-diff-gaussian-rasterization
pip install --break-system-packages --root-user-action=ignore --no-build-isolation -q . 2>&1 | tail -3
ok "diff-gaussian-rasterization"

log "  Building simple-knn..."
cd "$FOURDGS_DIR/submodules/simple-knn"
pip install --break-system-packages --root-user-action=ignore --no-build-isolation -q . 2>&1 | tail -3
ok "simple-knn"
cd "$REPO_DIR"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 5: VERIFY ALL IMPORTS
# ═══════════════════════════════════════════════════════════════════

log "Verifying all imports..."
python3 -c "
failed = []
checks = [
    'import torch',
    'import torchvision',
    'import numpy',
    'from tqdm import tqdm',
    'from PIL import Image',
    'from plyfile import PlyData',
    'import cv2',
    'import lpips',
    'import open3d',
    'import imageio',
    'import matplotlib; matplotlib.use(\"Agg\"); import matplotlib.pyplot',
    'import scipy',
    'import diff_gaussian_rasterization',
    'from simple_knn._C import distCUDA2',
]
for c in checks:
    name = c.split()[1].split('.')[0]
    try:
        exec(c)
    except Exception as e:
        failed.append(f'{name}: {e}')

import torch
print(f'  torch={torch.__version__} cuda={torch.cuda.is_available()}')
print(f'  {len(checks)-len(failed)}/{len(checks)} OK')
if failed:
    for f in failed:
        print(f'  FAIL: {f}')
    raise SystemExit(1)
" || fail "Import verification failed"
ok "All imports verified"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 6: RESTRUCTURE COLMAP DATA
# ═══════════════════════════════════════════════════════════════════

log "Restructuring COLMAP → 4DGS MultipleView format..."
python3 restructure_for_4dgs.py \
    --scene-dir scene \
    --output-dir "$DATA_DIR" \
    --image-dir scene/images
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 7: SMOKE TEST (3k iters, ~2 min)
# ═══════════════════════════════════════════════════════════════════

log "=== SMOKE TEST (3k iters — verifying training works) ==="
timer_start
cd "$FOURDGS_DIR"

python3 train.py \
    -s data/multipleview/replay \
    --port 6017 \
    --expname "multipleview/replay_fast" \
    --configs arguments/multipleview/replay_fast.py

timer_end "Smoke test"
ok "Smoke test passed — data + training pipeline works"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 8: QUALITY TRAINING (14k iters)
# ═══════════════════════════════════════════════════════════════════

log "=== QUALITY TRAINING (14k iters, batch=2 — full convergence) ==="
timer_start

python3 train.py \
    -s data/multipleview/replay \
    --port 6018 \
    --expname "multipleview/replay" \
    --configs arguments/multipleview/replay.py

timer_end "Quality training"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 9: EXPORT PER-FRAME PLYs
# ═══════════════════════════════════════════════════════════════════

log "Exporting per-frame PLYs..."
QUAL_MODEL="$FOURDGS_DIR/output/multipleview/replay"
QUAL_ITER=$(ls -1 "$QUAL_MODEL/point_cloud/" 2>/dev/null | grep "iteration_" | sed 's/iteration_//' | sort -n | tail -1)

python3 export_perframe_3DGS.py \
    --iteration "$QUAL_ITER" \
    --configs arguments/multipleview/replay.py \
    --model_path "$QUAL_MODEL"

QUAL_EXPORT="$QUAL_MODEL/gaussian_pertimestamp"
QUAL_COUNT=$(ls "$QUAL_EXPORT"/time_*.ply 2>/dev/null | wc -l)
ok "$QUAL_COUNT per-frame PLYs exported"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 10: GENERATE VIEWER MANIFEST
# ═══════════════════════════════════════════════════════════════════

log "Generating viewer manifest..."
cd "$REPO_DIR"

VIEWER_FRAMES="$REPO_DIR/viewer/public/frames"
mkdir -p "$VIEWER_FRAMES"
cp "$QUAL_EXPORT"/time_*.ply "$VIEWER_FRAMES/"

python3 -c "
import json, glob, os, time as t
d = '$VIEWER_FRAMES'
ps = sorted(glob.glob(os.path.join(d, 'time_*.ply')))
ns = [os.path.basename(p) for p in ps]
m = {'frames': ns, 'fps': 30, 'baseDir': '/frames/',
     'hero_frame': len(ns)//3, 'total_frames': len(ns),
     'generated_at': t.strftime('%Y-%m-%d %H:%M:%S')}
with open(os.path.join(os.path.dirname(d), 'manifest.json'), 'w') as f:
    json.dump(m, f, indent=2)
print(f'  {len(ns)} frames in manifest')
"
ok "Viewer manifest ready"
echo ""

# ═══════════════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════════════

TOTAL=$(( $(date +%s) - SCRIPT_START ))
echo "============================================================"
echo "  REPLAY — TRAINING COMPLETE"
echo "  Total: $(( TOTAL / 60 ))m $(( TOTAL % 60 ))s"
echo "============================================================"
echo ""
echo "  Quality model: $QUAL_MODEL"
echo "  PLYs: $QUAL_EXPORT ($QUAL_COUNT frames)"
echo "  Viewer: $VIEWER_FRAMES"
echo ""
echo "  Download to laptop:"
echo "    scp -P PORT -r root@POD_IP:$VIEWER_FRAMES/ ./viewer/public/frames/"
echo "    scp -P PORT root@POD_IP:$REPO_DIR/viewer/public/manifest.json ./viewer/public/"
echo ""
echo "  Then: cd viewer && npm run dev"
echo "============================================================"
