# BUILD PLAN — MVP by 10pm

## Team
- **Aditya** — 4DGS Training (Stage 3) — hardest part, sets the contracts
- **Divij** — COLMAP Pose Recovery (Stage 2)
- **Arshia** — Capture + Sync + Preprocessing (Stage 1)
- **Mia** — Cloud Infra + Environment (parallel to all stages)

---

## MINUTE 0-30: Everyone together

1. Aditya reads the 4DGaussians repo and posts to the group chat:
   - What folder structure 4DGS expects as input
   - What file format it wants camera poses in
   - This defines Contract B (see below) and everyone builds around it

2. Everyone records the sports moment together:
   - Pick something simple: a basketball shot, a jump, a catch
   - 4-5 phones, different angles around the action, spread out wide
   - One person claps loudly right before the action starts (this is the sync point)
   - Record for only 10-15 seconds total. Short is better.

3. All raw videos go into a shared Google Drive folder

4. Everyone splits to their stage

---

## STAGE 1 — Arshia — Capture + Sync + Preprocessing

### What you are building
A script that takes raw phone videos and outputs perfectly aligned frames.

### Tasks in order
1. Download all raw videos from the shared drive
2. Write a Python script that extracts the audio track from each video using ffmpeg
3. Write a sync function: use scipy to cross-correlate the audio waveforms and find the clap — this tells you the time offset between each video
4. Write a script that uses ffmpeg to:
   - Trim all videos so the clap lands on the same frame
   - Extract frames as PNG images at 30fps
   - Resize all frames to the same resolution (1920x1080, or 1280x720 if phones vary too much)
5. Organize the output into the Contract A folder structure (see below)
6. Run your pipeline on the real videos and upload the output folder to the shared drive / cloud box

### How to test before real data exists
Record 2 quick videos of anything on your phone from different angles with a clap. Run your pipeline on those.

### You are done when
A folder exists with identically-named frame PNGs for each camera, all the same resolution, all the same frame count, and the clap frame is frame 0 across all cameras.

---

## CONTRACT A — What Arshia outputs / What Divij consumes

```
scene/
  images/
    cam00/
      frame_00000.png
      frame_00001.png
      frame_00002.png
      ...
    cam01/
      frame_00000.png
      frame_00001.png
      ...
    cam02/
      ...
  metadata.json
```

### Rules
- Every camera folder has the EXACT same number of frames
- frame_00000.png from cam00 and frame_00000.png from cam01 are the SAME moment in time
- All PNGs are the same resolution
- Camera folders are named cam00, cam01, cam02, etc.
- Frame filenames are zero-padded to 5 digits

### metadata.json
```json
{
  "fps": 30,
  "num_cameras": 5,
  "num_frames": 150,
  "resolution": [1920, 1080],
  "sync_event_frame": 0
}
```

---

## STAGE 2 — Divij — COLMAP Pose Recovery

### What you are building
A script that takes Arshia's frame folder and figures out where each camera was in 3D space.

### Tasks in order
1. Install COLMAP (locally first, then on Mia's cloud box when it's ready)
2. Learn COLMAP basics: it takes images, finds matching features between them, and computes camera positions. Watch a 10-min tutorial if needed.
3. Write a script that:
   - Reads the Contract A folder
   - Feeds ALL frames from ALL cameras into COLMAP (or a representative subset — one frame per camera might be enough for static pose estimation)
   - Runs COLMAP's feature extraction, feature matching, and sparse reconstruction
4. IMPORTANT: ask Aditya what exact output format 4DGS needs (Contract B). COLMAP can output in multiple formats. Make sure you output the right one.
5. Write a small validation check: did COLMAP recover a pose for every camera? If not, something went wrong.
6. Run on Arshia's real output and produce Contract B

### How to test before real data exists
Download any multi-view image dataset (search "COLMAP example dataset"). Run your script on it. If COLMAP outputs camera poses, your script works.

### Heads up
COLMAP can be slow. On CPU it might take 30+ minutes. On GPU it's much faster. Use Mia's cloud box for the real run.

### You are done when
COLMAP has recovered camera positions for all cameras and the output is in the folder structure Aditya specified.

---

## CONTRACT B — What Divij outputs / What Aditya consumes

**This contract is defined by Aditya in the first 30 minutes** after reading the 4DGaussians repo.

Most likely it will look like this (but wait for Aditya to confirm):

```
scene/
  images/          <-- same images from Contract A, unchanged
    cam00/
    cam01/
    ...
  sparse/
    0/
      cameras.bin    <-- camera intrinsics (focal length, etc.)
      images.bin     <-- camera extrinsics (position + rotation per image)
      points3D.bin   <-- sparse 3D point cloud
  metadata.json    <-- same as Contract A
```

The sparse/ folder is COLMAP's native binary output. Divij just needs to make sure COLMAP writes to the right place.

---

## STAGE 3 — Aditya — 4DGS Training

### What you are building
The core reconstruction engine. Takes frames + camera poses and produces a 4D model you can render from any angle at any time.

### Tasks in order
1. FIRST 30 MINUTES: Read the 4DGaussians repo thoroughly. Understand:
   - What input format it expects (folder structure, pose format, config files)
   - How it handles time (does it need timestamps per frame? a video index?)
   - What it outputs after training (checkpoint files, .ply, etc.)
