"""Azure AI Foundry service - azure-ai-projects v2.x SDK wrapper.

Uses the Conversations + Responses API (v2.x pattern):
  project_client.get_openai_client()    -> openai_client
  openai_client.conversations.create()  -> conversation
  openai_client.responses.create()      -> agent response
  openai_client.conversations.delete()  -> cleanup

Falls back to direct Chat Completions when agent_reference is not available.

The ``foundry_agent_name`` stored in the database is the agent
**name** registered in the Microsoft Foundry project.
"""
import asyncio
import inspect
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_project_client = None
_openai_client = None
_agent_reference_available = None  # None=unknown, True=available, False=not available

# Cache: agent name → asst_* ID (populated lazily)
_assistant_id_cache: dict[str, str] = {}


# -- Credentials -------------------------------------------------------------

def _get_credential_async():
    """Build an async Azure credential from settings.

    When AZURE_AI_FOUNDRY_KEY is set, uses AzureKeyCredential.
    Falls back to service principal, then DefaultAzureCredential.
    """
    if settings.AZURE_AI_FOUNDRY_KEY:
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(settings.AZURE_AI_FOUNDRY_KEY)

    from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential

    if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET and settings.AZURE_TENANT_ID:
        return ClientSecretCredential(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
    return DefaultAzureCredential()


async def _api_key_get(path: str) -> dict:
    """Make a direct HTTP GET to the Foundry data plane using the API key.
    Used when AZURE_AI_FOUNDRY_KEY is set, since AIProjectClient with
    AzureKeyCredential sends 'Authorization: Bearer <key>' but the Foundry
    Projects API requires 'api-key: <key>' header.
    """
    import httpx
    endpoint = settings.AZURE_AI_FOUNDRY_ENDPOINT.rstrip("/")
    url = f"{endpoint}/{path.lstrip('/')}"
    if "api-version=" not in url:
        url += ("&" if "?" in url else "?") + "api-version=v1"
    headers = {
        "api-key": settings.AZURE_AI_FOUNDRY_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        return resp.json()


# -- Client lifecycle ---------------------------------------------------------

async def get_foundry_client():
    """Return an authenticated async AIProjectClient (cached)."""
    global _project_client, _openai_client
    if _project_client is not None:
        return _project_client

    from azure.ai.projects.aio import AIProjectClient

    endpoint = settings.AZURE_AI_FOUNDRY_ENDPOINT
    if not endpoint:
        raise RuntimeError("AZURE_AI_FOUNDRY_ENDPOINT is not configured")

    _project_client = AIProjectClient(
        endpoint=endpoint,
        credential=_get_credential_async(),
    )

    # Obtain the OpenAI client -- sync call in v2.x, handle async for compat
    result = _project_client.get_openai_client()
    _openai_client = (await result) if inspect.isawaitable(result) else result

    return _project_client


async def _ensure_clients():
    """Ensure both project and OpenAI clients are initialised."""
    if _project_client is None or _openai_client is None:
        await get_foundry_client()
    return _project_client, _openai_client


# -- Direct Chat Completion fallback ------------------------------------------

def _make_direct_openai_client():
    """Create a plain AsyncOpenAI client that authenticates via api-key header.

    Bypasses AIProjectClient's Azure credential wrapper which requires
    get_token() and does not work with AzureKeyCredential.
    """
    import openai
    endpoint = settings.AZURE_AI_FOUNDRY_ENDPOINT.rstrip("/")
    # The project endpoint's OpenAI-compatible base URL
    base_url = f"{endpoint}/openai/v1"
    return openai.AsyncOpenAI(
        api_key=settings.AZURE_AI_FOUNDRY_KEY,
        base_url=base_url,
        default_headers={"api-key": settings.AZURE_AI_FOUNDRY_KEY},
        max_retries=2,
    )


async def _run_chat_completion(messages: list[dict], timeout: float = 120.0) -> str:
    """Fallback: run a direct chat completion using the deployed model."""
    client = _make_direct_openai_client()
    model = settings.AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT or "gpt-4o"
    try:
        async with asyncio.timeout(timeout):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=4096,
            )
            return response.choices[0].message.content or "(No response)"
    except Exception as e:
        logger.error("Direct chat completion failed: %s", e)
        raise
    finally:
        await client.close()


async def _run_chat_completion_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
    timeout: float = 120.0,
) -> dict:
    """Run a chat completion with function calling support.

    Returns a dict:
      {"type": "message", "content": "..."}
      or
      {"type": "tool_calls", "tool_calls": [{"name": "...", "arguments": {...}}]}
    """
    client = _make_direct_openai_client()
    model = settings.AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT or "gpt-4o"

    try:
        async with asyncio.timeout(timeout):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=4096,
            )

            message = response.choices[0].message

            # Check if the model wants to call functions
            if getattr(message, "tool_calls", None):
                tool_calls = []
                for tc in message.tool_calls:
                    import json
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "name": tc.function.name,
                        "arguments": args,
                    })
                return {
                    "type": "tool_calls",
                    "tool_calls": tool_calls,
                }

            # Regular text response
            return {
                "type": "message",
                "content": message.content or "(No response)",
            }

    except Exception as e:
        logger.error("Chat completion with tools failed: %s", e)
        raise
    finally:
        await client.close()


