"""Upload a prepared sample and enroll it as a Bailian cloned voice.

The source sample is placed in the configured S3-compatible public bucket only
for the duration of the enrollment request, then removed. Provider credentials
and object-store credentials remain server-side.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

PREFIX_PATTERN = re.compile(r"[a-z0-9]{1,10}")
ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{2,128}")


def build_enrollment_payload(*, target_model: str, prefix: str, audio_url: str) -> dict[str, object]:
    if not ID_PATTERN.fullmatch(target_model):
        raise ValueError("invalid Bailian clone target model")
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError("voice prefix must contain 1-10 lowercase letters or digits")
    parsed = urllib.parse.urlparse(audio_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("voice clone sample must use a public HTTPS URL")
    return {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": target_model,
            "prefix": prefix,
            "url": audio_url,
            "max_prompt_audio_length": 20,
            "enable_preprocess": False,
            "enable_volume_normalization": "false",
            "language_hints": ["zh"],
        },
    }


def resolve_enrollment_endpoint(environ: Mapping[str, str]) -> str:
    configured = environ.get("BAILIAN_API_HOST", "").strip()
    if configured:
        host = configured.removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    else:
        workspace_id = environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        host = f"{workspace_id}.cn-beijing.maas.aliyuncs.com" if workspace_id else "dashscope.aliyuncs.com"
    return f"https://{host}/api/v1/services/audio/tts/customization"


def public_object_url(base_url: str, object_key: str) -> str:
    parsed = urllib.parse.urlparse(base_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("S3_PUBLIC_BASE_URL must be a public HTTPS URL")
    encoded_key = "/".join(urllib.parse.quote(segment, safe="") for segment in object_key.split("/"))
    return f"{base_url.rstrip('/')}/{encoded_key}"


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path, help="prepared mono PCM16 WAV sample")
    parser.add_argument("--prefix", default="openrt", help="provider voice prefix")
    parser.add_argument("--rights-confirmed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.rights_confirmed:
        raise SystemExit("voice rights must be explicitly confirmed")
    if not args.sample.is_file() or args.sample.suffix.lower() != ".wav":
        raise SystemExit("prepared WAV sample does not exist")

    try:
        import boto3
    except ModuleNotFoundError as error:
        raise SystemExit("boto3 is required for voice clone sample upload") from error

    environ = os.environ
    try:
        api_key = _required(environ, "DASHSCOPE_API_KEY")
        endpoint_url = _required(environ, "S3_ENDPOINT_URL")
        bucket = _required(environ, "S3_BUCKET")
        access_key = _required(environ, "S3_AK")
        secret_key = _required(environ, "S3_SK")
        public_base = _required(environ, "S3_PUBLIC_BASE_URL")
        target_model = environ.get("BAILIAN_VOICE_CLONE_MODEL", "").strip() or environ.get("BAILIAN_TTS_MODEL", "").strip() or "cosyvoice-v3-flash"
        prefix_root = environ.get("S3_PREFIX", "openrealtime/").strip().strip("/")
        object_key = "/".join(filter(None, [prefix_root, "voice-clones", f"{uuid.uuid4().hex}.wav"]))
        audio_url = public_object_url(public_base, object_key)
        payload = build_enrollment_payload(target_model=target_model, prefix=args.prefix, audio_url=audio_url)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=environ.get("S3_REGION", "auto").strip() or "auto",
    )
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=args.sample.read_bytes(),
        ContentType="audio/wav",
        Metadata={"purpose": "voice-clone-enrollment"},
    )
    try:
        request = urllib.request.Request(
            resolve_enrollment_endpoint(environ),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bailian voice enrollment failed ({error.code}): {detail[:500]}") from error
        voice_id = result.get("output", {}).get("voice_id")
        if not isinstance(voice_id, str) or not ID_PATTERN.fullmatch(voice_id):
            raise RuntimeError(f"Bailian voice enrollment returned no voice_id: {json.dumps(result, ensure_ascii=False)[:500]}")
        print(json.dumps({
            "voice_id": voice_id,
            "target_model": target_model,
            "request_id": result.get("request_id"),
        }, ensure_ascii=False))
    finally:
        try:
            client.delete_object(Bucket=bucket, Key=object_key)
        except Exception as error:  # Cleanup failure must not hide a successful enrollment.
            print(f"warning: failed to delete temporary clone sample: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
