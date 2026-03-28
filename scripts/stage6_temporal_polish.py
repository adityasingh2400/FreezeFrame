"""Stage 6: Temporal Cleanup (RGVI + RIFE) — POST-MVP

INPUT:  Spatially refined 4DGS output from Stage 5
OUTPUT: Temporally smooth replay

This stage:
  1. RGVI for localized video hole repair and reference-guided inpainting
  2. RIFE for frame interpolation and smoother motion (30+ FPS)

Only runs after BulletGen-style densification has improved the spatial quality.
"""


def run_rgvi():
    raise NotImplementedError("POST-MVP: implement RGVI temporal cleanup")


def run_rife():
    raise NotImplementedError("POST-MVP: implement RIFE frame interpolation")


def run():
    raise NotImplementedError("POST-MVP")


if __name__ == "__main__":
    run()
