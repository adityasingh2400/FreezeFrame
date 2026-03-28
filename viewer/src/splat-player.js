import { SplatMesh, SplatLoader } from '@sparkjsdev/spark';

const SPEEDS = [0.25, 0.5, 1, 2];

export class SplatPlayer {
  constructor(scene) {
    this._scene = scene;
    this._frames = [];
    this._mesh = null;
    this._currentFrame = 0;
    this._totalFrames = 0;
    this._playing = false;
    this._speed = 1;
    this._fps = 30;
    this._lastTimestamp = 0;
    this._accumulator = 0;
    this._onFrameChange = null;
    this._singleMode = false;
  }

  get currentFrame() { return this._currentFrame; }
  get totalFrames() { return this._totalFrames; }
  get playing() { return this._playing; }
  get speed() { return this._speed; }
  get fps() { return this._fps; }
  get mesh() { return this._mesh; }

  set onFrameChange(fn) { this._onFrameChange = fn; }

  async loadSingle(url) {
    this._singleMode = true;
    this._mesh = new SplatMesh({ url });
    this._mesh.quaternion.set(1, 0, 0, 0);
    this._scene.add(this._mesh);
    await this._mesh.initialized;
    this._totalFrames = 1;
    this._currentFrame = 0;
    return this._mesh.numSplats;
  }

  async loadFrames(urls, fps = 30, onProgress = null) {
    this._fps = fps;
    this._singleMode = false;
    this._totalFrames = urls.length;
    const loader = new SplatLoader();

    for (let i = 0; i < urls.length; i++) {
      const packed = await loader.loadAsync(urls[i]);
      this._frames.push(packed);
      if (onProgress) onProgress(i + 1, urls.length);
    }

    this._mesh = new SplatMesh({ packedSplats: this._frames[0] });
    this._mesh.quaternion.set(1, 0, 0, 0);
    this._scene.add(this._mesh);
    await this._mesh.initialized;
    this._currentFrame = 0;
    return this._mesh.numSplats;
  }

  setFrame(index) {
    if (this._singleMode || this._frames.length === 0) return;
    const clamped = Math.max(0, Math.min(index, this._totalFrames - 1));
    if (clamped === this._currentFrame) return;
    this._currentFrame = clamped;
    this._mesh.packedSplats = this._frames[clamped];
    this._mesh.packedSplats.needsUpdate = true;
    if (this._onFrameChange) this._onFrameChange(clamped);
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
    if (this._mesh) {
      this._scene.remove(this._mesh);
      this._mesh.dispose();
    }
    this._frames = [];
  }
}
