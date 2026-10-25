"""Claude backend: the Anthropic Messages API, with an API key from the Claude Console."""

from __future__ import annotations

import base64
import io

import anthropic
from PIL import Image

from .config import env

DEFAULT_MODEL = "claude-opus-5"
# If the model's safety checks decline a request, Anthropic re-runs it on a suitable model server-side.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5-1")


def model() -> str:
    return env("CLAUDE_MODEL", DEFAULT_MODEL)


def missing_settings() -> list[str]:
    return [] if env("ANTHROPIC_API_KEY") else ["ANTHROPIC_API_KEY"]


def image_block(image: Image.Image) -> dict:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=95)
    data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def generate(system: str, images: list[Image.Image], text: str, job_dir=None) -> str:
    missing = missing_settings()
    if missing:
        raise RuntimeError(f"The AI model is not set up yet: add {' and '.join(missing)} to .env")
    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    request = {
        "model": model(),
        "max_tokens": 64000,
        "system": system,
        "messages": [{"role": "user", "content": [*(image_block(image) for image in images), {"type": "text", "text": text}]}],
    }
    if request["model"] in FALLBACK_MODELS:
        request["betas"] = [FALLBACK_BETA]
        request["fallbacks"] = "default"
    effort = env("CLAUDE_EFFORT")  # low | medium | high (the default when unset) | xhigh | max
    if effort:
        request["output_config"] = {"effort": effort}
    # Streaming keeps a long reply (thinking + a full script) clear of HTTP timeouts.
    with client.beta.messages.stream(**request) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise RuntimeError(f"The AI model declined the request (category: {getattr(details, 'category', None)})")
    if message.stop_reason == "max_tokens":
        raise RuntimeError("The AI model's reply was cut off before the script was complete (max_tokens reached)")
    raw = "".join(block.text for block in message.content if block.type == "text").strip()
    if not raw:
        raise RuntimeError("The AI model returned an empty Blender script")
    return raw
