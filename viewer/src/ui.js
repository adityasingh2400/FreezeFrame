export class UI {
  constructor() {
    this._loadingScreen = document.getElementById('loading-screen');
    this._loadingFill = document.getElementById('loading-bar-fill');
    this._loadingText = document.getElementById('loading-text');
    this._fpsCounter = document.getElementById('fps-counter');
    this._splatCounter = document.getElementById('splat-counter');
    this._frameCount = 0;
    this._lastFpsUpdate = 0;
    this._fps = 0;
  }

  setLoadingProgress(loaded, total) {
    const pct = Math.round((loaded / total) * 100);
    this._loadingFill.style.width = `${pct}%`;
    this._loadingText.textContent = `Loading frames... ${loaded} / ${total}`;
  }

  setLoadingText(text) {
    this._loadingText.textContent = text;
  }

  hideLoading() {
    this._loadingScreen.classList.add('hidden');
    setTimeout(() => {
      this._loadingScreen.style.display = 'none';
    }, 600);
  }

  setSplatCount(count) {
    const formatted = count >= 1000 ? `${(count / 1000).toFixed(1)}k` : count;
    this._splatCounter.textContent = `${formatted} splats`;
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
}
