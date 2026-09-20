# Jhola demo video script (3 minutes)

Three beats, not eleven. The judging criteria reward "a single working feature" over "multiple broken or incomplete components", and penalise ideas that read as overly complex. Everything cut from this script stays live on the site for a judge who clicks.

Record: phone screen (WhatsApp) + laptop screen (console, store) + a camera shot for the opening and closing lines.

The longer version of this script, with every scenario and per-shot fallbacks, is in `demo-script-full.md`.

## Before recording

1. Message +91 96063 54404 from the demo phone so the 24-hour window is open.
2. Send `/reset`.
3. Admin key into the console header: `aws ssm get-parameter --name /jhola/demo-key --with-decryption --profile ayush-aws-bits-hack --query Parameter.Value --output text`
4. Tabs open: `/console`, `/console/redteam`, `/store#voice`. Grant mic permission, run one voice sentence to warm the Fargate task.
5. Send `/whoami` to warm the Lambda.
6. Real handwritten parchi on paper. Include one item outside Didi's scope, for example shampoo, so a block happens on the same list.
7. Architecture diagram from the README rendered as an image.
8. Phone on Do Not Disturb, browser zoom 110 to 125%.

## 0:00 to 0:25. The person

Camera on you, or on the parchi in your hand. No product name, no architecture yet.

> "Ten days ago the chairman of NPCI said an AI agent may work out what you want, but it must not be the thing that approves the payment. The day after, Amazon Pay launched agents that pay over UPI. Nobody has built the part in between."

> "Sunita didi works in my house. She buys our groceries. I want her to be able to pay for them: only groceries, only up to five hundred rupees a day. That rule has never existed in software."

## 0:25 to 1:15. The artifact

Phone. `/as didi`, photograph the real parchi, send it.

> "She sends the parchi the way she already does. Claude on Bedrock reads the handwriting, picks our usual brands, and every line is checked before any money moves."

Cart appears. Groceries auto-pay. The shampoo is blocked with the Hinglish reason.

> "Groceries, paid from the mandate. Shampoo, blocked, because it is outside what she is allowed to buy, and it says so in her language."

Cut to the console, 8 seconds, showing the order and the policy id on each line.

One short aside, 8 seconds, no lingering:

> "Or she can just talk to it."

Store tab, mic, one Hindi sentence, cart updates. Move on.

## 1:15 to 2:00. The proof

This is the part nobody else will have.

> "The real model refused every injection I wrote. That is good behaviour and useless evidence. A defence you cannot exercise is a defence you cannot trust. So I rigged a model that obeys the attacker and ran it through the real pipeline."

Run the red team. Cedar blocks. Audit shows the policy id.

Then the card on screen. Do not put a containment percentage on it: the live suite measures the model's resistance, the red team you just ran is what measures Cedar's containment.

> 76 live eval cases. 0 unsafe payments. 0 errors.
> Cedar containment: demonstrated by the compromised model you just watched.

## 2:00 to 2:25. Cloud integration

Architecture diagram on screen. Name five, mention the total.

> "WhatsApp comes in through AWS End User Messaging, SNS and Lambda. The agent is Strands on Bedrock, Claude Sonnet 5. Voice is Nova 2 Sonic. State and the audit trail are DynamoDB. The decision is Cedar, which is deterministic, runs locally, and never calls a model. Eighteen AWS services in total, all defined in SAM."

## 2:25 to 2:50. One lesson

To camera. Say one lesson, not three.

> "The model is not where the safety lives. Put the rules outside it, in something deterministic that a prompt cannot argue with."

## 2:50 to 3:00. Close

> "It is live. This is the number. Message it and it will set up your own household."

Show +91 96063 54404 and jhola-phi.vercel.app on screen.

## Cut from the video, kept on the site

Dietary and Jain rules, vrat mode, delegation with expiry, pantry prediction, recipe expansion, the Sunday refill schedule, plain-words rule drafting, learned brands, the store concept, multi-household onboarding. Each is real and each costs seconds you do not have. The README lists them.

## If something fails while recording

- Vision misreads an item: say "it asks me to confirm what it could not read" and continue.
- Reply takes more than 40 seconds: cut the wait in editing.
- Voice does not connect: skip the aside entirely, it is 8 seconds.
- WhatsApp is down: use `/console/try`, which is the same agent.
- Red team fails to load: the numbers card alone carries the beat.
