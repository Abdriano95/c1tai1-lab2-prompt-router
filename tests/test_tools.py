import json

from tools import classify_sensitivity, route_to_model, validate_response

if __name__ == "__main__":
    print("=========================================")
    print("        TEST 1: SENSITIVITY CLASSIFIER        ")
    print("=========================================")
    test_cases = [
        "Hej, mitt personnummer är 900101-1234 och jag behöver hjälp.",
        "Hej, mitt personnummer är 199011011234 och jag behöver hjälp.",
        "Min epost är test.testsson@exempel.se, kontakta mig där.",
        "Kan du ringa mig på 070-123 45 67?",
        "Kan du ringa mig på 0701234567?",
        "Kan du ringa mig på 004670-123 45 67?",
        "Kan du ringa mig på 970-123 45 67?",
        "Jag betalade med kortnummer 4532 1234 5678 9010 igår.",
        "Systemet kraschade på ip-adress 192.168.1.100.",
        "Jag köpte en ny skön madrass till sängen.", 
        "Jag har glömt mitt lösenord till kontot!", 
        "Vad är 15% av 4500?" 
    ]

    for i, test_text in enumerate(test_cases, 1):
        print(f"\nTest {i}: \"{test_text}\"")
        
        result = classify_sensitivity(test_text)
        
        print(json.dumps(result, indent=2, ensure_ascii=False))

    print("=========================================")
    print("        TEST 1: VALIDATE RESPONSE        ")
    print("=========================================")
    
    validator_tests = [
        {
            "name": "Godkänt svar",
            "prompt": "Vad är huvudstaden i Sverige?",
            "response": "Huvudstaden i Sverige är Stockholm."
        },
        {
            "name": "Tomt svar",
            "prompt": "Hallå?",
            "response": "   "
        },
        {
            "name": "För kort svar",
            "prompt": "Förklara kvantfysik.",
            "response": "Hej då."
        },
        {
            "name": "Vägrar svara (Refusal)",
            "prompt": "Hur hackar jag en bank?",
            "response": "Tyvärr, jag kan inte svara på det as an AI model."
        },
        {
            "name": "PII-läckage",
            "prompt": "Här är mitt personnummer: 19900101-1234, kom ihåg det.",
            "response": "Jag har sparat ditt personnummer 19900101-1234 i min databas."
        }
    ]

    for test in validator_tests:
        print(f"\nTestfall: {test['name']}")
        result = validate_response(test["response"], test["prompt"])
        print(json.dumps(result, indent=2, ensure_ascii=False))


    print("\n=========================================")
    print("         TEST 2: ROUTE TO MODEL          ")
    print("=========================================")
    print("(Observera: Detta anropar Groq via API, kan ta någon sekund...)")

    router_tests = [
        {
            "name": "Låg känslighet (snabb modell)",
            "prompt": "Vad är 2+2?",
            "level": "low"
        },
        {
            "name": "Hög känslighet (säker modell)",
            "prompt": "Sammanfatta denna journal för patienten.",
            "level": "high"
        },
        {
            "name": "Ogiltig nivå (ska falla tillbaka på high)",
            "prompt": "Detta testar default-logiken.",
            "level": "okänd_nivå"
        }
    ]

    for test in router_tests:
        print(f"\nTestfall: {test['name']} (Level: {test['level']})")

        result = route_to_model(test["prompt"], test["level"])
        
        # Eftersom response kan vara väldigt långt, klipper vi det lite för utskriften
        if result.get("response"):
            result["response"] = result["response"][:50] + "... [FÖRKORTAT]"
            
        print(json.dumps(result, indent=2, ensure_ascii=False))