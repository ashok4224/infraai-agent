"""Azure AI Foundry service - azure-ai-projects v2.x SDK wrapper.

Uses the Conversations + Responses API (v2.x pattern):
  project_client.get_openai_client()    -> openai_client
  openai_client.conversations.create()  -> conversation
  openai_client.responses.create()      -> agent response
  openai_client.conversations.delete()  -> cleanup

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


# -- Credentials -------------------------------------------------------------

def _get_credential_async():
    """Build an async Azure credential from settings."""
    from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential

    if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET and settings.AZURE_TENANT_ID:
        return ClientSecretCredential(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
    return DefaultAzureCredential()


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


# -- Core: run an agent -------------------------------------------------------

async def run_agent(agent_id: str, messages: list[dict], timeout: float = 120.0) -> str:
    """Run a Foundry agent using the Conversations + Responses API.

    ``agent_id`` is the agent name registered in Microsoft Foundry.
    Flow:
      1. Create a conversation with the caller's messages.
      2. Call responses.create() with an agent_reference.
      3. Return the agent's text response.
      4. Delete the conversation to clean up.
    """
    _, openai_client = await _ensure_clients()

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