# -- Assistants Threads API (used when AZURE_AI_FOUNDRY_KEY is set) -----------

_THREADS_API_VERSION = "2025-05-01"
# Cached bearer token for agents API (scope: https://ai.azure.com/.default)
_agents_token_cache: dict = {}


def _get_agents_bearer_token() -> str:
    """Get a bearer token for the Azure AI agents API using ClientSecretCredential.

    The Agents API requires AAD bearer token with scope https://ai.azure.com/.default.
    API key auth (api-key header) does NOT grant agents permissions — RBAC role
    'Azure AI User' on the Foundry resource is required for the service principal.
    """
    import time
    from azure.identity import ClientSecretCredential as SyncClientSecretCredential

    now = time.time()
    if _agents_token_cache.get("expires_at", 0) > now + 60:
        return _agents_token_cache["token"]

    if not (settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET and settings.AZURE_TENANT_ID):
        raise RuntimeError(
            "ClientSecretCredential not configured. Set AZURE_CLIENT_ID, "
            "AZURE_CLIENT_SECRET, AZURE_TENANT_ID in pod env vars."
        )

    cred = SyncClientSecretCredential(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
    )
    token = cred.get_token("https://ai.azure.com/.default")
    _agents_token_cache["token"] = token.token
    _agents_token_cache["expires_at"] = token.expires_on
    return token.token


def _threads_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_agents_bearer_token()}",
        "Content-Type": "application/json",
    }


def _threads_base() -> str:
    return settings.AZURE_AI_FOUNDRY_ENDPOINT.rstrip("/")


async def _load_assistant_id_cache() -> None:
    """Populate _assistant_id_cache by listing all agents in Foundry."""
    import httpx
    url = f"{_threads_base()}/assistants?api-version={_THREADS_API_VERSION}&limit=100"
    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.get(url, headers=_threads_headers())
        if r.status_code == 200:
            for a in r.json().get("data", []):
                name = a.get("name", "")
                aid = a.get("id", "")
                if name and aid:
                    _assistant_id_cache[name] = aid
            logger.info("Loaded %d Foundry agents into cache", len(_assistant_id_cache))
        else:
            logger.warning("Could not list Foundry assistants: %s %s", r.status_code, r.text[:200])


async def _ensure_assistant_id(agent_name: str) -> str | None:
    """Return the asst_* ID for the given agent name, fetching if needed."""
    if agent_name not in _assistant_id_cache:
        await _load_assistant_id_cache()
    return _assistant_id_cache.get(agent_name)


