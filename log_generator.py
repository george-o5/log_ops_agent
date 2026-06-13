import os
import time
import random
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()
HEC_URL   = os.getenv("SPLUNK_HEC_URL", "").strip()
HEC_TOKEN = os.getenv("SPLUNK_HEC_TOKEN", "").strip()

# Build header as module-level constant
HEADERS = {"Authorization": f"Splunk {HEC_TOKEN}","Content-Type": "application/json"}

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
    payload = {
        'event': event_data,
        'sourcetype': sourcetype,
        'index': 'main'
    }
    
    try:
        response = requests.post(HEC_URL, headers=HEADERS, json=payload, verify=False)
        if response.status_code != 200:
            print(f"❌ Error pushing event: HTTP {response.status_code} - {response.text}")
            return False
        return True
    except Exception as e:
        print(f"❌ Error pushing event: {e}")
        return False

# Generate and push security_logs and database events infinitely
security_actions = ["failed_login", "failed_login", "failed_login", "success_login"]
security_users = ["admin", "root", "deploy_user", "jenkins", "backup_svc"]

# Database log parameters
database_actions = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE TABLE", "DROP TABLE"]
database_tables = ["users", "orders", "products", "sessions", "audit_log", "config"]
database_users = ["app_user", "admin", "read_only", "backup_svc", "analytics"]

# Startup validation check
if len(HEC_TOKEN) != 36:
    print(f"❌ FATAL: HEC token looks wrong. Length={len(HEC_TOKEN)}, expected 36.")
    print("Go to Splunk Cloud → Settings → Data Inputs → HTTP Event Collector")
    exit(1)
print(f"✅ HEC token valid. Length=36. Last 6: ...{HEC_TOKEN[-6:]}")

print("🚀 Starting continuous log generator...")
print("📊 Generating 2-3 security/database logs every 5 seconds")
print("🛑 Press Ctrl+C to stop\n")

batch_count = 0
total_logs_sent = 0

try:
    while True:
        batch_count += 1
        num_logs = random.randint(2, 3)
        logs_generated = []
        
        # Generate 2-3 random logs (mix of security and database)
        for i in range(num_logs):
            log_type = random.choice(["security", "database"])
            
            if log_type == "security":
                event = {
                    "action": random.choice(security_actions),
                    "src_ip": random_ip(),
                    "user": random.choice(security_users),
                    "timestamp": datetime.now().isoformat(),
                    "log_type": "security"
                }
                push_to_splunk(event, "security_logs")
                logs_generated.append("security")
            else:
                event = {
                    "action": random.choice(database_actions),
                    "table": random.choice(database_tables),
                    "user": random.choice(database_users),
                    "src_ip": random_ip(),
                    "rows_affected": random.randint(1, 100),
                    "duration_ms": random.randint(10, 500),
                    "timestamp": datetime.now().isoformat(),
                    "log_type": "database"
                }
                push_to_splunk(event, "database_logs")
                logs_generated.append("database")
        
        # Print clean success message
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_summary = ", ".join([f"{logs_generated.count(t)} {t}" for t in set(logs_generated)])
        total_logs_sent += num_logs
        
        print(f"✅ [{timestamp}] Batch #{batch_count}: Sent {log_summary} logs → Total: {total_logs_sent}")
        
        # Wait 5 seconds before next batch
        time.sleep(5)

except KeyboardInterrupt:
    print(f"\n🛑 Stopped after {batch_count} batches ({total_logs_sent} total logs)")
    print("🔍 Check Splunk Cloud: index=main sourcetype=security_logs OR sourcetype=database_logs")