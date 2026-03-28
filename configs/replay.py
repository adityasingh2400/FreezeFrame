_base_ = './default.py'

# Config for Replay: 3 cameras (cam02-04), 80 frames (~2.7s @ 30fps)
# Optimized for A100 80GB — batch_size=4, 10k iters (~8-10 min)
#
# Two-phase training:
#   Coarse (iters 0-3000): static Gaussians, no deformation, learns geometry
#   Fine (iters 3000-10000): deformation network active, learns motion
#
# Temporal grid resolution = frame_count // 2 = 40

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
    batch_size=4,
    iterations=10000,
    coarse_iterations=3000,
    densify_until_iter=7000,
    densify_grad_threshold_coarse=0.0002,
    densify_grad_threshold_fine_init=0.0002,
    opacity_reset_interval=3000,
    opacity_threshold_coarse=0.005,
    opacity_threshold_fine_init=0.005,
    opacity_threshold_fine_after=0.005,
)
