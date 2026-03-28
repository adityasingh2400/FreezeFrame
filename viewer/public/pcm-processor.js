/**
 * AudioWorklet processor — Float32 → Int16 PCM at 16kHz.
 * Runs in the audio rendering thread; posts Int16 chunks to main thread.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._chunkSamples = 1600; // 100ms @ 16kHz
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const float32 = input[0];

    for (let i = 0; i < float32.length; i++) {
      // Clamp and convert float → int16
      const s = Math.max(-1, Math.min(1, float32[i]));
      this._buffer.push(s < 0 ? s * 0x8000 : s * 0x7fff);
    }

    while (this._buffer.length >= this._chunkSamples) {
      const chunk = this._buffer.splice(0, this._chunkSamples);
      const int16 = new Int16Array(chunk);
      // Transfer the underlying buffer so it's zero-copy
      this.port.postMessage(int16.buffer, [int16.buffer]);
    }

    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
