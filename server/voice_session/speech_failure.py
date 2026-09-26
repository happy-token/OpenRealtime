"""Safe user-facing provider failure categories; never echo provider responses."""

from __future__ import annotations

import re

from server.voice_session.protocol import VoiceSessionFailureFrame

_QUOTA = re.compile(
    r"quota|insufficient[_ -]?(balance|credit|funds)|credit[_ -]?exhaust|"
    r"(?:^|\D)402(?:\D|$)|余额不足|额度不足|配额不足|欠费|用量已达上限",
    re.IGNORECASE,
)
_AUTH = re.compile(
    r"invalid[_ -]?(api[_ -]?)?key|unauthorized|authentication[_ -]?fail|"
    r"permission[_ -]?denied|access[_ -]?denied|(?:^|\D)40[13](?:\D|$)|"
    r"密钥无效|鉴权失败|无权限",
    re.IGNORECASE,
)
_THROTTLE = re.compile(
    r"rate[_ -]?limit|too many requests|concurren|(?:^|\D)429(?:\D|$)|"
    r"请求过于频繁|并发限制",
    re.IGNORECASE,
)


def provider_failure_frame(capability: str, source: str, provider_error: str) -> VoiceSessionFailureFrame:
    if capability not in {"asr", "tts", "brain"} or source not in {"personal", "platform"}:
        raise ValueError("invalid provider failure context")
    owner = "你的" if source == "personal" else "平台"
    service = {"asr": "语音识别", "tts": "语音合成", "brain": "对话模型"}[capability]
    if _QUOTA.search(provider_error):
        code = f"{source}_quota_exhausted"
        action = "请更新你的 Key" if source == "personal" else "请等待平台额度恢复"
        message = f"{owner}{service}额度不足，本次会话已结束。{action}后重新开始。"
    elif _AUTH.search(provider_error):
        code = f"{source}_credential_invalid"
        message = f"{owner}{service} Key 无效或无权使用，本次会话已结束。请检查 Key 后重新开始。"
    elif _THROTTLE.search(provider_error):
        code = "provider_rate_limited"
        message = f"{service}服务商当前限制请求，本次会话已结束。请稍后手动重试。"
    else:
        code = "speech_provider_unavailable"
        message = f"{service}服务暂时不可用，本次会话已结束。请稍后手动重试。"
    return VoiceSessionFailureFrame(
        code=code,
        phase="active",
        retryable=False,
        session_disposition="close",
        safe_message=message,
    )
