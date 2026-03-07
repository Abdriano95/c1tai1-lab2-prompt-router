# Session Log — Debugging & Fixing Prompt Sensitivity Router

**Datum:** 2026-03-07

---

## Översikt

Hela agent-loopen (`agent.py`) och system-prompten (`prompts.py`) debuggades och fixades så att flödet **classify → route → validate → final** fungerar end-to-end. Totalt identifierades och åtgärdades **6 problem**. Filen `tools.py` (partnerns fil) rördes inte.

---

## Problem 1: Tool-namn mismatch (kritiskt)

### Symptom
Agenten körde alla 10 steg och avslutade med "max steps reached". Varje steg gav:
```
[Step X] ERROR: Unknown tool 'classify_sensitivity'
```

### Orsak
System-prompten instruerade LLM:en att anropa `classify_sensitivity`, men TOOLS-dictionaryn i `agent.py` registrerade funktionen under nyckeln `sensitivity_classifier`. LLM:en gjorde rätt enligt sin instruktion, men agent-loopen hittade aldrig en matchande funktion.

### Fix
Bytte nyckeln i TOOLS från `sensitivity_classifier` till `classify_sensitivity` (rad 44 i `agent.py`):

```python
# Före
TOOLS = {
    "sensitivity_classifier": lambda args: sensitivity_classifier(args["prompt"]),
    ...
}

# Efter
TOOLS = {
    "classify_sensitivity": lambda args: sensitivity_classifier(args["prompt"]),
    ...
}
```

### Varför just denna lösning
Att byta nyckelnamnet i TOOLS-dictionaryn är det enklaste. Alternativet — byta i system-prompten — hade också fungerat, men tool-registryt är en intern implementation detail medan system-prompten redan använde det mer beskrivande namnet `classify_sensitivity`.

---

## Problem 2: LLM:en loopade efter lyckad validering

### Symptom
Steg 1–3 fungerade korrekt (classify → route → validate), men sedan anropade LLM:en `validate_response` om och om igen istället för att returnera `"action": "final"`. Agenten nådde max_steps utan att någonsin avsluta.

### Orsak
Den ursprungliga system-prompten var för vag. Den sa bara "If validation fails, retry" men förklarade aldrig explicit att agenten **måste** returnera `"final"` direkt efter att validering ger `"pass"`. Llama 3.1 8B (orchestrator-modellen) behöver mer explicita instruktioner än större modeller.

### Fix — Del A: Omskriven system-prompt (`prompts.py`)
System-prompten skrevs om från en löst formulerad lista till en strikt pipeline-specifikation:

```
PIPELINE (follow this exact order):
  Step 1 → call classify_sensitivity
  Step 2 → call route_to_model (using the level from step 1)
  Step 3 → call validate_response (using the response from step 2)
  Step 4 → if validation status is "pass": return action "final"
            if validation status is "fail": retry route_to_model (max 2 retries)
```

Lade också till regeln:
```
As soon as validate_response returns status "pass", you MUST return action "final"
on the very next step. Do NOT call validate_response again after it passes.
```

### Fix — Del B: Dynamisk "next hint" i state-prompten (`agent.py`)
Lade till funktionen `_derive_next_hint()` som analyserar trajectory och genererar en explicit instruktion till LLM:en baserat på vad som hänt hittills:

- Om inget tool anropats → `"NEXT: call classify_sensitivity."`
- Om classify klar men inte route → `"NEXT: call route_to_model with level=\"high\"."`
- Om route klar men inte validate → `"NEXT: call validate_response..."`
- Om validate returnerade pass → `'NEXT: validation passed. You MUST return {"action": "final", ...} NOW.'`
- Om validate returnerade fail → `"NEXT: validation failed. Retry route_to_model..."`

### Varför just denna lösning
En 8B-modell med temperature=0 är pålitlig på att följa format, men dålig på att härleda implicit logik från en lång trajectory-dump. Genom att ge den en explicit "NEXT"-instruktion varje steg behöver den inte resonera om vad som bör hända — den bara följer instruktionen. Detta håller arkitekturen "agentic" (LLM:en fattar fortfarande beslutet) samtidigt som den får tillräcklig vägledning.

---

