# Jhola: household grocery delegation on WhatsApp, with Cedar as the boundary

WeMakeDevs x AWS "First Commit" hackathon, Ship It track. Solo builder: Ayush Gupta (GitHub madmecodes).

Live: https://jhola-phi.vercel.app. WhatsApp: +91 96063 54404. Repo: https://github.com/madmecodes/jhola.

## Problem

Indian households shop as a family: Mom, Dad, the house help, a teenager, a Jain grandmother, over WhatsApp, with handwritten parchis and voice notes. Shopping assistants like Rufus help one person choose. They do not help a family delegate. As commerce agents start paying on our behalf, the unsolved part is inside the home: who may order what, up to how much, and who has to say yes. If that lives in a prompt, a teenager or a seller listing can talk the agent out of it.

## What it does

Any WhatsApp number can message Jhola, answer three questions, and become the admin of its own household. The admin adds family in plain words: "Add Sunita didi 98765 43210, groceries only, 500 a day." Members send a parchi photo, a voice note, or a typed list in Hindi, Hinglish or English. A Strands agent on Bedrock (Claude Sonnet 5) reads it, resolves items to the family's learned usual brands, expands recipes, checks the pantry, and builds a cart.

Then Cedar decides. Per line: role and category scope, seller rating, quantity, and dietary rules checked against the person the item is for (Jain, veg, allergies, fasting, caffeine). Per order: the monthly UPI AutoPay mandate cap, the approval threshold, personal limits, time-boxed delegations. Outcomes: auto-pay, one-tap approval from the admin on WhatsApp, or block, always with policy ids and a Hinglish reason. Plain-words rules ("No chocolate for Aarav") are drafted into Cedar, validated and tested before the admin activates them. The model has no payment tool: payment happens inside `submit_order` after a Cedar allow, with a signed authorization the mandate service verifies. Everything is audited. A Sunday schedule proposes the refill. A browser store adds live voice with Nova 2 Sonic through the same gate. A red team page runs real attacks with a deliberately compromised model and shows Cedar holding.

## How it was built

Python 3.12, Strands Agents, cedarpy, boto3, uv. Next.js on Vercel. SAM and CloudFormation. About 100 offline pytest tests use a scripted Strands model provider, so the whole loop runs without an LLM. Payments are simulated; the 601-SKU catalog is a demo modeled on Amazon.in listings, not affiliated or scraped.

## AWS usage

End User Messaging Social (WhatsApp) publishes to SNS, which invokes a Lambda running the agent. DynamoDB holds one table partitioned per household plus a dedupe and rate-limit table. S3 holds media with a 7-day lifecycle. Transcribe handles voice notes; Polly speaks a short reply. API Gateway fronts the console Lambda; EventBridge Scheduler fires the Sunday refill; SSM holds the demo key. ECS Fargate runs the voice WebSocket server behind an ALB and CloudFront, streaming bidirectionally to Nova 2 Sonic. Bedrock is reached through IAM roles in a second account that trust one execution role and allow one model each, with one-hour STS credentials. No long-lived keys.

## Challenges

WhatsApp on AWS was the biggest setup effort: the WABA and number in End User Messaging, the SNS destination, media fetch, the 24-hour window that decides when an approval can be delivered, and duplicate webhooks that needed a dedupe on message id. The primary account's Bedrock access was pending, so I built a cross-account role with one trusted principal and one allowed model. Claude Sonnet 5 on Bedrock rejected the `temperature` parameter. Nova Sonic transcribes Hindi in Devanagari while the catalog aliases are Latin, so queries are transliterated first.

## What I learned

The model is not where the safety lives. The real model refused every injection I wrote, which is good behaviour and useless evidence: a defence you cannot exercise is a defence you cannot trust. I built a scripted compromised model that obeys the attacker and ran it through the real tool loop, Cedar and the mandate. Only then could I show containment does not depend on the model. Second, tenancy bugs hide in convenience code: a test running two households side by side caught an isolation bug before it reached the table. Third, deterministic beats clever where trust matters: onboarding and admin confirmations are written by code, so the Yes button does exactly what it says.

## What is next

Real UPI AutoPay through a PSP behind the same authorization interface. Real catalog data behind the diet and allergen rules. Approved WhatsApp templates so the Sunday refill can start the conversation. Fewer model calls per order.

Eval results: see `agent/evals/RESULTS.md` in the repository.

## AI tools used

Claude Code (Anthropic) for code, tests, infrastructure and documentation during the build. Claude Sonnet 5 on Amazon Bedrock as the runtime agent, vision reader and Cedar drafter. Amazon Nova 2 Sonic as the runtime voice model. Landing images and the logo were generated with FLUX.2-pro.
