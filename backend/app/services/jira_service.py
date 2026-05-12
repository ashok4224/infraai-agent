"""Jira & Jira Service Management integration service.

Connects to Jira Cloud or Server/Data Center via REST API to:
- Search for similar historical issues (incidents, bugs, problems)
- Retrieve knowledge base articles from Confluence spaces
- Validate connectivity (health check)
"""
import logging
import asyncio
from typing import Optional
from datetime import datetime, timezone

import httpx

from app.models.jira_config import JiraConfig

logger = logging.getLogger(__name__)

# Jira REST API paths
_API_V2 = "/rest/api/2"
_API_V3 = "/rest/api/3"  # Cloud uses v3
_AGILE_API = "/rest/agile/1.0"
_SERVICE_DESK_API = "/rest/servicedeskapi"


def _auth_headers(config: JiraConfig) -> dict:
    """Build authentication headers for Jira API requests."""
    import base64
    if config.instance_type == "cloud":
        # Cloud: Basic auth with email + API token
        creds = f"{config.auth_email}:{config.api_token}"
    else:
        # Server/DC: Basic auth with username + PAT (or password)
        creds = f"{config.auth_email}:{config.api_token}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _api_base(config: JiraConfig) -> str:
    """Return the correct REST API base for cloud vs server."""
    base = config.base_url.rstrip("/")
    return f"{base}{_API_V3}" if config.instance_type == "cloud" else f"{base}{_API_V2}"


async def check_jira_health(config: JiraConfig) -> dict:
    """Verify Jira connectivity by hitting the server info endpoint."""
    base = config.base_url.rstrip("/")
    url = f"{base}{_API_V2}/serverInfo"
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            resp = await client.get(url, headers=_auth_headers(config))
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": "healthy",
                    "server_title": data.get("serverTitle", ""),
                    "version": data.get("version", ""),
                    "deployment_type": data.get("deploymentType", config.instance_type),
                }
            elif resp.status_code == 401:
                return {"status": "unhealthy", "error": "Authentication failed — check email and API token"}
            elif resp.status_code == 403:
                return {"status": "unhealthy", "error": "Permission denied — check API token scopes"}
            else:
                return {"status": "unhealthy", "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    except httpx.ConnectError as e:
        return {"status": "unreachable", "error": f"Cannot connect to {base}: {e}"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)[:300]}


