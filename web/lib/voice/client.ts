/** WebSocket client for the Jhola voice server: mic in, Nova Sonic audio and events out. */

import { MicCapture, PcmPlayer } from "./audio";
import type { VoiceMember, VoiceServerEvent } from "./types";

export type VoiceClientHandlers = {
  onEvent: (event: VoiceServerEvent) => void;
  onLevel?: (level: number) => void;
  onSpeaking?: (speaking: boolean) => void;
  onClose?: (reason: string) => void;
};

export class VoiceClient {
  private ws: WebSocket | null = null;
  private mic: MicCapture | null = null;
  private player: PcmPlayer;
  private stopped = false;

  constructor(
    private url: string,
    private member: VoiceMember,
    private handlers: VoiceClientHandlers,
    private voice: string = "kiara",
  ) {
    this.player = new PcmPlayer(handlers.onSpeaking);
  }

  async start(): Promise<void> {
    await this.player.ensure(); // unlock audio inside the click handler
    this.mic = new MicCapture(
      (pcm) => {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
      },
      this.handlers.onLevel,
    );
    await this.mic.start();

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(this.url);
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", member: this.member, voice: this.voice }));
        resolve();
      };
      ws.onerror = () => reject(new Error("could not reach the voice server"));
      ws.onmessage = (e) => this.onMessage(e);
      ws.onclose = (e) => {
        if (!this.stopped) this.handlers.onClose?.(e.reason || "connection closed");
        this.cleanup();
      };
    });
  }

  private onMessage(e: MessageEvent): void {
    if (e.data instanceof ArrayBuffer) {
      void this.player.push(e.data);
      return;
    }
    let msg: VoiceServerEvent;
    try {
      msg = JSON.parse(e.data as string) as VoiceServerEvent;
    } catch {
      return;
    }
    if (msg.type === "interrupted") this.player.flush();
    this.handlers.onEvent(msg);
  }

  stop(): void {
    this.stopped = true;
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "stop" }));
    this.cleanup();
  }

  private cleanup(): void {
    this.mic?.stop();
    this.mic = null;
    this.player.close();
    try {
      this.ws?.close();
    } catch {
      /* already closing */
    }
    this.ws = null;
  }
}
