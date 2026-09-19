# Jhola infra (AWS SAM)

Real WhatsApp messages to +91 96063 54404 are answered live by the Jhola agent. A console HTTP API
serves the web console, and a Sunday schedule proposes the weekly refill.

```
WhatsApp user
   |
AWS End User Messaging Social (WABA, ap-south-1)
   |  webhook events
SNS jhola-whatsapp-events ----> SQS jhola-whatsapp-inbox (debug mirror, untouched)
   |  async invoke
Lambda jhola-whatsapp-agent (Python 3.12, arm64, 1024 MB, 180 s)
   |- dedupe on WhatsApp message id      DynamoDB jhola-processed-messages (TTL 7 days)
   |- identity: phone -> household       DynamoDB jhola-state (pk=collection, sk=key)
   |  unknown number -> onboarding         global: households, phones, onboarding, wa_last_inbound
   |- state per household                  hh#<household_id>#orders | mandate | txns | audit | members |
   |                                       prefs | purchases | sessions | rules | pending_actions | counters
   |- photos + voice notes                S3 jhola-media-<acct>-ap-south-1 (private, 7-day lifecycle)
   |     GetWhatsAppMessageMedia -> S3 inbound/<mediaId>/
   |     voice notes -> Amazon Transcribe (IdentifyLanguage hi-IN / en-IN) -> transcripts/
   |- Strands agent + Cedar policies (agent/)
   |     Bedrock Claude Sonnet 5 via sts:AssumeRole into the Bedrock account (us-east-1)
   |- replies: SendWhatsAppMessage (text, interactive reply buttons)
         voice note in -> text reply + short spoken reply (Polly Kajal, hi-IN, ogg/opus)
```

## Console API

`ConsoleHttpApi` (API Gateway HTTP API) -> Lambda `jhola-console-api` (same package as the WhatsApp
agent, handler `jhola.api_handler.handler`, same IAM role so the Bedrock account trusts it).

Base URL: `https://excijvqrxi.execute-api.ap-south-1.amazonaws.com` (stack output `ApiBaseUrl`).
CORS: `https://jhola-phi.vercel.app`, `http://localhost:3000`. Stage throttle: burst 20, rate 10 rps.

Every route takes an optional `household_id` (query string, or JSON body on POST), default `demo-gupta`
so the console works unchanged. A `household_id` other than the demo household always requires the demo key.

| Method | Path | Access | Returns |
|---|---|---|---|
| GET | `/api/households` | demo key | `{households[{household_id,name,demo,created_at,member_count,admins[masked],members[{id,display,role,phone_masked}],monthly_cap_inr}]}` for a household switcher |
| GET | `/api/household` | public | `{household, members[{id,name,role,phone_masked,limits_summary}], rules[{id,title_en,title_hinglish,cedar,source}], mandate{cap_inr,used_inr,remaining_inr,period}}` |
| GET | `/api/orders?limit=20` | public | `{orders[{order_id,member_name,role,created_at,status,total_inr,paid_inr,upi_ref,items[{sku,name,brand,qty,price_inr,decision,policy_ids,reason,amazon_search_url,fulfilment}],channel,input_type}]}`, newest first, drafts excluded |
| GET | `/api/audit?order_id=&limit=100` | public | `{events[{seq,ts,order_id,type,actor,summary,data}]}`, oldest first (the last `limit` events), phone numbers masked |
| GET | `/api/approvals` | public | `{pending[{order_id,member_name,total_inr,items_count,created_at,reasons}]}` |
| GET | `/api/jobs/{job_id}` | public | `{job_id,kind,status: running/done/error,result,error}` |
| POST | `/api/approvals/{order_id}` | demo key | body `{decision: approve/reject}` -> order (409 if not pending) |
| POST | `/api/chat` | public | body `{member: didi/teen/dad/mom, text?, image_base64?, media_type?, session_id?, button_id?}` -> `{reply_text, buttons, order?, decisions?, notifications}` |
| POST | `/api/rules/draft` | public | body `{text}` -> `{title, cedar, explanation_en, explanation_hinglish, validation{ok,errors}, repaired, test_results[{case,expected,actual,pass,policy_ids}]}`. Never activates |
| POST | `/api/rules/activate` | demo key | body `{cedar, title, title_hinglish?}` -> `{ok, rule}` (422 if invalid) |
| DELETE | `/api/rules/{id}` | demo key | deactivates a custom rule -> `{ok, rule}` |
| POST | `/api/redteam` | public | body `{attack: injection/overspend/forbidden_category}` -> `{attack, simulated_compromised_model: true, model_proposed, decisions, payment, audit, verdict}` |
| POST | `/api/refill/run` | demo key | body `{send?: true}` -> weekly refill proposal; `send:false` previews without WhatsApp |
| POST | `/api/demo/reset` | demo key | clears orders, payments, audit, sessions; mandate back to Rs 1850 used. Keeps the WhatsApp persona and custom rules |

