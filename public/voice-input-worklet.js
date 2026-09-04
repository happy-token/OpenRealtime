const TARGET_RATE_HZ = 16000;
const DEFAULT_FRAME_SAMPLES = 512;
const DEFAULT_MAX_BUFFER_FRAMES = Math.ceil(30000 / 32);
const DEFAULT_MAX_REPLAY_RATE = 2;
const DEFAULT_SILENCE_THRESHOLD = 0.003;
const DEFAULT_PRE_ROLL_FRAMES = Math.ceil(100 / 32);

class VoiceInputProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const config = options?.processorOptions ?? {};
    this._frameSamples = positiveInteger(config.flushSampleCount, DEFAULT_FRAME_SAMPLES);
    this._maxBufferFrames = positiveInteger(
      config.maxBufferFrames,
      DEFAULT_MAX_BUFFER_FRAMES,
    );
    this._maxReplayRate = Math.max(
      1,
      Math.min(DEFAULT_MAX_REPLAY_RATE, Number(config.maxReplayRate) || DEFAULT_MAX_REPLAY_RATE),
    );
    this._silenceThreshold = boundedNumber(
      config.silenceThreshold,
      DEFAULT_SILENCE_THRESHOLD,
      0,
      1,
    );
    this._preRollFrames = nonNegativeInteger(
      config.preRollFrames,
      DEFAULT_PRE_ROLL_FRAMES,
    );
    this._ratio = sampleRate / TARGET_RATE_HZ;
    this._inputEpoch = String(config.inputEpoch ?? "");
    this._state = "buffering";
    this._muted = false;
    this._downstreamPaused = false;
    this._speechDetected = false;
    this._preRoll = [];
    this._aggregateEnergy = 0;
    this._observedFrames = 0;
    this._source = new Float32Array(0);
    this._readPos = 0;
    this._pendingSamples = [];
    this._queuedFrames = [];
    this.port.onmessage = (event) => this._handleCommand(event.data);
  }

  _handleCommand(command) {
    if (!command || typeof command.type !== "string") return;
    if (command.type === "release") {
      if (command.input_epoch !== this._inputEpoch || this._state !== "buffering") return;
      this._state = this._queuedFrames.length === 0 ? "live" : "replaying";
      this._clearPreRoll();
      return;
    }
    if (command.type === "mute") {
      this._muted = Boolean(command.muted);
      return;
    }
    if (command.type === "reset") {
      this._reset(String(command.input_epoch ?? ""));
      return;
    }
    if (command.type === "begin_epoch") {
      this._reset(String(command.input_epoch ?? ""));
      this._state = "buffering";
      return;
    }
    if (command.input_epoch !== this._inputEpoch) return;
    if (command.type === "downstream_pause") {
      this._downstreamPaused = true;
      return;
    }
    if (command.type === "downstream_resume") {
      this._downstreamPaused = false;
      if (this._state === "live" && this._queuedFrames.length > 0) {
        this._state = "replaying";
      }
    }
  }

  _reset(nextEpoch) {
    for (const frame of this._queuedFrames) frame.pcm16.fill(0);
    this._queuedFrames = [];
    this._clearPreRoll();
    this._pendingSamples.fill(0);
    this._pendingSamples = [];
    this._source.fill(0);
    this._source = new Float32Array(0);
    this._readPos = 0;
    this._downstreamPaused = false;
    this._speechDetected = false;
    this._aggregateEnergy = 0;
    this._observedFrames = 0;
    this._inputEpoch = nextEpoch;
    this._state = "reset";
  }

  _appendInput(chunk) {
    const consumed = Math.min(Math.floor(this._readPos), this._source.length);
    const kept = this._source.length - consumed;
    const merged = new Float32Array(kept + chunk.length);
    merged.set(this._source.subarray(consumed));
    merged.set(chunk, kept);
    this._readPos -= consumed;
    this._source = merged;
  }

  _makeFrames(input) {
    this._appendInput(input);
    while (this._readPos + 1 < this._source.length) {
      const index = Math.floor(this._readPos);
      const fraction = this._readPos - index;
      const sample = this._source[index] * (1 - fraction)
        + this._source[index + 1] * fraction;
      const clamped = Math.max(-1, Math.min(1, sample));
      this._pendingSamples.push(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
      this._readPos += this._ratio;
    }

    const frames = [];
    while (this._pendingSamples.length >= this._frameSamples) {
      const pcm16 = new Int16Array(this._frameSamples);
      for (let index = 0; index < this._frameSamples; index += 1) {
        pcm16[index] = this._pendingSamples[index];
      }
      this._pendingSamples = this._pendingSamples.slice(this._frameSamples);
      frames.push(pcm16);
    }
    return frames;
  }

  _enqueue(pcm16, captureMode, energy = frameEnergy(pcm16)) {
    if (this._queuedFrames.length >= this._maxBufferFrames) {
      const failedEpoch = this._inputEpoch;
      const bufferedFrames = this._queuedFrames.length;
      const aggregateEnergy = this._observedFrames === 0
        ? 0
        : this._aggregateEnergy / this._observedFrames;
      this._reset("");
      this.port.postMessage({
        type: "overflow",
        inputEpoch: failedEpoch,
        bufferedFrames,
        aggregateEnergy,
      });
      return false;
    }
    this._queuedFrames.push({ pcm16, captureMode, energy });
    return true;
  }

  _clearPreRoll() {
    for (const frame of this._preRoll) frame.pcm16.fill(0);
    this._preRoll = [];
  }

  _bufferBeforeRelease(pcm16, energy) {
    if (this._speechDetected) return this._enqueue(pcm16, "prebuffer", energy);
    if (energy >= this._silenceThreshold) {
      this._speechDetected = true;
      for (const frame of this._preRoll) {
        if (!this._enqueue(frame.pcm16, "prebuffer", frame.energy)) return false;
      }
      this._preRoll = [];
      return this._enqueue(pcm16, "prebuffer", energy);
    }
    if (this._preRollFrames === 0) {
      pcm16.fill(0);
      return true;
    }
    this._preRoll.push({ pcm16, energy });
    while (this._preRoll.length > this._preRollFrames) {
      this._preRoll.shift().pcm16.fill(0);
    }
    return true;
  }

  _post(frame) {
    const message = {
      type: "audio_frame",
      inputEpoch: this._inputEpoch,
      captureMode: frame.captureMode,
      pcm16: frame.pcm16.buffer,
    };
    this.port.postMessage(message, [frame.pcm16.buffer]);
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input || input.length === 0 || this._muted || this._state === "reset") {
      return true;
    }
    const frames = this._makeFrames(input);
    const measured = frames.map((pcm16) => {
      const energy = frameEnergy(pcm16);
      this._aggregateEnergy += energy;
      this._observedFrames += 1;
      return { pcm16, energy };
    });
    if (this._state === "live" && !this._downstreamPaused) {
      for (const frame of measured) this._post({ ...frame, captureMode: "live" });
      return true;
    }

    if (this._state === "buffering") {
      for (const frame of measured) {
        if (!this._bufferBeforeRelease(frame.pcm16, frame.energy)) return true;
      }
      return true;
    }

    for (const frame of measured) {
      if (!this._enqueue(frame.pcm16, "live", frame.energy)) return true;
    }
    if (this._state === "live") this._state = "replaying";
    if (this._state === "replaying" && !this._downstreamPaused) {
      const replayBudget = Math.floor(frames.length * this._maxReplayRate);
      for (let count = 0; count < replayBudget && this._queuedFrames.length > 0; count += 1) {
        this._post(this._queuedFrames.shift());
      }
      if (this._queuedFrames.length === 0) this._state = "live";
    }
    return true;
  }
}

function positiveInteger(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function nonNegativeInteger(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}

function boundedNumber(value, fallback, minimum, maximum) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(minimum, Math.min(maximum, number)) : fallback;
}

function frameEnergy(pcm16) {
  if (pcm16.length === 0) return 0;
  let squared = 0;
  for (let index = 0; index < pcm16.length; index += 1) {
    const normalized = pcm16[index] / 0x8000;
    squared += normalized * normalized;
  }
  return Math.sqrt(squared / pcm16.length);
}

registerProcessor("voice-input", VoiceInputProcessor);
