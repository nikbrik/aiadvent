import os

import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
TIMEOUT_SECONDS = 60.0


class OpenRouterError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def chat_completion(prompt, temperature=0.7, top_p=1.0, top_k=40, model=None):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not set", 500)

    model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": temperature,
        "top_p": top_p,
    }

    if top_k != 0:
        body["top_k"] = top_k

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

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

    if response.status_code >= 400:
        raise OpenRouterError(
            f"OpenRouter returned HTTP {response.status_code}: {short_error(response)}",
            502,
        )

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
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
