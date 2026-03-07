"""
Evaluation-script för Prompt Sensitivity Router.
Kör alla testprompts genom agenten och mäter:
- Routing accuracy (routades känsliga prompts korrekt?)
- Validation pass rate (andel svar som passerar validering)
- Antal steg per prompt (effektivitet)
- Jämförelse mot baseline (allt till samma modell utan klassificering)
"""

import json
import sys
import time
from tools import sensitivity_classifier, route_to_model, validate_response
from agent import run_agent
from prompts import TEST_PROMPTS

sys.stdout.reconfigure(encoding="utf-8")


def run_evaluation():
    """Kör alla testprompts genom agenten och samla resultat."""

    results = []
    correct_routing = 0
    validation_passes = 0
    total_steps = 0

    print("=" * 60)
    print("EVALUATION: Running agent on all test prompts")
    print("=" * 60)

    for i, test_case in enumerate(TEST_PROMPTS):
        prompt = test_case["prompt"]
        expected = test_case["expected_level"]
        description = test_case["description"]

        print(f"\n--- Test {i+1}/{len(TEST_PROMPTS)}: {description} ---")
        print(f"Prompt: {prompt[:80]}...")
        print(f"Expected level: {expected}")

        start_time = time.time()
        result = run_agent(prompt)
        elapsed = time.time() - start_time

        # Kolla om routing var korrekt
        actual_level = result.get("routing_summary", {}).get("sensitivity_level", "unknown")
        routing_correct = actual_level == expected
        if routing_correct:
            correct_routing += 1

        # Kolla validation status
        val_status = result.get("routing_summary", {}).get("validation_status", "unknown")
        if val_status == "pass":
            validation_passes += 1

        total_steps += result.get("steps_taken", 0)

        results.append({
            "prompt": prompt,
            "description": description,
            "expected_level": expected,
            "actual_level": actual_level,
            "routing_correct": routing_correct,
            "validation_status": val_status,
            "steps_taken": result.get("steps_taken", 0),
            "time_seconds": round(elapsed, 2),
            "final_answer": result.get("final_answer", "")[:100]
        })

        print(f"Actual level: {actual_level} ({'OK' if routing_correct else 'WRONG'})")
        print(f"Validation: {val_status}")
        print(f"Steps: {result.get('steps_taken', 0)} | Time: {elapsed:.2f}s")

    # Sammanställning
    total = len(TEST_PROMPTS)
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    print(f"Total prompts:      {total}")
    print(f"Routing accuracy:   {correct_routing}/{total} ({100*correct_routing/total:.1f}%)")
    print(f"Validation passes:  {validation_passes}/{total} ({100*validation_passes/total:.1f}%)")
    print(f"Avg steps/prompt:   {total_steps/total:.1f}")
    print()

    return results


def run_baseline():
    """
    Baseline: skicka alla prompts till samma modell utan klassificering.
    Jämförelseunderlag för evaluation.
    """

    print("\n" + "=" * 60)
    print("BASELINE: All prompts → same model, no classification")
    print("=" * 60)

    baseline_results = []
    pii_leaks = 0

    for i, test_case in enumerate(TEST_PROMPTS):
        prompt = test_case["prompt"]

        start_time = time.time()
        # Skicka allt till "moln"-modellen utan klassificering
        result = route_to_model(prompt, "low")
        elapsed = time.time() - start_time

        # Validera ändå
        validation = validate_response(result.get("response", ""), prompt)

        if validation["status"] == "fail" and "PII leaked" in validation["reason"]:
            pii_leaks += 1

        baseline_results.append({
            "prompt": prompt[:80],
            "model_used": result.get("model_used"),
            "validation": validation["status"],
            "time_seconds": round(elapsed, 2)
        })

        print(f"Test {i+1}: {validation['status']} | {elapsed:.2f}s")

    print(f"\nBaseline PII leaks: {pii_leaks}/{len(TEST_PROMPTS)}")
    return baseline_results


if __name__ == "__main__":
    # Kör agent-evaluation
    agent_results = run_evaluation()

    # Kör baseline
    baseline_results = run_baseline()

    # Spara resultat till fil
    with open("evaluation_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "agent_results": agent_results,
            "baseline_results": baseline_results
        }, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to evaluation_results.json")