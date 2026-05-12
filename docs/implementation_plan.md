Here is the full consolidated plan:

---

## Plan: RAG Knowledge Base Integration

Add **opt-in Retrieval-Augmented Generation** to InfraAI. Connect GitHub, SharePoint, Jira, ServiceNow, and file uploads as knowledge sources — each with configurable filters to avoid loading unnecessary data. Documents are chunked, embedded, and stored in **PostgreSQL via pgvector** (built-in mode) with optional **Azure AI Search sync** (Foundry grounding). Alert analysis, Foundry agents, and chat all gain contextual knowledge retrieval. Periodic + on-demand sync keeps the index fresh. Full documentation included.

### Architecture

```
                    ┌─────────────────────────────┐
                    │  rag_enabled = true/false    │  ← app_settings toggle
                    └──────────┬──────────────────┘
                               │
        ┌──────────────────────┼──────────────────────────┐
        │ if OFF: skip         │ if ON: proceed            │
        ▼                      ▼                           │
  existing flow          Knowledge Sources                 │
  (unchanged)            GitHub | SharePoint | Jira        │
                         ServiceNow | Upload               │
                               │                           │
                         Per-Connector Filters              │
                               │                           │
                    Connector → Chunker → Embedder          │
                               │                           │
                    ┌──────────┴──────────┐                │
                    │ pgvector (always)    │ AI Search (opt)│
                    └──────────┬──────────┘                │
                               │                           │
                    KnowledgeRetriever                     │
                    ├─► AlertAnalyzer   (KB Context)       │
                    ├─► FoundryAnalyzer (grounding)        │
                    └─► ChatService     (RAG + citations)  │
```

---

### Phase 1: Database Foundation *(blocking — all phases depend on this)*

**Step 1** — **pgvector migration** `q4r5s6t7u8v9_knowledge_base_rag.py`:
- `CREATE EXTENSION IF NOT EXISTS vector` (graceful: logs warning if not installed, tables still created)
- `knowledge_sources` — name, source_type enum (`github`/`sharepoint`/`jira`/`servicenow`/`upload`), connection_config JSON (encrypted sensitive fields), filter_config JSON, sync_interval_hours, last_synced_at, sync_status, is_active, doc_count, chunk_count
- `knowledge_documents` — FK source, title, file_path, content_hash (SHA256), doc_type, chunk_count, raw_size_bytes, metadata JSON
- `knowledge_chunks` — FK document, chunk_index, content TEXT, `embedding vector(1536)`, token_count, metadata JSON (headings, section, line_range). IVFFLAT index on embedding with `vector_cosine_ops`

**Step 2** — **Models** — New `backend/app/models/knowledge.py`: `KnowledgeSource`, `KnowledgeDocument`, `KnowledgeChunk`. Register in __init__.py

**Step 3** — **Schemas** — New `backend/app/schemas/knowledge.py`:
- CRUD schemas: `KnowledgeSourceCreate/Update/Response` (masked secrets in response)
- Per-connector typed filter sub-schemas (validated on create/update):
  - `GitHubFilterConfig` — repos, branch, path_includes, path_excludes, file_extensions, max_file_size_kb, token
  - `SharePointFilterConfig` — site_ids, document_libraries, folder_paths, file_types, modified_after, exclude_patterns
  - `JiraFilterConfig` — project_keys, issue_types, statuses, labels, kb_space_keys, updated_after, max_results, custom_jql
  - `ServiceNowFilterConfig` — instance_url, auth_type, username, password, client_id, client_secret, tables, assignment_groups, ci_classes, kb_categories, state_filter, priority_filter, updated_after, max_results, include_comments, include_resolution
  - `UploadFilterConfig` — allowed_extensions, max_file_size_kb
- `KnowledgeSearchRequest` — query, top_k, source_filter, score_threshold
- `KnowledgeSearchResult` — chunk content, score, document title, source name, metadata
- `SyncStatusResponse` — status, doc_count, chunk_count, duration, errors

**Step 4** — **Feature toggle seeds** — Add to app_settings defaults in app_settings.py (category: `rag`):
- `rag_enabled` (default: `false`), `rag_embedding_model` (`text-embedding-3-small`), `rag_chunk_size` (`500`), `rag_chunk_overlap` (`50`), `rag_top_k` (`5`), `rag_score_threshold` (`0.7`)

**Step 5** — **Config** — Add `RAG_ENABLED: bool = False` to config.py

