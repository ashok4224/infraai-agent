"""Knowledge source connectors — fetch documents from GitHub, SharePoint, Jira, ServiceNow, and uploads."""
import hashlib
import logging
import os
import tempfile
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from fnmatch import fnmatch

logger = logging.getLogger(__name__)


@dataclass
class RawDocument:
    """A single document fetched from a knowledge source."""
    title: str
    content: str
    file_path: str = ""
    doc_type: str = "text"
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def raw_size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


class KnowledgeConnector(ABC):
    """Base class for knowledge source connectors."""

    @abstractmethod
    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        """Fetch documents from the source, applying filters."""
        ...

    @abstractmethod
    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        """Test connectivity and return basic info."""
        ...

    @abstractmethod
    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        """Estimate document count matching filters without full fetch."""
        ...


# ── GitHub Connector ─────────────────────────────────────────────────────

class GitHubConnector(KnowledgeConnector):

    _SUPPORTED_EXTENSIONS = {
        ".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".tf", ".hcl",
        ".properties", ".cfg", ".ini", ".env.example", ".xml", ".toml",
    }

    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        from github import Github

        token = connection_config.get("token", "")
        repos = filter_config.get("repos", [])
        branch = filter_config.get("branch", "main")
        path_includes = filter_config.get("path_includes", [])
        path_excludes = filter_config.get("path_excludes", [])
        file_extensions = set(filter_config.get("file_extensions", list(self._SUPPORTED_EXTENSIONS)))
        max_file_size_kb = filter_config.get("max_file_size_kb", 500)

        g = Github(token) if token else Github()
        documents: List[RawDocument] = []

        for repo_name in repos:
            try:
                repo = g.get_repo(repo_name)
                tree = repo.get_git_tree(branch, recursive=True)
                for item in tree.tree:
                    if item.type != "blob":
                        continue
                    if not self._passes_filters(item.path, file_extensions, path_includes, path_excludes):
                        continue
                    if item.size and item.size > max_file_size_kb * 1024:
                        continue
                    # Check .ragignore
                    try:
                        blob = repo.get_git_blob(item.sha)
                        import base64
                        content = base64.b64decode(blob.content).decode("utf-8", errors="replace")
                    except Exception as e:
                        logger.warning("Failed to read %s/%s: %s", repo_name, item.path, e)
                        continue

                    ext = Path(item.path).suffix.lower()
                    doc_type = self._ext_to_type(ext)
                    documents.append(RawDocument(
                        title=item.path,
                        content=content,
                        file_path=f"{repo_name}/{item.path}",
                        doc_type=doc_type,
                        metadata={"repo": repo_name, "branch": branch, "sha": item.sha},
                    ))
            except Exception as e:
                logger.error("Failed to fetch repo %s: %s", repo_name, e)

        logger.info("GitHub: fetched %d documents from %d repos", len(documents), len(repos))
        return documents

    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        from github import Github
        token = connection_config.get("token", "")
        g = Github(token) if token else Github()
        repos = filter_config.get("repos", [])
        results = {}
        for repo_name in repos:
            try:
                repo = g.get_repo(repo_name)
                results[repo_name] = {"status": "ok", "default_branch": repo.default_branch}
            except Exception as e:
                results[repo_name] = {"status": "error", "error": str(e)}
        return {"repos": results}

    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        from github import Github
        token = connection_config.get("token", "")
        g = Github(token) if token else Github()
        repos = filter_config.get("repos", [])
        branch = filter_config.get("branch", "main")
        path_includes = filter_config.get("path_includes", [])
        path_excludes = filter_config.get("path_excludes", [])
        file_extensions = set(filter_config.get("file_extensions", list(self._SUPPORTED_EXTENSIONS)))
        max_file_size_kb = filter_config.get("max_file_size_kb", 500)

        total_files = 0
        total_size = 0
        for repo_name in repos:
            try:
                repo = g.get_repo(repo_name)
                tree = repo.get_git_tree(branch, recursive=True)
                for item in tree.tree:
                    if item.type != "blob":
                        continue
                    if not self._passes_filters(item.path, file_extensions, path_includes, path_excludes):
                        continue
                    if item.size and item.size > max_file_size_kb * 1024:
                        continue
                    total_files += 1
                    total_size += item.size or 0
            except Exception as e:
                logger.warning("Preview failed for %s: %s", repo_name, e)
        return {"estimated_documents": total_files, "estimated_size_bytes": total_size}

    def _passes_filters(self, path: str, extensions: set, includes: list, excludes: list) -> bool:
        ext = Path(path).suffix.lower()
        if extensions and ext not in extensions:
            return False
        if includes and not any(path.startswith(inc.rstrip("/")) for inc in includes):
            return False
        if excludes and any(path.startswith(exc.rstrip("/")) for exc in excludes):
            return False
        return True

    def _ext_to_type(self, ext: str) -> str:
        if ext in (".md", ".rst"):
            return "markdown"
        elif ext in (".yaml", ".yml"):
            return "yaml"
        elif ext in (".json",):
            return "json"
        elif ext in (".tf", ".hcl"):
            return "iac"
        return "text"


