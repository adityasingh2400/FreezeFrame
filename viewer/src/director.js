import * as THREE from 'three';

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function easeOutQuad(t) {
  return 1 - (1 - t) * (1 - t);
}

const EASE_FNS = { easeInOutCubic, easeOutQuad, linear: t => t };

export class DirectorMode {
  constructor(camera, controls, player) {
    this._camera = camera;
    this._controls = controls;
    this._player = player;
    this._active = false;
    this._keyframes = [];
    this._startTime = 0;
    this._totalDuration = 0;
    this._btn = null;

    this._tmpPos = new THREE.Vector3();
    this._tmpTarget = new THREE.Vector3();

    this._createToggleButton();
  }

  get active() { return this._active; }

  setKeyframes(keyframes) {
    this._keyframes = keyframes.map(kf => ({
      time: kf.time,
      position: new THREE.Vector3(...kf.position),
      lookAt: new THREE.Vector3(...kf.lookAt),
      ease: EASE_FNS[kf.ease] || easeInOutCubic,
      speed: kf.speed ?? 1,
    }));
    if (this._keyframes.length > 0) {
      this._totalDuration = this._keyframes[this._keyframes.length - 1].time;
    }
  }

  loadDefault(totalFrames, fps) {
    const duration = (totalFrames / fps) * 1000;
    this.setKeyframes([
      { time: 0, position: [0, 1.5, 5], lookAt: [0, 0, 0], ease: 'easeOutQuad', speed: 0.5 },
      { time: duration * 0.15, position: [3, 1, 3], lookAt: [0, 0.5, 0], ease: 'easeInOutCubic', speed: 0.5 },
      { time: duration * 0.4, position: [4, 0.5, 0], lookAt: [0, 0.5, 0], ease: 'easeInOutCubic', speed: 0.25 },
      { time: duration * 0.6, position: [3, 2, -2], lookAt: [0, 0.8, 0], ease: 'easeInOutCubic', speed: 0.5 },
      { time: duration * 0.8, position: [0, 3, -3], lookAt: [0, 0.5, 0], ease: 'easeInOutCubic', speed: 1 },
      { time: duration, position: [0, 1.5, 5], lookAt: [0, 0, 0], ease: 'easeOutQuad', speed: 1 },
    ]);
  }

  start() {
    if (this._keyframes.length < 2) return;
    this._active = true;
    this._startTime = performance.now();
    this._controls.controls.enabled = false;
    this._player.play();
    this._btn.textContent = 'Exit Director';
    this._btn.classList.add('active');
  }

  stop() {
    this._active = false;
    this._controls.controls.enabled = true;
    this._player.pause();
    this._btn.textContent = 'Director Mode';
    this._btn.classList.remove('active');
  }

  toggle() {
    if (this._active) this.stop();
    else this.start();
  }

  update(timestamp) {
    if (!this._active || this._keyframes.length < 2) return;

    const elapsed = timestamp - this._startTime;
    if (elapsed >= this._totalDuration) {
      this.stop();
      return;
    }

    let kfA = this._keyframes[0];
    let kfB = this._keyframes[1];
    for (let i = 0; i < this._keyframes.length - 1; i++) {
      if (elapsed >= this._keyframes[i].time && elapsed < this._keyframes[i + 1].time) {
        kfA = this._keyframes[i];
        kfB = this._keyframes[i + 1];
        break;
      }
    }

    const segDuration = kfB.time - kfA.time;
    const segElapsed = elapsed - kfA.time;
    const rawT = Math.min(segElapsed / segDuration, 1);
    const t = kfB.ease(rawT);

    this._tmpPos.lerpVectors(kfA.position, kfB.position, t);
    this._tmpTarget.lerpVectors(kfA.lookAt, kfB.lookAt, t);

    this._camera.position.copy(this._tmpPos);
    this._controls.controls.target.copy(this._tmpTarget);

    const speed = THREE.MathUtils.lerp(kfA.speed, kfB.speed, t);
    this._player.setSpeed(speed);
  }

  _createToggleButton() {
    this._btn = document.createElement('button');
    this._btn.id = 'director-btn';
    this._btn.textContent = 'Director Mode';
    this._btn.style.cssText = `
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: rgba(255, 255, 255, 0.6);
      font-size: 12px;
      font-weight: 500;
      padding: 8px 20px;
      border-radius: 8px;
      cursor: pointer;
      font-family: inherit;
      z-index: 20;
      transition: all 0.2s;
      letter-spacing: 0.05em;
      pointer-events: auto;
    `;
    this._btn.addEventListener('mouseenter', () => {
      this._btn.style.background = 'rgba(255, 255, 255, 0.14)';
      this._btn.style.color = '#fff';
    });
    this._btn.addEventListener('mouseleave', () => {
      if (!this._active) {
        this._btn.style.background = 'rgba(255, 255, 255, 0.08)';
        this._btn.style.color = 'rgba(255, 255, 255, 0.6)';
      }
    });
    this._btn.addEventListener('click', () => this.toggle());
    document.body.appendChild(this._btn);
  }
}
