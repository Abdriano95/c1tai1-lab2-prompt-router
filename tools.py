import os
import re
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from typing import Dict, Any

load_dotenv()


# PII-mönster att matcha mot
PII_PATTERNS = {
    "personnummer": r"\b(?:\d{2}){3,4}[- ]?\d{4}\b",
    "epost": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    "telefonnummer": r"\b(?:\+46|0046|0)\s*\(?\d{1,3}\)?[\s-]?\d{2,3}[\s-]?\d{2,3}[\s-]?\d{2,3}\b",
    "kreditkort": r"\b(?:\d{4}[\s-]?){3}\d{4}\b|\b\d{4}[\s-]?\d{6}[\s-]?\d{5}\b",
    "ip_adress": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
    "postnummer": r"\b\d{3}\s?\d{2}\b",
}

# Platshållare för maskad PII
PII_LABELS = {
    "personnummer": "[PERSONNUMMER]",
    "epost": "[EMAIL]",
    "telefonnummer": "[TELEFONNUMMER]",
    "kreditkort": "[KREDITKORT]",
    "ip_adress": "[IP-ADRESS]",
    "postnummer": "[POSTNUMMER]",
}

# Känsliga nyckelord som indikerar personlig kontext
SENSITIVE_KEYWORDS = [
    "personnummer", "pnr", "social security",
    "lösenord", "password", "lösen", "psw",
    "telefonnummer", "phone number", "mobilnummer", "mobile number",
    "kreditkort", "bankkort", "credit card", "bankkontonummer",
    "hemadress", "home address", "gatuadress", "adress",
    "lön", "salary", "inkomst",
    "diagnos", "diagnosen", "medicinsk", "sjukdom",
]

def classify_sensitivity(prompt: str) -> dict[str, Any]:
    """
    Klassificerar känslighetsnivån för en given prompt.

    Parametrar:
        prompt (str): Prompten som ska klassificeras.

    Returnerar:
        dict: En dictionary med känslighetsnivå, detekterade matchningar och detaljer.
    """
    matches = []

    # Kolla PII-mönster med regex
    for pattern_name, pattern in PII_PATTERNS.items():
        found = re.findall(pattern, prompt, re.IGNORECASE)
        for match in found:
            matches.append(f"{pattern_name}: {match}")

    # Kolla nyckelord
    for keyword in SENSITIVE_KEYWORDS:
        kw_pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(kw_pattern, prompt, re.IGNORECASE):
            matches.append(f"keyword: {keyword}")

    # Bestäm känslighetsnivå
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


def mask_pii(text: str) -> dict[str, Any]:
    """
    Ersätter PII-matchningar med säkra platshållare så modellen aldrig ser rå känslig data.
    Används som tool vid eskalering innan prompt skickas till cloud-modellen.

    Parametrar:
        text: Texten som ska maskeras.

    Returnerar:
        dict med masked_text: den maskade texten.
    """
    masked = text
    for pattern_name, pattern in PII_PATTERNS.items():
        label = PII_LABELS.get(pattern_name, "[REDACTED]")
        masked = re.sub(pattern, label, masked, flags=re.IGNORECASE)
    return {"masked_text": masked}


MODELS = {
    "llama-large": ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY")),
    "llama-small": ChatGroq(model="llama-3.1-8b-instant", api_key=os.getenv("GROQ_API_KEY"))
}


def route_to_model(prompt: str, level: str) -> dict:
    """
    Routar prompten till rätt modell baserat på känslighetsnivå.

    Parametrar:
        prompt: Användarprompten (kan vara maskerad vid hög känslighet).
        level: "high" eller "low" från classify_sensitivity.

    Returnerar:
        dict med:
            - model_used: vilken modell som användes
            - response: modellens svar
            - routing_reason: varför denna modell valdes
    """

    mapping = {
        "high": {"id": "llama-small", "reason": "Känslig data — använder lokal/säker modell"},
        "low": {"id": "llama-large", "reason": "Ingen känslig data — använder kraftfull cloud-modell"},
    }

    config = mapping.get(level, mapping["high"])
    model_id = config["id"]

    try:
        llm = MODELS.get(model_id, MODELS["llama-large"])
        result = llm.invoke(prompt)

        return {
            "model_used": config["id"],
            "response": result.content,
            "routing_reason": config["reason"],
            "success": True
        }

    except Exception as e:
        return {
            "model_used": config["id"],
            "response": "",
            "routing_reason": config["reason"],
            "success": False,
            "error": str(e)
        }

MIN_RESPONSE_LENGTH = 10  # Minsta antal tecken för godkänt svar

# Vanliga fraser som indikerar att modellen vägrar svara
REFUSAL_KEYWORDS = ["kan inte svara", "inte behörig", "as an ai model", "cannot fulfill"]

def validate_response(response: str, original_prompt: str) -> dict:
    """
    Validerar att ett modellsvar uppfyller kvalitetskrav.

    Parametrar:
        response: Modellens svar.
        original_prompt: Ursprungsprompten (för PII-läckagekontroll).

    Returnerar:
        dict med:
            - status: "pass" eller "fail"
            - reason: förklaring
    """
    clean_res = response.strip()

    # Kontroll 1: Tomt eller för kort svar
    if not clean_res:
        return {"status": "fail", "reason": "Response is empty"}

    if len(clean_res) < MIN_RESPONSE_LENGTH:
        return {"status": "fail", "reason": f"Response too short ({len(clean_res)} chars)"}

    # Kontroll 2: Vägran (modellen nekar att svara)
    if any(word in clean_res.lower() for word in REFUSAL_KEYWORDS):
        return {"status": "fail", "reason": "Model refused to answer"}
    
    # Kontroll 3: PII-läckage — kolla om känslig data från prompten dyker upp i svaret
    for pattern_name, pattern in PII_PATTERNS.items():
        in_prompt = set(re.findall(pattern, original_prompt, re.IGNORECASE))
        
        for pii_value in in_prompt:
            if pii_value in response:
                return {
                    "status": "fail", 
                    "reason": f"Security breach: Sensitive {pattern_name} leaked"
                }

    return {"status": "pass", "reason": "All checks passed"}