_base_ = './default.py'

# FAST config for Replay — smoke test on A100, ~2-3 min
# Cranked batch_size for A100 80GB VRAM, reduced iters
# Switch to replay.py for the final quality run

ModelHiddenParams = dict(
    kplanes_config={
        'grid_dimensions': 2,
        'input_coordinate_dim': 4,
        'output_coordinate_dim': 16,
        'resolution': [64, 64, 64, 25]
    },
    multires=[1, 2],
    defor_depth=0,
    net_width=64,
    plane_tv_weight=0.0002,
    time_smoothness_weight=0.001,
    l1_time_planes=0.0001,
    no_do=False,
    no_dshs=False,
    no_ds=False,
)

OptimizationParams = dict(
    dataloader=True,
    batch_size=4,
    iterations=5000,
    coarse_iterations=1500,
    densify_until_iter=3500,
    opacity_reset_interval=2000,
    opacity_threshold_coarse=0.005,
    opacity_threshold_fine_init=0.005,
    opacity_threshold_fine_after=0.005,
)
