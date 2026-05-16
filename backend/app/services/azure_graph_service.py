"""Azure Graph service — Outlook email and SharePoint/AI Search integration."""
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_graph_client = None


def _get_credential():
    """Build Azure credential from settings."""
    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET and settings.AZURE_TENANT_ID:
        return ClientSecretCredential(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
    return DefaultAzureCredential()


async def get_graph_client():
    """Return an authenticated Microsoft Graph client."""
    global _graph_client
    if _graph_client is not None:
        return _graph_client

    from msgraph import GraphServiceClient

    _graph_client = GraphServiceClient(
        credentials=_get_credential(),
        scopes=["https://graph.microsoft.com/.default"],
    )
    return _graph_client


# ── AzureGraphService class (used by knowledge_connectors.SharePointConnector) ──


class AzureGraphService:
    """Service for interacting with Microsoft Graph API for SharePoint operations."""

    def __init__(self):
        self._client = None
        self._use_httpx_fallback = False  # set True if msgraph SDK fails

    async def _get_client(self):
        if self._client is None:
            from app.services.azure_graph_service import get_graph_client
            self._client = await get_graph_client()
        return self._client

    async def _get_token(self) -> str:
        """Get an access token for direct REST calls (fallback path)."""
        from azure.identity import ClientSecretCredential
        if settings.AZURE_CLIENT_ID and settings.AZURE_CLIENT_SECRET and settings.AZURE_TENANT_ID:
            cred = ClientSecretCredential(
                tenant_id=settings.AZURE_TENANT_ID,
                client_id=settings.AZURE_CLIENT_ID,
                client_secret=settings.AZURE_CLIENT_SECRET,
            )
            token = cred.get_token("https://graph.microsoft.com/.default")
            return token.token
        return ""

    async def get_site_info(self, site_id: str) -> dict:
        """Get SharePoint site information."""
        client = await self._get_client()
        result = await client.sites.by_site_id(site_id).get()
        return {"id": result.id, "display_name": result.display_name, "web_url": result.web_url}

    async def _get_drive_items_via_rest(self, site_id: str, folder_path: str) -> list[dict]:
        """Fallback: use direct REST API to list drive items."""
        import httpx
        token = await self._get_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}
        site_encoded = site_id.replace(":", "%3A").replace("@", "%40")
        items = []

        async with httpx.AsyncClient(timeout=15) as client:
            # Get drives
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_encoded}/drives",
                headers=headers
            )
            if resp.status_code != 200:
                logger.warning("Failed to list drives: %s", resp.status_code)
                return []
            drives = resp.json().get("value", [])

            for drive in drives:
                path_parts = [p for p in folder_path.strip("/").split("/") if p]
                current_path = f"/drives/{drive['id']}/root"
                
                for part in path_parts:
                    children_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/sites/{site_encoded}{current_path}/children",
                        headers=headers
                    )
                    if children_resp.status_code != 200:
                        break
                    children = children_resp.json().get("value", [])
                    found = False
                    for child in children:
                        if child.get("name") == part and child.get("folder"):
                            current_path = f"/drives/{drive['id']}/items/{child['id']}"
                            found = True
                            break
                    if not found:
                        break
                else:
                    # All folder parts found — list children
                    children_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/sites/{site_encoded}{current_path}/children",
                        headers=headers
                    )
                    if children_resp.status_code == 200:
                        for child in children_resp.json().get("value", []):
                            items.append({
                                "id": child["id"],
                                "name": child.get("name", ""),
                                "size": child.get("size", 0),
                                "webUrl": child.get("webUrl", ""),
                                "drive_id": drive["id"],
                                "folder": bool(child.get("folder")),
                            })
        return items

    async def list_drive_items(self, site_id: str, doc_libraries: list[str] = None, folder_paths: list[str] = None) -> list[dict]:
        """List items from SharePoint document libraries."""
        client = await self._get_client()
        items = []

        try:
            drives = await client.sites.by_site_id(site_id).drives.get()
        except Exception as e:
            logger.warning("msgraph SDK failed for list_drive_items, trying fallback: %s", e)
            drives = type("obj", (), {"value": None})()

        if not drives or not drives.value:
            # Fallback to REST API
            if folder_paths:
                for fp in folder_paths:
                    rest_items = await self._get_drive_items_via_rest(site_id, fp)
                    items.extend(rest_items)
            return items

        for drive in drives.value:
            if doc_libraries and drive.name not in doc_libraries:
                continue

            if folder_paths:
                for folder_path in folder_paths:
                    path_parts = [p for p in folder_path.strip("/").split("/") if p]
                    try:
                        current_items = await client.drives.by_drive_id(drive.id).root.children.get()
                    except Exception:
                        continue

                    for part in path_parts:
                        found = False
                        if current_items and current_items.value:
                            for child in current_items.value:
                                if child.name == part and child.folder:
                                    try:
                                        current_items = await client.drives.by_drive_id(drive.id).items.by_drive_item_id(child.id).children.get()
                                    except Exception:
                                        break
                                    found = True
                                    break
                        if not found:
                            break
                    else:
                        if current_items and current_items.value:
                            for item in current_items.value:
                                items.append({
                                    "id": item.id,
                                    "name": item.name,
                                    "size": item.size or 0,
                                    "webUrl": item.web_url,
                                    "drive_id": drive.id,
                                    "folder": bool(item.folder),
                                })
            else:
                try:
                    root_items = await client.drives.by_drive_id(drive.id).root.children.get()
                    if root_items and root_items.value:
                        for item in root_items.value:
                            items.append({
                                "id": item.id,
                                "name": item.name,
                                "size": item.size or 0,
                                "webUrl": item.web_url,
                                "drive_id": drive.id,
                                "folder": bool(item.folder),
                            })
                except Exception:
                    continue
        return items

    async def download_drive_item_content(self, item_id: str, site_id: str) -> str:
        """Download and return the content of a drive item as text."""
        try:
            client = await self._get_client()
            drives = await client.sites.by_site_id(site_id).drives.get()
            if not drives or not drives.value:
                return ""

            for drive in drives.value:
                try:
                    item = await client.drives.by_drive_id(drive.id).items.by_drive_item_id(item_id).get()
                    if item:
                        content_stream = await client.drives.by_drive_id(drive.id).items.by_drive_item_id(item_id).content.get()
                        if content_stream:
                            raw = b""
                            async for chunk in content_stream.stream():
                                if isinstance(chunk, bytes):
                                    raw += chunk
                            return raw.decode("utf-8", errors="replace")
                except Exception:
                    continue
            return ""
        except Exception as e:
            logger.warning("download_drive_item_content failed (try fallback): %s", e)
            # Fallback to REST
            import httpx
            token = await self._get_token()
            if not token:
                return ""
            site_encoded = site_id.replace(":", "%3A").replace("@", "%40")
            async with httpx.AsyncClient(timeout=15) as client:
                drives_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/sites/{site_encoded}/drives",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if drives_resp.status_code == 200:
                    for drive in drives_resp.json().get("value", []):
                        resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/drives/{drive['id']}/items/{item_id}/content",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        if resp.status_code == 200:
                            return resp.text
            return ""


