import json

from tools import sensitivity_classifier

if __name__ == "__main__":
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

    print("--- STARTAR PII-TEST ---")
    for i, test_text in enumerate(test_cases, 1):
        print(f"\nTest {i}: \"{test_text}\"")
        
        result = sensitivity_classifier(test_text)
        
        print(json.dumps(result, indent=2, ensure_ascii=False))