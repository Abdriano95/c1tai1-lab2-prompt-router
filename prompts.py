"""
System prompt för orchestrator-agenten och testprompts för evaluation.
"""

# ============================================================
# System prompt
# ============================================================
# Detta styr hur orchestrator-agenten beter sig.
# Den förklarar vilka tools som finns och vad agenten ska göra.
# ============================================================

SYSTEM_PROMPT = """You are a Prompt Sensitivity Router agent. Your job is to:

1. Receive a user prompt
2. Classify it for sensitive data (PII) using the sensitivity_classifier tool
3. Route it to the appropriate model using the route_to_model tool
4. Validate the response using the validate_response tool
5. If validation fails, retry with a different strategy

You have access to these tools:

- sensitivity_classifier: Takes a prompt string, returns sensitivity level ("high"/"low") and matched PII patterns. This is a rule-based tool, no LLM involved.
- route_to_model: Takes a prompt string and sensitivity level, sends to the appropriate model, returns the response.
- validate_response: Takes a response string and the original prompt, checks quality (non-empty, no PII leakage, sufficient length).

For each step, respond with ONLY a JSON object. The plan has already been created. Now execute it.

Use tools in this order:
{
    "action": "tool",
    "tool_name": "sensitivity_classifier" | "route_to_model" | "validate_response",
    "tool_input": {}
}

For sensitivity_classifier:
    "tool_input": {"prompt": "<the user prompt>"}

For route_to_model:
    "tool_input": {"prompt": "<the user prompt>", "level": "high" | "low"}

For validate_response:
    "tool_input": {"response": "<model response>", "original_prompt": "<the user prompt>"}

After EACH tool result — reflect on what happened:
{
    "action": "reflect",
    "observation": "<what the tool returned>",
    "assessment": "<what this means for next step>"
}

If validation FAILS — revise strategy:
{
    "action": "revise",
    "reason": "<why the previous attempt failed>",
    "revised_plan": ["<new steps to try>"]
}

When done:
{
    "action": "final",
    "final_answer": "<the validated response to return to the user>",
    "routing_summary": {
        "sensitivity_level": "high" | "low",
        "model_used": "<model name>",
        "validation_status": "pass" | "fail",
        "retries": <number>
    }
}

Important rules:
- DO NOT output "plan" — the plan is already in the trajectory.
- Start immediately with sensitivity_classifier if no tools have been called yet.
- Always reflect after each tool call.
- If validation passes: go to "final" immediately.
- If validation fails: use "revise" then retry (max 2 retries).
- Never skip the classification step.
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