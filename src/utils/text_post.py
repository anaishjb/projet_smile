import re

_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def clean_llm_reply(raw: str, state: str = "FREE_TALK", is_first_turn: bool = False) -> str:
    if not raw:
        return ""
    text = _EMOJI_RE.sub("", raw).strip()

    # Remove leading greeting phrases on non-first turns
    if not is_first_turn:
        text = re.sub(
            r"^(bonjour[\s,!]*|salut[\s,!]*|bonsoir[\s,!]*|coucou[\s,!]*|hey[\s,!]*)+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    # Strip questions during FAREWELL
    if state == "FAREWELL":
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s for s in sentences if not s.strip().endswith("?")]
        text = " ".join(sentences).strip()

    # Remove repeated consecutive phrases (e.g. "bien sûr bien sûr")
    text = re.sub(r"\b(.{4,}?)\s+\1\b", r"\1", text, flags=re.IGNORECASE)

    return text if text else raw.strip()
