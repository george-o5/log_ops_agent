import os
import requests
import random
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

SPLUNK_HEC_URL = os.getenv('SPLUNK_HEC_URL')
SPLUNK_HEC_TOKEN = os.getenv('SPLUNK_HEC_TOKEN')

if not SPLUNK_HEC_URL or not SPLUNK_HEC_TOKEN:
    print("Error: SPLUNK_HEC_URL and SPLUNK_HEC_TOKEN must be set in environment variables")
    exit(1)

# Generate random timestamp within last 7 days
def random_timestamp():
    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    random_time = seven_days_ago + timedelta(
        seconds=random.randint(0, int((now - seven_days_ago).total_seconds()))
    )
    return random_time.isoformat()

# Generate random IP address
def random_ip():
    return f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"

# Push event to Splunk HEC
def push_to_splunk(event_data, sourcetype):
    headers = {
        'Authorization': f'Splunk {SPLUNK_HEC_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'event': event_data,
        'sourcetype': sourcetype,
        'index': 'main'
    }
    
    try:
        response = requests.post(SPLUNK_HEC_URL, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Error pushing event: HTTP {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error pushing event: {e}")

# Generate and push security_logs events (80 events)
security_actions = ["failed_login", "failed_login", "failed_login", "success_login"]
security_users = ["admin", "root", "deploy_user", "jenkins", "backup_svc"]

for _ in range(80):
    event = {
        "action": random.choice(security_actions),
        "src_ip": random_ip(),
        "user": random.choice(security_users),
        "timestamp": random_timestamp()
    }
    push_to_splunk(event, "security_logs")

# Generate and push app_metrics events (70 events)
app_hosts = ["web-01", "web-02", "api-server", "db-primary"]

for _ in range(70):
    event = {
        "host": random.choice(app_hosts),
        "cpu_pct": round(random.uniform(10.0, 98.0), 1),
        "mem_pct": round(random.uniform(20.0, 95.0), 1),
        "timestamp": random_timestamp()
    }
    push_to_splunk(event, "app_metrics")

# Print summary
print("Pushed 150 events to Splunk Cloud.")
print("  - 80 security_logs events")
print("  - 70 app_metrics events")
print("Done. Check Splunk Cloud: index=main | stats count by sourcetype")