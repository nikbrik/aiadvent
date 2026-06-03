import logging
import os

import httpx

from http_log import log_exchange

logger = logging.getLogger("llm_demo")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
TIMEOUT_SECONDS = 60.0


class OpenRouterError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def chat_completion(
    messages,
    temperature=0.7,
    top_p=1.0,
    top_k=40,
    model=None,
    max_tokens=None,
    stop=None,
    response_format=None,
    provider=None,
    include_reasoning=False,
    reasoning=None,
):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not set", 500)

    model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
    }

    if top_k != 0:
        body["top_k"] = top_k

    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    if stop:
        body["stop"] = stop

    if response_format:
        body["response_format"] = response_format

    if provider:
        body["provider"] = provider

    if include_reasoning:
        body["include_reasoning"] = True

    if reasoning:
        body["reasoning"] = reasoning

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    log_exchange(
        logger,
        theme="openrouter_out",
        title="→ OUT Flask → OpenRouter",
        method="POST",
        url=OPENROUTER_URL,
        request_headers=headers,
        body=body,
    )

    try:
        response = httpx.post(
            OPENROUTER_URL,
            headers=headers,
            json=body,
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        raise OpenRouterError("OpenRouter request timed out", 504)
    except httpx.HTTPError as exc:
        raise OpenRouterError(f"OpenRouter request failed: {exc}", 502)

    try:
        response_data = response.json()
    except ValueError:
        response_data = response.text

    log_exchange(
        logger,
        theme="openrouter_in",
        title="← IN  OpenRouter → Flask",
        method="POST",
        url=OPENROUTER_URL,
        status=response.status_code,
        response_headers=response.headers,
        body=response_data,
    )

    if response.status_code >= 400:
        status = response.status_code if response.status_code < 500 else 502
        raise OpenRouterError(
            f"OpenRouter returned HTTP {response.status_code}: {short_error(response)}",
            status,
        )

    try:
        data = response_data if isinstance(response_data, dict) else response.json()
        choice = data["choices"][0]
        message = choice["message"]
        usage = data.get("usage") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        return {
            "content": message.get("content"),
            "reasoning": message.get("reasoning") or message.get("reasoning_content"),
            "finish_reason": choice.get("finish_reason"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens") or completion_details.get("reasoning_tokens"),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        raise OpenRouterError("OpenRouter response did not contain choices[0].message.content", 502)


def short_error(response):
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        if error:
            return str(error)[:300]

    return str(data)[:300]
