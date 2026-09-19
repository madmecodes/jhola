/**
 * Mic capture and playback for the Jhola voice assistant.
 *
 * Capture: an AudioWorklet reads the mic at 16 kHz (the AudioContext resamples), converts to
 * PCM16 and hands 20 ms frames to the caller. Playback: 24 kHz PCM16 chunks from Nova Sonic are
 * queued into a small jitter buffer and scheduled back to back, so speech does not stutter.
 */

export const INPUT_RATE = 16000;
export const OUTPUT_RATE = 24000;

const WORKLET = `
class JholaCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = [];
    this.target = 320; // 20 ms at 16 kHz
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];
    for (let i = 0; i < ch.length; i++) this.buf.push(ch[i]);
    while (this.buf.length >= this.target) {
      const frame = this.buf.splice(0, this.target);
      const pcm = new Int16Array(frame.length);
      let peak = 0;
      for (let i = 0; i < frame.length; i++) {
        const s = Math.max(-1, Math.min(1, frame[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (Math.abs(s) > peak) peak = Math.abs(s);
      }
      this.port.postMessage({ pcm: pcm.buffer, peak }, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor("jhola-capture", JholaCapture);
`;

export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;

  constructor(
    private onFrame: (pcm: ArrayBuffer) => void,
    private onLevel?: (level: number) => void,
  ) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx({ sampleRate: INPUT_RATE });
    await this.ctx.resume();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try {
      await this.ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "jhola-capture", { numberOfInputs: 1, numberOfOutputs: 0 });
    this.node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; peak: number }>) => {
      const rate = this.ctx?.sampleRate ?? INPUT_RATE;
      this.onFrame(rate === INPUT_RATE ? e.data.pcm : downsample(e.data.pcm, rate, INPUT_RATE));
      this.onLevel?.(e.data.peak);
    };
    source.connect(this.node);
  }

  stop(): void {
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.node = null;
    this.stream = null;
    this.ctx = null;
  }
}

/** Linear resample, used only if the browser refuses a 16 kHz AudioContext. */
function downsample(buffer: ArrayBuffer, from: number, to: number): ArrayBuffer {
  const input = new Int16Array(buffer);
  const ratio = from / to;
  const out = new Int16Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) out[i] = input[Math.floor(i * ratio)];
  return out.buffer;
}

export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private playAt = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private leadSeconds = 0.12; // jitter buffer

  constructor(private onSpeaking?: (speaking: boolean) => void) {}

  async ensure(): Promise<AudioContext> {
    if (!this.ctx) {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new Ctx({ sampleRate: OUTPUT_RATE });
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
    return this.ctx;
  }

  async push(pcm: ArrayBuffer): Promise<void> {
    const ctx = await this.ensure();
    const input = new Int16Array(pcm);
    if (!input.length) return;
    const buffer = ctx.createBuffer(1, input.length, OUTPUT_RATE);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < input.length; i++) ch[i] = input[i] / 0x8000;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    const now = ctx.currentTime;
    if (this.playAt < now + 0.02) this.playAt = now + this.leadSeconds;
    src.start(this.playAt);
    this.playAt += buffer.duration;
    this.sources.add(src);
    this.onSpeaking?.(true);
    src.onended = () => {
      this.sources.delete(src);
      if (!this.sources.size) this.onSpeaking?.(false);
    };
  }

  /** Barge-in: drop everything queued and stop immediately. */
  flush(): void {
    this.sources.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    this.sources.clear();
    this.playAt = 0;
    this.onSpeaking?.(false);
  }

  close(): void {
    this.flush();
    void this.ctx?.close();
    this.ctx = null;
  }
}