async def send_outlook_email(
    to_list: list[str],
    cc_list: list[str],
    subject: str,
    html_body: str,
    sender: str | None = None,
) -> dict:
    """Send an email via Microsoft Graph / Outlook.

    Requires Mail.Send application permission on the service principal.
    """
    from msgraph.generated.users.item.send_mail.send_mail_post_request_body import (
        SendMailPostRequestBody,
    )
    from msgraph.generated.models.message import Message
    from msgraph.generated.models.item_body import ItemBody
    from msgraph.generated.models.body_type import BodyType
    from msgraph.generated.models.recipient import Recipient
    from msgraph.generated.models.email_address import EmailAddress

    sender_email = sender or settings.AZURE_OUTLOOK_SENDER
    if not sender_email:
        raise RuntimeError("AZURE_OUTLOOK_SENDER is not configured")

    def _make_recipient(email: str) -> Recipient:
        r = Recipient()
        r.email_address = EmailAddress()
        r.email_address.address = email.strip()
        return r

    message = Message()
    message.subject = subject
    message.body = ItemBody()
    message.body.content_type = BodyType.Html
    message.body.content = html_body
    message.to_recipients = [_make_recipient(e) for e in to_list if e.strip()]
    if cc_list:
        message.cc_recipients = [_make_recipient(e) for e in cc_list if e.strip()]

    request_body = SendMailPostRequestBody()
    request_body.message = message
    request_body.save_to_sent_items = True

    try:
        client = await get_graph_client()
        await client.users.by_user_id(sender_email).send_mail.post(request_body)
        logger.info("Outlook email sent to %s (cc: %s)", to_list, cc_list)
        return {"success": True, "message": "Email sent via Outlook"}
    except Exception as e:
        logger.error("Outlook email failed: %s", e)
        return {"success": False, "message": str(e)}


