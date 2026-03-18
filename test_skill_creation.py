import requests
import json

def test_chat():
    url = "http://127.0.0.1:5300/api/v1/agents/insurance-broker/chat" # Adjusted ID if needed
    
    # Try to find a valid agent ID FIRST
    try:
        agents_resp = requests.get("http://127.0.0.1:5300/api/v1/agents")
        agents = agents_resp.json().get("agents", [])
        if not agents:
            print("❌ No agents found to test with.")
            return
        
        agent_id = agents[0]['id']
        url = f"http://127.0.0.1:5300/api/v1/agents/{agent_id}/chat"
        print(f"📡 Testing with Agent ID: {agent_id} ({agents[0]['name']})")
    except Exception as e:
        print(f"❌ Could not list agents: {e}")
        return

    payload = {
        "message": "tạo skill tìm kiếm google"
    }
    
    headers = {
        "Content-Type": "application/json"
    }

    print(f"🚀 Sending request to {url} (timeout=120s)...")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        print(f"📥 Status: {response.status_code}")
        print(f"📥 Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_chat()
