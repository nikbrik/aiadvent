"""Local token estimates for chat payloads.

Tokenizer choice:
- If ``tiktoken`` is installed, use ``cl100k_base`` (GPT-4 family) for a stable
  byte-pair estimate that tracks English and mixed text reasonably well.
- Otherwise fall back to a deterministic char heuristic: roughly one token per
  four Unicode characters, with a minimum of one token for non-empty text.

OpenRouter usage fields remain the source of truth for actual token counts.
Local estimates exist for preflight overflow checks and UI growth demos.
"""

import math

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
    _TOKENIZER = "tiktoken:cl100k_base"
except ImportError:
    _ENCODING = None
    _TOKENIZER = "approx:chars/4"

# Per-message overhead for role/name/formatting in chat payloads.
_MESSAGE_OVERHEAD_TOKENS = 4


def tokenizer_name():
    return _TOKENIZER


def count_text_tokens(text, model=None):
    del model  # reserved for future model-specific encodings
    text = str(text or "")
    if not text:
        return 0

    if _ENCODING is not None:
        return len(_ENCODING.encode(text))

    return max(1, math.ceil(len(text) / 4))


def count_message_tokens(messages, model=None):
    total = 0
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        total += _MESSAGE_OVERHEAD_TOKENS
        total += count_text_tokens(role, model)
        total += count_text_tokens(content, model)
    return total
