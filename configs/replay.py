_base_ = './default.py'

# QUALITY config for Replay: 3 cameras (cam02-04), 80 frames (~2.7s @ 30fps)
# Prioritizes reconstruction quality over training speed.
#
# Two-phase training:
#   Coarse (iters 0-3000): static Gaussians, no deformation, learns geometry
#   Fine (iters 3000-14000): deformation network active, learns motion
#
# Temporal grid resolution = frame_count // 2 = 40
# batch_size=2 to leave VRAM headroom for denser Gaussians

ModelHiddenParams = dict(
    kplanes_config={
        'grid_dimensions': 2,
        'input_coordinate_dim': 4,
        'output_coordinate_dim': 32,
        'resolution': [64, 64, 64, 40]
    },
    multires=[1, 2, 4],
    defor_depth=1,
    net_width=128,
    plane_tv_weight=0.0002,
    time_smoothness_weight=0.01,
    l1_time_planes=0.0001,
    no_do=False,
    no_dshs=False,
    no_ds=False,
)

OptimizationParams = dict(
    dataloader=True,
    batch_size=2,
    iterations=14000,
    coarse_iterations=3000,
    densify_until_iter=10000,
    densify_grad_threshold_coarse=0.0002,
    densify_grad_threshold_fine_init=0.0002,
    opacity_reset_interval=3000,
    opacity_threshold_coarse=0.005,
    opacity_threshold_fine_init=0.005,
    opacity_threshold_fine_after=0.005,
)
