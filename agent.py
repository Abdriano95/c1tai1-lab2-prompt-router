"""
Controller-loop för Prompt Sensitivity Router.
Baserad på minimal_agent.py-mönstret från workshoppen.

Orchestrator-LLM:en (Groq) bestämmer vilka tools att anropa.
Tools (i tools.py) utför arbetet och returnerar resultat.
Loopen kör tills agenten säger "final" eller max_steps nås.
"""

import json
import os
from typing import Any
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from tools import sensitivity_classifier, route_to_model, validate_response
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
    temperature=0
)

# ============================================================
# Tool-registry
# ============================================================
# Mappar tool-namn (som agenten refererar till) till funktioner.
# Agenten returnerar JSON med "tool_name" och "tool_input",
# och loopen anropar rätt funktion baserat på detta.
# ============================================================

TOOLS = {
    "sensitivity_classifier": lambda args: sensitivity_classifier(args["prompt"]),
    "route_to_model": lambda args: route_to_model(args["prompt"], args["level"]),
    "validate_response": lambda args: validate_response(args["response"], args["original_prompt"]),
}


# ============================================================
# State builder
# ============================================================
# Bygger prompten som orchestrator-LLM:en ser varje steg.
# Inkluderar: den ursprungliga prompten, stegräknare, och
# hela trajectory (allt som hänt hittills).
# ============================================================

def build_state_prompt(user_prompt: str, trajectory: list[dict[str, Any]], step: int) -> str:
    return (
        f"User prompt to process: {user_prompt}\n"
        f"Step: {step}/{MAX_STEPS}\n"
        f"Trajectory so far: {json.dumps(trajectory, ensure_ascii=False)}\n"
        "Choose the next action."
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

        # --- 4. Parsa JSON ---
        try:
            decision = json.loads(raw_output)
        except json.JSONDecodeError:
            # LLM returnerade inte giltig JSON — spara fel, fortsätt
            print(f"[Step {step}] ERROR: Invalid JSON")
            trajectory.append({
                "step": step,
                "error": "invalid_json",
                "raw_output": raw_output
            })
            continue

        action = decision.get("action")

        # --- 5a. Om "final" — vi är klara ---
        if action == "final":
            print(f"\n[Step {step}] FINAL ANSWER reached.")
            trajectory.append({
                "step": step,
                "action": "final",
                "decision": decision
            })
            return {
                "final_answer": decision.get("final_answer", "No answer provided"),
                "routing_summary": decision.get("routing_summary", {}),
                "trajectory": trajectory,
                "steps_taken": step
            }

        # --- 5b. Om "tool" — kör rätt tool ---
        if action == "tool":
            tool_name = decision.get("tool_name")
            tool_input = decision.get("tool_input", {})

            if tool_name not in TOOLS:
                # Okänt tool — spara fel, fortsätt
                print(f"[Step {step}] ERROR: Unknown tool '{tool_name}'")
                trajectory.append({
                    "step": step,
                    "error": f"unknown_tool: {tool_name}",
                    "decision": decision
                })
                continue

            # Kör tool
            print(f"[Step {step}] Calling tool: {tool_name}")
            try:
                tool_result = TOOLS[tool_name](tool_input)
            except Exception as e:
                tool_result = {"error": str(e)}
                print(f"[Step {step}] Tool error: {e}")

            print(f"[Step {step}] Tool result: {json.dumps(tool_result, ensure_ascii=False)}")

            # Spara i trajectory
            trajectory.append({
                "step": step,
                "action": "tool",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_result": tool_result
            })
            continue

        # --- 5c. Okänd action ---
        print(f"[Step {step}] ERROR: Unknown action '{action}'")
        trajectory.append({
            "step": step,
            "error": f"unknown_action: {action}",
            "decision": decision
        })

    # Om vi når hit har max_steps överskridits
    print(f"\nStopped after {MAX_STEPS} steps without final answer.")
    return {
        "final_answer": "Agent stopped: max steps reached without final answer.",
        "routing_summary": {},
        "trajectory": trajectory,
        "steps_taken": MAX_STEPS
    }


# ============================================================
# Entrypoint
# ============================================================

if __name__ == "__main__":
    # Snabbtest: kör en prompt genom hela flödet
    test_prompt = "Mitt personnummer är 199505151234 och jag behöver hjälp med min deklaration."
    print(f"Running agent with prompt: {test_prompt}")
    print("=" * 60)
    result = run_agent(test_prompt)
    print("=" * 60)
    print(f"\nFinal answer: {result['final_answer']}")
    print(f"Steps taken: {result['steps_taken']}")
    print(f"Routing summary: {json.dumps(result.get('routing_summary', {}), indent=2)}")