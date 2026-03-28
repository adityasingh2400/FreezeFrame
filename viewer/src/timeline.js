export class Timeline {
  constructor(player) {
    this._player = player;
    this._timeline = document.getElementById('timeline');
    this._playBtn = document.getElementById('play-btn');
    this._iconPlay = document.getElementById('icon-play');
    this._iconPause = document.getElementById('icon-pause');
    this._frameCounter = document.getElementById('frame-counter');
    this._speedBtns = document.querySelectorAll('.speed-btn');
    this._scrubbing = false;

    this._bindEvents();
  }

  _bindEvents() {
    this._playBtn.addEventListener('click', () => {
      this._player.togglePlay();
      this._updatePlayIcon();
    });

    this._timeline.addEventListener('input', () => {
      this._scrubbing = true;
      this._player.pause();
      this._player.setFrame(parseInt(this._timeline.value, 10));
      this._updatePlayIcon();
    });

    this._timeline.addEventListener('change', () => {
      this._scrubbing = false;
    });

    this._speedBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const speed = parseFloat(btn.dataset.speed);
        this._player.setSpeed(speed);
        this._speedBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  }

  init() {
    const max = Math.max(0, this._player.totalFrames - 1);
    this._timeline.max = max;
    this._timeline.value = 0;
    this._updateFrameCounter(0);
  }

  update() {
    if (!this._scrubbing) {
      this._timeline.value = this._player.currentFrame;
    }
    this._updateFrameCounter(this._player.currentFrame);
  }

  _updatePlayIcon() {
    const playing = this._player.playing;
    this._iconPlay.style.display = playing ? 'none' : 'block';
    this._iconPause.style.display = playing ? 'block' : 'none';
  }

  _updateFrameCounter(frame) {
    this._frameCounter.textContent = `${frame + 1} / ${this._player.totalFrames}`;
  }

  setActiveSpeed(speed) {
    this._speedBtns.forEach(b => {
      b.classList.toggle('active', parseFloat(b.dataset.speed) === speed);
    });
  }
}
