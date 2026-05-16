"""Foundry configuration router ??? manage Azure AI Foundry agent registry."""
import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.foundry_config import FoundryAgentConfig
from app.schemas.foundry_config import (
    FoundryAgentConfigResponse,
    FoundryAgentConfigCreate,
    FoundryAgentConfigUpdate,
    FoundryTestResult,
)
from app.auth.jwt_handler import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config", response_model=List[FoundryAgentConfigResponse])
async def list_foundry_agents(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """List all registered Foundry agents."""
    result = await db.execute(
        select(FoundryAgentConfig).order_by(FoundryAgentConfig.pipeline_order)
    )
    return result.scalars().all()


@router.post("/config", response_model=FoundryAgentConfigResponse, status_code=201)
async def create_foundry_agent(
    payload: FoundryAgentConfigCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Register a new Foundry agent in the pipeline."""
    agent = FoundryAgentConfig(**payload.model_dump())
    db.add(agent)
    await db.flush()
    await db.commit()
    await db.refresh(agent)
    return agent


@router.put("/config/{agent_id}", response_model=FoundryAgentConfigResponse)
async def update_foundry_agent(
    agent_id: UUID,
    payload: FoundryAgentConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Update a Foundry agent configuration."""
    result = await db.execute(
        select(FoundryAgentConfig).where(FoundryAgentConfig.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.flush()
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/config/{agent_id}", status_code=204)
async def delete_foundry_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Remove a Foundry agent from the registry."""
    result = await db.execute(
        select(FoundryAgentConfig).where(FoundryAgentConfig.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.flush()
    await db.commit()


@router.post("/test", response_model=FoundryTestResult)
async def test_foundry_connection(
    _user: User = Depends(require_admin),
):
    """Test connectivity to Azure AI Foundry."""
    try:
        from app.services.azure_foundry_service import test_connection
        result = await test_connection()
        return FoundryTestResult(**result)
    except ImportError:
        return FoundryTestResult(
            success=False,
            message="Azure AI Foundry SDK not installed (azure-ai-projects package missing)",
        )
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


@router.post("/test-agent/{agent_id}", response_model=FoundryTestResult)
async def test_foundry_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Test a specific Foundry agent."""
    result = await db.execute(
        select(FoundryAgentConfig).where(FoundryAgentConfig.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.foundry_agent_name:
        return FoundryTestResult(success=False, message="No Foundry agent name configured")

    try:
        from app.services.azure_foundry_service import test_agent
        result = await test_agent(agent.foundry_agent_name)
        return FoundryTestResult(**result)
    except ImportError:
        return FoundryTestResult(success=False, message="Azure SDK not installed")
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


@router.get("/status", response_model=dict)
async def foundry_pipeline_status(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    """Get the overall Foundry pipeline health status."""
    from app.config import settings as app_settings

    status = {
        "configured": bool(app_settings.AZURE_AI_FOUNDRY_ENDPOINT),
        "endpoint": app_settings.AZURE_AI_FOUNDRY_ENDPOINT or None,
        "project": app_settings.AZURE_AI_FOUNDRY_PROJECT or None,
        "outlook_configured": bool(app_settings.AZURE_OUTLOOK_SENDER),
        "sharepoint_configured": bool(app_settings.AZURE_SHAREPOINT_SITE_ID),
        "ai_search_configured": bool(app_settings.AZURE_AI_SEARCH_ENDPOINT),
        "agents": [],
    }

    result = await db.execute(
        select(FoundryAgentConfig).order_by(FoundryAgentConfig.pipeline_order)
    )
    agents = result.scalars().all()
    for agent in agents:
        status["agents"].append({
            "name": agent.agent_name,
            "agent_line": getattr(agent, "agent_line", "workflow"),
            "role": agent.role,
            "system_type": agent.system_type,
            "has_agent_name": bool(agent.foundry_agent_name),
            "is_active": agent.is_active,
            "order": agent.pipeline_order,
        })

    return status


@router.post("/test-outlook", response_model=FoundryTestResult)
async def test_outlook(
    _user: User = Depends(require_admin),
):
    """Test Outlook email connectivity."""
    try:
        from app.services.azure_graph_service import test_outlook
        result = await test_outlook()
        return FoundryTestResult(**result)
    except ImportError:
        return FoundryTestResult(success=False, message="msgraph-sdk not installed")
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


@router.post("/test-sharepoint", response_model=FoundryTestResult)
async def test_sharepoint(
    _user: User = Depends(require_admin),
):
    """Test SharePoint/AI Search connectivity."""
    try:
        from app.services.azure_graph_service import test_sharepoint
        result = await test_sharepoint()
        return FoundryTestResult(**result)
    except ImportError:
        return FoundryTestResult(success=False, message="msgraph-sdk not installed")
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


@router.post("/setup-knowledge-search", response_model=FoundryTestResult)
async def setup_knowledge_search(
    _user: User = Depends(require_admin),
):
    """One-time setup: enable file_search tool on the infraai-knowledge agent
    and attach the infraai-knowledge-store vector store.

    Call this once after deploying.  Safe to call multiple times (idempotent).
    """
    try:
        from app.services.azure_foundry_service import setup_knowledge_agent_file_search
        result = await setup_knowledge_agent_file_search()
        return FoundryTestResult(**result)
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


@router.get("/knowledge-store-files", response_model=FoundryTestResult)
async def list_knowledge_files(
    _user: User = Depends(require_admin),
):
    """List all files currently in the Foundry knowledge vector store."""
    try:
        from app.services.azure_foundry_service import list_knowledge_store_files
        files = await list_knowledge_store_files()
        return FoundryTestResult(
            success=True,
            message=f"{len(files)} file(s) in infraai-knowledge-store",
            response_preview=str([f.get("id") for f in files]),
        )
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))


class SharePointGroundingRequest(BaseModel):
    site_url: str          # e.g. https://mywinfo.sharepoint.com/sites/DBAGroup
    tenant_id: str
    client_id: str
    client_secret: str
    connection_name: str = "sharepoint-dbagroup"


@router.post("/setup-sharepoint-grounding", response_model=FoundryTestResult)
async def setup_sharepoint_grounding(
    req: SharePointGroundingRequest,
    _user: User = Depends(require_admin),
):
    """Connect SharePoint to the infraai-knowledge agent via sharepoint_grounding.

    This creates a Foundry SharePoint connection and configures the agent to
    search SharePoint LIVE on every query ??? no file sync or vector store needed
    for SharePoint content.

    Requires the app registration to have Sites.Read.All + Files.Read.All
    Microsoft Graph permissions granted.
    """
    try:
        from app.services.azure_foundry_service import setup_sharepoint_grounding as _setup
        result = await _setup(
            site_url=req.site_url,
            tenant_id=req.tenant_id,
            client_id=req.client_id,
            client_secret=req.client_secret,
            connection_name=req.connection_name,
        )
        return FoundryTestResult(**result)
    except Exception as e:
        return FoundryTestResult(success=False, message=str(e))

