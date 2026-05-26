import * as THREE from 'three';

/**
 * ImageStripPlayer: drag-to-rotate viewer for bullet-time image strips.
 *
 * Preloads a sequence of JPEG images (real + synthetic camera views) and
 * renders the current frame on a fullscreen textured quad. Horizontal
 * pointer drag maps to frame index for the "grab and rotate" interaction.
 */
export class ImageStripPlayer {
  constructor(scene) {
    this._scene = scene;
    this._textures = [];
    this._currentFrame = 0;
    this._totalFrames = 0;
    this._onFrameChange = null;

    // Fullscreen quad — geometry sized at runtime once we know the image aspect
    this._geometry = null;
    this._material = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.FrontSide,
    });
    this._quad = null;
    this._imageAspect = 1; // w/h, set after first texture loads

    // Drag state
    this._dragging = false;
    this._dragStartX = 0;
    this._dragStartFrame = 0;

    // Momentum / inertia
    this._velocity = 0;
    this._lastPointerX = 0;
    this._lastPointerTime = 0;
    this._animating = false;
  }

  get currentFrame() { return this._currentFrame; }
  get totalFrames() { return this._totalFrames; }
  get mesh() { return this._quad; }

  set onFrameChange(fn) { this._onFrameChange = fn; }

  /**
   * Load all images and add the quad to the scene.
   * Returns the ortho camera that should be used for rendering.
   */
  async loadImages(urls, onProgress = null) {
    const loader = new THREE.TextureLoader();
    this._textures = new Array(urls.length).fill(null);
    this._totalFrames = urls.length;
    let loaded = 0;

    // Load all textures in parallel
    const promises = urls.map((url, i) =>
      loader.loadAsync(url).then((tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.minFilter = THREE.LinearFilter;
        tex.magFilter = THREE.LinearFilter;
        this._textures[i] = tex;
        loaded++;
        if (onProgress) onProgress(loaded, urls.length);
      }).catch((err) => {
        console.warn(`Failed to load ${url}:`, err);
        loaded++;
        if (onProgress) onProgress(loaded, urls.length);
      })
    );

    await Promise.all(promises);

    // Determine image aspect from first loaded texture and build the quad
    const firstTex = this._textures.find(t => t != null);
    if (firstTex) {
      this._imageAspect = firstTex.image.width / firstTex.image.height;
      this._buildQuad();
      this._material.map = this._textures[0];
      this._material.needsUpdate = true;
    }

    this._scene.add(this._quad);
    return this._totalFrames;
  }

  /**
   * Build (or rebuild) the quad to fit the viewport while preserving image aspect.
   */
  _buildQuad() {
    if (this._quad && this._quad.parent) {
      this._quad.parent.remove(this._quad);
    }
    if (this._geometry) this._geometry.dispose();

    // Fit image inside a [-1,1] ortho box, letterboxing as needed
    const viewAspect = window.innerWidth / window.innerHeight;
    let w, h;
    if (this._imageAspect > viewAspect) {
      // Image is wider than viewport — fit to width
      w = 2;
      h = 2 * (viewAspect / this._imageAspect);
    } else {
      // Image is taller than viewport — fit to height
      h = 2;
      w = 2 * (this._imageAspect / viewAspect);
    }

    this._geometry = new THREE.PlaneGeometry(w, h);
    this._quad = new THREE.Mesh(this._geometry, this._material);
    this._quad.frustumCulled = false;
  }

  /**
   * Create an orthographic camera sized to display the images fullscreen.
   */
  createCamera() {
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
    cam.position.set(0, 0, 1);
    cam.lookAt(0, 0, 0);

    // Rebuild quad on resize to maintain correct aspect
    window.addEventListener('resize', () => {
      if (this._imageAspect && this._scene) {
        this._buildQuad();
        this._scene.add(this._quad);
        if (this._textures[this._currentFrame]) {
          this._material.map = this._textures[this._currentFrame];
          this._material.needsUpdate = true;
        }
      }
    });

    return cam;
  }

  setFrame(index) {
    const clamped = Math.max(0, Math.min(this._totalFrames - 1, Math.round(index)));
    if (clamped === this._currentFrame) return;
    this._currentFrame = clamped;

    const tex = this._textures[clamped];
    if (tex) {
      this._material.map = tex;
      this._material.needsUpdate = true;
    }

    if (this._onFrameChange) this._onFrameChange(clamped);
  }

  stepFrame(delta) {
    this.setFrame(this._currentFrame + delta);
  }

  /**
   * Bind drag-to-rotate interaction to the canvas.
   */
  bindDrag(canvas) {
    canvas.addEventListener('pointerdown', (e) => {
      this._dragging = true;
      this._dragStartX = e.clientX;
      this._dragStartFrame = this._currentFrame;
      this._velocity = 0;
      this._lastPointerX = e.clientX;
      this._lastPointerTime = performance.now();
      canvas.setPointerCapture(e.pointerId);
    });

    canvas.addEventListener('pointermove', (e) => {
      if (!this._dragging) return;

      const dx = e.clientX - this._dragStartX;
      // Full canvas width = 1.5x the total frames (feels natural)
      const sensitivity = this._totalFrames * 1.5;
      const frameDelta = (dx / window.innerWidth) * sensitivity;
      this.setFrame(Math.round(this._dragStartFrame - frameDelta));

      // Track velocity for momentum
      const now = performance.now();
      const dt = now - this._lastPointerTime;
      if (dt > 0) {
        this._velocity = (e.clientX - this._lastPointerX) / dt;
      }
      this._lastPointerX = e.clientX;
      this._lastPointerTime = now;
    });

    canvas.addEventListener('pointerup', (e) => {
      this._dragging = false;
      canvas.releasePointerCapture(e.pointerId);

      // Apply momentum
      if (Math.abs(this._velocity) > 0.1) {
        this._startMomentum();
      }
    });

    // Mouse wheel for stepping
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 1 : -1;
      this.setFrame(this._currentFrame + delta);
    }, { passive: false });
  }

  _startMomentum() {
    if (this._animating) return;
    this._animating = true;

    const decelerate = () => {
      if (Math.abs(this._velocity) < 0.01 || this._dragging) {
        this._animating = false;
        return;
      }

      const sensitivity = this._totalFrames * 1.5;
      const frameDelta = (this._velocity * 16) / window.innerWidth * sensitivity;
      this.setFrame(Math.round(this._currentFrame - frameDelta));

      this._velocity *= 0.92; // Friction
      requestAnimationFrame(decelerate);
    };

    requestAnimationFrame(decelerate);
  }

  /**
   * Play a boomerang animation: sweep forward then reverse through all frames.
   * Returns a promise that resolves when the animation completes.
   */
  playBoomerang(loops = 1, fps = 24) {
    return new Promise((resolve) => {
      if (this._boomerangRaf) cancelAnimationFrame(this._boomerangRaf);

      const total = this._totalFrames;
      if (total < 2) { resolve(); return; }

      const forward = [];
      for (let f = 0; f < total; f++) forward.push(f);
      const backward = [...forward].slice(1, -1).reverse();
      const sequence = [...forward, ...backward];

      let idx = 0;
      let lastTime = null;
      const delay = 1000 / fps;
      const totalSteps = sequence.length * loops;

      const step = (ts) => {
        if (lastTime === null) lastTime = ts;
        if (ts - lastTime >= delay) {
          const frame = sequence[idx % sequence.length];
          this._currentFrame = frame;
          const tex = this._textures[frame];
          if (tex) {
            this._material.map = tex;
            this._material.needsUpdate = true;
          }
          if (this._onFrameChange) this._onFrameChange(frame);
          idx++;
          lastTime = ts;
        }
        if (idx < totalSteps) {
          this._boomerangRaf = requestAnimationFrame(step);
        } else {
          this._boomerangRaf = null;
          resolve();
        }
      };

      this._boomerangRaf = requestAnimationFrame(step);
    });
  }

  /**
   * Entry animation: sweep forward 0→end, pause, then reverse end→0.
   * No duplicate frames at the boundaries.
   */
  playForwardReverse(fps = 24, pauseMs = 400) {
    return new Promise((resolve) => {
      if (this._boomerangRaf) cancelAnimationFrame(this._boomerangRaf);

      const total = this._totalFrames;
      if (total < 2) { resolve(); return; }

      const last = total - 1;
      const delay = 1000 / fps;
      let phase = 'forward';
      let frame = 0;
      let lastTime = null;
      let pauseStart = null;

      const showFrame = (f) => {
        this._currentFrame = f;
        const tex = this._textures[f];
        if (tex) { this._material.map = tex; this._material.needsUpdate = true; }
        if (this._onFrameChange) this._onFrameChange(f);
      };

      const step = (ts) => {
        if (lastTime === null) lastTime = ts;

        if (phase === 'pause') {
          if (ts - pauseStart >= pauseMs) {
            phase = 'reverse';
            frame = last - 1;
            lastTime = ts;
          }
          this._boomerangRaf = requestAnimationFrame(step);
          return;
        }

        if (ts - lastTime >= delay) {
          showFrame(frame);
          lastTime = ts;

          if (phase === 'forward') {
            if (frame >= last) {
              phase = 'pause';
              pauseStart = ts;
            } else {
              frame++;
            }
          } else {
            if (frame <= 0) {
              this._boomerangRaf = null;
              resolve();
              return;
            }
            frame--;
          }
        }

        this._boomerangRaf = requestAnimationFrame(step);
      };

      this._boomerangRaf = requestAnimationFrame(step);
    });
  }

  stopBoomerang() {
    if (this._boomerangRaf) {
      cancelAnimationFrame(this._boomerangRaf);
      this._boomerangRaf = null;
    }
  }

  dispose() {
    this.stopBoomerang();
    this._animating = false;
    this._dragging = false;
    this._onFrameChange = null;
    this._textures.forEach((t) => t?.dispose());
    this._textures = [];
    this._material.dispose();
    if (this._geometry) this._geometry.dispose();
    if (this._quad?.parent) this._quad.parent.remove(this._quad);
    this._quad = null;
    this._geometry = null;
    this._totalFrames = 0;
    this._currentFrame = 0;
  }
}
