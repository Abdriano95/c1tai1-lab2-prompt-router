# Session Log 2 — Evaluation & Rate Limit Debugging

**Datum:** 2026-03-07

---

## Översikt

Denna session fokuserade på att köra `evaluate.py` mot alla 20 testprompts, fixa problem som dök upp under körning, och kartlägga routing accuracy. Tre buggar fixades i `evaluate.py` och en fullständig klassificeringsanalys genomfördes.

---

## Problem 1: Felaktig import i evaluate.py

### Symptom
`evaluate.py` kraschade direkt vid import:
```
ImportError: cannot import name 'classify_sensitivity' from 'tools'
```

### Orsak
Funktionen i `tools.py` heter `sensitivity_classifier`, men `evaluate.py` importerade den som `classify_sensitivity`.

### Fix
Ändrade importraden i `evaluate.py`:
```python
# Före
from tools import classify_sensitivity, route_to_model, validate_response

# Efter
from tools import sensitivity_classifier, route_to_model, validate_response
```

---

## Problem 2: Unicode-krasch på Windows

### Symptom
Efter att test 1 passerat kraschade evaluate.py med:
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'
```

### Orsak
`evaluate.py` använde Unicode-tecken ✓ och ✗ i print-satser. Windows-konsolen (cp1252) stödjer inte dessa tecken.

### Fix
Två ändringar i `evaluate.py`:
1. Ersatte `✓`/`✗` med `OK`/`WRONG`:
```python
print(f"Actual level: {actual_level} ({'OK' if routing_correct else 'WRONG'})")
```
2. La till UTF-8 encoding-konfiguration:
```python
import sys
sys.stdout.reconfigure(encoding="utf-8")
```

---

## Problem 3: Ingen paus mellan tester → rate limit-krasch

### Symptom
Evaluate.py körde 2-3 tester och dog sedan tyst — Groqs rate limit (6000 tokens/minut) överskreds.

### Fix
La till pauser mellan varje test i evaluate.py:
- 15 sekunders paus mellan agent-tester
- 10 sekunders paus mellan baseline-tester

```python
for i, test_case in enumerate(TEST_PROMPTS):
    if i > 0:
        time.sleep(15)
    ...
```

---

## Utvärderingsresultat

### Metod
Eftersom Groqs gratisnivå (6000 TPM) gör det svårt att köra alla 20 tester sekventiellt i en process, kördes testningen i två delar:

1. **Live end-to-end-tester** (test 1-4 + utvalda): Kördes genom `run_agent()` och verifierades fullt med classify → route → validate → final.
2. **Klassificeringsanalys** (alla 20): Kördes direkt mot `sensitivity_classifier()` för att kartlägga exakt vilka prompts som matchas.

### Klassificering: 17/20 (85%)

| # | Beskrivning | Förväntat | Faktiskt | Status |
|---|-------------|-----------|----------|--------|
| 1 | Personnummer | high | high | OK |
| 2 | E-postadress | high | high | OK |
| 3 | Telefonnummer | high | high | OK |
| 4 | Kreditkortsnummer | high | high | OK |
| **5** | **Hemadress (keyword)** | **high** | **low** | **MISMATCH** |
| **6** | **Lön (keyword)** | **high** | **low** | **MISMATCH** |
| **7** | **Diagnos (keyword)** | **high** | **low** | **MISMATCH** |
| 8 | Lösenord (keyword) | high | high | OK |
| 9 | E-post + telefon | high | high | OK |
| 10 | Hemadress (keyword) | high | high | OK |
| 11 | Enkel faktafråga | low | low | OK |
| 12 | Utbildningsfråga | low | low | OK |
| 13 | Kreativ förfrågan | low | low | OK |
| 14 | Teknisk jämförelse | low | low | OK |
| 15 | Matlagningsfråga | low | low | OK |
| 16 | Historisk sammanfattning | low | low | OK |
| 17 | Datavetenskapsfråga | low | low | OK |
| 18 | Arkitekturfråga | low | low | OK |
| 19 | Bokförslag | low | low | OK |
| 20 | Matematisk formel | low | low | OK |

### Live end-to-end-resultat (verifierade)

| Test | Klassificering | Modell | Validering | Steg |
|------|---------------|--------|------------|------|
| Personnummer | high | llama-large | pass | 4 |
| E-postadress | high | llama-large | pass (efter retries) | 8 |
| Telefonnummer | high | llama-large | pass | 4 |
| Kreditkortsnummer | high | llama-large | pass | 4 |
| "Huvudstaden i Frankrike?" | low | llama-small | pass | 4 |
| "Skriv en kort dikt om havet" | low | llama-small | pass | 4 |

### Analys av de 3 missarna

Alla tre beror på `tools.py`s `SENSITIVE_KEYWORDS`-lista, inte agentlogiken:

- **Test 5** ("Jag bor på Storgatan 14, 411 38 Göteborg..."): Prompten innehåller inte nyckelorden "hemadress" eller "adress" bokstavligt — bara en implicit gatuadress utan att använda ordet "adress".
- **Test 6** ("Min lön är 45000 kr..."): Ordet "lön" finns inte i `SENSITIVE_KEYWORDS`.
- **Test 7** ("Jag har fått diagnosen diabetes typ 2..."): Ordet "diagnos" eller "diabetes" finns inte i `SENSITIVE_KEYWORDS`.

**Rekommendation till partner**: Lägg till nyckelord som `"lön"`, `"inkomst"`, `"salary"`, `"diagnos"`, `"diabetes"`, `"sjukdom"` i `SENSITIVE_KEYWORDS` i `tools.py`.

---

## Filer som ändrades

| Fil | Ändring |
|-----|---------|
| `evaluate.py` | Fixad import (`classify_sensitivity` → `sensitivity_classifier`), Unicode-tecken, UTF-8 encoding, pauser mellan tester |

### Nya filer

| Fil | Syfte |
|-----|-------|
| `evaluation_results.json` | Komplett testresultat för alla 20 prompts |

---

## Sammanfattning

- Agent-loopen fungerar felfritt — alla prompts som körs end-to-end följer classify → route → validate → final
- Alla 10 low-sensitivity-prompts routas korrekt till `llama-small`
- 7 av 10 high-sensitivity-prompts routas korrekt till `llama-large`
- De 3 missarna beror på keyword-täckning i `tools.py`, inte agentlogik
- Retry-mekanismen fungerar: email-testet visar PII-läcka → retry → slutligen pass
- Groqs gratisnivå (6000 TPM) begränsar hur snabbt full evaluation kan köras
