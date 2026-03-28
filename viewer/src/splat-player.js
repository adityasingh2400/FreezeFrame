import { SplatMesh, SplatLoader } from '@sparkjsdev/spark';

const SPEEDS = [0.25, 0.5, 1, 2];

/**
 * Double-buffered SplatPlayer: uses two SplatMesh objects and toggles
 * visibility to eliminate the visual flash that occurs when swapping
 * packedSplats data on a single mesh (Spark.js issue #220).
 */
export class SplatPlayer {
  constructor(scene) {
    this._scene = scene;
    this._frames = [];
    this._meshA = null;        // Double-buffer slot A
    this._meshB = null;        // Double-buffer slot B
    this._activeSlot = 'A';    // Which slot is currently visible
    this._currentFrame = 0;
    this._totalFrames = 0;
    this._playing = false;
    this._speed = 1;
    this._fps = 30;
    this._lastTimestamp = 0;
    this._accumulator = 0;
    this._onFrameChange = null;
    this._singleMode = false;
    this._loadedCount = 0;
    this._onLoadProgress = null;
  }

  get currentFrame() { return this._currentFrame; }
  get totalFrames() { return this._totalFrames; }
  get playing() { return this._playing; }
  get speed() { return this._speed; }
  get fps() { return this._fps; }
  get mesh() { return this._activeSlot === 'A' ? this._meshA : this._meshB; }
  get loadedCount() { return this._loadedCount; }

  set onFrameChange(fn) { this._onFrameChange = fn; }
  set onLoadProgress(fn) { this._onLoadProgress = fn; }

  async loadSingle(url) {
    this._singleMode = true;
    this._meshA = new SplatMesh({ url });
    this._meshA.quaternion.set(1, 0, 0, 0);
    this._scene.add(this._meshA);
    await this._meshA.initialized;
    this._totalFrames = 1;
    this._currentFrame = 0;
    this._loadedCount = 1;
    return this._meshA.numSplats;
  }

  /**
   * Progressive loading with double-buffer init: load hero frame first,
   * create both mesh slots, show immediately, then stream remaining frames.
   */
  async loadFrames(urls, fps = 30, onProgress = null, heroIndex = 0) {
    this._fps = fps;
    this._singleMode = false;
    this._totalFrames = urls.length;
    this._frames = new Array(urls.length).fill(null);

    const loader = new SplatLoader();

    // Phase 1: Load hero frame and display immediately
    const heroData = await loader.loadAsync(urls[heroIndex]);
    this._frames[heroIndex] = heroData;
    this._loadedCount = 1;

    // Create both double-buffer meshes with hero data
    this._meshA = new SplatMesh({ packedSplats: heroData });
    this._meshA.quaternion.set(1, 0, 0, 0);
    this._scene.add(this._meshA);
    await this._meshA.initialized;

    this._meshB = new SplatMesh({ packedSplats: heroData });
    this._meshB.quaternion.set(1, 0, 0, 0);
    this._meshB.visible = false;
    this._scene.add(this._meshB);
    await this._meshB.initialized;

    this._activeSlot = 'A';
    this._currentFrame = heroIndex;

    const splatCount = this._meshA.numSplats;
    if (onProgress) onProgress(1, urls.length);

    // Phase 2: Load remaining frames in background (outward from hero)
    const remaining = [];
    for (let i = 0; i < urls.length; i++) {
      if (i !== heroIndex) remaining.push(i);
    }
    remaining.sort((a, b) => Math.abs(a - heroIndex) - Math.abs(b - heroIndex));

    const CHUNK_SIZE = 4;
    for (let c = 0; c < remaining.length; c += CHUNK_SIZE) {
      const chunk = remaining.slice(c, c + CHUNK_SIZE);
      await Promise.all(chunk.map(async (idx) => {
        this._frames[idx] = await loader.loadAsync(urls[idx]);
        this._loadedCount++;
        if (onProgress) onProgress(this._loadedCount, urls.length);
        if (this._onLoadProgress) this._onLoadProgress(this._loadedCount, urls.length);
      }));
      await new Promise(r => setTimeout(r, 0));
    }

    return splatCount;
  }

  setFrame(index) {
    if (this._singleMode || this._totalFrames === 0) return;
    const clamped = Math.max(0, Math.min(index, this._totalFrames - 1));
    if (clamped === this._currentFrame) return;

    // Find target frame (or nearest loaded)
    let target = clamped;
    if (!this._frames[clamped]) {
      let nearest = clamped;
      for (let d = 1; d < this._totalFrames; d++) {
        if (clamped + d < this._totalFrames && this._frames[clamped + d]) { nearest = clamped + d; break; }
        if (clamped - d >= 0 && this._frames[clamped - d]) { nearest = clamped - d; break; }
      }
      if (!this._frames[nearest]) return;
      target = nearest;
    }

    this._currentFrame = target;

    // Double-buffer swap: write to standby mesh, then toggle visibility
    const standby = this._activeSlot === 'A' ? this._meshB : this._meshA;
    const active = this._activeSlot === 'A' ? this._meshA : this._meshB;

    standby.packedSplats = this._frames[target];
    standby.packedSplats.needsUpdate = true;
    standby.visible = true;
    active.visible = false;

    this._activeSlot = this._activeSlot === 'A' ? 'B' : 'A';

    if (this._onFrameChange) this._onFrameChange(this._currentFrame);
  }

  play() {
    this._playing = true;
    this._lastTimestamp = performance.now();
    this._accumulator = 0;
  }

  pause() {
    this._playing = false;
  }

  togglePlay() {
    if (this._playing) this.pause();
    else this.play();
  }

  setSpeed(speed) {
    this._speed = speed;
  }

  cycleSpeed(direction) {
    const idx = SPEEDS.indexOf(this._speed);
    const next = idx + direction;
    if (next >= 0 && next < SPEEDS.length) {
      this._speed = SPEEDS[next];
    }
    return this._speed;
  }

  stepFrame(delta) {
    this.setFrame(this._currentFrame + delta);
  }

  update(timestamp) {
    if (!this._playing || this._singleMode || this._totalFrames <= 1) return;

    const dt = timestamp - this._lastTimestamp;
    this._lastTimestamp = timestamp;
    this._accumulator += dt * this._speed;

    const frameDuration = 1000 / this._fps;
    if (this._accumulator >= frameDuration) {
      const steps = Math.floor(this._accumulator / frameDuration);
      this._accumulator -= steps * frameDuration;
      let next = this._currentFrame + steps;
      if (next >= this._totalFrames) next = 0;
      this.setFrame(next);
    }
  }

  dispose() {
    if (this._meshA) {
      this._scene.remove(this._meshA);
      this._meshA.dispose();
    }
    if (this._meshB) {
      this._scene.remove(this._meshB);
      this._meshB.dispose();
    }
    this._frames = [];
  }
}
