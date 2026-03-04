import re
from typing import Dict, Any

# PII-mönster att matcha mot
PII_PATTERNS = {
    "personnummer": r"\b(?:\d{2}){3,4}[- ]?\d{4}\b",
    "epost": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "telefonnummer": r"\b(?:\+46|0046|0)\s*\(?\d{1,3}\)?[\s-]?\d{2,3}[\s-]?\d{2,3}[\s-]?\d{2,3}\b",
    "kreditkort": r"\b(?:\d{4}[\s-]?){3}\d{4}\b|\b\d{4}[\s-]?\d{6}[\s-]?\d{5}\b",
    "ip_adress": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
}

# Känsliga nyckelord som indikerar personlig kontext
SENSITIVE_KEYWORDS = [
    "personnummer", "pnr", "social security",
    "lösenord", "password", "lösen", "psw",
    "telefonnummer", "phone number", "mobilnummer", "mobile number",
    "kreditkort", "bankkort", "credit card", "bankkontonummer",
    "hemadress", "home address", "gatuadress", "adress",
]

def sensitivity_classifier(expression: str) -> dict[str, Any]:
    """
    Classifies the sensitivity of a given expression.

    Parameters:
    expression (str): The input expression to classify.

    Returns:
    dict: A dictionary containing the sensitivity level, detected matches, and details.
    """
    matches = []

    # Kolla PII-mönster med regex
    for pattern_name, pattern in PII_PATTERNS.items():
        found = re.findall(pattern, expression, re.IGNORECASE)
        for match in found:
            matches.append(f"{pattern_name}: {match}")

    # Kolla nyckelord
    for keyword in SENSITIVE_KEYWORDS:
        kw_pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(kw_pattern, expression, re.IGNORECASE):
            matches.append(f"keyword: {keyword}")

    # Bestäm nivå
    if matches:
        return {
            "level": "high",
            "matches": matches,
            "details": f"PII detected: {', '.join(matches)}"
        }
    else:
        return {
            "level": "low",
            "matches": [],
            "details": "No PII detected"
        }