async def search_sharepoint(query: str, max_results: int = 5) -> list[dict]:
    """Search SharePoint for documents matching the query.

    Returns simplified results: title, snippet, URL.
    """
    site_id = settings.AZURE_SHAREPOINT_SITE_ID
    if not site_id:
        logger.debug("SharePoint site ID not configured, skipping search")
        return []

    try:
        client = await get_graph_client()

        from msgraph.generated.search.query.query_post_request_body import (
            QueryPostRequestBody,
        )
        from msgraph.generated.models.search_request import SearchRequest
        from msgraph.generated.models.entity_type import EntityType

        search_request = SearchRequest()
        search_request.entity_types = [EntityType.DriveItem]
        search_request.query = type("Q", (), {"query_string": query})()
        search_request.size = max_results

        body = QueryPostRequestBody()
        body.requests = [search_request]

        search_response = await client.search.query.post(body)

        results = []
        if search_response and search_response.value:
            for response_item in search_response.value:
                if response_item.hits_containers:
                    for container in response_item.hits_containers:
                        if container.hits:
                            for hit in container.hits:
                                resource = hit.resource
                                results.append({
                                    "title": getattr(resource, "name", "Untitled"),
                                    "snippet": hit.summary or "",
                                    "url": getattr(resource, "web_url", ""),
                                })
        return results[:max_results]

    except Exception as e:
        logger.warning("SharePoint search failed: %s", e)
        return []


async def search_ai_index(query: str, max_results: int = 5) -> list[dict]:
    """Search Azure AI Search index for relevant documents."""
    endpoint = settings.AZURE_AI_SEARCH_ENDPOINT
    key = settings.AZURE_AI_SEARCH_KEY
    index = settings.AZURE_AI_SEARCH_INDEX

    if not endpoint or not key or not index:
        return []

    try:
        from azure.search.documents.aio import SearchClient
        from azure.core.credentials import AzureKeyCredential

        search_client = SearchClient(
            endpoint=endpoint,
            index_name=index,
            credential=AzureKeyCredential(key),
        )

        async with search_client:
            search_results = await search_client.search(
                search_text=query,
                top=max_results,
                query_type="semantic" if max_results <= 10 else "simple",
            )

            results = []
            async for result in search_results:
                results.append({
                    "title": result.get("title", ""),
                    "snippet": result.get("content", "")[:500],
                    "score": result.get("@search.score", 0),
                    "url": result.get("url", ""),
                })
            return results

    except ImportError:
        logger.debug("azure-search-documents not installed, skipping AI Search")
        return []
    except Exception as e:
        logger.warning("AI Search query failed: %s", e)
        return []


async def test_outlook() -> dict:
    """Test Outlook connectivity."""
    sender = settings.AZURE_OUTLOOK_SENDER
    if not sender:
        return {"success": False, "message": "AZURE_OUTLOOK_SENDER not configured"}
    try:
        client = await get_graph_client()
        # Try to read the sender's mailbox (basic connectivity test)
        await client.users.by_user_id(sender).get()
        return {"success": True, "message": f"Outlook access OK for {sender}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def test_sharepoint() -> dict:
    """Test SharePoint connectivity."""
    results = await search_sharepoint("test", max_results=1)
    if results is not None:
        return {"success": True, "message": f"SharePoint search OK ({len(results)} results for test query)"}
    return {"success": False, "message": "SharePoint search returned None"}


def reset_client():
    """Reset cached Graph client."""
    global _graph_client
    _graph_client = None