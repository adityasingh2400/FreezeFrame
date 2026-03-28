#!/bin/bash
set -euo pipefail

# ┌──────────────────────────────────────────────────────────────────┐
# │  Replay — One-Shot RunPod Training Script                       │
# │                                                                  │
# │  Clones the repo + 4DGaussians, installs deps, restructures     │
# │  COLMAP output, runs fast + quality training, exports PLYs.      │
# │                                                                  │
# │  Usage: SSH into RunPod, then:                                   │
# │    git clone https://github.com/adityasingh2400/Replay.git \    │
# │      /workspace/Replay                                           │
# │    cd /workspace/Replay && bash runpod_setup.sh                  │
# │                                                                  │
# │  Expects: RunPod PyTorch 2.x template, CUDA 11.8+, A100/A6000   │
# └──────────────────────────────────────────────────────────────────┘

WORKSPACE="/workspace"
REPO_DIR="$WORKSPACE/Replay"
FOURDGS_DIR="$REPO_DIR/4DGaussians"
DATA_DIR="$FOURDGS_DIR/data/multipleview/replay"
GITHUB_REPO="https://github.com/adityasingh2400/Replay.git"
FOURDGS_REPO="https://github.com/hustvl/4DGaussians.git"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

timer_start() { TIMER_START=$(date +%s); }
timer_end()   {
    local elapsed=$(( $(date +%s) - TIMER_START ))
    echo -e "${GREEN}[DONE]${NC} $1 in ${elapsed}s ($(( elapsed / 60 ))m $(( elapsed % 60 ))s)"
}

SCRIPT_START=$(date +%s)

# ── 0. Sanity checks ────────────────────────────────────────────────

log "Checking GPU..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || fail "No GPU found"
echo ""

log "Checking CUDA..."
nvcc --version | grep "release" || fail "nvcc not found"
echo ""

# ── 1. Clone repos ──────────────────────────────────────────────────

if [ -d "$REPO_DIR/.git" ]; then
    log "Replay repo exists, pulling latest..."
    cd "$REPO_DIR" && git pull --ff-only || true
else
    log "Cloning Replay repo..."
    git clone "$GITHUB_REPO" "$REPO_DIR"
fi
cd "$REPO_DIR"
ok "Replay repo at $REPO_DIR"

if [ -d "$FOURDGS_DIR/.git" ]; then
    log "4DGaussians already cloned"
else
    log "Cloning 4DGaussians..."
    git clone --recursive "$FOURDGS_REPO" "$FOURDGS_DIR"
fi
ok "4DGaussians at $FOURDGS_DIR"

# Copy our custom training configs into 4DGaussians
cp configs/replay.py "$FOURDGS_DIR/arguments/multipleview/replay.py"
cp configs/replay_fast.py "$FOURDGS_DIR/arguments/multipleview/replay_fast.py"
ok "Custom configs copied"
echo ""

# ── 2. Install Python packages ──────────────────────────────────────

log "Installing Python packages..."

