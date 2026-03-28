export class UI {
  constructor() {
    this._loadingScreen = document.getElementById('loading-screen');
    this._loadingFill = document.getElementById('loading-bar-fill');
    this._loadingPct = document.getElementById('loading-pct');
    this._loadingText = document.getElementById('loading-text');
    this._errorScreen = document.getElementById('error-screen');
    this._errorMessage = document.getElementById('error-message');
    this._fpsCounter = document.getElementById('fps-counter');
    this._splatCounter = document.getElementById('splat-counter');
    this._sceneName = document.getElementById('scene-name');
    this._orbitHint = document.getElementById('orbit-hint');
    this._directorBtn = document.getElementById('director-btn');
    this._frameCount = 0;
    this._lastFpsUpdate = 0;
    this._fps = 0;
    this._hintDismissed = false;
  }

  setLoadingProgress(loaded, total) {
    const pct = Math.round((loaded / total) * 100);
    this._loadingFill.style.width = `${pct}%`;
    if (this._loadingPct) this._loadingPct.textContent = `${pct}%`;
    this._loadingText.textContent = `Loading frames... ${loaded} / ${total}`;
  }

  setLoadingText(text) {
    this._loadingText.textContent = text;
  }

  setSceneName(name) {
    if (this._sceneName) this._sceneName.textContent = name;
  }

  showError(message) {
    if (this._loadingScreen) {
      this._loadingScreen.classList.add('hidden');
    }
    if (this._errorMessage) this._errorMessage.textContent = message;
    if (this._errorScreen) this._errorScreen.classList.add('visible');
  }

  hideLoading() {
    this._loadingScreen.classList.add('hidden');
    setTimeout(() => {
      this._loadingScreen.style.display = 'none';
    }, 600);
  }

  setLoadingBg(loaded, total) {
    if (!this._bgIndicator) {
      this._bgIndicator = document.createElement('div');
      this._bgIndicator.id = 'bg-load-indicator';
      Object.assign(this._bgIndicator.style, {
        position: 'fixed', bottom: '80px', left: '50%', transform: 'translateX(-50%)',
        background: 'rgba(0,0,0,0.7)', color: '#8ef', padding: '4px 14px',
        borderRadius: '12px', fontSize: '12px', fontFamily: 'monospace',
        zIndex: '100', transition: 'opacity 0.4s', pointerEvents: 'none',
      });
      document.body.appendChild(this._bgIndicator);
    }
    if (loaded >= total) {
      this._bgIndicator.style.opacity = '0';
      setTimeout(() => this._bgIndicator.remove(), 500);
    } else {
      this._bgIndicator.textContent = `Loading ${loaded}/${total} frames...`;
      this._bgIndicator.style.opacity = '0.8';
    }
  }

  setSplatCount(count) {
    const formatted = count >= 1000 ? `${(count / 1000).toFixed(1)}k` : count;
    this._splatCounter.textContent = `${formatted} splats`;
  }

  dismissOrbitHint() {
    if (!this._hintDismissed && this._orbitHint) {
      this._hintDismissed = true;
      this._orbitHint.classList.add('dismissed');
    }
  }

  setDirectorActive(active) {
    if (this._directorBtn) {
      this._directorBtn.classList.toggle('active', active);
    }
  }

  updateFps(timestamp) {
    this._frameCount++;
    if (timestamp - this._lastFpsUpdate >= 500) {
      this._fps = Math.round(this._frameCount / ((timestamp - this._lastFpsUpdate) / 1000));
      this._fpsCounter.textContent = `${this._fps} fps`;
      this._frameCount = 0;
      this._lastFpsUpdate = timestamp;
    }
  }

  // ── Bullet-Time Mode ────────────────────────────────────────────

  showBulletTimeMode(moment, stripPlayer) {
    this._frameNames = null;

    // Set moment label
    const label = document.getElementById('bt-moment-label');
    if (label && moment) {
      label.textContent = moment.label || 'Bullet Time';
      label.style.display = '';
    }

    const desc = document.getElementById('bt-moment-desc');
    if (desc && moment) {
      desc.textContent = moment.description || '';
      desc.style.display = '';
    }

    // Show angle indicator
    const indicator = document.getElementById('bt-angle-indicator');
    if (indicator) indicator.style.display = '';

    // Show source badge
    const badge = document.getElementById('bt-source-badge');
    if (badge) badge.style.display = '';

    // Show drag hint
    const hint = document.getElementById('bt-drag-hint');
    if (hint) {
      hint.style.display = '';
      setTimeout(() => { hint.style.opacity = '0'; }, 4000);
    }

    // Update frame counter to show view number
    const counter = document.getElementById('frame-counter');
    const counterLabel = document.getElementById('frame-label');
    if (counter) counter.textContent = '001';
    if (counterLabel) counterLabel.textContent = 'View';

    // Wire up frame changes to counter + source badge
    if (stripPlayer) {
      stripPlayer.onFrameChange = (frame) => {
        if (counter) counter.textContent = String(frame + 1).padStart(3, '0');
        this.updateAngleIndicator(frame, stripPlayer.totalFrames);
        this.updateSourceBadge(frame);
      };
    }

    // Update badge for initial frame
    this.updateSourceBadge(0);
  }

  /**
   * Store frame filenames so we can determine real vs synthetic.
   */
  setFrameNames(names) {
    this._frameNames = names;
    this.updateSourceBadge(0);
  }

  updateAngleIndicator(currentFrame, totalFrames) {
    const fill = document.getElementById('bt-angle-fill');
    if (!fill) return;
    const pct = totalFrames > 1 ? (currentFrame / (totalFrames - 1)) * 100 : 0;
    fill.style.width = `${pct}%`;
  }

  updateSourceBadge(frame) {
    const badge = document.getElementById('bt-source-badge');
    if (!badge || !this._frameNames) return;

    const name = this._frameNames[frame] || '';
    const isReal = name.startsWith('cam');

    badge.textContent = isReal ? 'Real Camera' : 'AI Generated';
    badge.className = isReal ? 'bt-only source-real' : 'bt-only source-synth';
  }
}
