# Jhola: the approval layer for agents that spend your money

Jhola is the approval layer for agents that spend your money: the model builds the cart, a Cedar policy engine outside the model decides whether it may pay, and every decision cites the rule that made it.

It runs on WhatsApp for an Indian household - a handwritten parchi, a Hindi voice note, a house help, a teenager - because that is where the delegation problem is most obvious.

WeMakeDevs x AWS "First Commit" hackathon, Ship It track. Solo builder: Ayush Gupta (GitHub madmecodes).

Live: https://jhola-phi.vercel.app. WhatsApp: +91 96063 54404. Repo: https://github.com/madmecodes/jhola.

## Why now

At the Global Fintech Fest on 10 September 2026, NPCI chairman Ajay Kumar Choudhary drew the line for agentic payments in India. As reported, he said: "An AI agent may work out what a user wants. It should not be the thing that approves the payment." He also said "decision making and execution must remain separate", and that "an agent may read intent. Verifying identity, mandate, limits and consent sits with the authoriser." NPCI has said no agent-authorisation framework exists yet for UPI.

The next day, at the same event, Amazon Pay launched agentic UPI payments: a Smart Wallet that lets AI agents make UPI payments on a user's behalf, live first for flight booking. Amazon Pay already runs UPI Circle, which since around October 2025 has let one person delegate UPI spending to another - full and partial delegation, spending limits - aimed at household managers, teenagers aged 13 to 17 and dependents without their own bank accounts, across a reported 110 million-plus Amazon Pay UPI customers with about 75% of usage coming from tier-2 and tier-3 towns. Alexa+ launched in India on 16 September 2026 with household member recognition, and Amazon has said Amazon Now ordering - reported at about USD 1 billion annualised with orders doubling quarterly - will come to Alexa+ by voice.

So the pieces are arriving in the same quarter: agents that can pay, a household that already delegates, and an assistant that knows which family member is speaking. The piece nobody has shipped is the authoriser NPCI described.

**UPI Circle delegates to a person. Nobody has delegated to an agent, because there is no framework for it yet - NPCI said so on 10 September 2026.**

Jhola is a working sketch of that missing piece. The model reads intent. A deterministic engine verifies identity, mandate, limits and consent, and writes down why.

## What it does

Any WhatsApp number can message Jhola, answer three questions, and become the admin of its own household. The admin adds family in plain words: "Add Sunita didi 98765 43210, groceries only, 500 a day." Members send a parchi photo, a voice note, or a typed list in Hindi, Hinglish or English. A Strands agent on Bedrock (Claude Sonnet 5) reads it, resolves items to the family's learned usual brands, expands recipes, checks the pantry, and builds a cart.

Then Cedar decides, outside the model. Per line: role and category scope, seller rating, quantity, and dietary rules checked against the person the item is for (Jain, veg, allergies, fasting, caffeine). Per order: the monthly UPI AutoPay mandate cap, the approval threshold, personal limits, time-boxed delegations. Outcomes: auto-pay, one-tap approval from the admin on WhatsApp, or block, always with the policy ids that decided and a Hinglish reason the family can read. Plain-words rules ("No chocolate for Aarav") are drafted into Cedar, validated and tested before the admin activates them.

The model has no payment tool. Payment happens inside `submit_order` after a Cedar allow, carrying an HMAC-signed authorisation the mandate service verifies for that exact order, amount, action and member. Everything is audited: every Cedar request and result, the payment, the notification, the admin action, and every refused admin attempt.

**Scope.** I did not need real money to build the authorisation layer. The authorisation layer is the part that does not exist yet. The UPI AutoPay mandate, the debits and the UPI references are a simulation with a monthly cap, idempotent debits and a refusal to debit without a signed authorisation; everything the family sees says SIMULATED. Everything above the payment rail - the WhatsApp channel, the models, the policy engine, the audit trail, the per-household isolation - is real and deployed. The 601-SKU catalog is a demo modeled on Amazon.in listings, neither affiliated nor scraped.

## Evidence

