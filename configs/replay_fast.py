_base_ = './default.py'

# FAST smoke-test config — verifies data loads correctly before quality run
# ~2-3 min on A100. Output will look rough. Only used for validation.

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
    iterations=3000,
    coarse_iterations=1000,
    densify_until_iter=2000,
    opacity_reset_interval=1500,
    opacity_threshold_coarse=0.005,
    opacity_threshold_fine_init=0.005,
    opacity_threshold_fine_after=0.005,
)
