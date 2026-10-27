"""Canonical names for the banks exposed by the demo gateway."""
import re


_ALIASES = {
    'sbi': ('sbi', 'state bank of india', 'state bank of india limited', 'state bank of india ltd'),
    'pnb': ('pnb', 'punjab national bank', 'punjab national bank limited', 'punjab national bank ltd'),
    'hdfc': ('hdfc', 'hdfc bank', 'hdfc bank limited', 'hdfc bank ltd'),
    'icici': ('icici', 'icici bank', 'icici bank limited', 'icici bank ltd'),
}


def bank_code_for_name(name: str | None) -> str | None:
    """Resolve common printed full names/abbreviations without guessing unknown banks."""
    cleaned = re.sub(r'\((?:sbi|pnb|hdfc|icici)\)', ' ', name or '', flags=re.IGNORECASE)
    normalized = re.sub(r'[^a-z0-9]+', ' ', cleaned.casefold()).strip()
    parts = normalized.split()
    if parts and parts[0] == 'the':
        parts.pop(0)
    while parts and parts[-1] in {'limited', 'ltd'}:
        parts.pop()
    normalized = ' '.join(parts)
    for code, aliases in _ALIASES.items():
        if normalized in aliases:
            return code
    return None
