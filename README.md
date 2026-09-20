# Jhola

Jhola is the approval layer for agents that spend your money: the model builds the cart, a Cedar policy engine outside the model decides whether it may pay, and every decision cites the rule that made it.

It runs on WhatsApp for an Indian household - a handwritten parchi, a Hindi voice note, a house help, a teenager - because that is where the delegation problem is most obvious.

## Why now

At the Global Fintech Fest on 10 September 2026, NPCI chairman Ajay Kumar Choudhary drew the line for agentic payments in India. As reported, he said: "An AI agent may work out what a user wants. It should not be the thing that approves the payment." He also said "decision making and execution must remain separate", and that "an agent may read intent. Verifying identity, mandate, limits and consent sits with the authoriser." NPCI has said no agent-authorisation framework exists yet for UPI.

The next day, at the same event, Amazon Pay launched agentic UPI payments: a Smart Wallet that lets AI agents make UPI payments on a user's behalf, live first for flight booking. Amazon Pay already runs UPI Circle, which since around October 2025 has let one person delegate UPI spending to another - full and partial delegation, spending limits - aimed at household managers, teenagers aged 13 to 17 and dependents without their own bank accounts, across a reported 110 million-plus Amazon Pay UPI customers with about 75% of usage coming from tier-2 and tier-3 towns. Alexa+ launched in India on 16 September 2026 with household member recognition, and Amazon has said Amazon Now ordering - reported at about USD 1 billion annualised with orders doubling quarterly - will come to Alexa+ by voice.

So the pieces are arriving in the same quarter: agents that can pay, a household that already delegates, and an assistant that knows which family member is speaking. The piece nobody has shipped is the authoriser NPCI described.

**UPI Circle delegates to a person. Nobody has delegated to an agent, because there is no framework for it yet - NPCI said so on 10 September 2026.**

Jhola is a working sketch of that missing piece. The model reads intent. A deterministic engine verifies identity, mandate, limits and consent, and writes down why.

## What it is

A family member sends what they already send today: a photo of a handwritten parchi, a voice note, or a typed list in Hindi, Hinglish or English. A Strands agent on Amazon Bedrock (Claude Sonnet 5) turns it into a cart of the family's usual brands. Then a separate Cedar policy engine decides what happens to that cart: auto-pay from the household's UPI AutoPay mandate, hold it for the admin's one-tap approval, or block it. The model has no payment tool. Every step is written to an audit log.

**Scope.** I did not need real money to build the authorisation layer. The authorisation layer is the part that does not exist yet. So the UPI AutoPay mandate, the debits and the UPI references are a simulation in `agent/src/jhola/upi.py` - a monthly cap, idempotent debits per order, 12-digit UPI-style references, and a refusal to debit without a signed authorisation from the policy engine. Everything the family sees says SIMULATED. Everything above the payment rail - the channel, the models, the policy engine, the audit trail, the tenancy - is real and deployed.

