"""URL-specific robots rule inspection, not a guarantee of a vendor's behavior.

Implements group selection, wildcard fallback, merged matching groups,
longest rule and Allow-on-tie; UTF-8 and percent-encoded path comparison.
"""
import re
from urllib.parse import urlsplit, quote


def parse_groups(text):
    groups, agents, rules, saw_rule = [], [], [], False
    for raw in (text or "").lstrip("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (x.strip() for x in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if saw_rule:
                groups.append((agents, rules))
                agents, rules, saw_rule = [], [], False
            if value:
                agents.append(value.lower())
        elif field in ("allow", "disallow") and agents:
            saw_rule = True
            if value.startswith("/"):
                rules.append((field, value))
    if agents:
        groups.append((agents, rules))
    return groups


def _normalize_path(value):
    value = quote(value, safe="/%*?$&=:@!()+,;~-._")
    def pct(match):
        char = chr(int(match.group()[1:], 16))
        return char if char.isascii() and (char.isalnum() or char in "-._~") else match.group().upper()
    return re.sub(r"%[0-9a-fA-F]{2}", pct, value)


def evaluate_robots(text, agent, url):
    groups = parse_groups(text)
    named = [(max((len(a) for a in agents if a != "*" and a in agent.lower()), default=0), rules)
             for agents, rules in groups]
    specificity = max((n for n, _ in named), default=0)
    selected = [rules for n, rules in named if n == specificity] if specificity else [rules for agents, rules in groups if "*" in agents]
    parts = urlsplit(url)
    path = _normalize_path((parts.path or "/") + ("?" + parts.query if parts.query else ""))
    matches = []
    for rules in selected:
        for directive, pattern in rules:
            normalized = _normalize_path(pattern)
            end = normalized.endswith("$")
            body = normalized[:-1] if end else normalized
            regex = "^" + re.escape(body).replace(r"\*", ".*") + ("$" if end else "")
            if re.search(regex, path):
                length = len(body.replace("*", "").encode("utf-8"))
                matches.append((length, directive == "allow", directive, pattern))
    winner = max(matches, default=None)
    allowed = winner is None or winner[1]
    return {
        "allowed": allowed,
        "blocked": not allowed,
        "group": "specific" if specificity else "wildcard" if selected else "none",
        "matched_rule": f"{winner[2]}: {winner[3]}" if winner else "No matching restriction",
        "path": path,
    }
