# Jhola infra (AWS SAM)

Real WhatsApp messages to +91 96063 54404 are answered live by the Jhola agent.

```
WhatsApp user
   |
AWS End User Messaging Social (WABA, ap-south-1)
   |  webhook events
SNS jhola-whatsapp-events ----> SQS jhola-whatsapp-inbox (debug mirror, untouched)
   |  async invoke
Lambda jhola-whatsapp-agent (Python 3.12, arm64, 1024 MB, 180 s)
   |- dedupe on WhatsApp message id      DynamoDB jhola-processed-messages (TTL 7 days)
   |- state: orders, mandate, txns,       DynamoDB jhola-state (pk=collection, sk=key)
   |  audit log, conversation history,
   |  demo persona per phone
   |- photos + voice notes                S3 jhola-media-<acct>-ap-south-1 (private, 7-day lifecycle)
   |     GetWhatsAppMessageMedia -> S3 inbound/<mediaId>/
   |     voice notes -> Amazon Transcribe (IdentifyLanguage hi-IN / en-IN) -> transcripts/
   |- Strands agent + Cedar policies (agent/)
   |     Bedrock Claude Sonnet 5 via sts:AssumeRole into the Bedrock account (us-east-1)
   |- replies: SendWhatsAppMessage (text, interactive reply buttons)
         voice note in -> text reply + short spoken reply (Polly Kajal, hi-IN, ogg/opus)
```

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
`whatsapp_sent`, `handle_failed`). Every agent step is also in the audit log (`jhola-state`, pk `audit`).

## Demo persona commands (DEMO FEATURE)

For numbers in the `DemoPhones` parameter (default the owner, who is also Mom, the admin):

| Command | Effect |
|---|---|
| `/as mom`, `/as dad`, `/as didi`, `/as teen` | Act as that member (persisted per phone) |
| `/whoami` | Show the acting member |
| `/reset` | Clear orders, payments, history and conversation; mandate back to Rs 1850 used of Rs 5000 |
| `/help` | List commands |

Approval requests always go to the admin's real phone (so a single-phone demo gets the Approve /
Reject buttons). Messages for members without a real number (Dad, Didi, Aarav) are delivered to the
demo phone, prefixed `[Demo: message for Didi]`.

## Notes

- Replies are free-form, so they only work inside WhatsApp's 24-hour customer-service window
  (the user must have messaged the number in the last 24 hours).
- Status webhooks (sent/delivered/read) also invoke the Lambda and are ignored.
- Typical latency: text 10-30 s, parchi photo about 30 s, voice note about 30 s (Transcribe about 10 s).
- Cost at demo volume is a few cents: Lambda and DynamoDB on-demand are near zero, Transcribe is
  about $0.024 per minute of audio, Polly neural about $16 per 1M characters, Bedrock tokens
  dominate (billed in the Bedrock account). WhatsApp service conversations are free.