## Problem 3: Ingen hantering av rate limits

### Symptom
Agenten kraschade med `groq.RateLimitError: Error code: 429` efter för många API-anrop i snabb följd. Groqs gratisnivå har en gräns på 6000 tokens per minut.

### Orsak
Ingen retry-logik fanns. Varje LLM-anrop gjordes en gång och om det misslyckades kraschade hela programmet med ett ohanterat undantag.

### Fix
La till retry med exponentiell backoff runt orchestrator-anropet:

```python
for attempt in range(3):
    try:
        response = orchestrator_llm.invoke([...])
        break
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            wait = (attempt + 1) * 10  # 10s, 20s, 30s
            time.sleep(wait)
        else:
            raise
```

La också till en 2-sekunders paus mellan varje steg i agent-loopen (`time.sleep(2)`) för att vara snällare mot rate limits generellt.

### Varför just denna lösning
Exponentiell backoff är standardmönstret för rate limits. 3 försök med 10/20/30 sekunders väntan ger totalt 60 sekunders buffert, vilket täcker Groqs "try again in X seconds"-meddelande. Den lilla 2-sekunders pausen mellan steg förhindrar att vi överhuvudtaget når gränsen i normalfallet.

> **Uppdatering:** Denna rate limit-hantering togs senare bort efter uppgradering till en betald Groq dev-key som inte har samma begränsningar. Koden gör nu ett direkt `invoke()`-anrop utan retry eller pauser.

---

## Problem 4: JSON-parsning misslyckas på lång output

### Symptom
När modellsvaret var långt (t.ex. e-post-scenariot med detaljerade instruktioner) producerade LLM:en JSON som var avklippt — den sista `}` saknades. `json.loads()` gav `JSONDecodeError` och steget räknades som fel.

### Orsak
LLM:en försökte eka hela det långa modellsvaret inuti sin JSON-output men nådde sin output-token-gräns innan den hann stänga JSON-objektet. Dessutom: trajectory-dumpen i state-prompten inkluderade de fulla modellsvaren, vilket blåste upp LLM:ens input-kontext och lämnade ännu mindre utrymme för output.

### Fix — Del A: Ökad max_tokens
Satte `max_tokens=2048` på orchestrator-LLM:en (tidigare var det defaultvärdet, som kan vara lägre).

### Fix — Del B: Kompakt trajectory (`_compact_trajectory`)
Skapade en funktion som bygger en token-effektiv version av trajectory för LLM-kontexten. Specifikt trunkeras `route_to_model`-resultat till 300 tecken:

```python
if entry["tool_name"] == "route_to_model":
    c["result"] = {
        "model_used": result.get("model_used"),
        "response": result.get("response", "")[:300],
        "success": result.get("success"),
    }
```

Den fulla trajectory sparas fortfarande internt — det är bara LLM:ens vy som trunkeras.

### Fix — Del C: Markdown-stripping
La till regex som strippar markdown-kodblock (```` ```json ... ``` ````) från LLM-outputen innan JSON-parsning, ifall modellen wrappar sin JSON i kodblock.

### Fix — Del D: JSON-fallback vid parse-fel
Om JSON-parsning misslyckas, analyseras vilken tool som anropades senast:
- Om senaste tool var `route_to_model` → auto-konstruera ett `validate_response`-anrop med korrekta argument
- Om senaste tool var `validate_response` med status "pass" → auto-konstruera ett "final"-svar
- Annars → logga felet och fortsätt

### Varför just denna lösning
Att minska input-storleken (kompakt trajectory) och öka output-utrymmet (max_tokens) löser grundorsaken. JSON-fallbacken är ett säkerhetsnät som hanterar de fall som slipper igenom. Att auto-konstruera rätt tool-anrop baserat på pipeline-positionen är säkert eftersom flödet är deterministiskt: efter route kommer alltid validate.

---

## Problem 5: Validering av trunkerade svar

### Symptom
LLM:en trunkerade modellsvaret när den ekade det i `validate_response`-anropets JSON. T.ex. klipptes en e-postadress från `anna.svensson@gmail.com` till `anna.sven`, varpå PII-detektionen missade läckan och validering passerade felaktigt.

