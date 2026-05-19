"""Script to patch the ConfigMap with kubernetes Python client version of _k8s_exec_tool."""
import json

with open('C:/tmp/cm_fixed.json', encoding='utf-8') as f:
    obj = json.load(f)

tr = obj['data']['tool_registry.py']

# Find the k8s block by locating _SAFE_K8S_VERBS and the preceding comment
start_idx = tr.find('_SAFE_K8S_VERBS')
# Go back to find comment line start
comment_start = tr.rfind('\n#', 0, start_idx)
actual_start = comment_start + 1

# Find end: start of PostgreSQL section comment
postgres_comment = tr.find('# \U0001f4e6\U0001f4e6 PostgreSQL', start_idx)
if postgres_comment < 0:
    # Try the box-drawing comment style
    pg_fn_start = tr.find('async def _postgres_query_tool', start_idx)
    pg_comment = tr.rfind('\n#', 0, pg_fn_start)
    actual_end = pg_comment + 1
else:
    actual_end = postgres_comment

old_block = tr[actual_start:actual_end]
print(f"Found old block ({len(old_block)} chars)")
print("First 100:", repr(old_block[:100]))

new_block = r'''# ── Kubernetes executor — kubernetes Python client (in-cluster) ──
_SAFE_K8S_VERBS = {"get", "describe", "logs", "events", "version"}


async def _k8s_exec_tool(config_id: str, verb: str, resource: str, namespace: str = None, extra_args: list = None) -> dict:
    """Execute K8s operations via kubernetes Python client using in-cluster service account."""
    import asyncio

    if verb not in _SAFE_K8S_VERBS:
        return {"success": False, "error": f"Unsafe kubectl verb: {verb}", "requires_approval": True}

    def _run():
        try:
            from kubernetes import client as k8s_client, config as k8s_config
        except ImportError:
            return {"error": "kubernetes package not installed"}
        try:
            k8s_config.load_incluster_config()
        except Exception:
            try:
                k8s_config.load_kube_config()
            except Exception as e:
                return {"error": f"Cannot load k8s config: {e}"}

        v1 = k8s_client.CoreV1Api()
        apps_v1 = k8s_client.AppsV1Api()
        r = resource.lower().split("/")[0]

        try:
            if verb == "get":
                if r in ("pod", "pods"):
                    items = (v1.list_namespaced_pod(namespace) if namespace else v1.list_pod_for_all_namespaces()).items
                    rows = []
                    for p in items:
                        reasons = []
                        for cs in (p.status.container_statuses or []):
                            if cs.state and cs.state.waiting:
                                reasons.append(cs.state.waiting.reason or "Waiting")
                            elif cs.state and cs.state.terminated:
                                reasons.append("Terminated(exit=%d,reason=%s)" % (
                                    cs.state.terminated.exit_code or 0,
                                    cs.state.terminated.reason or ""))
                        rows.append("%s/%s  %s  %s" % (
                            p.metadata.namespace, p.metadata.name,
                            p.status.phase, ",".join(reasons) or "OK"))
                    return "\n".join(rows) or "No pods found"

                elif r in ("node", "nodes"):
                    items = v1.list_node().items
                    rows = []
                    for n in items:
                        conds = {c.type: c.status for c in n.status.conditions}
                        rows.append("%s  Ready=%s  %s" % (
                            n.metadata.name, conds.get("Ready", "?"),
                            n.status.node_info.kubelet_version))
                    return "\n".join(rows)

                elif r in ("event", "events"):
                    items = (v1.list_namespaced_event(namespace) if namespace
                             else v1.list_event_for_all_namespaces()).items
                    rows = []
                    for e in sorted(items, key=lambda x: str(x.last_timestamp or ""), reverse=True)[:50]:
                        rows.append("%s  %s  %s  %s/%s  %s" % (
                            e.metadata.namespace, e.type or "", e.reason or "",
                            e.involved_object.kind, e.involved_object.name, e.message or ""))
                    return "\n".join(rows) or "No events"

                elif r in ("deployment", "deployments"):
                    items = (apps_v1.list_namespaced_deployment(namespace) if namespace
                             else apps_v1.list_deployment_for_all_namespaces()).items
                    rows = []
                    for d in items:
                        rows.append("%s/%s  ready=%s/%s" % (
                            d.metadata.namespace, d.metadata.name,
                            d.status.ready_replicas, d.spec.replicas))
                    return "\n".join(rows)

                else:
                    return "Resource '%s' not supported" % r

            elif verb == "describe":
                parts = resource.split("/")
                name = parts[-1]
                if r in ("node", "nodes"):
                    n = v1.read_node(name)
                    conds = {c.type: c.status for c in n.status.conditions}
                    alloc = n.status.allocatable or {}
                    return "Node: %s\nConditions: %s\nAllocatable CPU: %s, Memory: %s" % (
                        name, conds, alloc.get("cpu"), alloc.get("memory"))
                else:
                    p = v1.read_namespaced_pod(name=name, namespace=namespace or "default")
                    cs_info = []
                    for cs in (p.status.container_statuses or []):
                        if cs.state and cs.state.waiting:
                            cs_info.append("  %s: Waiting — %s: %s" % (
                                cs.name, cs.state.waiting.reason, cs.state.waiting.message))
                        elif cs.state and cs.state.terminated:
                            cs_info.append("  %s: Terminated exit=%d reason=%s" % (
                                cs.name, cs.state.terminated.exit_code or 0,
                                cs.state.terminated.reason or ""))
                        elif cs.state and cs.state.running:
                            cs_info.append("  %s: Running since %s" % (
                                cs.name, cs.state.running.started_at))
                    return "Pod: %s\nNamespace: %s\nPhase: %s\nContainers:\n%s" % (
                        name, namespace or "default", p.status.phase, "\n".join(cs_info))

            elif verb == "logs":
                parts = resource.split("/")
                name = parts[-1]
                tail = 100
                for a in (extra_args or []):
                    if str(a).startswith("--tail="):
                        try:
                            tail = int(str(a).split("=")[1])
                        except Exception:
                            pass
                return v1.read_namespaced_pod_log(name=name, namespace=namespace or "default", tail_lines=tail)

            elif verb == "version":
                ver = k8s_client.VersionApi().get_code()
                return "Kubernetes %s" % ver.git_version

            elif verb == "events":
                items = (v1.list_namespaced_event(namespace) if namespace
                         else v1.list_event_for_all_namespaces()).items
                rows = []
                for e in sorted(items, key=lambda x: str(x.last_timestamp or ""), reverse=True)[:50]:
                    rows.append("%s  %s  %s  %s/%s  %s" % (
                        e.metadata.namespace, e.type or "", e.reason or "",
                        e.involved_object.kind, e.involved_object.name, e.message or ""))
                return "\n".join(rows) or "No events"

            else:
                return "Verb '%s' not supported" % verb

        except Exception as e:
            return {"error": str(e)}

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_run), timeout=30.0)
        if isinstance(result, dict) and "error" in result:
            logger.error("k8s_exec_tool error: %s", result["error"])
            return {"success": False, "error": result["error"]}
        logger.info("k8s_exec_tool OK: %s %s (ns=%s)", verb, resource, namespace)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("k8s_exec_tool failed: %s %s: %s", verb, resource, e)
        return {"success": False, "error": str(e)}


'''

tr = tr[:actual_start] + new_block + tr[actual_end:]
obj['data']['tool_registry.py'] = tr
obj.get('metadata', {}).pop('annotations', None)

with open('C:/tmp/cm_k8s.json', 'w', encoding='utf-8') as out:
    json.dump(obj, out)
print("Saved to C:/tmp/cm_k8s.json")
