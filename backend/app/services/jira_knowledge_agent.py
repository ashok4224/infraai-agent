"""Jira Knowledge Agent — enriches alert analysis with historical Jira data.

This module is called during alert analysis (Phase 2) to:
1. Search Jira for similar past incidents using the alert text
2. Search JSM Knowledge Base for relevant articles
3. Format the results as additional context for the AI prompt
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jira_config import JiraConfig
from app.models.alert import Alert
from app.services.jira_service import search_similar_issues, search_jsm_knowledge_base

logger = logging.getLogger(__name__)


async def gather_jira_context(db: AsyncSession, alert: Alert) -> dict:
    """Collect Jira issue history and KB articles relevant to this alert.

    Returns a dict with:
        - jira_similar_issues: list of matching issues
        - jira_kb_articles: list of KB articles
        - jira_summary: formatted text block for the AI prompt
    If no Jira configs are active, returns an empty dict.
    """
    result = await db.execute(
        select(JiraConfig).where(JiraConfig.is_active == True)
    )
    active_configs = result.scalars().all()
    if not active_configs:
        return {}

    # Build a search query from alert metadata
    search_text = _build_search_text(alert)
    if not search_text.strip():
        return {}

    all_issues = []
    all_articles = []

    for config in active_configs:
        try:
            issues_result = await search_similar_issues(config, search_text)
            for issue in issues_result.get("issues", []):
                issue["jira_config_name"] = config.name
                all_issues.append(issue)
        except Exception as e:
            logger.warning("Jira issue search failed for config '%s': %s", config.name, e)

        # Search KB if enabled
        if config.kb_enabled:
            try:
                kb_result = await search_jsm_knowledge_base(config, search_text)
                for article in kb_result.get("articles", []):
                    article["jira_config_name"] = config.name
                    all_articles.append(article)
            except Exception as e:
                logger.warning("Jira KB search failed for config '%s': %s", config.name, e)

    if not all_issues and not all_articles:
        return {}

    # Build a formatted summary for the AI prompt
    summary = _format_jira_context(all_issues, all_articles)

    return {
        "jira_similar_issues": all_issues,
        "jira_kb_articles": all_articles,
        "jira_summary": summary,
    }


def _build_search_text(alert: Alert) -> str:
    """Extract key searchable text from the alert for Jira queries."""
    parts = []
    if alert.alertname:
        parts.append(alert.alertname)
    if alert.summary:
        parts.append(alert.summary)
    if alert.description:
        # Truncate long descriptions to keep JQL manageable
        parts.append(alert.description[:200])

    # Also include key labels that might match Jira issue text
    labels = alert.labels or {}
    for key in ("job", "service", "component", "alertname"):
        if key in labels:
            parts.append(str(labels[key]))

    return " ".join(parts)


def _format_jira_context(issues: list, articles: list) -> str:
    """Format Jira data into a text block suitable for AI prompt injection."""
    sections = []

    if issues:
        sections.append("## Historical Jira Issues (Similar Past Incidents)")
        sections.append(
            "The following Jira issues were found that may be related to this alert. "
            "Use them to identify patterns, known root causes, and previously successful resolutions. "
            "If a past resolution directly applies, reference the Jira ticket in your analysis."
        )
        sections.append("")
        for i, issue in enumerate(issues[:8], 1):  # Cap at 8 issues
            sections.append(f"### {i}. [{issue['key']}] {issue.get('summary', '')}")
            sections.append(f"- **Status**: {issue.get('status', 'N/A')} | **Type**: {issue.get('issue_type', 'N/A')} | **Priority**: {issue.get('priority', 'N/A')}")
            if issue.get("resolution"):
                sections.append(f"- **Resolution**: {issue['resolution']}")
            if issue.get("labels"):
                sections.append(f"- **Labels**: {', '.join(issue['labels'])}")
            if issue.get("description_snippet"):
                sections.append(f"- **Description**: {issue['description_snippet'][:300]}")
            if issue.get("comments_snippet"):
                sections.append(f"- **Key Comments**: {issue['comments_snippet'][:400]}")
            sections.append(f"- **URL**: {issue.get('url', '')}")
            sections.append("")

    if articles:
        sections.append("## Knowledge Base Articles (JSM)")
        sections.append(
            "The following knowledge base articles were found that may contain "
            "documented solutions or runbooks for this type of issue."
        )
        sections.append("")
        for i, article in enumerate(articles[:5], 1):  # Cap at 5 articles
            sections.append(f"### KB {i}. {article.get('title', '')}")
            if article.get("snippet"):
                sections.append(f"{article['snippet'][:400]}")
            sections.append(f"- **URL**: {article.get('url', '')}")
            sections.append("")

    if sections:
        sections.append(
            "IMPORTANT: If any of the above Jira issues describe the SAME problem or a very "
            "similar root cause, reference the ticket key (e.g., PROJ-123) in your root_cause "
            "and action_plan. If a past resolution worked, recommend the same approach and note "
            "it was validated in a previous incident. Factor the historical data into your "
            "confidence_score — a matching past incident should INCREASE your confidence."
        )

    return "\n".join(sections)
