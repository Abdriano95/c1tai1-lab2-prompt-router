# Ändringslogg: mask_pii som tool

**Datum:** 2025-03-20  
**Ändringstyp:** Refaktorering / funktionsutökning  
**Omfattning:** 4 filer ändrade, 1 ny testsektion

---

## Sammanfattning

Metoden `mask_pii` har konverterats från en implicit intern funktion i agent-loopen till ett explicit anropbart tool som orchestrator-LLM:en kan använda vid eskalering. Detta gör PII-maskningen ett medvetet steg i agentens beslutsflöde i stället för dold logik.

---

## Bakgrund

**Tidigare:** Vid eskalering (när validering misslyckades för en prompt med hög känslighet) anropade agenten automatiskt `mask_pii(user_prompt)` innan `route_to_model` kördes. LLM:en behövde inte veta om maskningen — den skedde implicit i controller-koden.

**Nu:** LLM:en anropar explicit `mask_pii` som ett tool innan `route_to_model` vid eskalering. Agenten hämtar den maskade texten från trajectory och injicerar den i nästa route-anrop. Om LLM:en hoppar över steget finns en fallback som anropar `mask_pii` automatiskt.

---

## Tekniska ändringar

### 1. tools.py
- **Tillagt:** `PII_LABELS` (flyttat från agent.py) — mappning mellan PII-typer och platshållare
- **Tillagt:** `mask_pii(text: str) -> dict` — returnerar `{"masked_text": str}` med PII ersatt av platshållare (t.ex. `[PERSONNUMMER]`, `[EMAIL]`)
- **Exporterat:** `mask_pii` för användning i agent och tester

### 2. agent.py
- **Borttaget:** Lokal `mask_pii`-funktion och `PII_LABELS`
- **Tillagt:** Import av `mask_pii` från tools
- **Tillagt:** `"mask_pii"` i TOOLS-registret: `lambda args: mask_pii(args["text"])`
- **Uppdaterat:** `_derive_next_hint()` — vid eskalering: "call mask_pii first"; när senaste tool var mask_pii: "call route_to_model with level='low'"
- **Uppdaterat:** route_to_model-logik — vid eskalering hämtas maskad text från senaste `mask_pii`-resultat i trajectory; fallback till `mask_pii(user_prompt)` om inget finns
- **Uppdaterat:** `_compact_trajectory()` — visar trunkerat `mask_pii`-resultat (300 tecken) i LLM-kontexten
- **Tillagt:** JSON-fallback — om LLM returnerar ogiltig JSON efter `mask_pii`, auto-anropar agenten `route_to_model` med maskad prompt

### 3. prompts.py
- **Tillagt:** `mask_pii` i TOOLS-sektionen i SYSTEM_PROMPT
- **Uppdaterat:** Pipeline-steg 4–7 — vid fail + high: anropa `mask_pii` först, sedan `route_to_model` med level="low"
- **Uppdaterat:** CRITICAL RULES — "call mask_pii first, then route_to_model" vid eskalering

### 4. tests/test_tools.py
- **Tillagt:** Import av `mask_pii`
- **Tillagt:** Testsektion för `mask_pii` med 7 testfall:
  - Personnummer → `[PERSONNUMMER]`
  - E-post → `[EMAIL]`
  - Telefonnummer → `[TELEFONNUMMER]`
  - Kreditkort → `[KREDITKORT]`
  - IP-adress → `[IP-ADRESS]`
  - Postnummer → `[POSTNUMMER]`
  - Text utan PII → oförändrad

### 5. README.md
- Uppdaterad arkitekturdiagram med `mask_pii` som fjärde tool
- Uppdaterad mermaid-flowchart: MASK → Tool: mask_pii
- Ny sektion "mask_pii" i Verktygsbeskrivningar
- Uppdaterad route_to_model-beskrivning
- Eskaleringsväg: 6 → 7 steg (mask_pii som explicit steg)
- Uppdaterad tillståndshantering och filstruktur
- Korrigerad modellreferens: llama-3.3-70b-versatile (molnmodell)

---

## Flödesändring

**Eskalering — före:**
```
validate (fail) → [agent maskar automatiskt] → route_to_model (maskad) → validate → final
```

**Eskalering — efter:**
```
validate (fail) → mask_pii [LLM anropar] → route_to_model (maskad) → validate → final
```

---

## Verifiering

- **test_tools.py:** Alla tester passerar, inklusive nya mask_pii-tester
- **evaluate.py:** 20/20 prompts — 100 % routing accuracy, 100 % validation passes
- **Manuell test:** E-postadress-prompt som triggar eskalering — mask_pii anropas, [EMAIL] skickas till molnmodell, validering passerar

---

## Risker och fallback

- **LLM hoppar över mask_pii:** Agenten anropar `mask_pii(user_prompt)` automatiskt vid eskalering om inget mask_pii-resultat finns i trajectory
- **Extra steg:** Eskalering kräver nu 7 steg i stället för 6 (ett steg för mask_pii-anropet)