async def search_similar_issues(
    config: JiraConfig,
    search_text: str,
    max_results: Optional[int] = None,
) -> dict:
    """Search Jira for issues similar to the given alert text using JQL text search.

    Returns a dict with 'total' and 'issues' list.
    """
    limit = max_results or config.max_results or 10
    # Build JQL
    jql_parts = [f'text ~ "{_escape_jql(search_text)}"']

    if config.project_keys:
        keys = ", ".join(config.project_keys)
        jql_parts.append(f"project in ({keys})")

    if config.issue_types_filter:
        types = ", ".join(f'"{t}"' for t in config.issue_types_filter)
        jql_parts.append(f"issuetype in ({types})")

    if config.status_filter:
        statuses = ", ".join(f'"{s}"' for s in config.status_filter)
        jql_parts.append(f"status in ({statuses})")

    if config.label_filter:
        labels = ", ".join(f'"{lb}"' for lb in config.label_filter)
        jql_parts.append(f"labels in ({labels})")

    jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

    # Cloud instances must use the new JQL search endpoint (/search/jql)
    if config.instance_type == "cloud":
        url = f"{config.base_url.rstrip('/')}/rest/api/3/search/jql"
    else:
        api_base = _api_base(config)
        url = f"{api_base}/search"
    params = {
        "jql": jql,
        "maxResults": limit,
        "fields": "summary,status,issuetype,priority,resolution,description,labels,created,updated,comment",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
            resp = await client.get(url, headers=_auth_headers(config), params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Jira search failed: HTTP %s — %s", e.response.status_code, e.response.text[:300])
        return {"total": 0, "issues": [], "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error("Jira search error: %s", e)
        return {"total": 0, "issues": [], "error": str(e)[:300]}

    issues = []
    for item in data.get("issues", []):
        fields = item.get("fields", {})
        desc_raw = fields.get("description") or ""
        # Cloud API v3 returns desc as ADF (dict); v2 returns string
        if isinstance(desc_raw, dict):
            desc_snippet = _extract_adf_text(desc_raw)[:500]
        else:
            desc_snippet = str(desc_raw)[:500]

        # Collect top comments as additional context
        comments_text = ""
        comment_data = fields.get("comment", {})
        if isinstance(comment_data, dict):
            for c in (comment_data.get("comments") or [])[:3]:
                body = c.get("body", "")
                if isinstance(body, dict):
                    body = _extract_adf_text(body)
                comments_text += f"\n---\n{body[:300]}"

        issues.append({
            "key": item["key"],
            "summary": fields.get("summary", ""),
            "status": (fields.get("status") or {}).get("name", ""),
            "issue_type": (fields.get("issuetype") or {}).get("name", ""),
            "priority": (fields.get("priority") or {}).get("name"),
            "resolution": (fields.get("resolution") or {}).get("name") if fields.get("resolution") else None,
            "description_snippet": desc_snippet,
            "comments_snippet": comments_text[:800] if comments_text else None,
            "labels": fields.get("labels", []),
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "url": f"{config.base_url.rstrip('/')}/browse/{item['key']}",
        })

    return {"total": data.get("total", 0), "issues": issues}


async def search_jsm_knowledge_base(
    config: JiraConfig,
    search_text: str,
    max_results: int = 5,
) -> dict:
    """Search Jira Service Management knowledge base articles.

    JSM KB articles are backed by Confluence. This uses the Confluence REST API
    to search within the configured space keys.
    """
    if not config.jsm_enabled or not config.kb_enabled:
        return {"total": 0, "articles": []}

    base = config.base_url.rstrip("/")
    # Confluence Cloud is at the same domain as Jira Cloud
    confluence_api = f"{base}/wiki/rest/api"
    if config.instance_type != "cloud":
        # Server: Confluence may be on a different URL; fall back to same host
        confluence_api = f"{base}/rest/api"

    cql_parts = [f'text ~ "{_escape_jql(search_text)}" AND type = "page"']
    if config.kb_space_keys:
        spaces = " OR ".join(f'space = "{sk}"' for sk in config.kb_space_keys)
        cql_parts.append(f"({spaces})")
    cql = " AND ".join(cql_parts)

    url = f"{confluence_api}/content/search"
    params = {
        "cql": cql,
        "limit": max_results,
        "expand": "body.view,space",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
            resp = await client.get(url, headers=_auth_headers(config), params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Confluence KB search failed: %s", e)
        return {"total": 0, "articles": [], "error": str(e)[:300]}

    articles = []
    for item in data.get("results", []):
        body_html = (item.get("body", {}).get("view", {}).get("value") or "")
        # Strip HTML tags for a plain-text snippet
        import re
        plain = re.sub(r"<[^>]+>", " ", body_html)
        plain = re.sub(r"\s+", " ", plain).strip()

        articles.append({
            "title": item.get("title", ""),
            "space": (item.get("space") or {}).get("key", ""),
            "snippet": plain[:600],
            "url": f"{base}/wiki{item.get('_links', {}).get('webui', '')}",
        })

    return {"total": data.get("size", len(articles)), "articles": articles}


async def get_issue_detail(config: JiraConfig, issue_key: str) -> dict:
    """Fetch a single Jira issue with full description and comments."""
    api_base = _api_base(config)
    url = f"{api_base}/issue/{issue_key}"
    params = {"fields": "summary,status,issuetype,priority,resolution,description,labels,comment,created,updated"}

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            resp = await client.get(url, headers=_auth_headers(config), params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"error": str(e)[:300]}

    fields = data.get("fields", {})
    desc_raw = fields.get("description") or ""
    if isinstance(desc_raw, dict):
        description = _extract_adf_text(desc_raw)
    else:
        description = str(desc_raw)

    comments = []
    comment_data = fields.get("comment", {})
    if isinstance(comment_data, dict):
        for c in (comment_data.get("comments") or []):
            body = c.get("body", "")
            if isinstance(body, dict):
                body = _extract_adf_text(body)
            comments.append({
                "author": (c.get("author") or {}).get("displayName", "Unknown"),
                "body": str(body)[:500],
                "created": c.get("created"),
            })

    return {
        "key": data["key"],
        "summary": fields.get("summary", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "issue_type": (fields.get("issuetype") or {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name"),
        "resolution": (fields.get("resolution") or {}).get("name") if fields.get("resolution") else None,
        "description": description[:3000],
        "labels": fields.get("labels", []),
        "comments": comments[-10:],  # last 10 comments
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "url": f"{config.base_url.rstrip('/')}/browse/{data['key']}",
    }


# ────────────────────── Helpers ──────────────────────

def _escape_jql(text: str) -> str:
    """Escape special JQL characters in user-supplied text."""
    # Remove characters that break JQL string literals
    for ch in ['"', "\\", "\n", "\r", "\t"]:
        text = text.replace(ch, " ")
    # Collapse multiple spaces and truncate to avoid overly long queries
    text = " ".join(text.split())
    return text[:200]


def _extract_adf_text(adf: dict) -> str:
    """Recursively extract plain text from an Atlassian Document Format node."""
    if not isinstance(adf, dict):
        return str(adf)
    parts = []
    if adf.get("type") == "text":
        parts.append(adf.get("text", ""))
    for child in adf.get("content", []):
        parts.append(_extract_adf_text(child))
    return " ".join(parts)
