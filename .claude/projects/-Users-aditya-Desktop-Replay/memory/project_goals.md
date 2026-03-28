---
name: Project goals
description: Two post-MVP polish tracks - input video adaptability and Gemini Live voice interaction for the 4D replay viewer
type: project
---

Two polish tracks beyond MVP:

1. **Input adaptability** — Currently requires 4 phones at same resolution, same FPS, with compression on top. Goal: handle variance in input videos (different resolutions, FPS across cameras) and still produce decent outputs.

2. **Gemini Live voice interaction** — Voice commands to control the 4D replay viewer: "show me the block", "rewind to the swish", "rotate around the player", etc.

**Why:** MVP constraints (identical cameras/settings) are too restrictive for real-world use. Voice interaction makes the replay experience more natural and demo-worthy.

**How to apply:** When working on pipeline changes, consider multi-resolution/multi-FPS support. When working on the viewer, consider the voice interaction integration.
