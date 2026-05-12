#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_foundry_permissions.sh
#
# Assigns ALL required Azure RBAC roles for InfraAI Foundry integration.
# Run this ONCE after creating the service principal.
#
# Prerequisites:
#   az login   (with Owner or User Access Administrator on the subscription/RG)
#
# Usage:
#   # Interactive — prompts for values
#   ./setup_foundry_permissions.sh
#
#   # Non-interactive — pass via env vars
#   export AZURE_SUBSCRIPTION_ID="..."
#   export AZURE_RESOURCE_GROUP="..."
#   export AZURE_AI_SERVICES_NAME="..."
#   export AZURE_SP_OBJECT_ID="..."
#   ./setup_foundry_permissions.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  InfraAI — Azure AI Foundry Permission Setup               ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo

# ── Collect inputs ───────────────────────────────────────────────────────────

prompt_if_empty() {
  local varname="$1"
  local prompt_text="$2"
  local current_val="${!varname:-}"
  if [ -z "$current_val" ]; then
    read -rp "$prompt_text: " current_val
    if [ -z "$current_val" ]; then
      echo -e "${RED}ERROR: $varname is required.${NC}" >&2
      exit 1
    fi
    eval "$varname=\"$current_val\""
  else
    echo -e "  $prompt_text: ${GREEN}$current_val${NC} (from env)"
  fi
}

echo -e "${YELLOW}Step 1: Collect resource information${NC}"
echo

prompt_if_empty AZURE_SUBSCRIPTION_ID "Azure Subscription ID"
prompt_if_empty AZURE_RESOURCE_GROUP  "Resource Group name"

# ── Auto-discover resources if names not provided ────────────────────────────

if [ -z "${AZURE_AI_SERVICES_NAME:-}" ]; then
  echo
  echo "Searching for Cognitive Services accounts in RG '$AZURE_RESOURCE_GROUP'..."
  AI_ACCOUNTS=$(az cognitiveservices account list \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --subscription "$AZURE_SUBSCRIPTION_ID" \
    --query "[].{name:name, kind:kind, endpoint:properties.endpoint}" \
    -o table 2>/dev/null || true)

  if [ -n "$AI_ACCOUNTS" ]; then
    echo "$AI_ACCOUNTS"
    echo
  fi
  prompt_if_empty AZURE_AI_SERVICES_NAME "AI Services (CognitiveServices) account name"
fi

if [ -z "${AZURE_SP_OBJECT_ID:-}" ]; then
  echo
  echo -e "${YELLOW}Tip: Find the SP object ID with:${NC}"
  echo "  az ad sp show --id <app-id> --query id -o tsv"
  echo
  prompt_if_empty AZURE_SP_OBJECT_ID "Service Principal Object ID (the principal UUID from the error)"
fi

# ── Build scope paths ────────────────────────────────────────────────────────

COG_SCOPE="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$AZURE_RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AZURE_AI_SERVICES_NAME"

echo
echo -e "${YELLOW}Step 2: Assign RBAC roles${NC}"
echo
echo "  Service Principal : $AZURE_SP_OBJECT_ID"
echo "  CogSvc Scope      : $COG_SCOPE"
echo

# ── Role assignments ─────────────────────────────────────────────────────────
# Each assignment: (role_name, scope, purpose)
ASSIGNMENTS=(
  # On Cognitive Services account
  "Cognitive Services OpenAI User|$COG_SCOPE|List deployments, call model inference (deployments/read)"
  "Azure AI Developer|$COG_SCOPE|Create/run agents, conversations API (agents/write)"
  "Cognitive Services Contributor|$COG_SCOPE|Full agent lifecycle management"
)

PASS=0
SKIP=0
FAIL=0

for entry in "${ASSIGNMENTS[@]}"; do
  IFS='|' read -r role scope purpose <<< "$entry"

  printf "  %-42s on %-12s ... " "'$role'" "$(echo "$scope" | grep -oP '[^/]+$')"

  # Check if already assigned
  existing=$(az role assignment list \
    --assignee "$AZURE_SP_OBJECT_ID" \
    --role "$role" \
    --scope "$scope" \
    --query "length(@)" \
    -o tsv 2>/dev/null || echo "0")

  if [ "$existing" -gt 0 ] 2>/dev/null; then
    echo -e "${GREEN}EXISTS${NC} (already assigned)"
    SKIP=$((SKIP + 1))
    continue
  fi

  # Assign
  if az role assignment create \
    --assignee "$AZURE_SP_OBJECT_ID" \
    --role "$role" \
    --scope "$scope" \
    --only-show-errors \
    -o none 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
    PASS=$((PASS + 1))
  else
    echo -e "${RED}FAILED${NC}"
    echo -e "    ${RED}↳ $purpose${NC}"
    FAIL=$((FAIL + 1))
  fi
