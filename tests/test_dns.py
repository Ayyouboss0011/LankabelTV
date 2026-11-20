import sys
import os
sys.path.append(os.path.join(os.getcwd(), "src"))

try:
    from aniworld import config
    import requests
    print("Testing connection to s.to via Custom DNS...")
    r = requests.get("https://s.to", timeout=10)
    print(f"Success! Status Code: {r.status_code}")
    print(f"Resolved IP for s.to: {config._dns_cache.get('s.to', 'Not in cache')}")
except Exception as e:
    print(f"Error during test: {e}")
