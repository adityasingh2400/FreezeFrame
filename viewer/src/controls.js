import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const PRESETS = {
  front: {
    position: new THREE.Vector3(0, 1, 5),
    target: new THREE.Vector3(0, 0, 0),
  },
  side: {
    position: new THREE.Vector3(5, 1, 0),
    target: new THREE.Vector3(0, 0, 0),
  },
  top: {
    position: new THREE.Vector3(0, 6, 0.01),
    target: new THREE.Vector3(0, 0, 0),
  },
};

export class CameraController {
  constructor(camera, domElement) {
    this._camera = camera;
    this._controls = new OrbitControls(camera, domElement);
    this._controls.enableDamping = true;
    this._controls.dampingFactor = 0.08;
    this._controls.rotateSpeed = 0.8;
    this._controls.zoomSpeed = 1.2;
    this._controls.panSpeed = 0.6;
    this._controls.minDistance = 0.5;
    this._controls.maxDistance = 50;

    this._animating = false;
    this._animStart = null;
    this._animDuration = 600;
    this._fromPos = new THREE.Vector3();
    this._toPos = new THREE.Vector3();
    this._fromTarget = new THREE.Vector3();
    this._toTarget = new THREE.Vector3();
    this._activePreset = null;
    this._presetBtns = document.querySelectorAll('.preset-btn');

    this._bindPresetButtons();
  }

  get controls() { return this._controls; }

  _bindPresetButtons() {
    this._presetBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const preset = btn.dataset.preset;
        this.goToPreset(preset);
        this._presetBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  }

  goToPreset(name) {
    this._activePreset = name;
    const preset = PRESETS[name];
    if (!preset) return;

    this._fromPos.copy(this._camera.position);
    this._toPos.copy(preset.position);
    this._fromTarget.copy(this._controls.target);
    this._toTarget.copy(preset.target);
    this._animStart = performance.now();
    this._animating = true;
  }

  update() {
    if (this._animating) {
      const elapsed = performance.now() - this._animStart;
      const t = Math.min(elapsed / this._animDuration, 1);
      const ease = 1 - Math.pow(1 - t, 3);

      this._camera.position.lerpVectors(this._fromPos, this._toPos, ease);
      this._controls.target.lerpVectors(this._fromTarget, this._toTarget, ease);

      if (t >= 1) this._animating = false;
    }
    this._controls.update();
  }

  onUserInteract() {
    this._activePreset = null;
    this._presetBtns.forEach(b => b.classList.remove('active'));
  }
}