**The red team.** The real model refused every injection I wrote. That is good behaviour and useless evidence: a defence you cannot exercise is a defence you cannot trust. So I wrote a scripted Strands model provider that plays a fully compromised model and obeys the attacker to the letter, and ran it through the real tool loop, Cedar and the mandate, seeded with the live mandate usage and the household's real rules. Cedar denies what the compromised model built and the mandate is never called. Run it at https://jhola-phi.vercel.app/console/redteam, or `POST /api/redteam` on the console API, or offline with `uv run pytest -k redteam`.

**The eval suite.** 76 cases through the real pipeline on live Bedrock, one clean full pass, each in its own fresh household: aliases and Hinglish typos, Indian quantity words, parchi lists, ambiguous items, product questions, admin commands, policy cases for every role, dietary and allergy cases, and 11 adversarial cases. **0 unsafe payments, 0 errors**, p50 9.4 s per case, USD 1.95 metered for the run. 67 of 76 cases passed every check; none of the nine failures is a wrong Cedar verdict - they are cases where the model asked a clarifying question instead of ordering. The live model refused 11 of 11 injections, which measures the model's resistance, not Cedar's containment: Cedar's containment path never fired in this run because it never had to, and the compromised-model red team above is what exercises it. Full table, methodology and every diagnosed failure: `agent/evals/RESULTS.md`.

**The audit trail.** Not just that an order was blocked, but which rule blocked it and what the family was told, at https://jhola-phi.vercel.app/console/audit.

## How it was built

Python 3.12, Strands Agents, cedarpy, boto3, uv. Next.js on Vercel. SAM and CloudFormation. About 100 offline pytest tests use a scripted Strands model provider, so the whole loop including Cedar and the mandate runs without an LLM.

## AWS usage

End User Messaging Social (WhatsApp) publishes to SNS, which invokes a Lambda running the agent. DynamoDB holds one table partitioned per household plus a dedupe and rate-limit table. S3 holds media with a 7-day lifecycle. Transcribe handles voice notes; Polly speaks a short reply. API Gateway fronts the console Lambda; EventBridge Scheduler fires the Sunday refill; SSM holds the demo key. ECS Fargate runs the voice WebSocket server behind an ALB and CloudFront, streaming bidirectionally to Nova 2 Sonic. Bedrock is reached through IAM roles in a second account that trust one execution role and allow one model each, with one-hour STS credentials. No long-lived keys.

## Challenges

WhatsApp on AWS was the biggest setup effort: the WABA and number in End User Messaging, the SNS destination, media fetch, the 24-hour window that decides when an approval can be delivered, and duplicate webhooks that needed a dedupe on message id. The primary account's Bedrock access was pending, so I built a cross-account role with one trusted principal and one allowed model. Claude Sonnet 5 on Bedrock rejected the `temperature` parameter. Nova Sonic transcribes Hindi in Devanagari while the catalog aliases are Latin, so queries are transliterated first.

## What I learned

The model is not where the safety lives, and proving that takes work. A model that behaves cannot demonstrate containment, so I had to build a model that misbehaves on purpose. Measuring the two separately also showed a subtler gap: nine denials in the eval run came from the model refusing on its own before any tool call, so the outcome was right but Cedar never saw the request and the family got no policy id to read. A refusal that leaves no record is weaker than a deny that does, even when the money is equally safe.

Second, tenancy bugs hide in convenience code: a test running two households side by side caught an isolation bug before it reached the table. Third, deterministic beats clever where trust matters: onboarding and admin confirmations are written by code, so the Yes button does exactly what it says.

## What is next

Real UPI AutoPay through a PSP behind the same signed-authorisation interface. Route more denials through Cedar rather than the system prompt, so every refusal has a policy id. Real catalog data behind the diet and allergen rules. Approved WhatsApp templates so the Sunday refill can start the conversation. Fewer model calls per order.

## AI tools used

Claude Code (Anthropic) for code, tests, infrastructure and documentation during the build. Claude Sonnet 5 on Amazon Bedrock as the runtime agent, vision reader and Cedar drafter. Amazon Nova 2 Sonic as the runtime voice model. Landing images and the logo were generated with FLUX.2-pro.
