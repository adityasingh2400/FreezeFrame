#!/usr/bin/env python3
"""Patch 4DGaussians source for headless RunPod containers.

Applies minimal, targeted fixes so 4DGS runs on containers that lack
tkinter, have stale system Python packages, etc. Each patch is
idempotent — safe to run multiple times.

Run AFTER cloning 4DGaussians, BEFORE training.
"""

import re
import sys
from pathlib import Path


def patch_file(path, old, new, description):
    """Replace exact string in file. Idempotent: skips if already patched."""
    p = Path(path)
    if not p.exists():
        print(f"  SKIP {p} (not found)")
        return False
    content = p.read_text()
    if new in content:
        print(f"  OK   {description} (already patched)")
        return True
    if old not in content:
        print(f"  WARN {description} (old string not found)")
        return False
    content = content.replace(old, new)
    p.write_text(content)
    print(f"  FIXED {description}")
    return True


def patch_deformation_tkinter(fourdgs_dir):
    """Replace `from tkinter import W` with a constant.

    The imported W is immediately shadowed by the class parameter W=256,
    so the tkinter value is never used. Safe to replace with any string.
    """
    patch_file(
        fourdgs_dir / "scene" / "deformation.py",
        "from tkinter import W",
        'W = "w"  # patched: tkinter unavailable in headless containers',
        "deformation.py: tkinter → constant",
    )


def patch_mmcv_config(fourdgs_dir):
    """Replace mmcv.Config.fromfile with a stdlib equivalent.

    mmcv is a heavy dependency that often has version conflicts.
    Config.fromfile() just exec()s a Python file and collects its globals,
    which we can do with importlib.
    """
    config_shim = fourdgs_dir / "utils" / "config_shim.py"
    if not config_shim.exists():
        config_shim.write_text('''\
"""Minimal replacement for mmcv.Config.fromfile().

Loads a Python config file and exposes its top-level variables
as attributes/dict keys, exactly like mmcv.Config does.
"""

import importlib.util
import sys
from pathlib import Path


class Config(dict):
    """Dict subclass with attribute access, mimicking mmcv.Config."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def keys(self):
        return super().keys()

    @staticmethod
    def fromfile(filepath):
        filepath = str(Path(filepath).resolve())
        spec = importlib.util.spec_from_file_location("_config", filepath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = Config()
        for key, value in mod.__dict__.items():
            if not key.startswith("_"):
                cfg[key] = value
        return cfg
''')
        print("  FIXED created config_shim.py (mmcv replacement)")
    else:
        print("  OK   config_shim.py already exists")

    for script in ["train.py", "render.py", "export_perframe_3DGS.py", "merge_many_4dgs.py"]:
        path = fourdgs_dir / script
        if not path.exists():
            continue
        patch_file(
            path,
            "import mmcv",
            "from utils.config_shim import Config as _Config  # patched: mmcv replacement",
            f"{script}: mmcv import",
        )
        patch_file(
            path,
            "mmcv.Config.fromfile",
            "_Config.fromfile",
            f"{script}: mmcv.Config.fromfile call",
        )


def patch_multipleview_dataset(fourdgs_dir):
    """Fix hardcoded cam01 directory in multipleview_dataset.py.

    The loader counts frames from cam01/ but cam01 may not be registered by
    COLMAP. Replace with dynamic detection from extrinsics.
    """
    target = fourdgs_dir / "scene" / "multipleview_dataset.py"
    old = '        image_length = len(os.listdir(os.path.join(cam_folder,"cam01")))'
    new = '''\
        # Find the first camera directory that actually matches an extrinsic entry,
        # rather than hardcoding cam01 which may not have been registered by COLMAP.
        first_cam_number = None
        for key in cam_extrinsics:
            extr = cam_extrinsics[key]
            number = os.path.basename(extr.name)[5:-4]
            cam_dir = os.path.join(cam_folder, "cam" + number.zfill(2))
            if os.path.isdir(cam_dir):
                first_cam_number = number
                break
        if first_cam_number is None:
            first_cam_number = "01"
        ref_cam_dir = os.path.join(cam_folder, "cam" + first_cam_number.zfill(2))
        image_length = len(os.listdir(ref_cam_dir))'''
    patch_file(target, old, new, "multipleview_dataset.py: cam01 → dynamic camera detection")


