import httpx
import json

# Test GET /revision-desk/state
try:
    # First login to get a session cookie
    client = httpx.Client(follow_redirects=True)
    
    # Attempt to access endpoint without auth
    print("=== Without auth ===")
    resp = client.get('http://127.0.0.1:8001/revision-desk/state', timeout=5)
    print(f"Status: {resp.status_code}")
    print(f"URL after redirects: {resp.url}")
    print(f"Response length: {len(resp.text)}")
    if resp.status_code == 200:
        print(f"Response: {resp.text[:200]}")
    
    # Show cookies
    print(f"\nCookies in jar: {dict(client.cookies)}")
    
except Exception as e:
    print(f"Error: {e}")

