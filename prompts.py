"""
System prompt för orchestrator-agenten och testprompts för evaluation.
"""

# ============================================================
# System prompt
# ============================================================
# Detta styr hur orchestrator-agenten beter sig.
# Den förklarar vilka tools som finns och vad agenten ska göra.
# ============================================================

SYSTEM_PROMPT = """You are a Prompt Sensitivity Router agent. You follow a strict 3-step pipeline and then return a final answer. You respond with ONLY a single JSON object per step — no extra text, no markdown.

PIPELINE (follow this exact order):
  Step 1 → call classify_sensitivity
  Step 2 → call route_to_model (using the level from step 1)
  Step 3 → call validate_response (using the response from step 2)
  Step 4 → if validation status is "pass": return action "final"
            if validation status is "fail": retry route_to_model (max 2 retries), then validate again

TOOLS:

classify_sensitivity — classifies the prompt for PII.
  Input:  {"prompt": "<the user prompt>"}
  Output: {"level": "high"|"low", "matches": [...], "details": "..."}

route_to_model — sends the prompt to the appropriate LLM.
  Input:  {"prompt": "<the user prompt>", "level": "high"|"low"}
  Output: {"model_used": "...", "response": "...", "routing_reason": "..."}

validate_response — checks quality of the model response.
  Input:  {"response": "<model response>", "original_prompt": "<the user prompt>"}
  Output: {"status": "pass"|"fail", "reason": "..."}

RESPONSE FORMAT — every response must be exactly one JSON object:

To call a tool:
{"action": "tool", "tool_name": "<name>", "tool_input": {<args>}}

To return the final answer (MUST do this once validate_response returns "pass"):
{"action": "final", "final_answer": "<the validated model response>", "routing_summary": {"sensitivity_level": "<high or low>", "model_used": "<model name>", "validation_status": "pass", "retries": 0}}

CRITICAL RULES:
- Each tool is called AT MOST ONCE per pipeline pass (classify once, route once, validate once).
- As soon as validate_response returns status "pass", you MUST return action "final" on the very next step. Do NOT call validate_response again after it passes.
- Never skip classify_sensitivity.
- Never output anything other than a single JSON object.
"""


# ============================================================
# Testprompts
# ============================================================
# Används i evaluate.py. Varje prompt har en förväntad nivå
# så vi kan mäta routing accuracy.
# ============================================================

TEST_PROMPTS = [
    # --- HIGH sensitivity (innehåller PII) ---
    {
        "prompt": "Mitt personnummer är 199505151234 och jag behöver hjälp med min deklaration.",
        "expected_level": "high",
        "description": "Innehåller personnummer"
    },
    {
        "prompt": "Skicka fakturan till anna.svensson@gmail.com tack.",
        "expected_level": "high",
        "description": "Innehåller e-postadress"
    },
    {
        "prompt": "Ring mig på 0701234567 så diskuterar vi kontraktet.",
        "expected_level": "high",
        "description": "Innehåller telefonnummer"
    },
    {
        "prompt": "Mitt kreditkortsnummer är 4532-1234-5678-9012, kan du kolla saldot?",
        "expected_level": "high",
        "description": "Innehåller kreditkortsnummer"
    },
    {
        "prompt": "Jag bor på Storgatan 14, 411 38 Göteborg. Vad finns det för restauranger nära mig?",
        "expected_level": "high",
        "description": "Innehåller hemadress (keyword)"
    },
    {
        "prompt": "Min lön är 45000 kr i månaden, hur mycket skatt betalar jag?",
        "expected_level": "high",
        "description": "Innehåller lön (keyword)"
    },
    {
        "prompt": "Jag har fått diagnosen diabetes typ 2, vilka mediciner rekommenderas?",
        "expected_level": "high",
        "description": "Innehåller medicinsk diagnos (keyword)"
    },
    {
        "prompt": "Mitt lösenord till banken fungerar inte, kan du hjälpa mig?",
        "expected_level": "high",
        "description": "Nämner lösenord (keyword)"
    },
    {
        "prompt": "Kontakta mig via erik.berg@company.se eller på +46 70 123 45 67.",
        "expected_level": "high",
        "description": "Innehåller både e-post och telefonnummer"
    },
    {
        "prompt": "Jag behöver uppdatera min hemadress i systemet till Björkvägen 7.",
        "expected_level": "high",
        "description": "Innehåller hemadress (keyword)"
    },

    # --- LOW sensitivity (ingen PII) ---
    {
        "prompt": "Vad är huvudstaden i Frankrike?",
        "expected_level": "low",
        "description": "Enkel faktafråga"
    },
    {
        "prompt": "Förklara hur fotosyntesen fungerar.",
        "expected_level": "low",
        "description": "Utbildningsfråga"
    },
    {
        "prompt": "Skriv en kort dikt om havet.",
        "expected_level": "low",
        "description": "Kreativ förfrågan"
    },
    {
        "prompt": "Vad är skillnaden mellan Python och JavaScript?",
        "expected_level": "low",
        "description": "Teknisk jämförelse"
    },
    {
        "prompt": "Ge mig ett recept på kanelbullar.",
        "expected_level": "low",
        "description": "Matlagningsfråga"
    },
    {
        "prompt": "Sammanfatta andra världskriget på tre meningar.",
        "expected_level": "low",
        "description": "Historisk sammanfattning"
    },
    {
        "prompt": "Hur fungerar quicksort-algoritmen?",
        "expected_level": "low",
        "description": "Datavetenskapsfråga"
    },
    {
        "prompt": "Vad är fördelen med att använda microservices?",
        "expected_level": "low",
        "description": "Arkitekturfråga"
    },
    {
        "prompt": "Rekommendera tre bra böcker om maskininlärning.",
        "expected_level": "low",
        "description": "Bokförslag"
    },
    {
        "prompt": "Hur konverterar man Celsius till Fahrenheit?",
        "expected_level": "low",
        "description": "Matematisk formel"
    },
]