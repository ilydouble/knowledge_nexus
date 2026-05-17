import json, requests

with open("data/runtime/cloudreve_tokens.json") as f:
    store = json.load(f)

token = store.get("access_token", "")
base = "http://localhost:5212"
headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

r = requests.get(base + "/api/v4/file", headers=headers, params={"uri": "cloudreve://my"}, timeout=5)
raw_data = r.json().get("data", {})
files = raw_data.get("files", [])
first_file = files[0] if files else {}
file_id = first_file.get("id", "")
file_name = first_file.get("name", "")
print(f"First file: id={file_id}, name={file_name}")
print(f"  all keys: {list(first_file.keys())}")
print(f"  type field: {first_file.get('type')}  (0=file, 1=dir?)")
print(f"  raw_data top-level keys: {list(raw_data.keys())}")

print(f"\n  path field value: {first_file.get('path')}")
print(f"  capability: {first_file.get('capability')}")

file_uri = first_file.get("path", "")
print(f"  path(URI): {file_uri}")

# Find content download endpoint
tests = [
    ("GET", "/api/v4/file/archive", {"uri": file_uri}),
    ("GET", "/api/v4/file/archive", {"uri": "cloudreve://my"}),
    ("GET", "/api/v4/file/getContent", {"uri": file_uri}),
    ("GET", "/api/v4/file/preview", {"uri": file_uri}),
]
for method, path, params in tests:
    resp = requests.request(method, base + path, headers=headers, params=params, timeout=10, allow_redirects=False)
    ctype = resp.headers.get("Content-Type", "")
    body = resp.text[:120].replace("\n", " ") if "json" in ctype else f"binary {len(resp.content)} bytes"
    print(f"{method} {path}?uri=... -> {resp.status_code} {ctype[:30]}: {body}")

# Also check what directory response looks like for sub-directory detection
print("\nDirectory listing structure check:")
r2 = requests.get(base + "/api/v4/file", headers=headers, params={"uri": "cloudreve://my"}, timeout=5)
d = r2.json().get("data", {})
for item in d.get("files", [])[:5]:
    print(f"  type={item.get('type')} path={item.get('path')} name={item.get('name')}")
