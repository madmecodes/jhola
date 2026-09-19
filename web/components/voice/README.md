# JholaVoiceAssistant

Real-time voice shopping for the /store page. The browser captures the mic at 16 kHz, streams PCM16
to the Jhola voice server over a WebSocket, and plays back Amazon Nova 2 Sonic's 24 kHz speech while
cart, policy and order events arrive as JSON. Hindi, Hinglish and Indian English, with barge-in.

## Usage

```tsx
"use client";
import { useState } from "react";
import JholaVoiceAssistant from "@/components/voice/JholaVoiceAssistant";
import type { VoiceCart, VoiceOrder } from "@/lib/voice/types";

const VOICE_WSS = process.env.NEXT_PUBLIC_JHOLA_VOICE_WSS ?? "";

export function StoreVoice() {
  const [voiceCart, setVoiceCart] = useState<VoiceCart | null>(null);

  return (
    <JholaVoiceAssistant
      apiUrl={VOICE_WSS}
      member="dad"
      onCartUpdate={(cart: VoiceCart) => setVoiceCart(cart)}
      onOrder={(order: VoiceOrder) => console.log(order.status, order.order_id)}
    />
  );
}
```

`"use client"` is required (mic, WebSocket, AudioWorklet). The component renders nothing on the
server and asks for mic permission only when the user taps the button.

## Props

| Prop | Type | Required | Default | What it does |
|---|---|---|---|---|
| `apiUrl` | `string` | yes | - | `wss://` URL of the voice server (CloudFront). Set `NEXT_PUBLIC_JHOLA_VOICE_WSS` in Vercel |
| `member` | `"mom" \| "dad" \| "didi" \| "teen"` | yes | - | Acting family member. The server evaluates that member's Cedar rules; the model cannot change it |
| `onCartUpdate` | `(cart: VoiceCart) => void` | no | - | Fires on every cart change and once right after connecting (empty cart) |
| `onOrder` | `(order: VoiceOrder) => void` | no | - | Fires when checkout returns: `paid`, `pending_approval` or `denied` |
| `onDecisions` | `(d: VoiceDecisions) => void` | no | - | Cedar per-line decisions when the assistant checks the cart before ordering |
| `voice` | `"kiara" \| "arjun"` | no | `"kiara"` | Nova Sonic Indian voice (feminine / masculine) |
| `className` | `string` | no | `""` | Extra classes on the outer card |
| `showTranscript` | `boolean` | no | `true` | Set to `false` to render your own transcript from `onCartUpdate` siblings |

Types live in `web/lib/voice/types.ts` (`VoiceCart`, `VoiceCartLine`, `VoiceDecisions`, `VoiceOrder`,
`VoiceMember`). The component owns no global state and can be mounted more than once, but the server
allows two concurrent sessions per IP.

## What the user sees

Tap to talk, a live level meter, transcript bubbles for both sides, the voice cart, the Cedar
outcome (auto-pay / needs Mom's approval / blocked, with reasons and policy ids) and the order
result with the simulated UPI reference. Errors (mic blocked, server unreachable, session limit)
render as text inside the card.

## Behaviour notes

- Sessions are capped at 5 minutes; the remaining time is shown while connected.
- Barge-in: when the user speaks over the assistant, queued playback is dropped immediately.
- Orders placed by voice go through the same `submit_order` gate as WhatsApp, so they appear in the
  console with `channel: voice`.
- Chrome desktop and Android Chrome. iOS Safari needs the tap to start (it has one) and is untested.
- The page must be served over HTTPS (or localhost) for microphone access.