### Orsak
Samma token-limit-problem som #4, men med en allvarligare konsekvens: validering kördes på ett ofullständigt svar, vilket innebar att PII-mönster som fanns i det fulla svaret aldrig matchades.

### Fix
Agent-loopen auto-fyller nu `validate_response`-argumenten från det faktiska lagrade route-resultatet, oavsett vad LLM:en skickar:

```python
if tool_name == "validate_response":
    latest_route = next(
        (t["tool_result"] for t in reversed(trajectory)
         if t.get("tool_name") == "route_to_model"), None
    )
    if latest_route:
        tool_input["response"] = latest_route.get("response", "")
        tool_input["original_prompt"] = user_prompt
```

Samma princip för "final"-steget: `final_answer` hämtas alltid från det faktiska route-resultatet istället för LLM:ens (potentiellt trunkerade) version.

### Varför just denna lösning
Det är onödigt att låta LLM:en eka hela svaret bara för att skicka det vidare. Agent-loopen HAR redan det korrekta svaret i sin trajectory. Genom att använda det direkt elimineras alla trunkeringsproblem och vi sparar tokens.

---

## Problem 6: Max retries avslutade inte rent

### Symptom
Efter 3 misslyckade valideringsrundor (t.ex. e-post som alltid läcker PII) behövde agenten ytterligare ett LLM-anrop bara för att säga "final". Det anropet hann ofta inte genomföras p.g.a. rate limits, och agenten dog tyst.

### Orsak
Det fanns ingen logik i agent-loopen för att avsluta automatiskt när retry-gränsen nåtts. Logiken förlitade sig helt på att LLM:en skulle förstå från trajectory + hint att den skulle säga "final" — men rate limits förhindrade det sista LLM-anropet.

### Fix
La till auto-final-logik direkt i agent-loopen. Efter varje `validate_response` som ger "fail" kontrolleras antalet route_to_model-anrop. Om det är ≥ 3 returneras final direkt utan ytterligare LLM-anrop:

```python
if (tool_name == "validate_response"
        and tool_result.get("status") == "fail"):
    route_count = sum(
        1 for t in trajectory if t.get("tool_name") == "route_to_model"
    )
    if route_count >= 3:
        return {
            "final_answer": latest_route.get("response", "No answer"),
            "routing_summary": {
                "validation_status": "fail",
                "retries": route_count - 1,
                ...
            },
            ...
        }
```

### Varför just denna lösning
Att lägga avslutningslogiken i agent-loopen istället för att förlita sig på LLM:en för den sista åtgärden är mer robust. Det sparar ett API-anrop och eliminerar risken att rate limits eller token-begränsningar förhindrar avslutning. Routing-sammanfattningen sätts med `validation_status: "fail"` så att det tydligt framgår att svaret inte klarade validering.

---

## Testresultat

| Prompt | Känslighetsnivå | Modell | Validering | Steg |
|--------|-----------------|--------|------------|------|
| Personnummer (PII) | high | llama-large | pass | 4 |
| "Huvudstaden i Frankrike?" | low | llama-small | pass | 4 |
| "Skicka fakturan till anna.svensson@gmail.com" | high | llama-large | pass (efter retries) | 8 |
| "Skriv en kort dikt om havet" | low | llama-small | pass | 4 |

---

## Filer som ändrades

| Fil | Ändring |
|-----|---------|
| `agent.py` | Tool-registrering, rate limit retry, JSON-fallback, kompakt trajectory, auto-fill validate-args, auto-final vid max retries |
| `prompts.py` | Omskriven SYSTEM_PROMPT med explicit pipeline och strikta regler |

**`tools.py` ändrades INTE** (partnerns fil).

---

## Sammanfattning

Grundproblemet var att agenten aldrig kunde slutföra ett enda flöde. Efter fixarna klarar den:
- **Happy path** (4 steg): classify → route → validate (pass) → final
- **Retry path** (6–8 steg): classify → route → validate (fail) → retry route → validate → ... → final
- **Max retries exhausted**: avslutar rent med `validation_status: "fail"`
- **Rate limits**: hanteras med retry + backoff
- **Trunkerad LLM-output**: hanteras med fallback-logik och auto-fill från trajectory
