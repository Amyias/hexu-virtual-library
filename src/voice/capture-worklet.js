/* Microphone capture on the audio thread, for continuous listening (server-asr.js). It only
   collects samples into blocks and hands them to the page, so a slow frame on the main thread
   delays sending a block but never loses audio. */
const BLOCK = 1024;

class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(BLOCK);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (let at = 0; at < channel.length;) {
      const count = Math.min(channel.length - at, BLOCK - this.filled);
      this.block.set(channel.subarray(at, at + count), this.filled);
      this.filled += count;
      at += count;
      if (this.filled === BLOCK) {
        this.port.postMessage(this.block, [this.block.buffer]);
        this.block = new Float32Array(BLOCK);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("hexu-capture", Capture);
