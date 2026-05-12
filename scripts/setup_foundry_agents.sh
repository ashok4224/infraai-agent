#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# setup_foundry_agents.sh
#
# DEPRECATED — superseded by setup_foundry_agent_catalog.sh
# which creates the full 2-line catalog (workflow + technology
# specialists) and fixes the API call.
#
# This script is kept for reference only. Run the catalog script:
#   ./setup_foundry_agent_catalog.sh
#
# Root cause of original failures
# ────────────────────────────────
# "az ai agent create" does NOT exist in the Azure CLI.
# The Azure AI Foundry Agents REST API must be called directly:
#   POST {endpoint}/assistants?api-version=2024-05-01-preview
#   Authorization: Bearer $(az account get-access-token --resource https://ai.azure.com -o tsv --query accessToken)
# ────────────────────────────────────────────────────────────────

echo "This script is deprecated. Please use setup_foundry_agent_catalog.sh instead."
echo "  cd scripts && ./setup_foundry_agent_catalog.sh"
exit 0

: "${AZURE_AI_FOUNDRY_ENDPOINT:?Set AZURE_AI_FOUNDRY_ENDPOINT}"
: "${AZURE_AI_FOUNDRY_PROJECT:?Set AZURE_AI_FOUNDRY_PROJECT}"
MODEL="${AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT:-gpt-4o}"

echo "=== Azure AI Foundry Agent Setup ==="
echo "Endpoint : $AZURE_AI_FOUNDRY_ENDPOINT"
echo "Project  : $AZURE_AI_FOUNDRY_PROJECT"
echo "Model    : $MODEL"
echo

create_agent() {
  local name="$1"
  local instructions="$2"
  echo -n "Creating agent '$name' ... "

  local result
  result=$(az ai agent create \
    --endpoint "$AZURE_AI_FOUNDRY_ENDPOINT" \
    --project "$AZURE_AI_FOUNDRY_PROJECT" \
    --model "$MODEL" \
    --name "$name" \
    --instructions "$instructions" \
    --output json 2>/dev/null)

  local agent_id
  agent_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
  echo "OK  →  $agent_id"
  echo "$agent_id"
}

echo "── Step 1/5: Knowledge Agent ──"
KNOWLEDGE_ID=$(create_agent "infraai-knowledge" \
  "You are a knowledge retrieval agent. Given an alert description, search the organization's knowledge base (SharePoint, AI Search index, runbooks) for relevant documentation, past incidents, and standard operating procedures. Return the most relevant snippets with source references.")

echo
echo "── Step 2/5: Researcher Agent ──"
RESEARCHER_ID=$(create_agent "infraai-researcher" \
  "You are a database/infrastructure researcher agent. Given an alert with optional knowledge context, analyze the problem and generate a diagnostic plan. For database alerts, produce targeted SQL queries to collect evidence. For infrastructure alerts, suggest diagnostic commands. Format your output clearly with numbered diagnostic steps.")

echo
echo "── Step 3/5: Collector Agent ──"
# The collector step is handled locally (tool_registry executes SQL).
# This agent is optional — only used if you want Foundry to interpret raw results.
COLLECTOR_ID=$(create_agent "infraai-collector" \
  "You are a data collection and interpretation agent. You receive raw query results from database diagnostic queries. Organize and summarize the data, highlighting anomalies, thresholds exceeded, and key metrics. Present findings in a structured format.")

echo
echo "── Step 4/5: Solver Agent ──"
SOLVER_ID=$(create_agent "infraai-solver" \
  "You are an expert SRE/DBA solver agent. Given an alert, diagnostic data, and knowledge context, produce a complete incident analysis. Your response MUST be valid JSON with these fields: problem_statement (plain English, reference specific metrics), root_cause, confidence_score (0.0-1.0), action_plan (array of steps), fix_commands (array with type/description/command/risk_level/requires_approval), prevention_steps, risk_level (Low/Medium/High/Critical).")

echo
echo "── Step 5/5: Notifier (Chat) Agent ──"
NOTIFIER_ID=$(create_agent "infraai-notifier" \
  "You are a notification formatting agent. Given an incident analysis JSON, format a professional HTML email suitable for an operations team. Include severity badge, problem summary, action items with commands, risk assessment, and a link to the alert detail page. Keep the email concise and scannable.")

echo
echo "════════════════════════════════════════"
echo "Agent IDs — register these in Foundry Config UI:"
echo "  knowledge : $KNOWLEDGE_ID"
echo "  researcher: $RESEARCHER_ID"
echo "  collector : $COLLECTOR_ID"
echo "  solver    : $SOLVER_ID"
echo "  notifier  : $NOTIFIER_ID"
echo "════════════════════════════════════════"
