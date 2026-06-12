import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def generate_explanations(audit_results):
    """
    Takes the audited alert list and generates AI explanations for each alert.
    
    Args:
        audit_results: List of AlertHealthResult dictionaries
        
    Returns:
        List of dictionaries with "diagnosis" field populated
    """
    # Check for API keys
    groq_key = os.getenv('GROQ_API_KEY')
    gemini_key = os.getenv('GEMINI_API_KEY')
    
    updated_results = []
    
    for alert in audit_results:
        # Build prompt text
        name = alert.get('name', 'Unknown')
        query = alert.get('spl_query', 'Unknown')
        status = alert.get('status', 'Unknown')
        index_has_data = alert.get('index_has_data', False)
        
        prompt_text = f"Alert Name: {name}, SPL Query: {query}, Health Status: {status}, Index Has Data: {index_has_data}."
        
        diagnosis = "Alert analysis unavailable - check configuration manually."
        
        # Try GROQ API first
        if groq_key:
            try:
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a senior SOC analyst. Write a single, concise sentence (max 25 words) diagnostic explanation."
                        },
                        {
                            "role": "user",
                            "content": prompt_text
                        }
                    ]
                }
                
                response = requests.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                response_data = response.json()
                diagnosis = response_data["choices"][0]["message"]["content"].strip()
                
            except Exception:
                # Fall back to default message
                pass
        
        # Try Gemini API if GROQ failed or unavailable
        elif gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": f"You are a senior SOC analyst. Write a single, concise sentence (max 25 words) diagnostic explanation. Input details: {prompt_text}"
                                }
                            ]
                        }
                    ]
                }
                
                response = requests.post(url, json=payload)
                response.raise_for_status()
                
                response_data = response.json()
                diagnosis = response_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                
            except Exception:
                # Fall back to default message
                pass
        
        # Add diagnosis to alert copy
        updated_alert = alert.copy()
        updated_alert["diagnosis"] = diagnosis
        updated_results.append(updated_alert)
    
    return updated_results


if __name__ == "__main__":
    from splunk_agent import run_audit
    
    # Get audit results and generate explanations
    audit_results = run_audit()
    explained_results = generate_explanations(audit_results)
    
    # Print as clean JSON
    print(json.dumps(explained_results, indent=2))