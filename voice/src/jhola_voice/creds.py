"""AWS credentials for the Nova Sonic bidirectional stream (smithy SDK).

The experimental aws_sdk_bedrock_runtime client does not read AWS profiles or the ECS task role, so
credentials come from boto3 and are handed to the SDK through a small identity resolver:

  * JHOLA_VOICE_BEDROCK_ROLE_ARN set: assume that role (cross-account, Bedrock account) with the
    ambient credentials (the ECS task role on AWS). Refreshed every 45 minutes.
  * otherwise: the named profile JHOLA_BEDROCK_PROFILE (default "default") for local runs.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import timezone

import boto3
from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_core.aio.interfaces.identity import IdentityResolver

ROLE_ARN = os.environ.get("JHOLA_VOICE_BEDROCK_ROLE_ARN", "")
PROFILE = os.environ.get("JHOLA_BEDROCK_PROFILE", "default")
REGION = os.environ.get("JHOLA_BEDROCK_REGION", "us-east-1")
REFRESH_SECONDS = 45 * 60


def _fetch() -> AWSCredentialsIdentity:
    if ROLE_ARN:
        c = boto3.client("sts", region_name=os.environ.get("AWS_REGION", "ap-south-1")).assume_role(
            RoleArn=ROLE_ARN, RoleSessionName="jhola-voice", DurationSeconds=3600
        )["Credentials"]
        return AWSCredentialsIdentity(
            access_key_id=c["AccessKeyId"], secret_access_key=c["SecretAccessKey"], session_token=c["SessionToken"],
            expiration=c["Expiration"].astimezone(timezone.utc),
        )
    session = boto3.Session(profile_name=PROFILE) if PROFILE else boto3.Session()
    f = session.get_credentials().get_frozen_credentials()
    return AWSCredentialsIdentity(access_key_id=f.access_key, secret_access_key=f.secret_key, session_token=f.token)


class BotoCredentialsResolver(IdentityResolver[AWSCredentialsIdentity, dict]):
    def __init__(self) -> None:
        self._identity: AWSCredentialsIdentity | None = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    async def get_identity(self, *, properties: dict) -> AWSCredentialsIdentity:
        async with self._lock:
            if self._identity is None or time.time() - self._at > REFRESH_SECONDS:
                self._identity = await asyncio.to_thread(_fetch)
                self._at = time.time()
            return self._identity


RESOLVER = BotoCredentialsResolver()
