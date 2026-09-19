# Jhola agent

The household kirana ordering agent behind Jhola. Family members send a parchi photo, a text or a voice note on
WhatsApp. The agent turns it into a cart of the family's usual brands and
pack sizes, and a separate Cedar policy engine decides whether the order may be paid from the
household's UPI AutoPay mandate.

**The AI proposes; Cedar decides.** The model can only build carts and submit them. It has no
payment tool. Payment happens inside `submit_order`, and only with a signed authorization that the
policy engine issues after a Cedar allow. Every step is written to an audit log.

## Architecture

```
WhatsApp / any channel
        |
handle_message(sender_phone, text, image_bytes, media_type)      agent.py
        |
Strands Agent (Bedrock Claude, or ScriptedModel offline)
  tools: read_parchi_image  search_catalog  resolve_item  check_pantry
         expand_recipe      build_cart      submit_order  predict_refill
        |
OrderService.submit_order                                         orders.py
  1. Cedar purchase_item for each line   -> drop blocked lines     policy.py + policies/*.cedar
  2. Cedar auto_pay                      -> debit mandate
     else request_approval               -> ask the admin (Approve / Reject buttons)
     else deny                           -> reasons (+ ask admin to top up if mandate is exhausted)
  3. handle_approval -> Cedar approved_pay -> debit
        |
MandateService.debit(PaymentAuthorization)   SIMULATED UPI         upi.py
AuditLog (every step, with Cedar inputs and outputs)               audit.py
Repository: InMemory / JsonFile (local), DynamoDB (AWS)              store.py
```

| Module | What it does |
|---|---|
| `domain.py` | Catalog search, household preference memory, item resolution with substitution, pantry and refill prediction from purchase history, recipe expansion |
| `policy.py` | Builds Cedar entities and requests, maps policy ids to `@reason` / `@hinglish` annotations, signs payment authorizations |
| `policies/` | `jhola.cedarschema`, `items.cedar` (per line), `payments.cedar` (per order) |
| `upi.py` | Simulated mandate: create, remaining, idempotent debit with 12-digit UPI-style refs. Refuses to debit without a valid authorization |
| `vision.py` | `BedrockVisionReader` (Converse API with the image) and `FixtureVisionReader` (offline) |
| `whatsapp.py` | WhatsApp channel: parses End User Messaging Social webhook events, dedupes, media via S3, voice notes via Transcribe, demo persona commands, replies with text / reply buttons / Polly voice |
| `lambda_handler.py` | Lambda entry point (SNS event -> `WhatsAppChannel`), wired to DynamoDB, S3 and socialmessaging. See `../infra/README.md` |
| `api.py` | Console API logic: household, orders, audit, approvals, web chat, rules, red team, refill, demo reset |
| `api_handler.py` | Console Lambda entry point: HTTP API routing, demo key, per-IP rate limit, async jobs, Sunday refill schedule |
| `rules.py` | Custom household rules: Bedrock drafts Cedar from plain English / Hinglish, cedarpy validates (one repair attempt), test requests are evaluated, activation pins ids to `custom-<id>` |
| `redteam.py` | Injection, overspend and forbidden-category attacks with a compromised stub model, run in a sandbox |
| `stub_model.py` | `ScriptedModel`, a Strands model provider that emits scripted tool calls, so the full loop runs without an LLM |
| `scenarios.py` | Demo scenarios A to F |
| `data/` | 198-SKU catalog, Gupta family household (members, roles, preferences, 6 weeks of history), recipes |

### Rules (Cedar)

| Policy id | Rule |
|---|---|
| `mandate-monthly-cap` | Month spend + order must stay within the Rs 5000 mandate (blocks auto-pay, approval and approved pay) |
| `approval-above-threshold` | Orders above Rs 1000 cannot auto-pay (admin exempt), so they go to `request_approval` |
| `admin-approved-pay` | After the admin taps Approve, `approved_pay` is allowed |
| `house-help-category-scope` / `-outside-scope` | House help: staples, dairy, vegetables, fruits and cleaning only |
| `house-help-daily-cap` | House help: at most Rs 500 per day |
| `teen-category-scope` / `-outside-scope` | Teen: stationery and snacks only |
| `teen-no-energy-drinks` | Explicit forbid on energy drinks for teens |
| `min-seller-rating` | Seller rating must be at least 4.0 |
| `max-qty-per-line` | At most 5 units per line unless admin |