TORCH_VERSION=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null || echo "none")
CUDA_AVAIL=$(python3 -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
log "PyTorch: $TORCH_VERSION, CUDA: $CUDA_AVAIL"

if [ "$CUDA_AVAIL" != "True" ]; then
    fail "PyTorch CUDA not available. Use a PyTorch GPU template."
fi

pip install -q plyfile lpips pytorch_msssim "imageio[ffmpeg]" open3d scikit-image matplotlib tqdm opencv-python-headless

TORCH_SHORT=$(python3 -c "import torch; v=torch.__version__.split('+')[0].rsplit('.',1)[0]; print(v)")
CUDA_SHORT=$(python3 -c "import torch; print(torch.version.cuda.replace('.','')[:3])")
log "Installing mmcv for torch=$TORCH_SHORT cuda=$CUDA_SHORT..."
pip install -q mmcv==1.6.0 2>/dev/null || \
  pip install -q mmcv-full -f "https://download.openmmlab.com/mmcv/dist/cu${CUDA_SHORT}/torch${TORCH_SHORT}/index.html" 2>/dev/null || \
  pip install -q mmcv || \
  warn "mmcv install failed — will try to proceed anyway"
ok "Python packages"
echo ""

# ── 3. Build CUDA extensions ────────────────────────────────────────

log "Building 4DGS CUDA extensions..."
cd "$FOURDGS_DIR"

git submodule update --init --recursive 2>/dev/null || true

cd submodules/depth-diff-gaussian-rasterization
pip install -q . 2>&1 | tail -2
ok "diff-gaussian-rasterization"

cd "$FOURDGS_DIR/submodules/simple-knn"
pip install -q . 2>&1 | tail -2
ok "simple-knn"

cd "$REPO_DIR"
echo ""

# ── 4. Restructure COLMAP data ──────────────────────────────────────

log "Restructuring COLMAP → 4DGS MultipleView format..."

# Verify frame images exist (they should be in git)
CAM_COUNT=0
for cam in cam02 cam03 cam04; do
    n=$(ls scene/images/$cam/frame_*.jpg 2>/dev/null | wc -l)
    if [ "$n" -gt 0 ]; then
        CAM_COUNT=$((CAM_COUNT + 1))
    else
        warn "No frames in scene/images/$cam/"
    fi
done
[ "$CAM_COUNT" -eq 0 ] && fail "No frame images found. Cannot train."

python3 restructure_for_4dgs.py \
    --scene-dir scene \
    --output-dir "$DATA_DIR" \
    --image-dir scene/images

ok "Data ready at $DATA_DIR"
echo ""

# ── 5. Verify ────────────────────────────────────────────────────────

log "Verifying data layout..."
for f in sparse_/images.bin sparse_/cameras.bin points3D_multipleview.ply; do
    [ -f "$DATA_DIR/$f" ] && [ -s "$DATA_DIR/$f" ] && ok "$f" || fail "Missing: $f"
done
for cam in cam02 cam03 cam04; do
    d="$DATA_DIR/$cam"
    if [ -d "$d" ] || [ -L "$d" ]; then
        ok "$cam/ ($(ls "$d"/frame_*.jpg 2>/dev/null | wc -l) frames)"
    fi
done
echo ""

# ── 6. FAST smoke test (validates data before quality run) ───────

log "=== SMOKE TEST (3k iters, ~2 min — verifying data loads) ==="
timer_start
cd "$FOURDGS_DIR"

python3 train.py \
    -s data/multipleview/replay \
    --port 6017 \
    --expname "multipleview/replay_fast" \
    --configs arguments/multipleview/replay_fast.py

timer_end "Smoke test"
ok "Data loads correctly — proceeding to quality training"
echo ""

# ── 7. QUALITY training (the real run) ───────────────────────────

log "=== QUALITY TRAINING (batch=2, 14k iters — full convergence) ==="
timer_start

python3 train.py \
    -s data/multipleview/replay \
    --port 6018 \
    --expname "multipleview/replay" \
    --configs arguments/multipleview/replay.py

timer_end "Quality training"
echo ""

# ── 8. Export per-frame PLYs from quality model ──────────────────

log "Exporting per-frame PLYs (quality)..."
QUAL_MODEL="$FOURDGS_DIR/output/multipleview/replay"
QUAL_ITER=$(ls -1 "$QUAL_MODEL/point_cloud/" 2>/dev/null | grep "iteration_" | sed 's/iteration_//' | sort -n | tail -1)

python3 export_perframe_3DGS.py \
    --iteration "$QUAL_ITER" \
    --configs arguments/multipleview/replay.py \
    --model_path "$QUAL_MODEL"

QUAL_EXPORT="$QUAL_MODEL/gaussian_pertimestamp"
QUAL_COUNT=$(ls "$QUAL_EXPORT"/time_*.ply 2>/dev/null | wc -l)
ok "Quality: $QUAL_COUNT per-frame PLYs exported"
echo ""

# ── 9. Generate viewer manifest ──────────────────────────────────────

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
print(f'Manifest: {len(ns)} frames')
"
ok "Viewer manifest ready"
echo ""

# ── 10. Summary ──────────────────────────────────────────────────────

TOTAL_ELAPSED=$(( $(date +%s) - SCRIPT_START ))

echo ""
echo "============================================================"
echo "  REPLAY — TRAINING COMPLETE"
echo "  Total time: $(( TOTAL_ELAPSED / 60 ))m $(( TOTAL_ELAPSED % 60 ))s"
echo "============================================================"
echo ""
echo "  Quality model: $QUAL_MODEL"
echo "  Per-frame PLYs: $QUAL_EXPORT ($QUAL_COUNT frames)"
echo "  Viewer PLYs:   $VIEWER_FRAMES"
echo ""
echo "  Download to your laptop (fill in PORT and POD_IP from RunPod):"
echo "    scp -P PORT -r root@POD_IP:/workspace/Replay/viewer/public/frames/ ./viewer/public/frames/"
echo "    scp -P PORT root@POD_IP:/workspace/Replay/viewer/public/manifest.json ./viewer/public/"
echo ""
echo "  Then locally:  cd viewer && npm run dev"
echo "============================================================"