Errors are `{error}` with 400 / 401 / 404 / 405 / 409 / 413 / 422 / 429 / 500.

- **Demo key**: header `x-jhola-demo-key`. The value lives in the SSM SecureString `/jhola/demo-key`
  (created outside CloudFormation, read by the Lambda at cold start). Read it with
  `aws ssm get-parameter --name /jhola/demo-key --with-decryption --query Parameter.Value --output text`.
- **Rate limit** per source IP and minute (DynamoDB counter in `jhola-processed-messages`, TTL):
  120 for GETs, 20 for chat / rules draft / red team. Text is capped at 1000 characters, images at 4 MB.
- **Slow calls** (chat, rules draft, refill run) run in an async self-invocation of the function.
  The HTTP call waits up to 24 s; if the job is still running it answers `202 {pending: true, job_id}`,
  then poll `GET /api/jobs/{job_id}`. Typical: rules draft 11-16 s, text chat 10-25 s, parchi photo 25-35 s.
- **Web chat** runs the same `handle_message` as WhatsApp against the live household (orders are tagged
  `channel: web`, and they do use the mandate). Conversation history is kept per member and
  `session_id` (default: a hash of the caller IP), separate from WhatsApp. Notifications (for example an
  approval request to Mom) are returned in the response, never sent to WhatsApp.
- **Custom rules** are stored in `jhola-state` (pk `hh#<household_id>#rules`). Every order is evaluated against the base
  policies plus the active custom rules. Their policy ids are `custom-<rule id>`.
- **Red team** attacks run the real Strands loop, Cedar and UPI mandate with a scripted COMPROMISED
  model, in an in-memory sandbox seeded with the live mandate usage and custom rules. Live orders are
  never touched; one `redteam_run` event is written to the live audit log.

## Sunday refill (EventBridge Scheduler)

Schedule `jhola-weekly-refill`: `cron(0 9 ? * SUN *)` in `Asia/Kolkata` invokes `jhola-console-api`
with `{"jhola_job": "weekly_refill"}`. For every household with something running out it builds a draft
cart and sends it to that household's admin phone with an *Order all* button. Free-form WhatsApp messages only work within 24
hours of the admin's last message (tracked in `jhola-state`, pk `wa_last_inbound`). Outside the window
the job logs `refill_skipped` and sends nothing (there is no approved template). For the video: message
the number first, then `POST /api/refill/run` with the demo key.

## Accounts

| Account | Profile | What lives there |
|---|---|---|
| 446413909932 (infra) | `ayush-aws-bits-hack`, ap-south-1 | WhatsApp, SNS, Lambda, DynamoDB, S3, Transcribe, Polly (stack `jhola`) |
| 590183982967 (Bedrock) | `default`, us-east-1 | IAM role `jhola-bedrock-invoker` (stack `jhola-bedrock-invoker`) |

The Bedrock role trusts only `arn:aws:iam::446413909932:role/jhola-whatsapp-agent-role` and allows
only `bedrock:InvokeModel*` / `Converse*` on the `global.anthropic.claude-sonnet-5` inference
profile and the `anthropic.claude-sonnet-5` foundation model. The Lambda gets 1-hour STS
credentials; no long-lived keys exist anywhere.

