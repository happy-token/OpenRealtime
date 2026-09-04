// Clean-room reference implementation of the startup pre-buffer observed in
// the local Codex Voice client. It preserves speech captured while WebRTC and
// the Realtime session finish their startup barriers.

const BUFFER_SECONDS = 30;
const PRE_ROLL_SECONDS = 0.1;
const SILENCE_THRESHOLD = 0.003;

class FloatRingBuffer {
  constructor(capacity) {
    this.values = new Float32Array(capacity);
    this.start = 0;
    this.length = 0;
  }

  push(values) {
    for (let index = 0; index < values.length; index += 1) {
      const writeIndex = (this.start + this.length) % this.values.length;
      this.values[writeIndex] = values[index];
      if (this.length < this.values.length) {
        this.length += 1;
      } else {
        this.start = (this.start + 1) % this.values.length;
      }
    }
  }

  drainTrimmed(threshold, preRollSamples) {
    const ordered = new Float32Array(this.length);
    for (let index = 0; index < this.length; index += 1) {
      ordered[index] = this.values[(this.start + index) % this.values.length];
    }
    let firstSignal = 0;
    while (firstSignal < ordered.length && Math.abs(ordered[firstSignal]) < threshold) {
      firstSignal += 1;
    }
    const keptFrom = Math.max(0, firstSignal - preRollSamples);
    this.start = 0;
    this.length = 0;
    return ordered.subarray(keptFrom);
  }
}

class RealtimePrebufferProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = "buffering";
    this.history = new FloatRingBuffer(Math.ceil(sampleRate * BUFFER_SECONDS));
    this.replay = new Float32Array(0);
    this.replayOffset = 0;
    this.port.onmessage = ({ data }) => {
      if (data?.type !== "release" || this.phase !== "buffering") return;
      this.replay = this.history.drainTrimmed(
        SILENCE_THRESHOLD,
        Math.ceil(sampleRate * PRE_ROLL_SECONDS),
      );
      this.phase = "replaying";
    };
  }

  process(inputs, outputs) {
    const input = inputs[0]?.[0];
    const output = outputs[0]?.[0];
    if (!output) return true;
    output.fill(0);
    if (!input) return true;

    if (this.phase === "buffering") {
      this.history.push(input);
      return true;
    }

    if (this.phase === "live") {
      output.set(input.subarray(0, output.length));
      return true;
    }

    let written = 0;
    while (written < output.length && this.replayOffset < this.replay.length) {
      output[written] = this.replay[this.replayOffset];
      written += 1;
      this.replayOffset += 1;
    }
    if (this.replayOffset >= this.replay.length) {
      // Input that overlaps the short replay window is intentionally dropped;
      // queueing it would make startup latency permanent because an
      // AudioWorklet cannot emit samples faster than the render clock.
      if (written < output.length) {
        output.set(input.subarray(written, output.length), written);
      }
      this.phase = "live";
    }
    return true;
  }
}

registerProcessor("realtime-prebuffer", RealtimePrebufferProcessor);