def patch_export_perframe(fourdgs_dir):
    """Fix export_perframe_3DGS.py to export all frames, not just test views.

    The original iterates over test cameras (9 viewpoints) instead of
    all timestamps. Replace with a loop over all frame timestamps.
    """
    target = fourdgs_dir / "export_perframe_3DGS.py"
    old = '''args = get_combined_args(parser)
print("Rendering " , args.model_path)
if args.configs:
    import mmcv
    from utils.params_utils import merge_hparams
    config = mmcv.Config.fromfile(args.configs)
    args = merge_hparams(args, config)
# Initialize system state (RNG)
safe_state(args.quiet)
gaussians, scene = render_sets(model.extract(args), hyperparam.extract(args), args.iteration, pipeline.extract(args), args.skip_train, args.skip_test, args.skip_video)
output_path = os.path.join(args.model_path,"gaussian_pertimestamp")
os.makedirs(output_path,exist_ok=True)
print("Computing Gaussians.")
for index, viewpoint in enumerate(scene.getTestCameras()):
    
    points, scales_final, rotations_final, opacity_final, shs_final = get_state_at_time(gaussians, viewpoint)
    feature_dc_shape = gaussians._features_dc.shape[1]
    feature_rest_shape = gaussians._features_rest.shape[1]
    gs_ply = init_3DGaussians_ply(points, scales_final, rotations_final, opacity_final, shs_final, [feature_dc_shape, feature_rest_shape])
    gs_ply.write(os.path.join(output_path,"time_{0:05d}.ply".format(index)))
print("done")'''

    new = '''parser.add_argument("--num_frames", default=0, type=int,
                    help="Export this many evenly-spaced frames over [0,1]. "
                         "0 = auto-detect from training data.")

args = get_combined_args(parser)
print("Rendering " , args.model_path)
if args.configs:
    from utils.config_shim import Config as _Config  # patched: mmcv replacement
    from utils.params_utils import merge_hparams
    config = _Config.fromfile(args.configs)
    args = merge_hparams(args, config)
safe_state(args.quiet)
gaussians, scene = render_sets(model.extract(args), hyperparam.extract(args), args.iteration, pipeline.extract(args), args.skip_train, args.skip_test, args.skip_video)
output_path = os.path.join(args.model_path,"gaussian_pertimestamp")
os.makedirs(output_path,exist_ok=True)

# Determine number of frames: use --num_frames if given, else count from
# training data (total training samples / number of cameras).
num_frames = args.num_frames
if num_frames <= 0:
    train_cams = scene.getTrainCameras()
    test_cams = scene.getTestCameras()
    n_train = len(train_cams)
    n_test_per_cam = 3  # test split takes 3 frames per camera
    n_test = len(test_cams)
    n_cameras = max(1, n_test // n_test_per_cam) if n_test > 0 else 1
    num_frames = max(1, n_train // n_cameras)
    print(f"Auto-detected: {n_train} training samples / {n_cameras} cameras = {num_frames} frames")

print(f"Exporting {num_frames} per-frame Gaussian PLY files.")

class TimeQuery:
    def __init__(self, t):
        self.time = t

means3D = gaussians.get_xyz
feature_dc_shape = gaussians._features_dc.shape[1]
feature_rest_shape = gaussians._features_rest.shape[1]

for i in tqdm(range(num_frames), desc="Exporting frames"):
    t = float(i) / float(num_frames)
    viewpoint = TimeQuery(t)
    points, scales_final, rotations_final, opacity_final, shs_final = get_state_at_time(gaussians, viewpoint)
    gs_ply = init_3DGaussians_ply(points, scales_final, rotations_final, opacity_final, shs_final, [feature_dc_shape, feature_rest_shape])
    gs_ply.write(os.path.join(output_path, "time_{0:05d}.ply".format(i)))

print(f"Done. Exported {num_frames} frames to {output_path}")'''

    patch_file(target, old, new, "export_perframe_3DGS.py: export all frames, not just test views")


def main():
    if len(sys.argv) > 1:
        fourdgs_dir = Path(sys.argv[1])
    else:
        fourdgs_dir = Path(__file__).resolve().parent / "4DGaussians"

    print(f"Patching 4DGaussians at {fourdgs_dir}")
    print()

    print("[1/2] Patching tkinter import...")
    patch_deformation_tkinter(fourdgs_dir)
    print()

    print("[2/2] Replacing mmcv.Config with stdlib shim...")
    patch_mmcv_config(fourdgs_dir)
    print()

    print("[3/4] Fixing multipleview_dataset.py cam01 hardcode...")
    patch_multipleview_dataset(fourdgs_dir)
    print()

    print("[4/4] Fixing export_perframe_3DGS.py (80-frame export)...")
    patch_export_perframe(fourdgs_dir)
    print()

    print("All patches applied. Verifying imports...")
    # Quick smoke test
    sys.path.insert(0, str(fourdgs_dir))
    try:
        from utils.config_shim import Config
        print("  OK   config_shim imports")
    except Exception as e:
        print(f"  FAIL config_shim: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
