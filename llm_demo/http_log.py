import json
import os
import sys
from typing import Any, Mapping, Optional


LINE = "─" * 62
FRAME = "═" * 62
ESC = "\x1b"

SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization"}
)

THEMES = {
    "browser_in": {"title": "1;36", "frame": "90", "accent": "36"},
    "browser_out": {"title": "1;32", "frame": "90", "accent": "32"},
    "openrouter_out": {"title": "1;33", "frame": "90", "accent": "33"},
    "openrouter_in": {"title": "1;35", "frame": "90", "accent": "35"},
}


def _use_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("LLM_DEMO_LOG_COLOR", "1") == "0":
        return False
    if os.getenv("TERM") == "dumb":
        return False
    if os.getenv("FORCE_COLOR") or os.getenv("CLICOLOR_FORCE"):
        return True
    return sys.stderr.isatty()


def _c(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"{ESC}[{code}m{text}{ESC}[0m"


def _status_style(status: int) -> str:
    if status < 300:
        return "1;32"
    if status < 400:
        return "1;36"
    if status < 500:
        return "1;33"
    return "1;31"


def redact_headers(headers: Optional[Mapping[str, str]]) -> dict[str, str]:
    if not headers:
        return {}

    redacted = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            if key.lower() == "authorization" and value.lower().startswith("bearer "):
                redacted[key] = "Bearer ***"
            else:
                redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def indent_block(text: str, prefix: str = "  ") -> str:
    if text == "(empty)":
        return f"{prefix}(empty)"
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def format_json(data: Any) -> str:
    if data is None:
        return "(empty)"

    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2)

    if isinstance(data, str):
        stripped = data.strip()
        if not stripped:
            return "(empty)"
        try:
            return json.dumps(json.loads(stripped), ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            return data

    if isinstance(data, bytes):
        return format_json(data.decode("utf-8", errors="replace"))

    return str(data)


def format_headers(headers: Optional[Mapping[str, str]]) -> str:
    redacted = redact_headers(headers)
    if not redacted:
        return f"  {_c('2', '(none)')}"

    lines = []
    for key, value in redacted.items():
        if value in ("***", "Bearer ***"):
            value_part = _c("31", value)
        else:
            value_part = value
        lines.append(f"  {_c('36', key)}{_c('90', ': ')}{value_part}")
    return "\n".join(lines)


def log_exchange(
    logger,
    *,
    theme: str = "browser_in",
    title: str,
    method: Optional[str] = None,
    url: Optional[str] = None,
    status: Optional[int] = None,
    request_headers: Optional[Mapping[str, str]] = None,
    response_headers: Optional[Mapping[str, str]] = None,
    body: Any = None,
    body_label: str = "Body",
    skip_body: bool = False,
):
    palette = THEMES.get(theme, THEMES["browser_in"])
    frame = _c(palette["frame"], FRAME)
    line = _c(palette["frame"], LINE)

    parts = ["", frame, f"  {_c(palette['title'], title)}"]

    if method and url:
        status_part = ""
        if status is not None:
            status_part = f"  {_c('90', '→')}  {_c(_status_style(status), str(status))}"
        parts.append(
            f"  {_c('1;97', method)} {_c(palette['accent'], url)}{status_part}"
        )

    parts.append(line)

    if request_headers is not None:
        parts.extend([f"  {_c('1;97', 'Request headers')}", format_headers(request_headers), ""])

    if response_headers is not None:
        parts.extend([f"  {_c('1;97', 'Response headers')}", format_headers(response_headers), ""])

    if not skip_body:
        body_text = format_json(body)
        if body_text.startswith("(") and "bytes" in body_text:
            body_text = _c("2", body_text)
        parts.extend([f"  {_c('1;97', body_label)}:", indent_block(body_text)])

    parts.append(frame)
    message = "\n".join(parts)

    # Пишем напрямую в stderr — logging иногда «съедает» ESC-символы.
    sys.stderr.write(message + "\n")
    sys.stderr.flush()
