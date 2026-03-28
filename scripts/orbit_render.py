#!/usr/bin/env python3
"""
orbit_render.py — Render 4DGS model from 8 orbit angles × all time steps.

Run from /workspace/4DGaussians:
    python /workspace/Replay/scripts/orbit_render.py \
        -m output/jumpingjacks \
        --configs arguments/dnerf/jumpingjacks.py

Output:
    /workspace/Replay/output/multiview/az{0-7}/frame_{t:05d}.png
    /workspace/Replay/output/multiview/meta.json
"""

import os, sys, copy, json, math
import numpy as np
import torch
from pathlib import Path
from PIL import Image
from tqdm import tqdm

GS4D_ROOT = Path("/workspace/4DGaussians")
REPLAY_OUT = Path("/workspace/Replay/output/multiview")
sys.path.insert(0, str(GS4D_ROOT))

N_ANGLES = 8   # evenly-spaced orbit positions

from argparse import ArgumentParser
from arguments import ModelParams, PipelineParams, get_combined_args
from gaussian_renderer import render, GaussianModel
from scene import Scene
from scene.cameras import Camera
from utils.general_utils import safe_state


def get_video_cameras(scene):
    """Try multiple ways to get the video/orbit cameras."""
    for attr in ["getVideoCameras", "getVideoCamera"]:
        if hasattr(scene, attr):
            cams = getattr(scene, attr)()
            if cams:
                return cams
    # Fallback: check internal dict
    for attr in ["video_cameras", "_video_cameras"]:
        if hasattr(scene, attr):
            d = getattr(scene, attr)
            if isinstance(d, dict):
                return list(d.values())[0] if d else []
            return d
    return []


def clone_camera_at_time(base_cam, t, uid):
    """Create a copy of base_cam with a different time value."""
    # Get R and T — handle numpy or tensor
    R = base_cam.R
    T = base_cam.T
    if isinstance(R, torch.Tensor):
        R = R.cpu().numpy()
    if isinstance(T, torch.Tensor):
        T = T.cpu().numpy()

    dummy = torch.zeros(3, base_cam.image_height, base_cam.image_width)
    return Camera(
        colmap_id=base_cam.colmap_id,
        R=R,
        T=T,
        FoVx=base_cam.FoVx,
        FoVy=base_cam.FoVy,
        image=dummy,
        gt_alpha_mask=None,
        image_name=f"orbit_uid{uid}",
        uid=uid,
        time=t,
    )


def main():
    parser = ArgumentParser()
    mp = ModelParams(parser, sentinel=True)
    pp = PipelineParams(parser)
    parser.add_argument("--iteration", default=-1, type=int)
    parser.add_argument("--configs",   type=str, required=True)
    args = get_combined_args(parser)

    safe_state(False)

    print("[ORBIT] Loading model...")
    gaussians = GaussianModel(args.sh_degree)
    scene = Scene(args, gaussians, load_iteration=args.iteration, shuffle=False)
    bg = torch.tensor([1,1,1] if args.white_background else [0,0,0],
                      dtype=torch.float32, device="cuda")

    # ── Get orbit cameras ──────────────────────────────────────────────────────
    video_cams = get_video_cameras(scene)
    if not video_cams:
        print("[ORBIT] No video cameras found, using test cameras")
        video_cams = scene.getTestCameras()
    if not video_cams:
        print("[ORBIT] ERROR: no cameras found"); return

    print(f"[ORBIT] Found {len(video_cams)} video cameras")

    # Sample N_ANGLES evenly from the orbit
    n = len(video_cams)
    orbit_cams = [video_cams[int(i * n / N_ANGLES)] for i in range(N_ANGLES)]

    # ── Get time steps ─────────────────────────────────────────────────────────
    train_cams = scene.getTrainCameras()
    all_times = sorted(set(round(float(c.time), 6) for c in train_cams))
    # Cap at 150 frames
    if len(all_times) > 150:
        step = len(all_times) // 150
        all_times = all_times[::step][:150]

    print(f"[ORBIT] {len(all_times)} time steps × {N_ANGLES} angles = {len(all_times)*N_ANGLES} frames")

    REPLAY_OUT.mkdir(parents=True, exist_ok=True)

    # ── Render grid ────────────────────────────────────────────────────────────
    for ai, base_cam in enumerate(orbit_cams):
        out_dir = REPLAY_OUT / f"az{ai:02d}"
        out_dir.mkdir(exist_ok=True)
        print(f"\n[ORBIT] Angle {ai+1}/{N_ANGLES}...")

        for ti, t in enumerate(tqdm(all_times)):
            cam = clone_camera_at_time(base_cam, t, uid=ai * 10000 + ti)
            with torch.no_grad():
                result = render(cam, gaussians, pp, bg)
            img = (result["render"].clamp(0, 1).cpu()
                   .permute(1, 2, 0).numpy() * 255).astype(np.uint8)
            Image.fromarray(img).save(out_dir / f"frame_{ti:05d}.png")

    # ── Write meta ─────────────────────────────────────────────────────────────
    meta = {
        "n_angles": N_ANGLES,
        "n_frames": len(all_times),
        "fps": 30,
        "hero_frame": len(all_times) // 2,
    }
    (REPLAY_OUT / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\n[ORBIT] Done! Output: {REPLAY_OUT}")
    print(f"[ORBIT] {N_ANGLES} angles × {len(all_times)} frames = {N_ANGLES*len(all_times)} total")


if __name__ == "__main__":
    main()