async def _run_via_threads(agent_name: str, messages: list[dict], timeout: float) -> str:
    """Run a Foundry agent via the OpenAI Assistants Threads API (API key auth).

    Flow: create thread → add messages → create run → poll until complete
          → extract assistant reply → delete thread.
    """
    import httpx

    assistant_id = await _ensure_assistant_id(agent_name)
    if not assistant_id:
        raise ValueError(f"Agent '{agent_name}' not found in Foundry (check name spelling)")

    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    async with httpx.AsyncClient(timeout=max(timeout, 30.0)) as http:
        # 1. Create empty thread
        r = await http.post(f"{base}/threads?api-version={ver}", headers=hdrs, json={})
        r.raise_for_status()
        thread_id = r.json()["id"]
        logger.debug("Created thread %s for agent %s", thread_id, agent_name)

        try:
            # 2. Add user/assistant messages (skip system — that's in the agent instructions)
            for msg in messages:
                role = msg.get("role", "")
                if role in ("user", "assistant"):
                    r2 = await http.post(
                        f"{base}/threads/{thread_id}/messages?api-version={ver}",
                        headers=hdrs,
                        json={"role": role, "content": msg.get("content", "")},
                    )
                    r2.raise_for_status()

            # 3. Create run
            r = await http.post(
                f"{base}/threads/{thread_id}/runs?api-version={ver}",
                headers=hdrs,
                json={"assistant_id": assistant_id},
            )
            r.raise_for_status()
            run_id = r.json()["id"]
            logger.debug("Created run %s for thread %s", run_id, thread_id)

            # 4. Poll until terminal state
            poll_interval = 1.0
            elapsed = 0.0
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                poll_interval = min(poll_interval * 1.5, 5.0)  # back off up to 5s

                r = await http.get(
                    f"{base}/threads/{thread_id}/runs/{run_id}?api-version={ver}",
                    headers=hdrs,
                )
                r.raise_for_status()
                run_data = r.json()
                status = run_data.get("status", "")
                logger.debug("Run %s status: %s (%.0fs elapsed)", run_id, status, elapsed)

                if status == "completed":
                    break
                if status in ("failed", "cancelled", "expired"):
                    last_err = run_data.get("last_error", {})
                    raise RuntimeError(f"Agent run {status}: {last_err}")
            else:
                raise TimeoutError(f"Agent run timed out after {int(timeout)}s")

            # 5. Retrieve the assistant reply (most recent assistant message)
            r = await http.get(
                f"{base}/threads/{thread_id}/messages?api-version={ver}&order=desc&limit=10",
                headers=hdrs,
            )
            r.raise_for_status()
            for msg in r.json().get("data", []):
                if msg.get("role") == "assistant":
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            return block["text"]["value"]
            return "(No response from agent)"

        finally:
            # Clean up thread regardless of success/failure
            try:
                await http.delete(
                    f"{base}/threads/{thread_id}?api-version={ver}", headers=hdrs
                )
            except Exception:
                pass


# -- Core: run an agent -------------------------------------------------------

async def run_agent(
    agent_id: str,
    messages: list[dict],
    timeout: float = 120.0,
    tools: list[dict] | None = None,
) -> str | dict:
    """Run a Foundry agent by name (foundry_agent_name from DB).

    When AZURE_AI_FOUNDRY_KEY is set:
      → Uses the OpenAI Assistants Threads API to invoke the named agent.
      → Falls back to direct Chat Completions only if the Threads call fails.
    When using managed identity / service principal:
      → Uses the Conversations + Responses API (v2 SDK pattern).

    Args:
        agent_id: The Foundry agent name.
        messages: Conversation messages.
        timeout: Max seconds to wait.
        tools: Optional OpenAI function schemas for tool calling.
               When provided, returns a dict with 'type', 'content', 'tool_calls'.
               When None, returns a plain string (backward compatible).
    """
    global _agent_reference_available

    # If tools are provided, use the direct chat completion with function calling.
    # This is the most reliable path for tool calling across all auth methods.
    if tools:
        logger.debug("Using direct chat completion with tools for agent %s", agent_id)
        return await _run_chat_completion_with_tools(messages, tools, timeout=timeout)

    # Primary path: API key set → use Assistants Threads API (asst_* agents)
    if settings.AZURE_AI_FOUNDRY_KEY:
        try:
            logger.debug("Using Assistants Threads API for agent %s", agent_id)
            return await _run_via_threads(agent_id, messages, timeout=timeout)
        except (ValueError, RuntimeError, TimeoutError) as e:
            # ValueError = agent not found in Foundry; don't silently swallow
            logger.error("Threads API failed for agent %s: %s — falling back to direct completion", agent_id, e)
            return await _run_chat_completion(messages, timeout=timeout)
        except Exception as e:
            logger.warning("Threads API unexpected error for agent %s: %s — falling back", agent_id, e)
            return await _run_chat_completion(messages, timeout=timeout)

    _, openai_client = await _ensure_clients()

    # Skip Responses API if we already know it's not available
    if _agent_reference_available is False:
        logger.debug("Using direct chat completion for agent %s (agent_reference unavailable)", agent_id)
        return await _run_chat_completion(messages, timeout=timeout)

    conversation_id = None
    try:
        async with asyncio.timeout(timeout):
            # Build v2.x conversation items from caller messages
            items = [
                {
                    "type": "message",
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                }
                for msg in messages
            ]

            # 1. Create conversation
            conversation = await openai_client.conversations.create(items=items)
            conversation_id = conversation.id

            # 2. Invoke agent
            response = await openai_client.responses.create(
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": agent_id,
                        "type": "agent_reference",
                    }
                },
            )

            _agent_reference_available = True

            # 3. Extract text -- prefer output_text, fall back to output items
            text = getattr(response, "output_text", None)
            if text:
                return text

            for item in getattr(response, "output", []):
                if getattr(item, "type", "") == "message":
                    for block in getattr(item, "content", []):
                        t = getattr(block, "text", None)
                        if t:
                            return t

            return "(No response from agent)"

    except asyncio.TimeoutError:
        logger.warning("Foundry agent %s timed out after %.0fs", agent_id, timeout)
        raise TimeoutError(f"Agent run timed out after {int(timeout)}s")
    except Exception as e:
        err_str = str(e).lower()
        # If agent_reference is not supported, fall back to direct completions
        if any(kw in err_str for kw in ("agent", "not found", "404", "unsupported", "not supported", "agent_reference")):
            logger.warning("agent_reference not available for %s (%s) - falling back to direct chat completion", agent_id, e)
            _agent_reference_available = False
            # Clean up conversation if created
            if conversation_id and _openai_client:
                try:
                    await _openai_client.conversations.delete(conversation_id=conversation_id)
                except Exception:
                    pass
                conversation_id = None
            return await _run_chat_completion(messages, timeout=timeout)
        logger.error("Foundry agent %s call failed: %s", agent_id, e)
        raise
    finally:
        if conversation_id and _openai_client:
            try:
                await _openai_client.conversations.delete(
                    conversation_id=conversation_id
                )
            except Exception:
                pass