2. Post Contract B to the group chat — tell Divij exactly what you need
3. Post Contract C (your output format) so everyone knows what the viewer will load
4. Get 4DGS running on the repo's provided example data on Mia's cloud box
5. Understand the training config: number of iterations, resolution, how many Gaussians, etc. For MVP, go fast and ugly — low resolution, fewer iterations. You can crank quality later.
6. When Divij's output is ready, run 4DGS on the real data
7. Monitor training, check intermediate outputs, debug if it looks wrong

### How to test before real data exists
Use 4DGaussians' own example dataset. If training runs and produces renderable output, your pipeline works.

### You are done when
4DGS has finished training and you can render novel viewpoints from the trained model (even if they look rough).

---

## CONTRACT C — What Aditya outputs / What the viewer loads

**Aditya defines this after reading the 4DGS repo.**

Most likely:
```
output/
  point_cloud.ply        <-- or a folder of checkpoints
  cameras.json           <-- camera info for the viewer
  config.yaml            <-- training config (viewer might need this)
```

The key thing everyone needs to know: what is the ONE file the viewer needs to load to show the scene? Aditya posts this to the group chat.

---

## MIA — Cloud Infra (parallel to everything)

### What you are building
The machine where the heavy computation runs. Divij and Aditya cannot work without this.

### Tasks in order
1. Spin up a cloud GPU instance with an A100 (or A6000 minimum). Options:
   - RunPod (runpod.io) — fast, on-demand, good for this
   - Lambda Labs (lambdalabs.com)
   - Vast.ai — cheapest but less reliable
2. Install system deps:
   ```
   CUDA toolkit
   conda or mamba
   ffmpeg
   git
   COLMAP (apt install colmap or build from source)
   ```
3. Clone and install 4DGaussians:
   ```
   git clone the 4DGaussians repo
   install its Python dependencies
   download its example dataset
   run training on the example — does it work?
   ```
4. Clone and install COLMAP Python bindings if needed
5. Set up SSH access for Aditya, Divij, and Arshia — everyone should be able to:
   ```
   ssh user@cloud-box
   cd /workspace
   ```
   and see the shared scene/ folder
6. Set up a shared /workspace directory where everyone's scripts read and write
7. VERIFY everything works: download 4DGS example data, run COLMAP on it, run 4DGS on it, see output. If this works end to end on test data, the infra is ready.

### You are done when
Aditya can SSH in and start 4DGS training with one command. Divij can SSH in and run COLMAP with one command. Nothing is missing.

### After infra is stable
Help whoever is most stuck. You've seen the full pipeline on test data, so you understand how all the pieces connect.

---

## STAGE 4 — Everyone — Viewer (after 4DGS produces output)

Everyone reconvenes and builds the viewer together. Tasks:

1. Find an open-source Gaussian splat web viewer that can load Contract C's output format
2. Get it running locally
3. Load the trained model
4. Verify you can orbit (mouse drag) and zoom (scroll)
5. Add a time slider if the viewer doesn't have one
6. That's the MVP. It will look rough. That's fine.

---

## TIMELINE

```
Hour 0-0.5    Everyone together: read repo, set contracts, record videos, split
Hour 0.5-2    Everyone builds their stage on test data
              Mia has cloud box ready by end of hour 2
Hour 2-3      Arshia delivers real synced frames
              Divij runs COLMAP on real frames (on cloud box)
Hour 3-5      Aditya runs 4DGS training (on cloud box)
              While training runs: everyone preps viewer
Hour 5-6      Load trained model into viewer
              MVP exists
```

---

## COMMUNICATION RULES

1. All contracts and format decisions go in the group chat immediately
2. If your stage is broken, say so immediately — don't debug alone for 2 hours
3. When your stage works on test data, post a screenshot or terminal output as proof
4. When your stage works on real data, post the output path on the cloud box
5. Nobody touches anyone else's output folder — read only

---

## IF SOMETHING GOES WRONG

- **COLMAP fails to find poses:** Try using fewer frames (just 1 frame per camera instead of all frames). Try a different feature matcher. Ask Aditya.
- **4DGS won't install:** Dependency hell is real. Mia should have it working on test data first. If it still fails, try a different Gaussian splatting repo (gaussian-splatting by graphdeco is simpler but 3D only, not 4D).
- **Sync is off:** If audio sync doesn't work, manually align videos in any video editor to the clap frame and export. Ugly but fast.
- **Cloud box dies:** Have COLMAP installed locally as backup. 4DGS can train on any CUDA GPU, even a laptop 3060, just slower.
- **Training takes too long:** Reduce resolution to 640x360. Reduce iterations to minimum. You need output, not quality. Quality is tomorrow.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | SELECTIVE mode, 5 proposals, 2 accepted (Mia→viewer owner, early COLMAP validation), 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 2 issues (demo offline fallback resolved, config DRY→utils.py), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR (FULL) | score: 3/10 → 9/10, 4 decisions made |

- **OUTSIDE VOICE:** Claude subagent found 10 issues in CEO review. Most critical: Mia needs a deliverable (fixed), COLMAP needs early validation (fixed), .ply export is real engineering (acknowledged).
- **UNRESOLVED:** 0
- **VERDICT:** CEO + ENG + DESIGN CLEARED — ready to implement.