Every decision returns the matching policy ids, an English reason and a short Hinglish line.

Custom rules added from the console (`/api/rules/draft`, then `/api/rules/activate`) are evaluated
together with these base policies on every later order; forbid always wins. Product entities carry
`name`, `brand`, `category`, `tags` (Set of lowercase words such as "chocolate"), `price_inr` and
`seller_rating`, so a rule like "no chocolate for Aarav" is `resource.tags.contains("chocolate")`.

Item search matches the catalog's Hindi / Hinglish aliases ("arhar ki dal", "kothmir", "pyaj",
"dudh"), and an unrequested processed form (powder) ranks below the fresh item.

## Run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
cd agent
uv sync
uv run pytest                              # Cedar policy, payment gating, scenario and console API tests
uv run python -m jhola.scenarios           # scenarios A-F with the scripted stub model (offline)
uv run python -m jhola.scenarios C --audit # one scenario, with the full audit trail
uv run python -m jhola.parchi samples/parchi.jpg   # render the synthetic parchi image
```

Scenarios:

- **A** Didi sends a parchi photo. Cart of Rs 342, auto-paid.
- **B** Teen asks for 4 Red Bull and a geometry box. Red Bull is blocked, the geometry box is paid.
- **C** Dad asks for rajma chawal for 6. The recipe is expanded, rice is skipped because it is in the pantry, and the out-of-stock rajma is substituted. The Rs 1179 cart goes to Mom for approval and is paid once she approves.
- **D** Sunday refill job predicts what is running out and proposes it to Mom. She taps Order all.
- **E** A seller description contains a prompt injection. The model adds 10 units, Cedar blocks the line (`max-qty-per-line`), and the audit log flags the suspicious text.
- **F** The mandate is nearly used up. Didi's order is within her daily limit but over the remaining mandate, so it is blocked and Mom is asked to top up.

### Live model (Bedrock)

The LLM runs in its own AWS account, separate from the infra/WhatsApp account:

| Env | Default | Used for |
|---|---|---|
| `JHOLA_MODEL_ID` | `global.anthropic.claude-sonnet-5` | Agent and vision model |
| `JHOLA_BEDROCK_PROFILE` | `default` | AWS profile for Bedrock calls |
| `JHOLA_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `JHOLA_BEDROCK_ROLE_ARN` | unset | If set, assume this role for Bedrock (cross-account, used by the Lambda) |
| `AWS_PROFILE` | `ayush-aws-bits-hack` | Infra (WhatsApp, Lambda, DynamoDB), ap-south-1 |
| `JHOLA_ADMIN_PHONE` | `+919999900001` | Admin (Mom) WhatsApp number |

```bash
uv run python -m jhola.scenarios --live A B
```

In live mode the real model chooses the tool calls and writes the replies. The parchi image is read
by Bedrock vision.

## Channel API

```python
from jhola.agent import handle_message, handle_approval

reply = handle_message("+919999900003", text=None, image_bytes=jpg, media_type="image/jpeg")
reply.text, reply.buttons, reply.notifications   # notifications: messages for other members (e.g. Mom)
handle_approval("+919999900001", "JH-20260920-0001", "approve")
```

`handle_message` also takes `channel` ("whatsapp" / "web"), `input_type` ("text" / "image" / "voice")
and `session_key` (conversation history key, default the member's phone); orders are stamped with
channel and input type.

### Console HTTP API

`jhola.api_handler.handler` serves the web console. The routes, access rules and the async job
pattern are documented in `../infra/README.md`.

| Method | Path | Access |
|---|---|---|
| GET | `/api/household`, `/api/orders`, `/api/audit`, `/api/approvals`, `/api/jobs/{id}` | public |
| POST | `/api/chat`, `/api/rules/draft`, `/api/redteam` | public, rate limited |
| POST | `/api/approvals/{order_id}`, `/api/rules/activate`, `/api/refill/run`, `/api/demo/reset` | `x-jhola-demo-key` |
| DELETE | `/api/rules/{id}` | `x-jhola-demo-key` |

On AWS, `jhola.lambda_handler.handler` runs the same agent behind WhatsApp with `DynamoDBRepository`
(see `../infra/README.md`). The module-level functions use a local JSON state file (`agent/.state/jhola.json`). For tests or a
different backend, build `JholaAgent(Jhola(repo, clock), model_factory, vision)` yourself.