# -- Knowledge Base: Files API + Vector Stores --------------------------------
#
# Azure AI Foundry has a fully managed knowledge pipeline built in:
#   1. Files API  — upload documents (PDF, MD, TXT, DOCX, …)
#   2. Vector Stores — Foundry auto-chunks + auto-embeds the files
#   3. file_search tool — attach vector store to an agent; it searches natively
#
# No Azure Blob Storage, no Azure AI Search, no pgvector required.
# Everything lives inside the Foundry project endpoint.

_KNOWLEDGE_VECTOR_STORE_NAME = "infraai-knowledge-store"
_knowledge_vector_store_id: str | None = None  # cached after first lookup


async def upload_file_to_foundry(filename: str, content_bytes: bytes) -> str:
    """Upload a document to Azure AI Foundry Files API.

    Returns the file_id (e.g. 'file-abc123') which can then be added to a
    vector store.  The same service-principal bearer token is reused.
    """
    import httpx

    base = _threads_base()
    ver = _THREADS_API_VERSION

    # Foundry Files API uses multipart/form-data
    files = {"file": (filename, content_bytes, _mime_type(filename))}
    data = {"purpose": "assistants"}

    # Build auth header without Content-Type so httpx sets multipart boundary
    hdrs = {"Authorization": f"Bearer {_get_agents_bearer_token()}"}

    async with httpx.AsyncClient(timeout=60.0) as http:
        r = await http.post(
            f"{base}/files?api-version={ver}",
            headers=hdrs,
            files=files,
            data=data,
        )
        r.raise_for_status()
        file_id = r.json()["id"]
        logger.info("Uploaded file '%s' to Foundry → %s", filename, file_id)
        return file_id


def _mime_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "md": "text/markdown",
        "txt": "text/plain",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "yaml": "text/yaml",
        "yml": "text/yaml",
        "json": "application/json",
    }.get(ext, "application/octet-stream")


