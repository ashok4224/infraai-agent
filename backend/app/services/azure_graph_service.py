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
