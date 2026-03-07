# Session Log 3 — PII-maskning & 20/20 Evaluation

**Datum:** 2026-03-07
**Av:** Abdulla (med AI-assistans)

---

## Översikt

Denna session fokuserade på att åtgärda det sista failande testet (test 2, email-prompten) genom att implementera PII-maskning i agent-loopen. Resultatet: **20/20 routing, 20/20 validation**.

---

## Utgångsläge

Från session 2 hade vi:
- Routing: 20/20 (100%)
- Validation: 19/20 (95%)
- Enda failure: Test 2 ("Skicka fakturan till anna.svensson@gmail.com tack.")

---

## Problemanalys

### Kedjan som orsakade failure

1. `classify_sensitivity` hittar `anna.svensson@gmail.com` via epost-regex → level `"high"`
2. `route_to_model` skickar **hela prompten inklusive emailadressen** rakt till llama-large
3. Modellen svarar naturligt med "du kan skicka till anna.svensson@gmail.com genom att..."
4. `validate_response` hittar emailadressen i svaret → **"Security breach: Sensitive epost leaked"**
5. Agenten retryar, men samma prompt med samma email skickas varje gång → modellen ekar alltid emailen → validation failar → max retries → ger upp

### Grundorsak

`route_to_model` fick den råa prompten med PII. Modellen såg emailadressen och nämnde den i svaret. Retries hjälpte inte eftersom samma PII skickades varje gång.

---

## Lösning: PII-maskning

### Koncept

Innan prompten skickas till `route_to_model` ersätts all detekterad PII med säkra platshållare. Modellen ser aldrig den känsliga datan och kan därmed inte eka den tillbaka.

Exempel:
- Före: `"Skicka fakturan till anna.svensson@gmail.com tack."`
- Efter: `"Skicka fakturan till [EMAIL] tack."`

### Implementation (i `agent.py`)

Importerar `PII_PATTERNS` från `tools.py` och skapar en `mask_pii()`-funktion:

```python
from tools import ..., PII_PATTERNS

PII_LABELS = {
    "personnummer": "[PERSONNUMMER]",
    "epost": "[EMAIL]",
    "telefonnummer": "[TELEFONNUMMER]",
    "kreditkort": "[KREDITKORT]",
    "ip_adress": "[IP-ADRESS]",
    "postnummer": "[POSTNUMMER]",
}

def mask_pii(text: str) -> str:
    masked = text
    for pattern_name, pattern in PII_PATTERNS.items():
        label = PII_LABELS.get(pattern_name, "[REDACTED]")
        masked = re.sub(pattern, label, masked, flags=re.IGNORECASE)
    return masked
```

Maskningen appliceras i tool-dispatchen, precis innan `route_to_model` anropas:

```python
if tool_name == "route_to_model":
    tool_input["prompt"] = mask_pii(user_prompt)
```

### Viktigt designbeslut

- `classify_sensitivity` får fortfarande den **råa** prompten — den behöver se PII för att kunna detektera den
- `route_to_model` får den **maskerade** prompten — modellen ska aldrig se känslig data
- `validate_response` körs mot den **råa** prompten som `original_prompt` — så PII-läckagechecken fungerar korrekt

---

## Resultat efter fix

### Agent evaluation: 20/20

| # | Beskrivning | Routing | Validation | Steg |
|---|-------------|---------|------------|------|
| 1 | Personnummer | high (OK) | pass | 4 |
| 2 | **E-postadress** | **high (OK)** | **pass** | **4** |
| 3 | Telefonnummer | high (OK) | pass | 4 |
| 4 | Kreditkortsnummer | high (OK) | pass | 4 |
| 5 | Hemadress (keyword) | high (OK) | pass | 4-6 |
| 6 | Lön (keyword) | high (OK) | pass | 4 |
| 7 | Medicinsk diagnos | high (OK) | pass | 4 |
| 8 | Lösenord (keyword) | high (OK) | pass | 4 |
| 9 | E-post + telefon | high (OK) | pass | 4 |
| 10 | Hemadress (keyword) | high (OK) | pass | 4 |
| 11-20 | Low sensitivity | low (OK) | pass | 4 |

**Routing accuracy: 20/20 (100%)**
**Validation passes: 20/20 (100%)**
**Avg steps/prompt: ~4.2**

### Före vs efter maskning (test 2)

| | Före | Efter |
|---|------|-------|
| Vad modellen ser | `anna.svensson@gmail.com` | `[EMAIL]` |
| Modellens svar nämner | Emailadressen bokstavligt | "den angivna e-postadressen" |
| Validation | fail (PII leaked) | pass |
| Steg | 7 (max retries) | 4 |

---

## Rate limit-hantering borttagen

Separat ändring i denna session: all rate limit-hantering (retry-loopar, `time.sleep()`, pauser mellan tester) togs bort från `agent.py` och `evaluate.py` efter uppgradering till betald Groq dev-key.

---

## Filer som ändrades

| Fil | Ändring |
|-----|---------|
| `agent.py` | Lade till `mask_pii()` funktion, importerar `PII_PATTERNS`, maskar prompt innan `route_to_model`. Tog bort rate limit retry och pauser. |
| `evaluate.py` | Tog bort pauser mellan tester. |

---

## Sammanfattning

- PII-maskning implementerad: känslig data ersätts med platshållare (`[EMAIL]`, `[PERSONNUMMER]` etc.) innan den skickas till modellen
- Test 2 (email) fixad: gick från fail till pass
- Alla 20 tester passerar nu: 20/20 routing, 20/20 validation
- Rate limit-hantering borttagen efter uppgradering till betald API-nyckel
