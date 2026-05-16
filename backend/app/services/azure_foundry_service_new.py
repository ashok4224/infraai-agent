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

async def _run_chat_completion(messages: list[dict], timeout: float = 120.0) -> str:
    """Fallback: run a direct chat completion using the deployed model."""
    _, openai_client = await _ensure_clients()
    model = "gpt-4o"
    try:
        async with asyncio.timeout(timeout):
            response = await openai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=4096,
            )
            return response.choices[0].message.content or "(No response)"
    except Exception as e:
        logger.error("Direct chat completion failed: %s", e)
        raise


# -- Core: run an agent -------------------------------------------------------

async def run_agent(agent_id: str, messages: list[dict], timeout: float = 120.0) -> str:
    """Run a Foundry agent, falling back to direct Chat Completions.

    Primary: Conversations + Responses API with agent_reference.
    Fallback: Direct chat.completions.create() when agent_reference unavailable.
    """
    global _agent_reference_available
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


# -- Admin helpers -------------------------------------------------------------

async def list_agents() -> list[dict]:
    """List deployments available in the Foundry project."""
    try:
        if settings.AZURE_AI_FOUNDRY_KEY:
            data = await _api_key_get("deployments")
            return [
                {
                    "id": d.get("name", ""),
                    "name": d.get("name", ""),
                    "model": d.get("modelName", ""),
                    "instructions": "",
                }
                for d in data.get("value", [])
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
        logger.error("Failed to list Foundry deployments: %s", e)
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
