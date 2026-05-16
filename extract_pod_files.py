"""Extract files from pod using base64 to avoid PowerShell encoding corruption."""
import subprocess, base64, os

FILES_TO_EXTRACT = {
    "config.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/config.py", "infraaiagent-main/backend/app/config_pod.py"],
    "azure_foundry_service.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/services/azure_foundry_service.py", "infraaiagent-main/backend/app/services/azure_foundry_service_pod.py"],
    "foundry_analyzer.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/services/foundry_analyzer.py", "infraaiagent-main/backend/app/services/foundry_analyzer_pod.py"],
    "chat_service.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/services/chat_service.py", "infraaiagent-main/backend/app/services/chat_service_pod.py"],
    "knowledge_connectors.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/services/knowledge_connectors.py", "infraaiagent-main/backend/app/services/knowledge_connectors_pod.py"],
    "knowledge_router.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/routers/knowledge.py", "infraaiagent-main/backend/app/routers/knowledge_pod.py"],
    "foundry_config.py": ["infraai-backend-c5595cdf6-tf4b5", "/app/app/routers/foundry_config.py", "infraaiagent-main/backend/app/routers/foundry_config_pod.py"],
}

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()

for name, (pod, path, dest) in FILES_TO_EXTRACT.items():
    # Get base64 encoded content from pod
    python_cmd = f"import base64; print(base64.b64encode(open('{path}','rb').read()).decode())"
    b64, err = run(["kubectl", "exec", "-n", "infraai", pod, "--", "python", "-c", python_cmd])
    if err:
        print(f"ERROR {name}: {err}")
        continue
    try:
        data = base64.b64decode(b64)
    except Exception as e:
        print(f"BASE64 ERROR {name}: {e}")
        continue
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    nulls = data.count(b"\x00")
    print(f"OK {name}: {len(data)} bytes -> {dest}" + (f" (WARN: {nulls} nulls)" if nulls else ""))