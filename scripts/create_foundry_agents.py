"""
Create Azure AI Foundry agents and seed foundry_agent_configs table.
Run inside the backend pod:
  kubectl cp scripts/create_foundry_agents.py infraai/<pod>:/tmp/create_foundry_agents.py
  kubectl exec -n infraai <pod> -- python3 /tmp/create_foundry_agents.py
"""
import httpx
import asyncio
import json
import sys
import os

sys.path.insert(0, "/app")

ENDPOINT = "https://winfo-infra-agent-resource.services.ai.azure.com/api/projects/infra-agent"
API_KEY = os.environ.get("AZURE_AI_FOUNDRY_KEY", "")
MODEL = "gpt-4o"
API_VERSION = "2024-05-01-preview"

HEADERS = {
    "api-key": API_KEY,
    "Content-Type": "application/json",
}

AGENTS = [
    {
        "name": "infraai-researcher",
        "instructions": (
            "You are the diagnostic researcher agent for an SRE/Ops AI platform. "
            "Given an alert, triage brief, and knowledge context, produce a targeted diagnostic plan. "
            "Suggest SQL queries in ```sql blocks and OS commands in ```bash blocks. "
            "Label every query/command with a short name. "
            "Order steps: quick checks first, expensive queries last. "
            "Do NOT include destructive commands."
        ),
        "role": "researcher",
        "pipeline_order": 30,
        "system_type": "all",
        "agent_line": "workflow",
        "is_optional": False,
    },
    {
        "name": "infraai-solver",
        "instructions": (
            "You are an expert SRE/DBA solver agent. "
            "Given an alert, diagnostic data, and knowledge context, produce a complete incident analysis. "
            "Your response MUST be valid JSON with these fields: "
            "problem_statement (plain English, reference specific metrics), "
            "root_cause, confidence_score (0.0-1.0), "
            "action_plan (array of steps), "
            "fix_commands (array with type/description/command/risk_level/requires_approval), "
            "prevention_steps, risk_level (Low/Medium/High/Critical)."
        ),
        "role": "solver",
        "pipeline_order": 60,
        "system_type": "all",
        "agent_line": "workflow",
        "is_optional": False,
    },
    {
        "name": "infraai-notifier",
        "instructions": (
            "You are a notification formatting agent. "
            "Given an incident analysis JSON, format a concise professional summary "
            "suitable for an operations team. Include: severity, problem summary, "
            "action items with commands, and risk assessment. Keep it scannable."
        ),
        "role": "notifier",
        "pipeline_order": 80,
        "system_type": "all",
        "agent_line": "workflow",
        "is_optional": True,
    },
]


async def create_or_get_agent(client, name, instructions):
    """Create agent if it doesn't exist, return its id."""
    # Check existing
    r = await client.get(f"{ENDPOINT}/assistants?api-version={API_VERSION}")
    if r.status_code == 200:
        existing = r.json().get("data", [])
        for a in existing:
            if a.get("name") == name:
                print(f"  {name}: already exists (id={a['id']})")
                return a["id"]

    # Create
    payload = {"model": MODEL, "name": name, "instructions": instructions}
    r = await client.post(
        f"{ENDPOINT}/assistants?api-version={API_VERSION}",
        json=payload,
    )
    if r.status_code in (200, 201):
        data = r.json()
        agent_id = data.get("id") or data.get("name")
        print(f"  {name}: created (id={agent_id})")
        return agent_id
    else:
        print(f"  {name}: FAILED {r.status_code} - {r.text[:200]}")
        return None


async def seed_db(agent_name_map):
    """Insert foundry_agent_configs rows."""
    from app.database import async_session
    from app.models.foundry_config import FoundryAgentConfig
    from sqlalchemy import select, delete

    async with async_session() as db:
        # Clear existing
        await db.execute(delete(FoundryAgentConfig))
        await db.commit()

        for agent_def in AGENTS:
            foundry_id = agent_name_map.get(agent_def["name"])
            config = FoundryAgentConfig(
                agent_name=agent_def["name"],
                foundry_agent_name=foundry_id or agent_def["name"],
                role=agent_def["role"],
                pipeline_order=agent_def["pipeline_order"],
                system_type=agent_def["system_type"],
                agent_line=agent_def.get("agent_line", "workflow"),
                is_optional=agent_def.get("is_optional", False),
                is_active=True,
                description=f"Auto-created {agent_def['role']} agent",
            )
            db.add(config)

        await db.commit()
        print("DB seeded successfully.")

    # Verify
    async with async_session() as db:
        result = await db.execute(select(FoundryAgentConfig).order_by(FoundryAgentConfig.pipeline_order))
        rows = result.scalars().all()
        print(f"Total agents in DB: {len(rows)}")
        for row in rows:
            print(f"  [{row.pipeline_order}] {row.agent_name} (role={row.role}, foundry_name={row.foundry_agent_name})")


async def main():
    print("=== Azure AI Foundry Agent Setup ===")
    print(f"Endpoint : {ENDPOINT}")
    print(f"Model    : {MODEL}")
    print()

    agent_name_map = {}

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        # Test connectivity
        r = await client.get(f"{ENDPOINT}/assistants?api-version={API_VERSION}")
        print(f"Assistants API status: {r.status_code}")
        if r.status_code not in (200, 201):
            print(f"Cannot reach Assistants API: {r.text[:300]}")
            print()
            print("Seeding DB with placeholder agent names (will use deployment fallback)...")
            for agent_def in AGENTS:
                agent_name_map[agent_def["name"]] = agent_def["name"]
        else:
            print("Assistants API accessible.")
            print()
            for agent_def in AGENTS:
                agent_id = await create_or_get_agent(
                    client, agent_def["name"], agent_def["instructions"]
                )
                if agent_id:
                    agent_name_map[agent_def["name"]] = agent_id

    print()
    print("=== Seeding database ===")
    await seed_db(agent_name_map)


if __name__ == "__main__":
    asyncio.run(main())
