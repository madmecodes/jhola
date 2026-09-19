# Jhola voice assistant

Real-time voice-to-voice shopping for the Gupta family: the browser streams mic audio to a Python
WebSocket server, the server holds a bidirectional stream with **Amazon Nova 2 Sonic**
(`amazon.nova-2-sonic-v1:0`), and the model speaks back in Hinglish while calling shopping tools.

Orders placed by voice go through the **same Cedar policy gate as WhatsApp** (`Jhola.submit_order`),
so they auto-pay from the simulated UPI mandate, go to Mom for approval, or are denied - and they
show up in the console tagged `channel: voice`.

```
browser (AudioWorklet, 16 kHz PCM16)
   |  wss://<cloudfront>/  (binary audio frames + JSON control)
CloudFront (Bedrock account) -> ALB (ap-south-1) -> ECS Fargate ARM64 task
   |
jhola_voice.server     WebSocket session, origin check, per-IP limit, 5 min cap
jhola_voice.sonic      Nova 2 Sonic bidirectional stream (sessionStart / promptStart / audioInput)
jhola_voice.tools      search, details, compare, cart, check_cart (Cedar), checkout (submit_order)
   |
jhola package (agent/) -> DynamoDB jhola-state, household partition hh#demo-gupta#
                          (orders, mandate, txns, audit, voice_carts)
```

## Tools the model can call

| Tool | What it does |
|---|---|
| `search_products(query, category?)` | Catalog search. Devanagari queries are transliterated ("दूध" -> "doodh") and a misheard word is snapped to the closest catalog word |
| `get_product_details(sku)` | Price, MRP, pack, stock, fulfilment, seller rating, price per 100 g/ml, nutrition if the catalog has it (otherwise "not available"), closest in-stock swap |
| `compare_products(skus)` | Two to four products side by side |
| `add_to_cart` / `remove_from_cart` / `view_cart` | Session cart, mirrored to DynamoDB (`voice_carts`) |
| `check_cart` | Cedar per-line decisions, mandate remaining, and whether checkout would auto-pay, need approval or be denied. No payment |
| `checkout` | `Jhola.build_cart` + `Jhola.submit_order`: the real gate. Returns paid / pending_approval / denied |

The acting member (mom / dad / didi / teen) comes from the client `start` message, never from the
model, and the household is the multi-tenant `demo-gupta` partition by default
(`JHOLA_HOUSEHOLD_ID` picks another one), so every write lands where the console reads. The model has no payment tool; payment only happens inside `submit_order` after a Cedar allow.
Seller descriptions that look like prompt injection are withheld from the model.

## Wire protocol

Client to server: `{"type":"start","member":"dad","voice":"kiara"}`, then binary frames of 16 kHz
mono PCM16 (or `{"type":"audio","data":"<base64>"}`), and `{"type":"stop"}`.

Server to client: binary frames of 24 kHz mono PCM16 (assistant speech) plus JSON events
`ready`, `transcript` (user and assistant), `interrupted` (barge-in), `tool`, `cart`, `decisions`,
`order`, `error`, `ended`. `GET /health` returns `ok` for the load balancer.

Limits: 5 minute sessions, 2 concurrent sessions per IP, origin allow-list
(`https://jhola-phi.vercel.app`, `http://localhost:3000`).

## Run locally

```bash
cd voice
uv sync
uv run python scripts/make_wav.py                     # Polly Hinglish test utterances (infra account)
JHOLA_VOICE_MEMORY=1 uv run python -m jhola_voice.server      # in-memory state, Bedrock via profile "default"
uv run python scripts/test_client.py ws://localhost:8080 dad /tmp/jhola-voice/ask.wav /tmp/jhola-voice/order.wav
```

`JHOLA_VOICE_MEMORY=1` keeps orders out of the shared state. Without it the server uses
`agent/.state/jhola.json`, or DynamoDB when `JHOLA_TABLE` is set.