async def ensure_knowledge_vector_store() -> str:
    """Get the existing infraai-knowledge-store vector store ID, or create it.

    The vector store ID is cached in memory after the first call.
    """
    global _knowledge_vector_store_id
    if _knowledge_vector_store_id:
        return _knowledge_vector_store_id

    import httpx

    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    async with httpx.AsyncClient(timeout=30.0) as http:
        # Search existing vector stores
        r = await http.get(f"{base}/vector_stores?api-version={ver}&limit=100", headers=hdrs)
        r.raise_for_status()
        for vs in r.json().get("data", []):
            if vs.get("name") == _KNOWLEDGE_VECTOR_STORE_NAME:
                _knowledge_vector_store_id = vs["id"]
                logger.info("Found existing vector store: %s", _knowledge_vector_store_id)
                return _knowledge_vector_store_id

        # Create it if not found
        r = await http.post(
            f"{base}/vector_stores?api-version={ver}",
            headers=hdrs,
            json={"name": _KNOWLEDGE_VECTOR_STORE_NAME},
        )
        r.raise_for_status()
        _knowledge_vector_store_id = r.json()["id"]
        logger.info("Created vector store: %s", _knowledge_vector_store_id)
        return _knowledge_vector_store_id


async def add_file_to_knowledge_store(file_id: str) -> None:
    """Add an already-uploaded file to the knowledge vector store.

    Foundry automatically chunks + embeds the file asynchronously.
    """
    import httpx

    vs_id = await ensure_knowledge_vector_store()
    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            f"{base}/vector_stores/{vs_id}/files?api-version={ver}",
            headers=hdrs,
            json={"file_id": file_id},
        )
        r.raise_for_status()
        logger.info("Added file %s to vector store %s", file_id, vs_id)


async def list_knowledge_store_files() -> list[dict]:
    """List all files in the knowledge vector store."""
    import httpx

    vs_id = await ensure_knowledge_vector_store()
    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.get(
            f"{base}/vector_stores/{vs_id}/files?api-version={ver}&limit=100",
            headers=hdrs,
        )
        r.raise_for_status()
        return r.json().get("data", [])