To move Bedrock into the infra account later: deploy with `--parameter-overrides BedrockRoleArn=""`.
The Lambda then calls Bedrock with its own role (the template adds the Bedrock permissions instead).

## Deploy

Requires the SAM CLI and uv. No Docker: the Makefile in `agent/` installs Linux arm64 wheels with uv.

```bash
cd infra
sam build && sam deploy        # settings in samconfig.toml (stack jhola, ap-south-1)

# once, in the Bedrock account (after the stack above created the Lambda role)
aws cloudformation deploy --template-file bedrock-role.yaml --stack-name jhola-bedrock-invoker \
  --capabilities CAPABILITY_NAMED_IAM --region us-east-1 --profile default
```

Logs: CloudWatch `/aws/lambda/jhola-whatsapp-agent` (JSON; events `inbound`, `voice_transcribed`,
`whatsapp_sent`, `handle_failed`) and `/aws/lambda/jhola-console-api` (`api_request`, `job_done`,
`weekly_refill`). Phone numbers are masked in logs and API responses. Every agent step is also in the
household's audit log (`jhola-state`, pk `hh#<household_id>#audit`).

### Data migration (single household -> tenancy)

```bash
cd agent
AWS_PROFILE=ayush-aws-bits-hack AWS_DEFAULT_REGION=ap-south-1 \
JHOLA_ADMIN_PHONE=+916307178243 JHOLA_DEMO_PHONES=+916307178243 \
  uv run python -m jhola.migrate jhola-state      # add --dry-run to only count
```

Copies the old `orders`, `mandate`, `txns`, `audit`, `purchases`, `sessions`, `rules` items into
`hh#demo-gupta#...`, raises the per-household counters, seeds the demo household and flags the owner's
phone `demo=true`. It never deletes or overwrites, so it is safe to run again and the old keys remain.

## Households on WhatsApp

Any number can message Jhola. A number it has never seen gets a 3-question onboarding and becomes the
admin of a new household; the admin adds family in plain words ("Add Sunita didi 98765 43210, groceries
only, 500 a day"), always confirmed with Yes / No. See `../agent/README.md` for the data model, the
onboarding flow and the admin commands.

## Demo persona commands (DEMO FEATURE)

Only for phones flagged `demo=true` in the directory (seeded from the `DemoPhones` parameter: the owner,
who is also Mom, admin of the seeded household `demo-gupta`). They do not exist for anyone else and are
not listed in their `/help`:

| Command | Effect |
|---|---|
| `/as mom`, `/as dad`, `/as didi`, `/as teen` | Act as that member (persisted per phone) |
| `/whoami` | Show the acting member |
| `/reset` | Clear orders, payments, history and conversation; mandate back to Rs 1850 used of Rs 5000 |
| `/help` | List commands (ordinary members get the normal help) |

Approval requests always go to the admin's real phone (so a single-phone demo gets the Approve /
Reject buttons). Messages for members without a real number (Dad, Didi, Aarav) are delivered to the
demo phone, prefixed `[Demo: message for Didi]`.

## Notes

- Replies are free-form, so they only work inside WhatsApp's 24-hour customer-service window
  (the user must have messaged the number in the last 24 hours).
- Status webhooks (sent/delivered/read) also invoke the Lambda and are ignored.
- Extended thinking is off for the agent (`JHOLA_THINKING=off`) and the tool block is prompt-cached.
  Measured on a 3-item text order: 12-14 s with thinking, 11-12 s without; the four sequential model
  calls (resolve, build cart, submit, reply) dominate.
- Typical latency: text 10-30 s, parchi photo about 30 s, voice note about 30 s (Transcribe about 10 s).
- Cost at demo volume is a few cents: Lambda and DynamoDB on-demand are near zero, Transcribe is
  about $0.024 per minute of audio, Polly neural about $16 per 1M characters, Bedrock tokens
  dominate (billed in the Bedrock account). WhatsApp service conversations are free.