| Env | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | Listen port |
| `JHOLA_SONIC_MODEL_ID` | `amazon.nova-2-sonic-v1:0` | Nova Sonic model |
| `JHOLA_VOICE_BEDROCK_ROLE_ARN` | unset | Cross-account role to assume for Bedrock (set on ECS) |
| `JHOLA_BEDROCK_PROFILE` | `default` | Local AWS profile for Bedrock when no role is set |
| `JHOLA_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `JHOLA_TABLE` | unset | DynamoDB state table (`jhola-state` on AWS) |
| `JHOLA_HOUSEHOLD_ID` | `demo-gupta` | Household whose partition the session reads and writes |
| `JHOLA_VOICE_ORIGINS` | vercel + localhost | Allowed browser origins |
| `JHOLA_VOICE_MAX_SECONDS` | `300` | Session cap |
| `JHOLA_VOICE_MAX_PER_IP` | `2` | Concurrent sessions per IP |
| `JHOLA_VOICE_MEMORY` | unset | Use an in-memory repository instead of the shared state |

## Deploy

Two accounts, like the rest of Jhola: the server runs in the infra account, Bedrock lives in the
Bedrock account, and CloudFront sits in the Bedrock account too (the infra account is not verified
for CloudFront).

```bash
# 1. image (arm64) -> ECR in the infra account
aws ecr create-repository --repository-name jhola-voice --profile ayush-aws-bits-hack --region ap-south-1
aws ecr get-login-password --region ap-south-1 --profile ayush-aws-bits-hack \
  | docker login --username AWS --password-stdin 446413909932.dkr.ecr.ap-south-1.amazonaws.com
docker build --platform linux/arm64 -f voice/Dockerfile -t 446413909932.dkr.ecr.ap-south-1.amazonaws.com/jhola-voice:v1 .
docker push 446413909932.dkr.ecr.ap-south-1.amazonaws.com/jhola-voice:v1

# 2. ECS + ALB (infra account); creates the task role the Bedrock role trusts
aws cloudformation deploy --template-file infra/voice.yaml --stack-name jhola-voice \
  --capabilities CAPABILITY_NAMED_IAM --region ap-south-1 --profile ayush-aws-bits-hack \
  --parameter-overrides ImageUri=446413909932.dkr.ecr.ap-south-1.amazonaws.com/jhola-voice:v1 \
  VpcId=<vpc> "SubnetIds=<subnet-a>,<subnet-b>,<subnet-c>"

# 3. Bedrock role (Bedrock account), trusts only jhola-voice-task-role
aws cloudformation deploy --template-file infra/voice-bedrock-role.yaml \
  --stack-name jhola-voice-bedrock-invoker --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 --profile default

# 4. CloudFront (Bedrock account) in front of the ALB -> wss URL
aws cloudformation deploy --template-file infra/voice-cloudfront.yaml --stack-name jhola-voice-cdn \
  --region us-east-1 --profile default --parameter-overrides AlbDomainName=<jhola-voice AlbDns output>
```

A new image is rolled out with `docker push ...:vN` and step 2 again with the new tag.

Logs: CloudWatch `/ecs/jhola-voice`. Cost: one 0.5 vCPU / 1 GB Fargate task, an ALB, and Nova Sonic
usage (billed in the Bedrock account) while a session is open.

## Browser client

`web/components/voice/JholaVoiceAssistant.tsx` with `web/lib/voice/{audio,client,types}.ts`.
Props and usage: `web/components/voice/README.md`.

## Known limitations

- Nova 2 Sonic holds a stream for at most 8 minutes; sessions here are capped at 5.
- One task, no autoscaling: a handful of concurrent sessions, not a crowd.
- The cart lives in the session (mirrored to `voice_carts`); reconnecting starts a fresh cart.
- Nova Sonic transcribes Hindi in Devanagari, so catalog queries are transliterated before search.
  Unusual words fall back to a fuzzy match against catalog tags and aliases.
- Approval requests raised by a voice checkout are visible in the console; they are not pushed to
  WhatsApp from this server.