async def setup_knowledge_agent_file_search(knowledge_agent_name: str = "infraai-knowledge") -> dict:
    """Enable file_search tool on the infraai-knowledge agent and attach the vector store.

    Call this once after creating the vector store.  Safe to call multiple
    times — it is idempotent (PATCH replaces tools/tool_resources).
    """
    import httpx

    assistant_id = await _ensure_assistant_id(knowledge_agent_name)
    if not assistant_id:
        return {"success": False, "message": f"Agent '{knowledge_agent_name}' not found in Foundry"}

    vs_id = await ensure_knowledge_vector_store()
    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    patch_body = {
        "tools": [{"type": "file_search"}],
        "tool_resources": {
            "file_search": {
                "vector_store_ids": [vs_id],
            }
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            f"{base}/assistants/{assistant_id}?api-version={ver}",
            headers=hdrs,
            json=patch_body,
        )
        r.raise_for_status()
        logger.info("infraai-knowledge agent updated with file_search tool and vector store %s", vs_id)
        return {
            "success": True,
            "assistant_id": assistant_id,
            "vector_store_id": vs_id,
            "message": f"file_search enabled on {knowledge_agent_name} with store {vs_id}",
        }


async def create_sharepoint_connection(
    site_url: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    connection_name: str = "sharepoint-dbagroup",
) -> dict:
    """Create a SharePoint Online connection in the Foundry project.

    This connection is then used by the sharepoint_grounding agent tool so the
    agent can search SharePoint live — no file-sync or vector-store upload needed.

    Returns {"success": True, "connection_id": "...", "connection_name": "..."}
    """
    import httpx

    base = settings.AZURE_AI_FOUNDRY_ENDPOINT.rstrip("/")
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    body = {
        "name": connection_name,
        "type": "SharePointOnline",
        "properties": {
            "category": "SharePointOnline",
            "target": site_url,
            "authType": "ServicePrincipal",
            "credentials": {
                "tenantId": tenant_id,
                "clientId": client_id,
                "clientSecret": client_secret,
            },
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        # Try to create; if 409 Conflict, connection already exists — fetch it
        r = await http.put(
            f"{base}/connections/{connection_name}?api-version={ver}",
            headers=hdrs,
            json=body,
        )
        if r.status_code == 409:
            # Already exists — get its ID
            r2 = await http.get(
                f"{base}/connections/{connection_name}?api-version={ver}",
                headers=hdrs,
            )
            r2.raise_for_status()
            conn = r2.json()
        else:
            r.raise_for_status()
            conn = r.json()

    conn_id = conn.get("id") or conn.get("name", connection_name)
    logger.info("SharePoint connection ready: %s", conn_id)
    return {"success": True, "connection_id": conn_id, "connection_name": connection_name}


async def setup_sharepoint_grounding(
    site_url: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    knowledge_agent_name: str = "infraai-knowledge",
    connection_name: str = "sharepoint-dbagroup",
) -> dict:
    """Create a SharePoint connection + configure infraai-knowledge agent with
    sharepoint_grounding tool so it searches SharePoint live on every query.

    Also keeps file_search so uploaded files still work.
    Idempotent — safe to call multiple times.
    """
    import httpx

    # 1. Ensure the SharePoint connection exists
    conn_result = await create_sharepoint_connection(
        site_url, tenant_id, client_id, client_secret, connection_name
    )
    conn_id = conn_result["connection_id"]

    # 2. Find the knowledge agent
    assistant_id = await _ensure_assistant_id(knowledge_agent_name)
    if not assistant_id:
        return {"success": False, "message": f"Agent '{knowledge_agent_name}' not found in Foundry"}

    # 3. Also ensure vector store exists (keep file_search working too)
    vs_id = await ensure_knowledge_vector_store()

    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    patch_body = {
        "tools": [
            {"type": "file_search"},
            {
                "type": "sharepoint_grounding",
                "sharepoint_grounding": {
                    "connections": [{"connection_id": conn_id}],
                },
            },
        ],
        "tool_resources": {
            "file_search": {
                "vector_store_ids": [vs_id],
            }
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as http:
        r = await http.post(
            f"{base}/assistants/{assistant_id}?api-version={ver}",
            headers=hdrs,
            json=patch_body,
        )
        r.raise_for_status()

    logger.info(
        "infraai-knowledge agent configured with sharepoint_grounding (%s) + file_search (%s)",
        conn_id, vs_id,
    )
    return {
        "success": True,
        "assistant_id": assistant_id,
        "connection_id": conn_id,
        "vector_store_id": vs_id,
        "message": (
            f"Agent '{knowledge_agent_name}' now has sharepoint_grounding (live search) "
            f"+ file_search (uploaded docs). SharePoint site: {site_url}"
        ),
    }


# -- Admin helpers -------------------------------------------------------------

async def list_agents() -> list[dict]:
    """List agents available in the Foundry project."""
    try:
        if settings.AZURE_AI_FOUNDRY_KEY:
            import httpx
            url = f"{_threads_base()}/assistants?api-version={_THREADS_API_VERSION}&limit=100"
            async with httpx.AsyncClient(timeout=15.0) as http:
                r = await http.get(url, headers=_threads_headers())
                r.raise_for_status()
                return [
                    {
                        "id": a.get("id", ""),
                        "name": a.get("name", ""),
                        "model": a.get("model", ""),
                        "instructions": (a.get("instructions") or "")[:200],
                    }
                    for a in r.json().get("data", [])
                ]
        client, _ = await _ensure_clients()
        result = []
        async for deployment in client.deployments.list():
            result.append({
                "id": getattr(deployment, "name", ""),
                "name": getattr(deployment, "name", ""),
                "model": getattr(deployment, "model_name", ""),
                "instructions": "",
            })
        return result
    except Exception as e:
        logger.error("Failed to list Foundry agents: %s", e)
        raise


async def test_connection() -> dict:
    """Test connectivity to Azure AI Foundry."""
    try:
        if settings.AZURE_AI_FOUNDRY_KEY:
            data = await _api_key_get("deployments")
            count = len(data.get("value", []))
            return {
                "success": True,
                "message": f"Connected to Azure AI Foundry ({count} deployment(s) found)",
                "agent_count": count,
            }
        client, _ = await _ensure_clients()
        count = 0
        async for _ in client.deployments.list():
            count += 1
        return {
            "success": True,
            "message": f"Connected to Azure AI Foundry ({count} deployment(s) found)",
            "agent_count": count,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection failed: {str(e)}",
        }


async def test_agent(agent_id: str) -> dict:
    """Test a specific agent with a simple prompt."""
    try:
        response = await run_agent(
            agent_id,
            [{"role": "user", "content": "Respond with 'OK' to confirm you are operational."}],
            timeout=30.0,
        )
        return {
            "success": True,
            "message": "Agent responded successfully",
            "response_preview": response[:200],
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Agent test failed: {str(e)}",
        }


def reset_client():
    """Reset cached clients (e.g., after config change)."""
    global _project_client, _openai_client
    _project_client = None
    _openai_client = None