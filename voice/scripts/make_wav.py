"""Generate test utterances with Amazon Polly (infra account) as 16 kHz mono PCM16 WAV files.

    uv run python scripts/make_wav.py                       # the default Hinglish script
    uv run python scripts/make_wav.py out.wav "text" Kajal  # one file
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import boto3

OUT = Path(os.environ.get("JHOLA_VOICE_WAV_DIR", "/tmp/jhola-voice"))
PROFILE = os.environ.get("JHOLA_INFRA_PROFILE", "ayush-aws-bits-hack")
REGION = os.environ.get("JHOLA_INFRA_REGION", "ap-south-1")

SCRIPT = [
    ("ask.wav", "Mujhe do packet doodh aur ek paneer chahiye. Paneer mein kitna protein hai?", "Kajal"),
    ("order.wav", "Theek hai, wahi add karo aur order kar do.", "Kajal"),
]


def synth(text: str, voice: str, path: Path) -> Path:
    polly = boto3.Session(profile_name=PROFILE, region_name=REGION).client("polly")
    audio = polly.synthesize_speech(Text=text, VoiceId=voice, Engine="neural", LanguageCode="hi-IN",
                                    OutputFormat="pcm", SampleRate="16000")["AudioStream"].read()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio)
    print(f"{path}  {len(audio) / 32000:.1f}s  {text}")
    return path


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        synth(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "Kajal", Path(sys.argv[1]))
    else:
        for name, text, voice in SCRIPT:
            synth(text, voice, OUT / name)
