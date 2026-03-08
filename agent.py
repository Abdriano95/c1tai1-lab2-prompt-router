"""
Controller-loop för Prompt Sensitivity Router.
Baserad på minimal_agent.py-mönstret från workshoppen.

Orchestrator-LLM:en (Groq) bestämmer vilka tools att anropa.
Tools (i tools.py) utför arbetet och returnerar resultat.
Loopen kör tills agenten säger "final" eller max_steps nås.
"""

import json
import os
import re
from typing import Any
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from tools import classify_sensitivity, route_to_model, validate_response, PII_PATTERNS
from prompts import SYSTEM_PROMPT

load_dotenv()

# ============================================================
# Konfiguration
# ============================================================

MAX_STEPS = 10  # Säkerhetsgräns — agenten stoppas om den inte avslutar

# Orchestrator-modellen — bestämmer vilka tools att anropa
orchestrator_llm = ChatGroq(
    model="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY") or "",
    temperature=0,
    max_tokens=2048,
)

# ============================================================
# Tool-registry
# ============================================================
# Mappar tool-namn (som agenten refererar till) till funktioner.
# Agenten returnerar JSON med "tool_name" och "tool_input",
# och loopen anropar rätt funktion baserat på detta.
# ============================================================

TOOLS = {
    "classify_sensitivity": lambda args: classify_sensitivity(args["prompt"]),
    "route_to_model": lambda args: route_to_model(args["prompt"], args["level"]),
    "validate_response": lambda args: validate_response(args["response"], args["original_prompt"]),
}

PII_LABELS = {
    "personnummer": "[PERSONNUMMER]",
    "epost": "[EMAIL]",
    "telefonnummer": "[TELEFONNUMMER]",
    "kreditkort": "[KREDITKORT]",
    "ip_adress": "[IP-ADRESS]",
    "postnummer": "[POSTNUMMER]",
}

def mask_pii(text: str) -> str:
    """Ersätter PII-matchningar med säkra platshållare så modellen aldrig ser rå känslig data."""
    masked = text
    for pattern_name, pattern in PII_PATTERNS.items():
        label = PII_LABELS.get(pattern_name, "[REDACTED]")
        masked = re.sub(pattern, label, masked, flags=re.IGNORECASE)
    return masked


# ============================================================
# State builder
# ============================================================
# Bygger prompten som orchestrator-LLM:en ser varje steg.
# Inkluderar: den ursprungliga prompten, stegräknare, och
# hela trajectory (allt som hänt hittills).
# ============================================================

def _derive_next_hint(trajectory: list[dict[str, Any]]) -> str:
    """Analyserar trajectory och ger LLM:en en ledtråd om vad nästa steg ska vara."""
    tool_entries = [t for t in trajectory if t.get("action") == "tool"]
    last_tool = tool_entries[-1] if tool_entries else None
    tools_called = [t["tool_name"] for t in tool_entries]

    classify_result = next(
        (t["tool_result"] for t in tool_entries
         if t["tool_name"] == "classify_sensitivity"), None
    )

    def _latest_route_result():
        for t in reversed(tool_entries):
            if t["tool_name"] == "route_to_model":
                return t["tool_result"]
        return {}

    if not last_tool or "classify_sensitivity" not in tools_called:
        return "NEXT: call classify_sensitivity."

    if last_tool["tool_name"] == "classify_sensitivity":
        level = classify_result.get("level", "high") if classify_result else "high"
        return f'NEXT: call route_to_model with level="{level}".'

    if last_tool["tool_name"] == "route_to_model":
        route_res = _latest_route_result()
        model_response = route_res.get("response", "")
        return (
            "NEXT: call validate_response with the model response.\n"
            f"Full model response to validate: {model_response}"
        )

    if last_tool["tool_name"] == "validate_response":
        status = last_tool.get("tool_result", {}).get("status")
        if status == "pass":
            route_res = _latest_route_result()
            model_response = route_res.get("response", "")
            model_used = route_res.get("model_used", "unknown")
            level = classify_result.get("level", "unknown") if classify_result else "unknown"
            return (
                'NEXT: validation passed. You MUST return {"action": "final", ...} NOW.\n'
                f"Use this as final_answer: {model_response}\n"
                f"model_used: {model_used}\n"
                f"sensitivity_level: {level}"
            )
        else:
            route_count = sum(1 for t in tool_entries if t["tool_name"] == "route_to_model")
            orig_level = classify_result.get("level", "low") if classify_result else "low"

            if route_count >= 2:
                route_res = _latest_route_result()
                return (
                    'NEXT: max retries reached. Return {"action": "final", ...} now.\n'
                    f"Use this as final_answer: {route_res.get('response', '')}\n"
                    f"validation_status: fail"
                )

            if orig_level == "high" and route_count == 1:
                return (
                    'NEXT: validation failed. Escalate: call route_to_model with level="low" '
                    "(PII will be masked automatically, cloud model gets a safe prompt)."
                )

            return 'NEXT: validation failed. Retry route_to_model with the same level.'

    return "NEXT: choose the appropriate action."