# ── SharePoint Connector ─────────────────────────────────────────────────

class SharePointConnector(KnowledgeConnector):

    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        from app.services.azure_graph_service import AzureGraphService
        from app.config import settings

        graph_service = AzureGraphService()
        site_ids = filter_config.get("site_ids", [])
        if not site_ids:
            site_ids = [settings.AZURE_SHAREPOINT_SITE_ID] if settings.AZURE_SHAREPOINT_SITE_ID else []

        doc_libraries = filter_config.get("document_libraries", [])
        folder_paths = filter_config.get("folder_paths", [])
        file_types = set(filter_config.get("file_types", [".md", ".txt", ".docx", ".pdf"]))
        exclude_patterns = filter_config.get("exclude_patterns", [])

        documents: List[RawDocument] = []
        for site_id in site_ids:
            try:
                items = await graph_service.list_drive_items(site_id, doc_libraries, folder_paths)
                for item in items:
                    name = item.get("name", "")
                    ext = Path(name).suffix.lower()
                    if file_types and ext not in file_types:
                        continue
                    if any(fnmatch(name, pat) for pat in exclude_patterns):
                        continue

                    content = await graph_service.download_drive_item_content(item["id"], site_id)
                    if not content:
                        continue

                    documents.append(RawDocument(
                        title=name,
                        content=content,
                        file_path=item.get("webUrl", name),
                        doc_type="markdown" if ext == ".md" else "text",
                        metadata={"site_id": site_id, "item_id": item["id"]},
                    ))
            except Exception as e:
                logger.error("SharePoint fetch failed for site %s: %s", site_id, e)

        logger.info("SharePoint: fetched %d documents", len(documents))
        return documents

    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        from app.services.azure_graph_service import AzureGraphService
        from app.config import settings
        graph_service = AzureGraphService()
        site_ids = filter_config.get("site_ids", [])
        if not site_ids:
            site_ids = [settings.AZURE_SHAREPOINT_SITE_ID] if settings.AZURE_SHAREPOINT_SITE_ID else []
        try:
            for sid in site_ids:
                await graph_service.get_site_info(sid)
            return {"status": "ok", "sites": len(site_ids)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        # For SharePoint, preview is similar to test — count matching items
        try:
            docs = await self.fetch_documents(connection_config, filter_config)
            return {"estimated_documents": len(docs), "estimated_size_bytes": sum(d.raw_size_bytes for d in docs)}
        except Exception as e:
            return {"estimated_documents": 0, "error": str(e)}


# ── Jira Connector ───────────────────────────────────────────────────────

class JiraConnector(KnowledgeConnector):

    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        from app.services.jira_service import JiraService
        from sqlalchemy.ext.asyncio import AsyncSession

        project_keys = filter_config.get("project_keys", [])
        issue_types = filter_config.get("issue_types", ["Incident", "Problem", "Bug"])
        statuses = filter_config.get("statuses", ["Done", "Resolved", "Closed"])
        labels = filter_config.get("labels", [])
        custom_jql = filter_config.get("custom_jql", "")
        updated_after = filter_config.get("updated_after", "")
        max_results = filter_config.get("max_results", 500)
        kb_space_keys = filter_config.get("kb_space_keys", [])

        # Build JQL
        if custom_jql:
            jql = custom_jql
        else:
            jql_parts = []
            if project_keys:
                jql_parts.append(f"project in ({', '.join(project_keys)})")
            if issue_types:
                types = ", ".join(f'"{t}"' for t in issue_types)
                jql_parts.append(f"issuetype in ({types})")
            if statuses:
                status_str = ", ".join(f'"{s}"' for s in statuses)
                jql_parts.append(f"status in ({status_str})")
            if labels:
                for label in labels:
                    jql_parts.append(f'labels = "{label}"')
            if updated_after:
                jql_parts.append(f'updated >= "{updated_after}"')
            jql = " AND ".join(jql_parts) if jql_parts else "resolution IS NOT EMPTY"
            jql += " ORDER BY updated DESC"

        documents: List[RawDocument] = []

        # Fetch issues via REST (using connection_config for auth)
        base_url = connection_config.get("base_url", "")
        auth_email = connection_config.get("auth_email", "")
        api_token = connection_config.get("api_token", "")

        if not base_url:
            logger.warning("Jira connector: no base_url configured")
            return documents

        import httpx
        import base64

        auth_header = base64.b64encode(f"{auth_email}:{api_token}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_header}", "Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                start_at = 0
                while start_at < max_results:
                    batch_size = min(50, max_results - start_at)
                    resp = await client.get(
                        f"{base_url.rstrip('/')}/rest/api/2/search",
                        params={"jql": jql, "startAt": start_at, "maxResults": batch_size,
                                "fields": "summary,description,comment,resolution,labels,status,issuetype,updated"},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    issues = data.get("issues", [])
                    if not issues:
                        break

                    for issue in issues:
                        fields = issue.get("fields", {})
                        parts = [
                            f"# {issue['key']}: {fields.get('summary', '')}",
                            f"**Type**: {fields.get('issuetype', {}).get('name', '')}",
                            f"**Status**: {fields.get('status', {}).get('name', '')}",
                            f"**Resolution**: {fields.get('resolution', {}).get('name', '') if fields.get('resolution') else 'Unresolved'}",
                        ]
                        if fields.get("description"):
                            parts.append(f"\n## Description\n{fields['description'][:3000]}")

                        comments = fields.get("comment", {}).get("comments", [])
                        if comments:
                            parts.append("\n## Comments")
                            for c in comments[-5:]:  # Last 5 comments
                                parts.append(f"- {c.get('body', '')[:500]}")

                        content = "\n".join(parts)
                        documents.append(RawDocument(
                            title=f"{issue['key']}: {fields.get('summary', '')}",
                            content=content,
                            file_path=f"{base_url}/browse/{issue['key']}",
                            doc_type="markdown",
                            metadata={"key": issue["key"], "issue_type": fields.get("issuetype", {}).get("name", "")},
                        ))

                    start_at += len(issues)
                    if start_at >= data.get("total", 0):
                        break
        except Exception as e:
            logger.error("Jira connector fetch failed: %s", e)

        # Confluence KB articles
        if kb_space_keys:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    for space_key in kb_space_keys:
                        cql = f'type = "page" AND space = "{space_key}" ORDER BY lastModified DESC'
                        resp = await client.get(
                            f"{base_url.rstrip('/')}/wiki/rest/api/content/search",
                            params={"cql": cql, "limit": min(max_results, 50), "expand": "body.storage"},
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            results = resp.json().get("results", [])
                            for article in results:
                                body = article.get("body", {}).get("storage", {}).get("value", "")
                                # Strip HTML tags for plain text
                                import re
                                clean_body = re.sub(r'<[^>]+>', ' ', body)[:5000]
                                documents.append(RawDocument(
                                    title=article.get("title", ""),
                                    content=clean_body,
                                    file_path=f"{base_url}/wiki{article.get('_links', {}).get('webui', '')}",
                                    doc_type="text",
                                    metadata={"space": space_key, "type": "confluence_kb"},
                                ))
            except Exception as e:
                logger.error("Confluence KB fetch failed: %s", e)

        logger.info("Jira: fetched %d documents (issues + KB)", len(documents))
        return documents

    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        import httpx, base64
        base_url = connection_config.get("base_url", "")
        auth_email = connection_config.get("auth_email", "")
        api_token = connection_config.get("api_token", "")
        auth_header = base64.b64encode(f"{auth_email}:{api_token}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/rest/api/2/myself",
                    headers={"Authorization": f"Basic {auth_header}", "Accept": "application/json"},
                )
                resp.raise_for_status()
                user = resp.json()
                return {"status": "ok", "user": user.get("displayName", "unknown")}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        # Quick JQL count
        import httpx, base64
        base_url = connection_config.get("base_url", "")
        auth_email = connection_config.get("auth_email", "")
        api_token = connection_config.get("api_token", "")
        auth_header = base64.b64encode(f"{auth_email}:{api_token}".encode()).decode()
        custom_jql = filter_config.get("custom_jql", "")
        if not custom_jql:
            parts = []
            for k, v in [("project_keys", "project in"), ("issue_types", "issuetype in"), ("statuses", "status in")]:
                vals = filter_config.get(k, [])
                if vals:
                    formatted = ", ".join(f'"{x}"' for x in vals)
                    parts.append(f"{v} ({formatted})")
            custom_jql = " AND ".join(parts) if parts else "resolution IS NOT EMPTY"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{base_url.rstrip('/')}/rest/api/2/search",
                    params={"jql": custom_jql, "maxResults": 0},
                    headers={"Authorization": f"Basic {auth_header}", "Accept": "application/json"},
                )
                resp.raise_for_status()
                total = resp.json().get("total", 0)
                return {"estimated_documents": total}
        except Exception as e:
            return {"estimated_documents": 0, "error": str(e)}


# ── ServiceNow Connector ────────────────────────────────────────────────

class ServiceNowConnector(KnowledgeConnector):

    async def _get_auth_headers(self, connection_config: dict) -> dict:
        auth_type = connection_config.get("auth_type", "basic")
        instance_url = connection_config.get("instance_url", "").rstrip("/")

        if auth_type == "oauth2":
            import httpx
            resp = await httpx.AsyncClient(timeout=15).post(
                f"{instance_url}/oauth_token.do",
                data={
                    "grant_type": "client_credentials",
                    "client_id": connection_config.get("client_id", ""),
                    "client_secret": connection_config.get("client_secret", ""),
                },
            )
            resp.raise_for_status()
            token = resp.json().get("access_token", "")
            return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        else:
            import base64
            username = connection_config.get("username", "")
            password = connection_config.get("password", "")
            auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def _build_query(self, filter_config: dict, table: str) -> str:
        parts = []
        if table in ("incident", "problem"):
            groups = filter_config.get("assignment_groups", [])
            if groups:
                parts.append(f"assignment_group.nameIN{','.join(groups)}")
            states = filter_config.get("state_filter", [])
            if states:
                state_map = {"New": "1", "In Progress": "2", "On Hold": "3",
                             "Resolved": "6", "Closed": "7", "Canceled": "8"}
                nums = [state_map.get(s, s) for s in states]
                parts.append(f"stateIN{','.join(nums)}")
            priorities = filter_config.get("priority_filter", [])
            if priorities:
                parts.append(f"priorityIN{','.join(priorities)}")
            ci_classes = filter_config.get("ci_classes", [])
            if ci_classes:
                parts.append(f"cmdb_ci.sys_class_nameIN{','.join(ci_classes)}")
        elif table == "kb_knowledge":
            categories = filter_config.get("kb_categories", [])
            if categories:
                parts.append(f"kb_category.sys_idIN{','.join(categories)}")
            parts.append("workflow_state=published")

        updated_after = filter_config.get("updated_after", "")
        if updated_after:
            parts.append(f"sys_updated_on>{updated_after}")

        return "^".join(parts) if parts else ""

    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        import httpx
        instance_url = connection_config.get("instance_url", "").rstrip("/")
        tables = filter_config.get("tables", ["incident", "problem", "kb_knowledge"])
        max_results = filter_config.get("max_results", 500)
        include_comments = filter_config.get("include_comments", True)
        include_resolution = filter_config.get("include_resolution", True)

        headers = await self._get_auth_headers(connection_config)
        documents: List[RawDocument] = []

        for table in tables:
            query = self._build_query(filter_config, table)
            fields = "number,short_description,description,close_notes,state,priority,sys_updated_on"
            if table == "kb_knowledge":
                fields = "number,short_description,text,sys_updated_on,kb_category"

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    offset = 0
                    while offset < max_results:
                        batch = min(100, max_results - offset)
                        params = {
                            "sysparm_query": query,
                            "sysparm_limit": batch,
                            "sysparm_offset": offset,
                            "sysparm_fields": fields,
                        }
                        resp = await client.get(
                            f"{instance_url}/api/now/table/{table}",
                            params=params,
                            headers=headers,
                        )
                        resp.raise_for_status()
                        records = resp.json().get("result", [])
                        if not records:
                            break

                        for record in records:
                            if table == "kb_knowledge":
                                content = f"# {record.get('short_description', '')}\n\n{record.get('text', '')}"
                                doc_type = "markdown"
                            else:
                                parts = [
                                    f"# {record.get('number', '')}: {record.get('short_description', '')}",
                                    f"**Priority**: {record.get('priority', '')}",
                                    f"**State**: {record.get('state', '')}",
                                ]
                                if record.get("description"):
                                    parts.append(f"\n## Description\n{record['description'][:3000]}")
                                if include_resolution and record.get("close_notes"):
                                    parts.append(f"\n## Resolution\n{record['close_notes'][:2000]}")
                                content = "\n".join(parts)
                                doc_type = "markdown"

                            documents.append(RawDocument(
                                title=f"{record.get('number', '')}: {record.get('short_description', '')}",
                                content=content,
                                file_path=f"{instance_url}/nav_to.do?uri=/{table}.do?sys_id={record.get('sys_id', '')}",
                                doc_type=doc_type,
                                metadata={"table": table, "number": record.get("number", "")},
                            ))

                        offset += len(records)
            except Exception as e:
                logger.error("ServiceNow fetch failed for table %s: %s", table, e)

        # Fetch work notes/comments for incidents if requested
        if include_comments and "incident" in tables:
            # Work notes are in sys_journal_field — skip for now to avoid excessive API calls
            pass

        logger.info("ServiceNow: fetched %d documents from %d tables", len(documents), len(tables))
        return documents

    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        import httpx
        instance_url = connection_config.get("instance_url", "").rstrip("/")
        try:
            headers = await self._get_auth_headers(connection_config)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{instance_url}/api/now/table/sys_user?sysparm_limit=1",
                    headers=headers,
                )
                resp.raise_for_status()
                return {"status": "ok", "instance": instance_url}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        import httpx
        instance_url = connection_config.get("instance_url", "").rstrip("/")
        tables = filter_config.get("tables", ["incident", "problem", "kb_knowledge"])
        total = 0
        try:
            headers = await self._get_auth_headers(connection_config)
            async with httpx.AsyncClient(timeout=15) as client:
                for table in tables:
                    query = self._build_query(filter_config, table)
                    resp = await client.get(
                        f"{instance_url}/api/now/stats/{table}",
                        params={"sysparm_query": query, "sysparm_count": "true"},
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        stats = resp.json().get("result", {}).get("stats", {})
                        total += int(stats.get("count", 0))
        except Exception as e:
            return {"estimated_documents": 0, "error": str(e)}
        return {"estimated_documents": total}


# ── Upload Connector ─────────────────────────────────────────────────────

class UploadConnector(KnowledgeConnector):

    UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "knowledge")

    async def fetch_documents(self, connection_config: dict, filter_config: dict) -> List[RawDocument]:
        allowed_ext = set(filter_config.get("allowed_extensions", [".md", ".txt", ".pdf", ".docx", ".yaml", ".json"]))
        max_size_kb = filter_config.get("max_file_size_kb", 5000)
        upload_dir = Path(self.UPLOAD_DIR)
        if not upload_dir.exists():
            return []

        documents: List[RawDocument] = []
        for fpath in upload_dir.rglob("*"):
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext not in allowed_ext:
                continue
            if fpath.stat().st_size > max_size_kb * 1024:
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                documents.append(RawDocument(
                    title=fpath.name,
                    content=content,
                    file_path=str(fpath.relative_to(upload_dir)),
                    doc_type="markdown" if ext == ".md" else "text",
                    metadata={"upload": True},
                ))
            except Exception as e:
                logger.warning("Failed to read uploaded file %s: %s", fpath, e)

        logger.info("Upload: fetched %d documents", len(documents))
        return documents

    async def test_connection(self, connection_config: dict, filter_config: dict) -> dict:
        upload_dir = Path(self.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        return {"status": "ok", "path": str(upload_dir)}

    async def preview(self, connection_config: dict, filter_config: dict) -> dict:
        docs = await self.fetch_documents(connection_config, filter_config)
        return {"estimated_documents": len(docs)}


# ── Connector factory ────────────────────────────────────────────────────

_CONNECTORS = {
    "github": GitHubConnector,
    "sharepoint": SharePointConnector,
    "jira": JiraConnector,
    "servicenow": ServiceNowConnector,
    "upload": UploadConnector,
}


def get_connector(source_type: str) -> KnowledgeConnector:
    cls = _CONNECTORS.get(source_type)
    if not cls:
        raise ValueError(f"Unknown source type: {source_type}. Supported: {list(_CONNECTORS.keys())}")
    return cls()