Built solo by Ayush Gupta ([madmecodes](https://github.com/madmecodes)) for the WeMakeDevs x AWS "First Commit" hackathon, Ship It track.

- Live site: https://jhola-phi.vercel.app (landing, `/console`, `/store` with live voice)
- WhatsApp: +91 96063 54404
- Console API: https://excijvqrxi.execute-api.ap-south-1.amazonaws.com
- Voice WebSocket: wss://d1askyzfnq83xf.cloudfront.net
- Hackathon writeup: [SUBMISSION.md](SUBMISSION.md). Deeper walkthrough: [docs/architecture.md](docs/architecture.md). Demo video script: [docs/demo-script.md](docs/demo-script.md).

## The boundary

The model is good at understanding "do we have chawal at home" and bad at being a security boundary. So the model proposes and a deterministic engine decides.

- **The model cannot pay.** It can build carts and call `submit_order`. Payment happens inside `submit_order`, only after Cedar allows.
- **The mandate refuses unsigned debits.** The mandate service will not debit without an HMAC-signed `PaymentAuthorization` issued by the policy engine for that exact order, amount, action and member. The key never leaves the engine. It is defence in depth against a future bug that calls the mandate from the wrong place.
- **Cedar, not prompt rules.** Prompt rules are advice. Cedar rules are enforced, typed against a schema (`agent/src/jhola/policies/jhola.cedarschema`), validated before activation, and return the policy ids that decided. Per line: role and category scope, seller rating, quantity caps, dietary and allergy rules checked against the person the item is for. Per order: the monthly mandate cap, the approval threshold, personal daily and per-order limits, time-boxed delegations.
- **Every decision cites its rule.** Each Cedar result carries the matching policy ids, an English reason and a Hinglish line, with the household's own numbers filled in. That is what the family reads on WhatsApp and what the console shows.
- **Plain words still work.** "No chocolate for Aarav" is drafted into Cedar by Bedrock against the schema, validated by cedarpy (one automatic repair attempt), tested against the model's own generated cases, and only then can the admin activate it. Custom rules run alongside the base policies; forbid always wins.
- **Untrusted text is data.** Seller descriptions, text inside images and transcripts are labelled as data in tool results and the system prompt, a pattern check flags suspicious descriptions into the audit log, and the voice server withholds them. None of that is the safety boundary. Cedar is.

## The red team: containment you can exercise

The demo I most wanted was prompt injection. I wrote one, ran it, and Claude ignored it. I wrote nastier ones. All ignored.

That is exactly what you want from a model, and it is useless as evidence. A defence you cannot exercise is a defence you cannot trust, because someday a model, a prompt or a fine-tune will fail and you need to know what happens next.

So `agent/src/jhola/stub_model.py` contains a scripted Strands model provider that plays a fully compromised model: it reads the injection and obeys it to the letter. Everything after the model is real - the tool loop, Cedar, the mandate, the audit trail, seeded with the live mandate usage and the household's real rules. Cedar sees what the compromised model built, the forbid fires, no line survives, and the mandate is never called.

Run it yourself: https://jhola-phi.vercel.app/console/redteam, three attacks (prompt injection in a seller listing, overspend past the mandate, forbidden category). The page says in bold that the model is deliberately compromised. `POST /api/redteam {"attack": "injection" | "overspend" | "forbidden_category"}` on the console API does the same thing without a browser, and `agent/tests/` covers the same paths offline.

## The audit trail

Everything is recorded: message received, items extracted, each Cedar request and result with its policy ids, the payment, the notification, the admin action, and every refused admin attempt. Phone numbers are masked. The admin can open it at https://jhola-phi.vercel.app/console/audit. This is the half of "an agent spent my money" that usually does not exist: not just that it was blocked, but which rule blocked it and what the family was told.

Household isolation is enforced the same way: services only ever receive a `ScopedRepository` that prefixes every key with `hh#<household_id>#`, and a test runs two households side by side and asserts neither can see the other's orders, mandate, rules or audit trail. It caught a real isolation bug.

## Evaluation

76 cases through the real pipeline (Strands agent on live Bedrock, tools, Cedar, simulated UPI), each in its own fresh copy of the demo household: aliases and Hinglish typos, Indian quantity words, parchi-style lists, ambiguous items, product questions, admin commands, policy cases for every role, dietary and allergy cases, and 11 adversarial / prompt-injection cases.

EVAL RESULTS: see [agent/evals/RESULTS.md](agent/evals/RESULTS.md) for the full table, methodology and every diagnosed failure.

## Try it in 2 minutes

**WhatsApp (any number works)**

1. Message +91 96063 54404 on WhatsApp with "hi".
2. Answer three questions: your name and what to call the home, a monthly budget (default Rs 5000), an approval threshold (default Rs 1000). You are now the admin of your own household.
3. Send a list: "2 kg atta, 1 litre doodh, pyaaz" or a photo of a handwritten list or a voice note.
4. Add family in plain words: "Add Sunita didi +91 98765 43210, groceries only, 500 a day". Tap Yes. Ask them to say hi to the number.
5. Say "Show my rules" or "This month's spending".

Replies work inside WhatsApp's 24-hour window, so message the number first if you have not for a day. Only numbers that have messaged Jhola can be messaged back.

**Web console (no WhatsApp needed)**

- https://jhola-phi.vercel.app/console/redteam: run three attacks through the real pipeline with a deliberately compromised model. Watch Cedar block them and see the audit trail.
- https://jhola-phi.vercel.app/console/try: chat as Mom, Dad, Didi or the teen against the live demo household. Attach a parchi photo. Didi's groceries pay, her shampoo does not; the teen gets the geometry box, not the Red Bull; Dad's dinner above Rs 1000 waits for Mom. Switch to Mom to tap Approve.
- https://jhola-phi.vercel.app/console/rules: type a rule in plain words ("No chocolate for Aarav"). See the drafted Cedar, the validator result and the auto-generated test cases. Activation needs the admin key.
- https://jhola-phi.vercel.app/store#voice: tap the mic and talk. Ask which dal has more protein, add it, say "order it". The order goes through the same Cedar gate. Chrome desktop or Android Chrome.

## Architecture

```mermaid
flowchart TB
    subgraph Family
        WA[WhatsApp user]
        BR[Browser: console and store]
    end

    subgraph Infra["AWS account A (ap-south-1)"]
        EUM[End User Messaging Social]
        SNS[SNS jhola-whatsapp-events]
        L1[Lambda jhola-whatsapp-agent<br/>Strands agent]
        L2[Lambda jhola-console-api]
        APIGW[API Gateway HTTP API]
        SCH[EventBridge Scheduler<br/>Sunday 09:00 IST]
        DDB[(DynamoDB jhola-state<br/>hh#household#collection)]
        DDB2[(DynamoDB processed-messages<br/>dedupe, rate limits)]
        S3[(S3 media<br/>7-day lifecycle)]
        TR[Amazon Transcribe]
        PO[Amazon Polly]
        SSM[SSM demo key]
        ALB[ALB]
        FG[Fargate: voice server<br/>WebSocket]
    end

    subgraph Bedrock["AWS account B (us-east-1)"]
        STS[IAM roles<br/>jhola-bedrock-invoker<br/>jhola-voice-bedrock-invoker]
        CS[Bedrock Claude Sonnet 5]
        NS[Bedrock Nova 2 Sonic]
        CF[CloudFront wss]
    end

    subgraph Agent["Inside each Lambda / task"]
        CED[Cedar policy gate<br/>items, diet, payments]
        UPI[Simulated UPI mandate<br/>signed authorization required]
    end

    V[Vercel: Next.js site]

    WA --> EUM --> SNS --> L1
    L1 --> S3 --> TR
    L1 --> PO
    L1 -- sts:AssumeRole --> STS --> CS
    L1 --> CED --> UPI --> DDB
    L1 --> DDB2
    BR --> V
    BR --> APIGW --> L2
    L2 -- sts:AssumeRole --> STS
    L2 --> CED
    L2 --> DDB
    L2 --> SSM
    SCH --> L2
    BR -- wss --> CF --> ALB --> FG
    FG -- sts:AssumeRole --> STS --> NS
    FG --> CED
    FG --> DDB
```

Two accounts: the infra account holds WhatsApp, Lambda, DynamoDB, S3, Transcribe, Polly, ECS and API Gateway. The Bedrock account holds two IAM roles, each trusting exactly one execution role in the infra account and allowing exactly one model. The Lambda and the Fargate task get one-hour STS credentials. There are no long-lived keys anywhere. See [docs/architecture.md](docs/architecture.md) for sequence diagrams and the data model.

## Security

- Least privilege IAM: the Lambda role can send and fetch media for one phone number id, read and write three S3 prefixes, use two DynamoDB tables, read one SSM parameter, and assume one role. The Bedrock-side roles trust one principal each and allow one model each.
- No long-lived keys. Lambda and Fargate use execution roles; Bedrock is reached with one-hour STS credentials refreshed every 45 minutes.
- Phone numbers are masked (`+91******8243`) in logs, API responses and audit data.
- Rate limits: API Gateway stage throttle (burst 20, 10 rps) plus per-IP per-minute counters in DynamoDB (120 reads, 20 writes for chat, rule drafts and red team). Text capped at 1000 characters, images at 4 MB. Voice: 5-minute sessions, 2 per IP, origin allow-list.
- The console demo key lives in an SSM SecureString, is read at cold start, and gates approvals, rule activation, refill runs, reset and any non-demo household.
- Admin actions are decided in code: `admin.py` checks the role on propose and again on confirm, refused attempts are audited, and confirmation text is written by code so the Yes button does exactly what it says.
- WhatsApp message dedupe by message id (TTL 7 days). Inbound media expires from S3 after 7 days.
- CORS is limited to the Vercel origin and localhost. The ALB only accepts CloudFront origin-facing ranges.

## More that is built

The delegation layer needs a product around it, so there is one. None of this is the point of the submission; all of it is live.

**Inputs**
- Typed lists in English, Hindi or Hinglish ("arhar ki dal", "kothmir", "dudh").
- Handwritten parchi photo, read by Bedrock vision (Claude Sonnet 5, Converse API).
- WhatsApp voice notes, transcribed with Amazon Transcribe (hi-IN / en-IN language identification). Replies come back as text plus a short spoken reply (Amazon Polly, Kajal, hi-IN).
- Live voice-to-voice in the browser store with Amazon Nova 2 Sonic: barge-in, Hindi/Hinglish, product comparison, nutrition questions, checkout.

**Household**
- Identity is the sender's WhatsApp phone number. No login, no app.
- Onboarding for unknown numbers: three deterministic questions, no LLM, creates a household with that number as admin.
- Family admin in plain words: add or remove members, set daily and per-order limits, restrict categories, change the budget, set the approval threshold. Every change is a pending action shown with Yes / No buttons and written by code, not the model.
- Role templates: admin, adult, house_help, teen, elder.
- Learned usual brands: the first "atta" gets a sensible default; a paid order or an explicit pick ("Aashirvaad wala") becomes the household's preference.
- Delegation with expiry: "Didi can spend 1500 this week". Cedar honours `delegated_cap_inr` only while `context.today <= delegated_until`.
- Memory per member (history, language, limits) and per household (brands, pantry, rules, mandate).
- Pantry and refill prediction from purchase history; recipe expansion ("rajma chawal for 6").

**Dietary policy (`diet.cedar`)**
- Checked against the member the item is for (`context.beneficiary`, so "Dadi ke liye namkeen" ordered by Didi is checked against Dadi): vegetarian, eggetarian, vegan and Jain profiles, allergies, vrat (fasting) mode with an end date, a per-order caffeine cap and a default 100 mg cap for teens. The catalog carries `veg`, `jain_friendly`, `vrat_friendly`, allergens and caffeine per SKU.

**Proactive**
- Sunday 09:00 IST refill: EventBridge Scheduler invokes the console Lambda, which predicts what each household is running out of and sends the admin a draft cart with an "Order all" button (only when the 24-hour window is open).

**Console**
- Overview (members, limits, mandate usage, recent orders), audit trail, rules (base and custom, with Cedar source), try-it chat, red team. Reads are public; approvals, activation, refill and reset need the demo key.

## AWS services and why each is there

| Service | Why |
|---|---|
| AWS End User Messaging Social | The WhatsApp Business channel. Delivers inbound messages and media, sends text, interactive reply buttons and audio. |
| Amazon SNS | End User Messaging publishes webhook events to a topic. SNS gives async fan-out (an SQS debug mirror sits on the same topic) and retries. |
| AWS Lambda (arm64, Python 3.12) | Runs the Strands agent per message and the console API. Bursty, idle most of the day, no server to keep warm. |
| Amazon Bedrock, Claude Sonnet 5 | The agent model and the parchi vision reader (Converse API). Also drafts Cedar rules from plain words. |
| Amazon Bedrock, Nova 2 Sonic | Bidirectional speech-to-speech for the browser store. |
| Amazon DynamoDB | Single table `jhola-state` (`pk` = collection, `sk` = key) with per-household partitions. A second table dedupes WhatsApp message ids and holds rate-limit counters with TTL. |
| Amazon S3 | Inbound photos and voice notes, transcripts, outbound audio. Private, encrypted, 7-day lifecycle. |
| Amazon Transcribe | Voice notes to text with language identification limited to hi-IN and en-IN. |
| Amazon Polly | Short spoken reply (Kajal, hi-IN) when the member sent a voice note. |
| Amazon API Gateway (HTTP API) | Fronts the console Lambda with CORS locked to the Vercel origin and stage throttling. |
| Amazon EventBridge Scheduler | Sunday 09:00 IST cron in `Asia/Kolkata` for the weekly refill proposal. |
| AWS Systems Manager Parameter Store | SecureString holding the console demo key, read at cold start. |
| Amazon ECS on Fargate (arm64) | The voice WebSocket server. A Nova Sonic session is a long-lived bidirectional stream, which Lambda cannot hold. |
| Application Load Balancer | Health checks and routing to the Fargate task. Security group admits only CloudFront origin-facing ranges. |
| Amazon CloudFront | Gives the browser a trusted `wss://` endpoint without a custom domain. |
| AWS IAM and STS | Cross-account roles with one trusted principal and one allowed model each; one-hour credentials. |
| AWS SAM / CloudFormation | Everything above is in `infra/*.yaml`. |
| Amazon CloudWatch Logs | JSON logs with phone numbers masked, 7 to 14 day retention. |

## Design decisions

**Single DynamoDB table with household partitions.** `pk` is a collection name, prefixed with `hh#<household_id>#` for household data. Services only receive a `ScopedRepository` that adds the prefix, so a bug in order code cannot read another family's orders. Global collections (`phones`, `households`, `onboarding`) are the only unscoped ones. On-demand billing, no capacity planning, a single-digit number of items per order.

**SNS to Lambda.** End User Messaging Social publishes to SNS. Lambda subscribes with async invoke, one retry, and a 10-minute max event age. Duplicate deliveries are caught with a conditional put on the WhatsApp message id. Status webhooks (sent, delivered, read) hit the same function and are ignored.

**Fargate for voice, not Lambda.** Nova 2 Sonic is a bidirectional stream that lasts minutes with audio flowing both ways. Lambda has no long-lived WebSocket and a 15-minute ceiling with no bidirectional streaming. One 0.5 vCPU Fargate task behind an ALB handles the demo. It reuses the `jhola` package, so voice checkouts go through the same `submit_order`.

**Two Bedrock accounts.** The primary hackathon account's Bedrock model access was still pending activation, so model calls assume a role in a second account (`infra/bedrock-role.yaml`, `infra/voice-bedrock-role.yaml`). The role trusts only the Lambda and task roles and allows only the two models. Set `BedrockRoleArn=""` to run Bedrock in the same account once access is active. CloudFront also lives in the second account because the primary account is not verified for CloudFront.

**Latency trade-offs.** A text order takes four sequential model calls (resolve, build cart, submit, reply). Extended thinking is off (`JHOLA_THINKING=off`); measured on a 3-item order it saved 1 to 2 seconds and changed nothing, because Cedar makes the decision. The tool block is prompt-cached. Typical: text 10 to 30 s, parchi photo about 30 s, voice note about 30 s of which Transcribe is about 10 s. The console API answers slow calls with `202 {job_id}` after 24 s and the browser polls. Onboarding and admin confirmations are deterministic code with no model call, so they are instant.

## Cost

Rough estimate per 1,000 orders, marked as such. Assumptions: a text order makes four Claude Sonnet 5 calls with about 6,000 input tokens each (system prompt, tool schemas, catalog results, history) and about 400 output tokens each; 1 USD = Rs 88; Anthropic list price for Sonnet 5 of $2 per million input tokens and $10 per million output tokens (Bedrock pricing is set separately by AWS, so check the Bedrock price page); prompt caching of the tool block lowers the real input cost, ignored here.

| Item | Arithmetic | USD | INR |
|---|---|---|---|
| Bedrock input | 1,000 x 24,000 tokens = 24M x $2/M | 48.00 | 4,224 |
| Bedrock output | 1,000 x 1,600 tokens = 1.6M x $10/M | 16.00 | 1,408 |
| Parchi photos (say 30%) | 300 vision calls, about 2,000 image tokens each = 0.6M x $2/M | 1.20 | 106 |
| Voice notes (say 20%) | 200 x 0.3 min x $0.024/min Transcribe; 200 x 250 chars Polly neural at $16/M | 1.44 + 0.80 | 197 |
| Lambda | 1,000 x 20 s x 1 GB arm64 at about $0.0000133/GB-s, plus requests | 0.30 | 26 |
| DynamoDB | about 60 writes and 100 reads per order, on-demand | 0.10 | 9 |
| S3, SNS, API Gateway, CloudWatch | small at this volume | 0.50 | 44 |
| WhatsApp | user-initiated service conversations inside the 24-hour window are free | 0 | 0 |
| Total | | about 68 | about 6,000 |

So roughly Rs 6 per order, and Bedrock tokens are about 90% of it. The voice store is separate: one Fargate task (0.5 vCPU, 1 GB) and an ALB cost about $30 to $40 a month whether or not anyone talks to it, plus Nova 2 Sonic per-minute usage. Cutting cost means fewer model calls per order (merging resolve and build steps) and smaller tool results, not a cheaper model; Cedar does the deciding either way.

## Known limitations

- **The catalog is a demo catalog.** 601 SKUs modeled on Amazon.in grocery listings with Hindi/Hinglish aliases and search links. Prices, ratings, nutrition and stock are illustrative. No scraping. Jhola is not affiliated with Amazon. Nothing is fulfilled.
- **WhatsApp 24-hour window.** Jhola can only reply to a number that messaged it in the last 24 hours. Approval requests to an admin who has gone quiet are held and delivered when they next message. The Sunday refill skips such households. No approved templates yet.
- **Demo household.** The seeded Gupta family (Mom, Dad, Didi, Aarav, Dadi) has a demo phone with persona commands (`/as`, `/whoami`, `/reset`) that ordinary numbers do not get. The console defaults to this household; other households need the demo key.
- **Onboarding is admin-only by phone.** Members are added by the admin; WhatsApp does not allow Jhola to message a new number first, so the member has to say hi.
- **Diet and nutrition data is approximate.** The catalog's veg, Jain, vrat, allergen and nutrition fields are illustrative label-style data marked `nutrition_source: approximate`. The diet policies enforce them faithfully, but the data itself is demo data and nothing here is medical advice.
- **Voice.** One Fargate task, no autoscaling; sessions capped at 5 minutes; the cart lives in the session; approval requests from a voice checkout show in the console but are not pushed to WhatsApp from the voice server. Nova Sonic transcribes Hindi in Devanagari, so queries are transliterated before catalog search and unusual words fall back to fuzzy matching.
- **Latency.** 10 to 30 s per WhatsApp turn. Acceptable for a chat that replaces a phone call to the kirana, not for a chatbot.
- **Injection detection is a regex.** It is a flag for the audit log, not the defence. Cedar is.

## Run locally / deploy

**Agent (Python 3.12, [uv](https://docs.astral.sh/uv/))**

```bash
cd agent
uv sync
uv run pytest                                  # policy, payments, scenarios, API, tenancy, onboarding, admin, WhatsApp
uv run python -m jhola.scenarios               # scenarios A to F with the scripted stub model, no AWS needed
uv run python -m jhola.scenarios C --audit     # one scenario with the full audit trail
uv run python -m jhola.scenarios --live A B    # real Bedrock (profile "default", us-east-1 by default)
uv run python -m evals.run --live              # the 76-case eval suite against live Bedrock
```

`cd agent && uv run pytest` runs about 100 tests in a few seconds with no AWS access: Cedar decisions for every base policy, payment authorization and idempotent debit, scenarios A to F end to end with the scripted model, the console API, household isolation, onboarding, admin commands, and WhatsApp event parsing. `tests/test_e2e_dynamo.py` runs two households against the real table when `JHOLA_E2E_TABLE` is set. Environment variables (`JHOLA_MODEL_ID`, `JHOLA_BEDROCK_ROLE_ARN`, `JHOLA_ADMIN_PHONE`, and so on) are listed in [agent/README.md](agent/README.md).

**Infra (SAM, no Docker: the Makefile installs Linux arm64 wheels with uv)**

```bash
cd infra
sam build && sam deploy                        # stack "jhola", ap-south-1, settings in samconfig.toml
# once, in the Bedrock account, after the stack created the Lambda role
aws cloudformation deploy --template-file bedrock-role.yaml --stack-name jhola-bedrock-invoker \
  --capabilities CAPABILITY_NAMED_IAM --region us-east-1 --profile default
```

The WhatsApp Business account, phone number and SNS topic are created in the End User Messaging console and passed in as parameters. The demo key is an SSM SecureString created outside CloudFormation. Details, routes and the data migration: [infra/README.md](infra/README.md).

**Voice server (Docker, ECS Fargate)**: build an arm64 image, push to ECR, deploy `infra/voice.yaml`, `infra/voice-bedrock-role.yaml` and `infra/voice-cloudfront.yaml`. Steps in [voice/README.md](voice/README.md). Locally: `JHOLA_VOICE_MEMORY=1 uv run python -m jhola_voice.server`.

**Web (Next.js 16, Vercel)**

```bash
cd web
npm install
NEXT_PUBLIC_JHOLA_API=https://excijvqrxi.execute-api.ap-south-1.amazonaws.com \
NEXT_PUBLIC_JHOLA_VOICE_WSS=wss://d1askyzfnq83xf.cloudfront.net \
npm run dev                                    # without NEXT_PUBLIC_JHOLA_API the console runs on an in-browser mock
```

Deploy with `vercel` from `web/`; `vercel.json` sets the framework. Set the two `NEXT_PUBLIC_` variables in the Vercel project.

## Repository layout

```
agent/      Python package "jhola": Strands agent, tools, Cedar policies, order and mandate services,
            WhatsApp channel, console API, rules drafting, red team, onboarding, admin, tenancy, tests
  src/jhola/policies/   jhola.cedarschema, items.cedar, diet.cedar, payments.cedar
  src/jhola/data/       demo catalog (601 SKUs), demo household, recipes
  evals/                eval harness and RESULTS.md
infra/      SAM template (WhatsApp Lambda, console API, DynamoDB, S3, scheduler), cross-account Bedrock roles,
            voice ECS/ALB stack, CloudFront for wss
voice/      Python WebSocket server for Nova 2 Sonic, tools that reuse the jhola package, Dockerfile
web/        Next.js site: landing, /console (overview, audit, rules, try, redteam), /store with voice, privacy, terms
docs/       architecture.md, demo-script.md, blog-post.md
SUBMISSION.md   hackathon writeup
```

## AI tools used

- Claude Code (Anthropic) for writing and refactoring code, tests, infrastructure templates and documentation during the build.
- Claude Sonnet 5 on Amazon Bedrock is the runtime agent, vision reader and Cedar drafter. Amazon Nova 2 Sonic is the runtime voice model.
- The landing page photographs and the logo were generated with FLUX.2-pro.

## License

MIT. See [LICENSE](LICENSE).