def _compact_trajectory(trajectory: list[dict[str, Any]]) -> list[dict]:
    """Skapar en tokeneffektiv version av trajectory för LLM-kontexten."""
    compact = []
    for entry in trajectory:
        c = {"step": entry["step"]}
        if entry.get("error"):
            c["error"] = entry["error"]
        elif entry.get("action") == "tool":
            c["tool"] = entry["tool_name"]
            result = entry.get("tool_result", {})
            if entry["tool_name"] == "route_to_model":
                c["result"] = {
                    "model_used": result.get("model_used"),
                    "response": result.get("response", "")[:300],
                    "success": result.get("success"),
                }
            else:
                c["result"] = result
        elif entry.get("action") == "final":
            c["action"] = "final"
        compact.append(c)
    return compact


def build_state_prompt(user_prompt: str, trajectory: list[dict[str, Any]], step: int) -> str:
    hint = _derive_next_hint(trajectory)
    compact = _compact_trajectory(trajectory)
    return (
        f"User prompt to process: {user_prompt}\n"
        f"Step: {step}/{MAX_STEPS}\n"
        f"Trajectory so far: {json.dumps(compact, ensure_ascii=False)}\n"
        f"{hint}"
    )


# ============================================================
# Agent loop
# ============================================================
# Kärnan i systemet. Loopar: bygg state → LLM beslutar →
# kör tool → spara resultat → repeat.
#
# Stoppar när:
# 1. Agenten returnerar action: "final"
# 2. max_steps nås (säkerhetsgräns)
# ============================================================

