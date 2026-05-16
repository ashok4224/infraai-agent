"""Rebuild foundry-service-patch ConfigMap with all original files + patched
knowledge_sync_service.py and knowledge_retrieval_service.py.
Then patch deployment and rollout restart."""
import json, subprocess, os

NS = "infraai"
CM_NAME = "foundry-service-patch"
BASE = r"infraaiagent-main\backend\app"

FILES = {
    "azure_foundry_service.py":   f"{BASE}/services/azure_foundry_service_pod.py",
    "config.py":                  f"{BASE}/config_pod.py",
    "foundry_analyzer.py":        f"{BASE}/services/foundry_analyzer_pod.py",
    "chat_service.py":            f"{BASE}/services/chat_service_pod.py",
    "knowledge_connectors.py":    f"{BASE}/services/knowledge_connectors_pod.py",
    "knowledge_router.py":        f"{BASE}/routers/knowledge_pod.py",
    "foundry_config.py":          f"{BASE}/routers/foundry_config_pod.py",
    "knowledge_sync_service.py":  f"{BASE}/services/knowledge_sync_service.py",
    "knowledge_retrieval_service.py": f"{BASE}/services/knowledge_retrieval_service.py",
}

def run(args):
    print(f"  RUN: {' '.join(args)}")
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}")
    else:
        out = r.stdout.strip()
        if out:
            print(f"  OK: {out}")
    return r.returncode

def main():
    # 1. Delete old ConfigMap
    print("1. Deleting old ConfigMap...")
    run(["kubectl", "delete", "configmap", CM_NAME, "-n", NS, "--ignore-not-found"])

    # 2. Create new ConfigMap with all files
    print(f"2. Creating ConfigMap with {len(FILES)} files...")
    cmd = ["kubectl", "create", "configmap", CM_NAME, "-n", NS]
    for key, path in FILES.items():
        cmd += ["--from-file", f"{key}={path}"]
    rc = run(cmd)
    if rc != 0:
        print("FATAL: ConfigMap creation failed")
        return

    # 3. Patch deployment to add knowledge_retrieval_service.py mount
    print("3. Patching deployment with new volume mount...")
    mount_patch = json.dumps([{
        "op": "add",
        "path": "/spec/template/spec/containers/0/volumeMounts/-",
        "value": {
            "name": "foundry-patch",
            "mountPath": "/app/app/services/knowledge_retrieval_service.py",
            "subPath": "knowledge_retrieval_service.py"
        }
    }])
    rc = run(["kubectl", "patch", "deploy", "infraai-backend", "-n", NS,
              "--type", "json", "-p", mount_patch])
    if rc != 0:
        print("WARNING: volume mount patch failed (may already exist)")

    # 4. Rollout restart
    print("4. Triggering rollout restart...")
    run(["kubectl", "rollout", "restart", "deploy/infraai-backend", "-n", NS])

    print("\n5. Waiting for rollout (120s max)...")
    run(["kubectl", "rollout", "status", "deploy/infraai-backend", "-n", NS, "--timeout=120s"])

    print("\n=== All done! ===")

if __name__ == "__main__":
    main()