done

# ── Microsoft Graph API permissions (for email + SharePoint) ─────────────────

echo
echo -e "${YELLOW}Step 3: Check Microsoft Graph API permissions${NC}"
echo

# Try to find the app registration from the SP
APP_ID=$(az ad sp show --id "$AZURE_SP_OBJECT_ID" --query appId -o tsv 2>/dev/null || true)

if [ -n "$APP_ID" ]; then
  echo "  App Registration: $APP_ID"
  echo

  GRAPH_PERMS=(
    "810c84a8-4a9e-49e6-bf7d-12d183f40d01|Mail.Send|Send email via Microsoft Graph (Outlook)"
    "332a536c-c7ef-4017-ab91-336970924f0d|Sites.Read.All|Read SharePoint sites for knowledge search"
  )

  for entry in "${GRAPH_PERMS[@]}"; do
    IFS='|' read -r perm_id perm_name purpose <<< "$entry"
    printf "  %-25s ... " "$perm_name"

    # Check if already configured
    existing=$(az ad app permission list --id "$APP_ID" \
      --query "[?resourceAccess[?id=='$perm_id']]" \
      -o tsv 2>/dev/null | wc -l || echo "0")

    if [ "$existing" -gt 0 ] 2>/dev/null; then
      echo -e "${GREEN}EXISTS${NC}"
    else
      if az ad app permission add \
        --id "$APP_ID" \
        --api 00000003-0000-0000-c000-000000000000 \
        --api-permissions "${perm_id}=Role" \
        --only-show-errors 2>/dev/null; then
        echo -e "${GREEN}ADDED${NC} (needs admin consent)"
      else
        echo -e "${YELLOW}SKIPPED${NC} (add manually if needed)"
      fi
    fi
  done

  echo
  echo -e "  ${YELLOW}Granting admin consent...${NC}"
  if az ad app permission admin-consent --id "$APP_ID" --only-show-errors 2>/dev/null; then
    echo -e "  ${GREEN}Admin consent granted${NC}"
  else
    echo -e "  ${YELLOW}Admin consent may need to be granted manually in Azure Portal${NC}"
    echo "  → Entra ID → App registrations → $APP_ID → API permissions → Grant admin consent"
  fi
else
  echo -e "  ${YELLOW}Could not find App Registration for SP $AZURE_SP_OBJECT_ID${NC}"
  echo "  Graph permissions (Mail.Send, Sites.Read.All) must be configured manually."
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Summary${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "  Assigned : ${GREEN}$PASS${NC}"
echo -e "  Existing : ${GREEN}$SKIP${NC}"
echo -e "  Failed   : ${RED}$FAIL${NC}"
echo

if [ $FAIL -gt 0 ]; then
  echo -e "${RED}Some assignments failed. Common causes:${NC}"
  echo "  - You don't have Owner / User Access Administrator on the scope"
  echo "  - The resource name is incorrect"
  echo "  - The role name doesn't exist in the subscription"
  echo
  echo "Try running with elevated permissions:"
  echo "  az login --scope https://management.azure.com/.default"
fi

echo -e "${YELLOW}Note: Role assignments can take 2-5 minutes to propagate.${NC}"
echo

# ── Verification ─────────────────────────────────────────────────────────────

echo -e "${YELLOW}Step 4: Verify assignments${NC}"
echo
echo "Current role assignments for principal $AZURE_SP_OBJECT_ID:"
echo
az role assignment list \
  --assignee "$AZURE_SP_OBJECT_ID" \
  --all \
  --query "[].{Role:roleDefinitionName, Scope:scope}" \
  --output table 2>/dev/null || echo "  (could not list — check permissions)"

echo
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Required roles for InfraAI Foundry:                       ║${NC}"
echo -e "${CYAN}║                                                            ║${NC}"
echo -e "${CYAN}║  On CognitiveServices account:                             ║${NC}"
echo -e "${CYAN}║    ✓ Cognitive Services OpenAI User  (deployments/read)    ║${NC}"
echo -e "${CYAN}║    ✓ Azure AI Developer              (agents/write)        ║${NC}"
echo -e "${CYAN}║    ✓ Cognitive Services Contributor   (full agent mgmt)    ║${NC}"
echo -e "${CYAN}║                                                            ║${NC}"
echo -e "${CYAN}║  Microsoft Graph (app permissions):                        ║${NC}"
echo -e "${CYAN}║    ✓ Mail.Send                       (Outlook email)       ║${NC}"
echo -e "${CYAN}║    ✓ Sites.Read.All                  (SharePoint search)   ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "Wait 2-5 minutes, then retry ${GREEN}Test Connection${NC} in InfraAI."