def run_agent(user_prompt: str) -> dict:
    """
    Kör hela agent-loopen för en enda prompt.

    Args:
        user_prompt: Prompten från användaren.

    Returns:
        dict med slutresultat, routing-info, och full trajectory.
    """
    trajectory = []

    for step in range(1, MAX_STEPS + 1):
        # --- 1. Bygg state-prompt ---
        state_prompt = build_state_prompt(user_prompt, trajectory, step)

        # --- 2. Skicka till orchestrator-LLM ---
        response = orchestrator_llm.invoke([
            ("system", SYSTEM_PROMPT),
            ("human", state_prompt)
        ])
        raw_output = response.content.strip()

        # --- 3. Logga rå output ---
        print(f"\n[Step {step}] Raw LLM output:")
        print(raw_output)

        # --- 4. Parsa JSON (strippar eventuella markdown-kodblock) ---
        cleaned = raw_output.strip()
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
        if md_match:
            cleaned = md_match.group(1).strip()

        try:
            decision = json.loads(cleaned)
        except json.JSONDecodeError:
            last_tool_entry = next(
                (t for t in reversed(trajectory) if t.get("action") == "tool"), None
            )
            if last_tool_entry and last_tool_entry["tool_name"] == "route_to_model":
                print(f"[Step {step}] JSON-parsning misslyckades — anropar validate_response automatiskt")
                route_res = last_tool_entry["tool_result"]
                decision = {
                    "action": "tool",
                    "tool_name": "validate_response",
                    "tool_input": {
                        "response": route_res.get("response", ""),
                        "original_prompt": user_prompt,
                    }
                }
            elif last_tool_entry and last_tool_entry["tool_name"] == "validate_response":
                val_status = last_tool_entry.get("tool_result", {}).get("status")
                if val_status == "pass":
                    latest_route = next(
                        (t["tool_result"] for t in reversed(trajectory)
                         if t.get("tool_name") == "route_to_model"), {}
                    )
                    print(f"[Step {step}] JSON-parsning misslyckades — konstruerar final-svar automatiskt")
                    decision = {
                        "action": "final",
                        "final_answer": latest_route.get("response", "No answer"),
                        "routing_summary": {
                            "sensitivity_level": next(
                                (t["tool_result"].get("level") for t in trajectory
                                 if t.get("tool_name") == "classify_sensitivity"), "unknown"),
                            "model_used": latest_route.get("model_used", "unknown"),
                            "validation_status": "pass",
                            "retries": sum(1 for t in trajectory
                                           if t.get("tool_name") == "route_to_model") - 1,
                        }
                    }
                else:
                    print(f"[Step {step}] FEL: Ogiltig JSON")
                    trajectory.append({
                        "step": step, "error": "invalid_json",
                        "raw_output": raw_output[:200]
                    })
                    continue
            else:
                print(f"[Step {step}] FEL: Ogiltig JSON")
                trajectory.append({
                    "step": step, "error": "invalid_json",
                    "raw_output": raw_output[:200]
                })
                continue

        action = decision.get("action")

        # --- 5a. "final" — agenten är klar ---
        if action == "final":
            print(f"\n[Step {step}] FINAL ANSWER reached.")
            latest_route = next(
                (t["tool_result"] for t in reversed(trajectory)
                 if t.get("tool_name") == "route_to_model"), None
            )
            final_answer = (
                latest_route.get("response", "") if latest_route
                else decision.get("final_answer", "No answer provided")
            )
            routing_summary = decision.get("routing_summary", {})
            if latest_route:
                routing_summary.setdefault("model_used", latest_route.get("model_used"))

            trajectory.append({
                "step": step,
                "action": "final",
                "decision": decision
            })
            return {
                "final_answer": final_answer,
                "routing_summary": routing_summary,
                "trajectory": trajectory,
                "steps_taken": step
            }

        # --- 5b. "tool" — kör rätt tool ---
        if action == "tool":
            tool_name = decision.get("tool_name")
            tool_input = decision.get("tool_input", {})

            if tool_name not in TOOLS:
                print(f"[Step {step}] FEL: Okänt tool '{tool_name}'")
                trajectory.append({
                    "step": step,
                    "error": f"unknown_tool: {tool_name}",
                    "decision": decision
                })
                continue

            if tool_name == "route_to_model":
                route_count = sum(
                    1 for t in trajectory if t.get("tool_name") == "route_to_model"
                )
                classify_level = next(
                    (t["tool_result"].get("level") for t in trajectory
                     if t.get("tool_name") == "classify_sensitivity"), "low"
                )
                if classify_level == "high" and route_count > 0:
                    tool_input["prompt"] = mask_pii(user_prompt)
                    tool_input["level"] = "low"
                else:
                    tool_input["prompt"] = user_prompt

            if tool_name == "validate_response":
                latest_route = next(
                    (t["tool_result"] for t in reversed(trajectory)
                     if t.get("tool_name") == "route_to_model"), None
                )
                if latest_route:
                    tool_input["response"] = latest_route.get("response", "")
                    tool_input["original_prompt"] = user_prompt

            print(f"[Step {step}] Calling tool: {tool_name}")
            try:
                tool_result = TOOLS[tool_name](tool_input)
            except Exception as e:
                tool_result = {"error": str(e)}
                print(f"[Step {step}] Tool-fel: {e}")

            print(f"[Step {step}] Tool result: {json.dumps(tool_result, ensure_ascii=False)}")

            trajectory.append({
                "step": step,
                "action": "tool",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_result": tool_result
            })

            if (tool_name == "validate_response"
                    and tool_result.get("status") == "fail"):
                route_count = sum(
                    1 for t in trajectory if t.get("tool_name") == "route_to_model"
                )
                if route_count >= 2:
                    print(f"\n[Step {step}] Max antal retries uppnått — returnerar slutsvar.")
                    latest_route = next(
                        (t["tool_result"] for t in reversed(trajectory)
                         if t.get("tool_name") == "route_to_model"), {}
                    )
                    classify_level = next(
                        (t["tool_result"].get("level") for t in trajectory
                         if t.get("tool_name") == "classify_sensitivity"), "unknown"
                    )
                    return {
                        "final_answer": latest_route.get("response", "No answer"),
                        "routing_summary": {
                            "sensitivity_level": classify_level,
                            "model_used": latest_route.get("model_used", "unknown"),
                            "validation_status": "fail",
                            "retries": route_count - 1,
                        },
                        "trajectory": trajectory,
                        "steps_taken": step,
                    }

            continue

        # --- 5c. Okänd action ---
        print(f"[Step {step}] FEL: Okänd action '{action}'")
        trajectory.append({
            "step": step,
            "error": f"unknown_action: {action}",
            "decision": decision
        })

    # Om vi når hit har max_steps överskridits
    print(f"\nStoppad efter {MAX_STEPS} steg utan slutgiltigt svar.")
    return {
        "final_answer": "Agenten stoppades: max antal steg nåddes utan slutgiltigt svar.",
        "routing_summary": {},
        "trajectory": trajectory,
        "steps_taken": MAX_STEPS
    }


# ============================================================
# Startpunkt
# ============================================================

if __name__ == "__main__":
    test_prompt = "Mitt personnummer är 199505151234 och jag behöver hjälp med min deklaration."
    print(f"Running agent with prompt: {test_prompt}")
    print("=" * 60)
    result = run_agent(test_prompt)
    print("=" * 60)
    print(f"\nFinal answer: {result['final_answer']}")
    print(f"Steps taken: {result['steps_taken']}")
    print(f"Routing summary: {json.dumps(result.get('routing_summary', {}), indent=2, ensure_ascii=False)}")