**Step 6** — **Requirements** — Add to requirements.txt: `pgvector>=0.3.0`, `tiktoken>=0.7.0`, `PyGithub>=2.0.0`, `gitpython>=3.1.0`, `apscheduler>=3.10.0`

**Step 7** — **init-db** — Add `CREATE EXTENSION IF NOT EXISTS vector` to init.sql

---

### Phase 2: Core Services *(Steps 8–12 parallel, Step 13 depends on all)*

**Step 8** — **RAG guard helper** — New `backend/app/services/rag_utils.py`:
- `async is_rag_enabled(db) → bool` — checks `app_settings.rag_enabled`, falls back to `config.RAG_ENABLED`
- `async get_rag_settings(db) → dict` — returns all `rag_*` settings
- Used by every service to short-circuit when RAG is off

**Step 9** — **Embedding Service** — New `backend/app/services/embedding_service.py` *(parallel)*:
- Multi-provider: OpenAI `text-embedding-3-small` / Azure OpenAI / Foundry
- `embed_text()`, `embed_batch()`. Model from `rag_embedding_model` setting
- Batch size: 100 texts per API call

**Step 10** — **Document Chunker** — New `backend/app/services/chunker_service.py` *(parallel)*:
- Format-aware recursive splitting: Markdown (## headers → paragraphs → sentences), YAML/JSON (top-level keys), IaC/HCL (resource blocks), plain text (paragraphs)
- Chunk size/overlap from `rag_chunk_size`/`rag_chunk_overlap` settings. `tiktoken` for token counting.
- Each chunk carries: heading hierarchy metadata, line range, file section

**Step 11** — **Source Connectors** — New `backend/app/services/knowledge_connectors.py` *(parallel)*:
- Base `KnowledgeConnector` with `fetch_documents(filter_config) → list[RawDocument]`
- **GitHubConnector**: PyGithub + shallow clone → filter by `path_includes`/`path_excludes`/`file_extensions`/`max_file_size_kb`. `.ragignore` support. PAT auth.
- **SharePointConnector**: Extends `azure_graph_service`. Filters by `site_ids`, `document_libraries`, `folder_paths`, `file_types`, `modified_after`, `exclude_patterns`. Downloads content via Graph `driveItem/content`.
- **JiraConnector**: Extends `jira_service.py`. Builds JQL from `project_keys`, `issue_types`, `statuses`, `labels`, `updated_after` (or uses `custom_jql`). CQL for Confluence via `kb_space_keys`. Caps at `max_results`.
- **ServiceNowConnector** *(new)*: Auth via basic or OAuth2 (`/oauth_token.do`). Queries Table API `GET /api/now/table/{table}` with `sysparm_query` built from `assignment_groups`, `state_filter`, `priority_filter`, `ci_classes`, `updated_after`. KB via `kb_knowledge` table filtered by `kb_categories`. Extracts `short_description`, `description`, `close_notes`, `work_notes`, `resolution_code`. Caps at `max_results` per table.
- **UploadConnector**: Receives files via API. Validates `allowed_extensions`/`max_file_size_kb`. Stores in `uploads/knowledge/`.

**Step 12** — **PII redaction during ingestion** — Apply existing `pii_redactor.redact_text()` to document content *before* chunking/embedding. Prevents sensitive data from being stored in vectors.

**Step 13** — **Knowledge Retrieval Service** — New `backend/app/services/knowledge_retrieval_service.py` *(depends on 8–12)*:
- `search(query, top_k, source_types, score_threshold)` — guarded by `is_rag_enabled()`. Embed query → pgvector cosine similarity → optional AI Search merge/dedup → score filter → return ranked results with source attribution
- `get_context_for_alert(alert) → str` — builds search from alert name/summary/labels, formats top-K chunks as `## Knowledge Base Context` Markdown
- `get_context_for_chat(query) → str` — same for chat
- `sync_chunks_to_ai_search(chunks)` — pushes to Azure AI Search index if configured (for Foundry grounding)

---

### Phase 3: Integration into Existing Pipelines *(Steps 14–17 parallel, depend on Phase 2)*

**Step 14** — **Alert Analyzer** — Modify alert_analyzer.py:
- After Jira knowledge fetch, before final AI call: `if await is_rag_enabled(db): kb_context = await knowledge_retrieval.get_context_for_alert(alert)`
- Inject as `## Knowledge Base Context` section in analysis prompt
- Instruct AI: "Reference knowledge base articles when they match. Cite source document names."

**Step 15** — **Foundry Analyzer** — Modify foundry_analyzer.py:
- In `knowledge` agent step: add pgvector retrieval alongside existing SharePoint/AI Search
- Merge into triage_master grounding context

**Step 16** — **Chat Service** — Modify chat_service.py:
- Before AI call: `if await is_rag_enabled(db): rag_context = await knowledge_retrieval.get_context_for_chat(user_message)`
- Inject as system context. Update `_CHAT_SYSTEM_PROMPT` to cite sources. Works for both built-in and Foundry modes.

**Step 17** — **Jira Knowledge Agent** — Modify jira_knowledge_agent.py:
- Add optional vector similarity search for past incidents alongside existing JQL keyword search

---

### Phase 4: Sync Engine + API *(depends on Phase 2)*

**Step 18** — **Sync Service** — New `backend/app/services/knowledge_sync_service.py`:
- `sync_source(source_id)`: fetch via connector (with filters) → compare content_hash (skip unchanged) → PII redact → chunk → embed in batches → upsert pgvector (delete old chunks for changed docs) → optionally push to AI Search → update source status
- `sync_all_active_sources()`: iterate active sources
- Scheduler: APScheduler `AsyncIOScheduler`. **Only starts if `is_rag_enabled()` at app startup.** Checks sources where $\text{now} - \text{last\_synced\_at} > \text{sync\_interval\_hours}$

**Step 19** — **Knowledge API Router** — New `backend/app/routers/knowledge.py`:
- All endpoints **guarded**: return 404 `"RAG is not enabled"` if toggle is off
- Source CRUD:
  - `POST /api/knowledge/sources` — create (admin)
  - `GET /api/knowledge/sources` — list with sync status
  - `PUT /api/knowledge/sources/{id}` — update config/filters
  - `DELETE /api/knowledge/sources/{id}` — remove + all docs/chunks
  - `POST /api/knowledge/sources/{id}/sync` — manual sync trigger
  - `POST /api/knowledge/sources/{id}/test` — test connection with filters
  - `POST /api/knowledge/sources/{id}/preview` — returns estimated doc count matching current filters (validate before full sync)
  - `GET /api/knowledge/sources/{id}/status` — sync progress
- Documents:
  - `GET /api/knowledge/documents` — list indexed docs (paginated, filterable by source)
  - `DELETE /api/knowledge/documents/{id}` — remove specific doc
- Upload:
  - `POST /api/knowledge/upload` — upload file(s) for indexing
- Search:
  - `POST /api/knowledge/search` — semantic search (testing/debugging)
- Settings:
  - `GET /api/knowledge/settings` — RAG toggle state + all RAG settings (for frontend visibility)

**Step 20** — **Register** in main.py: knowledge router (`/api/knowledge`), conditional scheduler startup on `startup` event

---

### Phase 5: Frontend UI *(depends on Phase 4)*

**Step 21** — **Knowledge Base Tab** in SystemConfigPage.tsx:
- Conditionally rendered: fetch `GET /api/knowledge/settings` — hide tab if `rag_enabled=false`
- RAG enable/disable toggle at top (admin only)
- RAG settings section: embedding model, chunk size, top_k, score threshold
- Source list (cards: type icon, name, doc count, last synced, status badge, sync/edit/delete actions)
- Add/Edit source modal with type-specific filter forms:
  - **GitHub**: Multi-input repos, branch, path include/exclude lists, extension checkboxes, max file size
  - **SharePoint**: Site picker, library names, folder paths, file type checkboxes, "modified after" date picker, exclude patterns
  - **Jira**: Project keys, issue type/status/label multi-selects, KB space keys, date picker, optional custom JQL textarea
  - **ServiceNow**: Instance URL, auth type toggle (basic/OAuth2), credential fields, table checkboxes, assignment groups, CI classes, KB categories, priority/state multi-selects, date picker
  - **Upload**: Extension whitelist checkboxes, max file size slider, drag-and-drop area
- **Preview button** per source: calls `/preview` to show estimated doc count before sync
- Per-source "Sync Now" + global "Sync All" buttons with progress indicators

**Step 22** — **Chat Source Citations** — Modify AskMePage.tsx:
- Chat messages that used RAG context show expandable "Sources" section
- Each source: relevance score badge, document title, source type icon, chunk preview snippet

**Step 23** — **API Client** — Modify client.ts:
- Knowledge source CRUD, sync trigger, test, preview, document list, upload, search, settings

---

### Phase 6: Documentation *(parallel with Phase 5, depends on Phase 4)*

**Step 24** — **New: `docs/RAG_KNOWLEDGE_BASE.md`** — Comprehensive RAG setup guide:
- **Overview**: What RAG is, how it enhances alert analysis/chat, architecture diagram
- **Prerequisites**: pgvector installation (apt, Docker image `pgvector/pgvector:pg16`, Helm), embedding API access
- **Enabling RAG**: Step-by-step — enable in UI (app_settings) or via .env (`RAG_ENABLED=true`), verify with `SELECT vector_version()`
- **RAG Settings**: Table of all `rag_*` settings with descriptions, defaults, and recommendations
- **Configuring Knowledge Sources**: Subsection per connector type:
  - **GitHub**: PAT creation, repo format, branch selection, path/extension filters, `.ragignore` file, example configs
  - **SharePoint**: Site ID lookup, document library names, folder scoping, file type filtering, Graph API permissions needed
  - **Jira**: Project key format, issue type/status/label filtering, Confluence space keys, custom JQL examples, reusing existing Jira config
  - **ServiceNow**: Instance URL format, basic vs OAuth2 auth setup, table selection, assignment group/CI class filtering, KB category IDs, SNOW API permissions needed
  - **File Upload**: Supported formats, size limits, bulk upload via API
- **Sync Configuration**: Periodic sync setup (interval per source), manual sync from UI, sync status monitoring
- **Using RAG in Alert Analysis**: How to verify KB context appears in analysis, tuning top_k and score_threshold
- **Using RAG in Chat**: How to see source citations, asking infrastructure questions that leverage docs
- **API Reference**: All `/api/knowledge/*` endpoints with request/response examples
- **Cost Estimation**: Embedding token costs per model, estimating cost based on doc count
- **Troubleshooting**: Common issues (pgvector not installed, empty search results, sync failures, permission errors)

**Step 25** — **New: `docs/SERVICENOW_INTEGRATION.md`** — ServiceNow-specific setup:
- Instance configuration (URL, auth)
- OAuth2 application setup in ServiceNow (System OAuth → Application Registry)
- Required ServiceNow roles (`itil`, `knowledge`, `cmdb_read`)
- Table API access setup
- Filter configuration examples
- Testing the connection
- Troubleshooting SNOW-specific errors

**Step 26** — **Update COMPLETE_GUIDE.md** — Add new section (e.g., Section 21 or insert after integrations):
- **Section: Knowledge Base & RAG**: Overview + link to `docs/RAG_KNOWLEDGE_BASE.md`
- **Section: ServiceNow Integration**: Overview + link to `docs/SERVICENOW_INTEGRATION.md`
- Update existing Jira/SharePoint sections to mention RAG indexing capability

**Step 27** — **Update README.md** — Add to documentation table:

| Guide | Description |
|-------|-------------|
| `docs/RAG_KNOWLEDGE_BASE.md` | RAG setup — knowledge sources (GitHub, SharePoint, Jira, ServiceNow), pgvector, filtering, sync |
| `docs/SERVICENOW_INTEGRATION.md` | ServiceNow integration — instance setup, OAuth2, table filtering |

**Step 28** — **Update DEPLOYMENT.md** — Add:
- pgvector prerequisite section: Docker image (`pgvector/pgvector:pg16` or `ankane/pgvector`), apt package (`postgresql-16-pgvector`), Helm chart config
- RAG-related environment variables (`RAG_ENABLED`, `EMBEDDING_MODEL`)
- Note: RAG is optional, deployments without pgvector work fine with `RAG_ENABLED=false`

---

### Relevant Files

**New files (10):**
| File | Purpose |
|------|---------|
| `backend/alembic/versions/q4r5s6t7u8v9_knowledge_base_rag.py` | pgvector + 3 tables migration |
| `backend/app/models/knowledge.py` | KnowledgeSource, KnowledgeDocument, KnowledgeChunk |
| `backend/app/schemas/knowledge.py` | CRUD + filter sub-schemas + search schemas |
| `backend/app/services/rag_utils.py` | RAG toggle guard helper |
| `backend/app/services/embedding_service.py` | Multi-provider embedding |
| `backend/app/services/chunker_service.py` | Format-aware document chunking |
| `backend/app/services/knowledge_connectors.py` | GitHub, SharePoint, Jira, ServiceNow, Upload connectors |
| `backend/app/services/knowledge_retrieval_service.py` | Unified semantic search + AI Search sync |
| `backend/app/services/knowledge_sync_service.py` | Background sync engine + scheduler |
| `backend/app/routers/knowledge.py` | REST API for knowledge management |

**New docs (2):**
| File | Purpose |
|------|---------|
| `docs/RAG_KNOWLEDGE_BASE.md` | Full RAG setup, configuration, usage, API reference, troubleshooting |
| `docs/SERVICENOW_INTEGRATION.md` | ServiceNow-specific setup and auth guide |

**Modified files (14):**
| File | Change |
|------|--------|
| requirements.txt | +pgvector, tiktoken, PyGithub, gitpython, apscheduler |
| __init__.py | Register knowledge models |
| main.py | Register knowledge router, conditional scheduler startup |
| config.py | +`RAG_ENABLED: bool = False` |
| app_settings.py | Seed RAG category defaults |
| alert_analyzer.py | Guarded RAG context injection |
| foundry_analyzer.py | Guarded pgvector in knowledge step |
| chat_service.py | Guarded RAG chat + source citations |
| jira_knowledge_agent.py | Optional vector similarity |
| init.sql | +`CREATE EXTENSION IF NOT EXISTS vector` |
| SystemConfigPage.tsx | Conditional Knowledge Base tab + filter forms |
| AskMePage.tsx | Source citations in chat |
| client.ts | Knowledge API functions |
| README.md | +RAG and ServiceNow doc links |
| COMPLETE_GUIDE.md | +KB/RAG section, +ServiceNow section |
| DEPLOYMENT.md | +pgvector prerequisites, +RAG env vars |

---

### Verification

1. **RAG OFF (default)**: Deploy fresh → no Knowledge tab visible, alert analysis unchanged, chat has no RAG, scheduler not running
2. **Enable RAG**: Toggle `rag_enabled=true` → tab appears, scheduler starts
3. **pgvector**: `SELECT vector_version()` succeeds after migration
4. **GitHub sync**: Add repo with `path_includes: ["docs/"]` → only docs/ files indexed
5. **SharePoint sync**: Configure with `document_libraries: ["IT Runbooks"]` → only that library indexed
6. **Jira sync**: Configure with `project_keys: ["OPS"]`, `statuses: ["Resolved"]` → only resolved OPS issues indexed
7. **ServiceNow sync**: Configure with `tables: ["incident"]`, `state_filter: ["Resolved"]` → only resolved incidents indexed
8. **Preview**: Call `/preview` before sync → returns estimated doc count matching filters
9. **Search**: `POST /api/knowledge/search` returns relevant chunks with scores > 0.7
10. **Alert RAG**: Trigger test alert → analysis includes "Knowledge Base Context" → cites KB articles
11. **Chat RAG**: Ask question matching docs → response shows expandable "Sources" section
12. **Disable RAG**: Toggle off → tab hidden, scheduler stops, next analysis skips RAG
13. **No pgvector**: If extension missing, migration warns, RAG stays off, everything else works
14. **Docs**: All links in README resolve, RAG_KNOWLEDGE_BASE.md covers all connector types

---

### Decisions

- **RAG default: OFF** — `RAG_ENABLED=false` in .env, `rag_enabled=false` in `app_settings`
- **Hybrid storage**: pgvector (always when enabled) + Azure AI Search (optional Foundry grounding)
- **Per-connector filters**: Typed Pydantic sub-schemas in `connection_config`/`filter_config` JSON columns (follows existing JiraConfig pattern)
- **Preview before sync**: `/preview` endpoint validates filters → shows estimated count before committing
- **Embedding**: `text-embedding-3-small` (1536 dims), configurable via `rag_embedding_model`
- **Chunk**: 500 tokens / 50 overlap, configurable via `rag_chunk_size`/`rag_chunk_overlap`
- **PII**: `pii_redactor.py` applied during ingestion before embedding
- **Git provider**: GitHub only. GitLab/ADO/Bitbucket excluded from this scope.
- **ServiceNow**: New connector. Basic + OAuth2 auth. incident/problem/kb_knowledge tables.
- **Sync**: Periodic (APScheduler, per-source interval) + manual trigger. No webhook-driven sync.
- **Graceful degradation**: No pgvector → RAG features return empty, app works normally

### Further Considerations

1. **pgvector Docker**: Current docker-compose.yml likely uses `postgres:16`. Needs switching to `pgvector/pgvector:pg16` — a one-line change but affects existing deployments. Will document migration path.
2. **Embedding costs**: ~$0.02/1M tokens. 10K chunks ≈ $0.10. Consider adding cost estimate to sync preview UI.
3. **Large repos**: For repos with 1000+ files, `path_includes` filters are critical. Default should encourage scoping (show warning if no path filter set on GitHub sources).


Here's the cost estimation section to add to the consolidated plan:

---

## Cost Estimates & Sizing Guide

### Embedding Costs (One-Time Indexing + Re-Sync)

| Model | Cost/1M tokens | Dimensions | Quality |
|-------|---------------|------------|---------|
| `text-embedding-3-small` (recommended) | $0.02 | 1536 | Good |
| `text-embedding-3-large` | $0.13 | 3072 | Better |
| `text-embedding-ada-002` | $0.10 | 1536 | Legacy |

**Typical document → token conversion:**
- 1 page of documentation ≈ 500 tokens
- 1 Jira incident (summary + description + comments) ≈ 800 tokens
- 1 ServiceNow KB article ≈ 1,200 tokens
- 1 Terraform/YAML file ≈ 300–2,000 tokens

**Embedding cost by knowledge base size (text-embedding-3-small):**

| Scale | Documents | Chunks (~500 tok each) | Total Tokens | Embedding Cost | Re-Sync Cost/Month |
|-------|-----------|----------------------|--------------|----------------|---------------------|
| **Small** (single team) | 200 docs | ~1,000 | 500K | **$0.01** | $0.005 (10% change) |
| **Medium** (department) | 2,000 docs | ~10,000 | 5M | **$0.10** | $0.02 |
| **Large** (enterprise) | 20,000 docs | ~100,000 | 50M | **$1.00** | $0.20 |
| **Very Large** | 100,000 docs | ~500,000 | 250M | **$5.00** | $1.00 |

Re-sync costs assume ~10% of docs change per sync cycle (content hash skips unchanged docs).

---

### RAG Query Costs (Per Alert / Per Chat)

Each RAG retrieval requires **1 embedding call** for the query (~20–50 tokens):

| Operation | Embedding Cost | AI Inference Cost (added context) | Total Added Cost |
|-----------|---------------|----------------------------------|-----------------|
| Query embedding (search) | ~$0.000001 | — | Negligible |
| Alert analysis (+5 chunks × 500 tok = 2,500 tok extra context) | — | ~$0.0025 (GPT-4o input) | **~$0.003/alert** |
| Chat message (+5 chunks) | — | ~$0.0025 | **~$0.003/message** |

**Monthly RAG query cost by alert volume (GPT-4o, $2.50/1M input tokens):**

| Alert Volume | RAG Queries/Month | Extra Input Tokens | RAG Overhead | vs. Baseline Cost |
|-------------|-------------------|-------------------|-------------|-------------------|
| **50 alerts/day** | 1,500 | 3.75M | **$0.01** | +3% |
| **200 alerts/day** | 6,000 | 15M | **$0.04** | +3% |
| **1,000 alerts/day** | 30,000 | 75M | **$0.19** | +3% |
| **5,000 alerts/day** | 150,000 | 375M | **$0.94** | +3% |

RAG adds roughly **3% overhead** to existing AI inference cost per alert — the extra 2,500 tokens of context is small relative to the full analysis prompt (~8K–15K tokens).

---

### Baseline AI Costs (Without RAG — For Reference)

**Built-in mode** (2 AI calls/alert):

| Model | Input Cost/1M | Output Cost/1M | Cost/Alert (~12K in, ~2K out) | 200 alerts/day |
|-------|-------------|---------------|-------------------------------|----------------|
| GPT-4o | $2.50 | $10.00 | **$0.05** | **$300/mo** |
| GPT-4o-mini | $0.15 | $0.60 | **$0.003** | **$18/mo** |
| GPT-4.1 | $2.00 | $8.00 | **$0.04** | **$240/mo** |
| GPT-4.1-mini | $0.40 | $1.60 | **$0.008** | **$48/mo** |

**Foundry mode** (6–8 AI calls/alert):

| Model | Cost/Alert (~40K in, ~8K out) | 200 alerts/day |
|-------|-------------------------------|----------------|
| GPT-4o | **$0.18** | **$1,080/mo** |
| GPT-4o-mini | **$0.011** | **$66/mo** |

---

### PostgreSQL Storage & Memory Sizing

**pgvector storage per chunk:**
- Content (TEXT): ~500 bytes avg
- Embedding vector(1536): 6,144 bytes (1536 × 4 bytes float32)
- Metadata + indexes: ~500 bytes
- **Total per chunk: ~7 KB**

**Database sizing by scale:**

| Scale | Chunks | pgvector Storage | IVFFLAT Index | Total DB Growth | RAM for Index |
|-------|--------|-----------------|--------------|-----------------|---------------|
| **Small** | 1,000 | 7 MB | 3 MB | **10 MB** | 16 MB |
| **Medium** | 10,000 | 70 MB | 30 MB | **100 MB** | 64 MB |
| **Large** | 100,000 | 700 MB | 300 MB | **1 GB** | 512 MB |
| **Very Large** | 500,000 | 3.5 GB | 1.5 GB | **5 GB** | 2 GB |

**PostgreSQL resource recommendations:**

| Scale | CPU | RAM | Disk | `maintenance_work_mem` | `shared_buffers` |
|-------|-----|-----|------|----------------------|-----------------|
| **Small** (<1K chunks) | 1 vCPU | 1 GB | 10 GB | 64 MB | 256 MB |
| **Medium** (<10K chunks) | 2 vCPU | 4 GB | 20 GB | 256 MB | 1 GB |
| **Large** (<100K chunks) | 4 vCPU | 8 GB | 50 GB | 512 MB | 2 GB |
| **Very Large** (<500K chunks) | 8 vCPU | 16 GB | 100 GB | 1 GB | 4 GB |

---

### Azure AI Search Costs (Optional — Foundry Grounding)

Only applies if using hybrid mode with Foundry:

| Tier | $/Month | Storage | Docs | Best For |
|------|---------|---------|------|----------|
| Free | $0 | 50 MB | 10K | Dev/test |
| Basic | $75 | 2 GB | 1M | Small deployments |
| S1 Standard | $250 | 25 GB | 1M | Medium |
| S2 Standard | $1,000 | 100 GB | 1M | Large |

---

### Total Monthly Cost Summary

**Scenario: Medium deployment — 2,000 docs indexed, 200 alerts/day, GPT-4o, built-in mode**

| Component | One-Time | Monthly |
|-----------|----------|---------|
| Initial embedding (2K docs → 10K chunks) | $0.10 | — |
| Re-sync embedding (10% changed) | — | $0.02 |
| RAG query overhead (6K queries) | — | $0.04 |
| Baseline AI (alerts, no RAG) | — | $300.00 |
| PostgreSQL storage (+100 MB) | — | $0 (existing DB) |
| Azure AI Search (if used) | — | $75 (Basic tier) |
| **Total RAG overhead** | **$0.10** | **$0.06** (+0.02% of AI cost) |
| **Total with AI Search** | **$0.10** | **$75.06** |

**Key takeaway**: RAG embedding/query costs are **negligible** — less than $1/month even at enterprise scale. The real costs are the LLM inference (which you're already paying) and optionally Azure AI Search ($75+/month). pgvector adds zero cost beyond the PostgreSQL you already run.

---

### Sizing Recommendations Per Deployment Tier

| Tier | Docs | Alerts/Day | pgvector | AI Search | Est. Monthly Total |
|------|------|-----------|----------|-----------|-------------------|
| **Starter** | <500 | <50 | Yes (existing PG) | No | +$0.01 (RAG only) |
| **Professional** | 500–5K | 50–500 | Yes (4 GB RAM PG) | Optional | +$0–75 |
| **Enterprise** | 5K–50K | 500–5K | Yes (8 GB RAM PG) | Recommended | +$75–250 |
| **Large Enterprise** | 50K+ | 5K+ | Yes (16 GB RAM PG) | Required | +$250–1,000 |

---

These estimates will be included in Phase 6, Step 24 (`docs/RAG_KNOWLEDGE_BASE.md`) under a **"Cost Estimation & Sizing"** section, and the frontend will show an estimated cost when previewing a sync (Step 21 — preview button shows "~X docs, ~Y chunks, ~$Z embedding cost").

Ready to approve the full plan for implementation?