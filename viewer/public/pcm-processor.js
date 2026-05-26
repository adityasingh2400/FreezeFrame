/**
 * AudioWorklet processor — Float32 → Int16 PCM at 16kHz.
 * Runs in the audio rendering thread; posts Int16 chunks to main thread.
 *
 * Uses 512-sample chunks (~32ms) for low-latency streaming to Gemini Live.
 * Pre-allocated ring buffer avoids GC pressure in the real-time audio thread.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._chunkSamples = 512;  // ~32ms @ 16kHz — sweet spot for Gemini VAD
    this._ring = new Int16Array(2048);
    this._writePos = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const float32 = input[0];
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      this._ring[this._writePos++] = s < 0 ? (s * 0x8000) | 0 : (s * 0x7fff) | 0;

      if (this._writePos >= this._chunkSamples) {
        const chunk = new Int16Array(this._chunkSamples);
        chunk.set(this._ring.subarray(0, this._chunkSamples));
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this._writePos = 0;
      }
    }

    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
