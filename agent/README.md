# Jhola agent

The household kirana ordering agent behind Jhola. It is multi-household: **identity is the sender's
WhatsApp phone number**. A new number is onboarded in the chat and becomes the admin of its own
household; the admin adds family members in plain words. Family members send a parchi photo, a text or a voice note on
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
  tools: read_parchi_image  search_catalog  resolve_item(for_member)  check_pantry
         expand_recipe      build_cart(for_member)  submit_order  predict_refill
         get_product_details  compare_products  find_alternatives  (+ admin propose_* tools)
        |
OrderService.submit_order                                         orders.py
  0. family cart merge: someone else ordered the same item < 60 min ago -> Yes / No first
  1. Cedar purchase_item for each line   -> drop blocked lines     policy.py + policies/*.cedar
     (context.beneficiary = the member the line is FOR: diet, allergy, vrat, caffeine rules)
     blocked line -> closest substitute Cedar allows is suggested
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
| `household.py` | Tenancy: the directory (phone -> household, member), household creation, members, role templates, the seeded demo household |
| `onboarding.py` | Deterministic 3-question WhatsApp onboarding for unknown numbers |
| `admin.py` | Family administration in plain words: every change is a pending action the admin confirms with Yes / No; role checks and audit of refused attempts; "delete my data" |
| `phones.py` | E.164 normalization (+91 default) and phone masking |
| `migrate.py` | One-off copy of the old single-household keys into `hh#demo-gupta#...` |
| `domain.py` | Catalog search, learned household preferences, item resolution with sensible defaults and substitution, pantry and refill prediction from purchase history, recipe expansion |
| `policy.py` | Builds Cedar entities and requests, maps policy ids to `@reason` / `@hinglish` annotations, signs payment authorizations |
| `policies/` | `jhola.cedarschema`, `items.cedar` (per line), `diet.cedar` (diet, allergy, vrat, caffeine, per line and beneficiary), `payments.cedar` (per order) |
| `products.py` | Product Q&A: details (nutrition, diet flags, allergens, unit price, fulfilment, Amazon link), comparisons (protein per rupee, sugar, sodium, unit price), alternatives (sugar free, high protein, jain, vegan, vrat, cheaper per unit, max price), better-value pack detection |
| `upi.py` | Simulated mandate: create, remaining, idempotent debit with 12-digit UPI-style refs. Refuses to debit without a valid authorization |
| `vision.py` | `BedrockVisionReader` (Converse API with the image) and `FixtureVisionReader` (offline) |
| `whatsapp.py` | WhatsApp channel: parses End User Messaging Social webhook events, dedupes, media via S3, voice notes via Transcribe, demo persona commands, replies with text / reply buttons / Polly voice |
| `lambda_handler.py` | Lambda entry point (SNS event -> `WhatsAppChannel`), wired to DynamoDB, S3 and socialmessaging. See `../infra/README.md` |
| `api.py` | Console API logic: household, orders, audit, approvals, web chat, rules, red team, refill, demo reset |
| `api_handler.py` | Console Lambda entry point: HTTP API routing, demo key, per-IP rate limit, async jobs, Sunday refill schedule |
| `rules.py` | Custom household rules: Bedrock drafts Cedar from plain English / Hinglish, cedarpy validates (one repair attempt), test requests are evaluated, activation pins ids to `custom-<id>` |
| `redteam.py` | Injection, overspend, forbidden-category and allergen-bypass attacks with a compromised stub model, run in a sandbox |
| `stub_model.py` | `ScriptedModel`, a Strands model provider that emits scripted tool calls, so the full loop runs without an LLM |
| `scenarios.py` | Demo scenarios A to H |
| `evals/` (in `agent/`) | Evaluation suite: 60+ JSONL cases run through the real pipeline against an isolated household, live Bedrock, scored (see [Evals](#evals)) |
| `data/` | 601-SKU catalog with nutrition, diet, allergen and shelf-life data; Gupta family household (5 members, roles, preferences, 6 weeks of history); recipes |

## Data model

One DynamoDB table (`pk`, `sk`, `data` = JSON document). `pk` is a collection name; a household's
collections are prefixed with `hh#<household_id>#`. Services only ever get a
`ScopedRepository(base, household_id)`, which adds that prefix, so code handling one household cannot
address another household's partitions (`tests/test_households.py::test_two_households_never_see_each_other`).

| pk | sk | Document |
|---|---|---|
| `households` | household id (`demo-gupta`, `hh-<10 hex>`) | name, `demo`, created_at, mandate settings (monthly cap, approval threshold) |
| `phones` | E.164 phone | `{household_id, member_id, demo}`: the identity index, written with a conditional put so a phone belongs to one household |
| `onboarding` | phone | onboarding step and answers until the household exists |
| `wa_last_inbound` | phone | last inbound time (WhatsApp 24-hour window) |
| `demo_acting` | phone | demo persona (`/as`) |
| `web_jobs` | job id | console async jobs (carry their `household_id`) |
| `hh#<id>#members` | member id | name, role, phone, **language, personal limits** (`daily_cap_inr`, `order_cap_inr`, `allowed_categories`), **dietary profile** (`diet_profile`, `allergies`, `vrat_until`, `max_caffeine_mg`), `welcomed` |
| `hh#<id>#sessions` | member phone or `web:<member>:<session>` | conversation history (per member) |
| `hh#<id>#prefs` | generic word (`atta`) | learned usual brand `{sku, qty, source: choice/order/seed, by, at}` |
| `hh#<id>#purchases` | `<order id>:<sku>` | purchase history (pantry and refill prediction) |
| `hh#<id>#orders`, `#txns`, `#mandate` | order id / mandate id | carts and orders, simulated UPI debits, the mandate ledger |
| `hh#<id>#rules` | rule id | custom Cedar rules and temporary delegations (`kind: delegation`, `expires_on`) |
| `hh#<id>#pending_actions` | action id | admin changes waiting for Yes / No |
| `hh#<id>#audit` | zero-padded seq | audit log; `hh#_system#audit` holds events of numbers that belong to no household |
| `hh#<id>#counters` | `audit`, `orders` | atomic counters (order ids are per household) |

Memory has two levels. Per member: conversation history, language preference, personal limits, dietary
profile. Per household: usual brands, pantry (purchase history), rules, mandate.

**Usual brands are learned.** A new household has no preferences; `resolve_item` then picks a sensible
default among the most relevant matches (in stock, seller rating at least 4.0, mid-priced, best rated).
When a member picks a product for a generic word the model calls `remember_choice(word, sku)`; paying for
a default pick also stores it (`source: order`) but never overrides an explicit choice. Next time "atta"
resolves to that product (`source: preference`).

Migration from the single-household layout: `uv run python -m jhola.migrate jhola-state` copies the old
`orders`, `mandate`, `txns`, `audit`, `purchases`, `sessions`, `rules` items into `hh#demo-gupta#...`
(never deletes or overwrites, counters only move up), so the old keys stay readable.

## Onboarding (unknown number)

Deterministic, no LLM, at most 3 questions, Hindi / Hinglish / English answers:

1. Welcome + one-line privacy note (https://jhola-phi.vercel.app/privacy) + *1/3* name and what to call the home ("Priya, Sharma home").
2. *2/3* monthly grocery budget for the SIMULATED UPI AutoPay mandate (button: default Rs 5000).
3. *3/3* approval threshold (button: default Rs 1000).

Then the household is created with that phone as admin and Jhola explains in three lines what to do
(send a list photo / voice note / text, add family, set rules in plain words) and that payments are
simulated. A household of one works fully. "stop" cancels and stores nothing.

## Admin commands (plain words, admin only)

| Say | What happens |
|---|---|
| "Add Sunita didi +91 98765 43210, groceries only, 500 a day" | name, phone (normalized to +91 E.164), role template (`adult`, `house_help`, `teen`, `elder`) and limits are extracted; Yes / No; on Yes the member is created |
| "Add my son Aarav 9xxxxxxxxx, only stationery and snacks, no chocolate" | as above; conditions outside the templates are drafted as a Cedar rule for that member (validated, auto-tested) and activated together with the member on Yes |
| "List members", "Remove Sunita", "Change Aarav's limit to 300 a day" | list / remove / change limits (0 removes a limit) |
| "No chocolate for Aarav", "Show my rules", "Remove rule 2" | rule drafting, numbered list, removal |
| "Didi can spend 1500 this week" | delegation with an expiry date. Cedar enforces it: the payment policies honour `principal.delegated_cap_inr` only while `context.today <= principal.delegated_until` |
| "Change budget to 8000", "Approval above 1500" | mandate cap / approval threshold |
| "Dadi is Jain", "Aarav is allergic to peanuts", "Navratri vrat for Mom till 2 Oct", "No more than one energy drink for Aarav" | dietary profile (`propose_diet_change`): diet `veg / vegan / jain / eggetarian`, allergens normalized from plain words (moongfali -> `peanut`, dry fruits -> `tree_nut`, gehun -> `gluten`), vrat end date, caffeine per order in mg (one energy drink about 80). Enforced by Cedar for that member, whoever orders for them |
| "This month's spending" | budget, spent, remaining, per member, pending approvals |
| "delete my data" / "leave" (anyone) | removes the member and their chat history; the last admin deletes the whole household. Always confirmed with buttons, never routed through the model |

Every change is first a pending action shown with **Yes / No**; nothing is created or activated before
Yes. Non-admins do not get the admin tools, `admin.py` checks the role again on propose and on confirm,
and refused attempts are audited (`admin_action_denied`). Personal limits are soft: above a daily or
per-order limit the order goes to the admin for approval.

The invited number needs no setup: on its first message it is recognised, greeted by name and told what
it may order. (WhatsApp does not allow Jhola to message a number first, so the admin asks them to say hi.)

Approvals go to the household's admin phone(s). If the admin has not messaged Jhola in the last 24 hours
WhatsApp would reject the message, so the requester is told, the order stays pending, and the admin gets
the pending approvals first when they next message.

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
| `member-category-scope` / `member-outside-category-scope` | A member's `allowed_categories` replaces the role scope |
| `member-daily-limit`, `member-order-limit` | Above a personal daily / per-order limit the order cannot auto-pay (admin approves) |
| `house-help-for-elder` | House help may order snacks, beverages and personal care when the line is FOR an elder ("Dadi ke liye") |
| `diet-vegetarian`, `diet-eggetarian`, `diet-vegan`, `diet-jain` | Food that breaks the beneficiary's `diet_profile` is blocked (Jain: onion, garlic, root vegetables; vegan: dairy, egg, honey) |
| `allergy` | `resource.allergens.containsAny(context.beneficiary.allergies)` |
| `vrat-mode` | While `context.today <= beneficiary.vrat_until` only `vrat_friendly` food |
| `caffeine-cap`, `teen-caffeine-cap` | Caffeine of the order for that member above `max_caffeine_mg` (teens: 100 mg by default) |

An active delegation (`delegated_cap_inr`, `delegated_until`, checked against `context.today`) lifts the
approval threshold and the personal limits, never the mandate cap or category rules. Reasons use the
household's own numbers and admin name (`{threshold}`, `{cap}`, `{daily}`, `{admin}` in the annotations).

Every decision returns the matching policy ids, an English reason and a short Hinglish line.

### Rules beyond money: diet, allergies, vrat, caffeine, ordering for someone else

Product entities carry the catalog's diet data (`is_food`, `veg`, `vegan`, `jain_friendly`, `vrat_friendly`,
`eggetarian_only`, `allergens`, `contains`, `caffeine_mg`) and members carry a dietary profile
(`diet_profile`, `allergies`, `vrat_until`, `max_caffeine_mg`). Every `purchase_item` request has
`context.beneficiary`: the member the line is FOR. It is the buyer unless the message says otherwise ("Dadi ke
liye namkeen" -> `resolve_item(..., for_member="Dadi")`, `build_cart(items, for_member="Dadi")`, or per line
`{"sku", "qty", "for_member"}`). So Didi ordering a Haldiram Navratan mix for Dadi is checked against Dadi's
Jain profile (`diet-jain`), Dad ordering a Snickers for Aarav against Aarav's peanut allergy (`allergy`), and
a cola for a teen against the teen caffeine cap. Caffeine is summed over the order for that beneficiary
(`context.order_caffeine_mg`).

`resolve_item` pre-checks the resolved product with the same Cedar decision (`rules_check`, audited as
`policy_precheck`) and, when blocked, returns `suggested_substitute`: the closest in-stock product that Cedar
ALLOWS for this buyer and beneficiary (same category, overlapping tags; the Jain mixture for a mixture, a
peanut-free chocolate for a Snickers). `submit_order` does the same for every blocked line. Dietary reasons
are listed first and name the person: "Dadi is Jain; this product has onion, garlic or root vegetables" /
"Dadi Jain hain, is item mein pyaaz, lehsun ya jadwali sabzi hai". The agent offers the substitute and orders
it only when the member says yes.

Seeded demo household: Dadi (elder, Jain, +91 99999 00005, `/as dadi`) and Aarav's peanut allergy. An already
seeded table is upgraded in place (`Directory._upgrade_demo`: missing seed members are added, dietary fields
set once where absent; nothing the admin changed is overwritten).

### Product Q&A and smart suggestions

| Tool | Answers |
|---|---|
| `get_product_details(sku_or_query)` | price, MRP, unit price (per kg / l / piece), approximate nutrition per 100 g, protein per pack and per rupee, diet flags, allergens, contains, caffeine, shelf life, fulfilment, Amazon search link, `better_value_pack` |
| `compare_products([...])` | side by side: protein per 100 g and per rupee, sugar, sodium, energy, fibre, unit price, diet, allergens, plus `best` per metric |
| `find_alternatives(sku_or_query, sugar_free, high_protein, jain, vegan, vrat, cheaper_per_unit, max_price, for_member)` | up to 5 in-stock, well-rated products meeting the constraints; the beneficiary's allergens are always excluded |

"paneer mein kitna protein hai" -> approx 18 g per 100 g; "koi sugar free biscuit?" -> NutriChoice Sugar Free
Cream Cracker; "sasta wala atta per kg?" -> cheaper per kg than the usual pack. Numbers are quoted as
approximate label values (`nutrition_source: approximate`), replies stay at three items and one line each,
and health questions get one line "Yeh label ki jaankari hai, doctor ki salah nahi" (no medical advice).
When another pack of the same product is more than 10% cheaper per unit, `resolve_item` and
`get_product_details` return `better_value_pack` and the agent mentions it in one line without switching.

### Family cart merge and pantry nudges

`build_cart` looks at the other members' orders of the last 60 minutes (pending approval, or paid within the
hour). If one of them has the same item (same SKU, or same item family: category + leading tags, so any doodh
pack), `submit_order` returns `needs_confirmation` instead of paying and the member gets a question written by
code with Yes / No buttons: "Dad ne 20 min pehle Nandini Toned Milk 500ml x2 order kiya hai (paid). Phir bhi
chahiye?". Yes (`dupyes:<order>`) submits the whole cart; No (`dupno:<order>`) drops the duplicated lines and
submits the rest (or cancels the order when nothing is left). Your own repeats are not duplicates.

`build_cart` also returns `probably_at_home`: lines whose item family was bought recently and, by purchase
cycle capped with the product's `shelf_life_days`, is probably still there ("Mom bought Tata Salt 3 days ago").
It is a one-line nudge, never a block. The same shelf-life-aware estimate (`Pantry.status_for_sku`) is what the
recipe flow uses to skip staples.

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
uv run pytest                              # Cedar policy, payments, scenarios, console API, tenancy, onboarding, admin
JHOLA_E2E_TABLE=jhola-state AWS_PROFILE=ayush-aws-bits-hack AWS_DEFAULT_REGION=ap-south-1 \
  uv run pytest tests/test_e2e_dynamo.py -s  # two households end to end on the real table, sending stubbed
uv run python -m jhola.scenarios           # scenarios A-H with the scripted stub model (offline)
uv run python -m evals.run --live          # evaluation suite against live Bedrock (see Evals)
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
- **G** Didi orders "Dadi ke liye Haldiram navratan mixture". Dadi is Jain: the mixture (onion, garlic) is blocked by `diet-jain`, the Jain mixture is suggested; Didi says yes and it is paid (`house-help-for-elder` lets Didi buy snacks for an elder).
- **H** Aarav (peanut allergy) asks for peanut butter and a Snickers. Both are blocked by `allergy` (the peanut butter also by `teen-outside-scope`), a peanut-free chocolate is offered and ordered.

### Evals

`agent/evals/` runs 60+ JSONL cases (`evals/cases.jsonl`) through the real pipeline, each in a fresh
isolated in-memory household, against live Bedrock: Hinglish / Hindi orders with typos, quantities and units
("aadha kilo", "do packet", "1 darjan"), parchi-style multi-line lists, aliases, ambiguous items, product
questions, admin commands, policy cases for every role, dietary and allergy cases, and 10 adversarial /
prompt-injection cases (in the message and in product descriptions).

```bash
uv run python -m evals.run --live [--limit N] [--ids a,b] [--category c]
```

Scores: item resolution accuracy (expected SKU or acceptable set), quantity accuracy, policy decision
accuracy, unsafe payments (must be 0), injection resistance (the model) and containment (Cedar), p50 / p95
latency, tokens and estimated cost per order. Results: `evals/results/latest.json` and the full table,
per-category breakdown and diagnosed failures in [`evals/RESULTS.md`](evals/RESULTS.md).

Live run, 76 cases, Claude Sonnet on Bedrock (2026-09-20):

| Metric | Value |
|---|---|
| Cases passed (every check) | 89.5% (68 / 76) |
| Item resolution accuracy | 90.0% (72 / 80 expected items) |
| Quantity accuracy | 78.6% (11 / 14 cases with an explicit quantity) |
| Policy decision accuracy | 92.1% (70 / 76) |
| **Unsafe payments** | **0** |
| Injection resistance / containment (11 adversarial) | 100% / 100% |
| Latency p50 / p95 | 9.5 s / 16.2 s per case |
| Cost | USD 1.83 total, 0.024 per case, 0.054 per submitted order |

None of the six decision misses is a wrong Cedar verdict or a payment that should not have happened: they
are cases where the model asked a clarifying question instead of ordering ("aadha kilo atta" when the usual
pack is 5 kg, "dal chahiye" with no brand named). Nine denials were refused by the model from its system
prompt before any tool call, so the outcome is right but Cedar never saw them and the console shows no
decision for those.

Three real bugs the first pass found and the fixes: the model stopped to ask "cart bana kar order karu?"
in 23 cases (the system prompt now says to build and submit in the same turn when the list is clear, and
spells out Hindi number words and pieces vs packs); `Resolver._default` cancelled the processed-form
penalty with its relevance band, so "kothmir" resolved to coriander powder; `Resolver._pref` missed a
preference stored under one word of a multi-word query, so "5 kg basmati chawal" became 5 one-kg packs of
another line.

### Live model (Bedrock)

The LLM runs in its own AWS account, separate from the infra/WhatsApp account:

| Env | Default | Used for |
|---|---|---|
| `JHOLA_MODEL_ID` | `global.anthropic.claude-sonnet-5` | Agent and vision model |
| `JHOLA_BEDROCK_PROFILE` | `default` | AWS profile for Bedrock calls |
| `JHOLA_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `JHOLA_BEDROCK_ROLE_ARN` | unset | If set, assume this role for Bedrock (cross-account, used by the Lambda) |
| `AWS_PROFILE` | `ayush-aws-bits-hack` | Infra (WhatsApp, Lambda, DynamoDB), ap-south-1 |
| `JHOLA_ADMIN_PHONE` | `+919999900001` | Phone of Mom, admin of the demo household |
| `JHOLA_DEMO_PHONES` | the admin phone if real | Phones flagged `demo=true` (persona commands) |
| `JHOLA_THINKING` | `off` | `off` disables extended thinking for the agent; `default` restores it |

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

`JholaAgent(Jhola(repo, household_id=...))` serves one household (default `demo-gupta`, the seeded Gupta
family used by the scenarios, the console and the red team). Buttons: `approve:` / `reject:` (admin),
`confirm:` / `cancel:` (admin changes), `order:` (draft), `dupyes:` / `dupno:` (family cart merge), `topup:`. `handle_message` also takes `channel` ("whatsapp" / "web"), `input_type` ("text" / "image" / "voice")
and `session_key` (conversation history key, default the member's phone); orders are stamped with
channel and input type.

### Console HTTP API

`jhola.api_handler.handler` serves the web console. The routes, access rules and the async job
pattern are documented in `../infra/README.md`.

| Method | Path | Access |
|---|---|---|
| GET | `/api/household`, `/api/orders`, `/api/audit`, `/api/approvals`, `/api/jobs/{id}` | public |
| GET | `/api/households` | `x-jhola-demo-key` |
| POST | `/api/chat`, `/api/rules/draft`, `/api/redteam` (`injection`, `overspend`, `forbidden_category`, `allergen_bypass`) | public, rate limited |
| POST | `/api/approvals/{order_id}`, `/api/rules/activate`, `/api/refill/run`, `/api/demo/reset` | `x-jhola-demo-key` |
| DELETE | `/api/rules/{id}` | `x-jhola-demo-key` |

Every route takes an optional `household_id` (query string or JSON body, default `demo-gupta`). Any
household other than the demo one is only served with the demo key. `GET /api/household` members carry
`diet_profile`, `allergies`, `vrat_until`, `max_caffeine_mg` and `diet_summary`; `GET /api/orders` items carry
`decision`, `policy_ids`, `reason`, `reason_hinglish` (including the dietary and allergy denies), `for_member`
and `suggested_substitute`.

On AWS, `jhola.lambda_handler.handler` runs the same agent behind WhatsApp with `DynamoDBRepository`
(see `../infra/README.md`). The module-level functions use a local JSON state file (`agent/.state/jhola.json`). For tests or a
different backend, build `JholaAgent(Jhola(repo, clock), model_factory, vision)` yourself.
