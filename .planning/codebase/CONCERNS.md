# Codebase Concerns

**Analysis Date:** 2026-06-21

## Tech Debt

**Split active and legacy SQL paths:**
- Issue: The Streamlit path uses `src/agent/orchestrator.py`, `src/agent/langgraph_sql_agent.py`, and `src/agent/sql_validator.py`, while the CLI path in `main.py` still uses legacy `app/*` modules. The legacy path has a weaker validator and executor contract.
- Files: `main.py`, `app/sql_validator.py`, `app/query_executor.py`, `app/prompt_builder.py`, `src/agent/sql_validator.py`, `src/agent/orchestrator.py`
- Impact: Fixes to the active agent can miss the CLI path, and CLI behavior can execute SQL under different safety rules from the Streamlit app.
- Fix approach: Either retire `main.py` and the legacy `app/*` SQL path, or make the CLI call `src.agent.orchestrator.run_orchestrator` so all entry points share validation, backend selection, logging, and reporting behavior.

**Large Streamlit controller module:**
- Issue: UI, chat state, model configuration, memory review, template approval, golden-test UI, result export, and agent execution are all implemented in one 1321-line file.
- Files: `streamlit_app.py`
- Impact: Small UI changes can accidentally affect memory approval, evaluation controls, or query execution. It also makes testing the Streamlit workflows difficult.
- Fix approach: Split route/page rendering, chat state, feedback/export helpers, memory review, and golden-test UI into separate modules while keeping `streamlit_app.py` as a thin entry point.

**Unpinned dependency set:**
- Issue: Dependencies are listed without versions or hashes.
- Files: `requirements.txt`, `Dockerfile`
- Impact: Rebuilds can change model adapter behavior, LangGraph APIs, Databricks connector behavior, Streamlit rendering, or pandas export output without a code change.
- Fix approach: Pin runtime dependencies, generate a lock or constraints file, and separate production dependencies from evaluation/dev tooling.

**Committed runtime and evaluation artifacts:**
- Issue: Runtime-like files and result artifacts are tracked despite `.gitignore` rules that ignore future log CSVs and generated evaluation outputs.
- Files: `logs/feedback.csv`, `evaluation/demo/golden_results.jsonl`, `memory/demo/memory_candidates.yaml`, `memory/demo/solution_templates.yaml`, `.gitignore`
- Impact: Prompts, generated SQL, feedback comments, evaluation failures, and manual review data can become part of source history and bias future tests.
- Fix approach: Move mutable logs/results to ignored runtime storage, keep only curated seed fixtures in git, and add a pre-commit check for `logs/*.csv`, `evaluation/**/golden_results.jsonl`, and non-seed `memory/**` changes.

**Evaluation can be biased by approved memory:**
- Issue: Approved demo memory includes a manual TPC-H Q1 template whose note says it should not be used during golden evaluation, while golden tests enable approved memory by default.
- Files: `memory/demo/solution_templates.yaml`, `evaluation/run_evaluation.py`, `src/agent/golden_test_runner.py`, `src/agent/langgraph_sql_agent.py`
- Impact: Golden-test pass rates can reflect committed templates instead of the agent's general SQL capability.
- Fix approach: Default golden tests to `use_approved_memory=False`, or maintain a separate evaluation memory fixture that excludes solution-leaking templates.

**Binary PowerPoint template has no generation contract:**
- Issue: A Wuerth PPTX master is present as a binary asset, but there is no PowerPoint generation code, no package dependency for PPTX manipulation, and no template validation workflow.
- Files: `assets/templates/PPT_Vorlage_Wuerth.pptx`, `requirements.txt`, `streamlit_app.py`, `src/agent/reporting_agent.py`
- Impact: Future slide generation can silently break on placeholder names, layout IDs, embedded objects, fonts, brand colors, or unsupported chart/data shapes.
- Fix approach: Define a slide-generation contract before using the template: supported layouts, placeholder names, result-data schema, text overflow rules, chart rendering rules, and visual regression checks.

## Known Bugs

**Committed golden results contain many failed and errored runs:**
- Symptoms: The current `evaluation/demo/golden_results.jsonl` artifact contains 66 passed, 140 failed, and 135 error records. Failures include SQL validation errors, output mismatches, execution errors, recursion-limit errors, and `name 'Any' is not defined` errors.
- Files: `evaluation/demo/golden_results.jsonl`, `evaluation/run_evaluation.py`, `src/agent/golden_test_runner.py`, `src/agent/langgraph_sql_agent.py`
- Trigger: Running demo golden questions through `evaluation/run_evaluation.py` or using the Streamlit golden-test page.
- Workaround: Treat the existing JSONL as a failure log, not a passing baseline. Re-run scoped golden tests after fixing SQL generation or evaluation issues, and archive or regenerate stale result artifacts.

**Evaluation masks a runtime typing error:**
- Symptoms: `src/agent/golden_test_runner.py` catches `NameError` with text `name 'Any' is not defined`, mutates `src.agent.langgraph_sql_agent.Any`, and retries.
- Files: `src/agent/golden_test_runner.py`, `src/agent/langgraph_sql_agent.py`, `evaluation/demo/golden_results.jsonl`
- Trigger: Golden-test execution when the runtime hits that missing symbol path.
- Workaround: The retry patch keeps evaluation moving, but the source failure should be removed and covered by a direct test instead of monkey-patching the module at runtime.

**Wuerth local semantics encode unresolved source-data limits:**
- Symptoms: The Wuerth local semantic layer marks revenue, turnover, invoice amount, packing cost, shipment date, plant, shipping point, and statistics currency as unavailable. It also marks the material mapping as a candidate that needs business confirmation.
- Files: `semantic_layer/databricks/wuerth_semantic_layer.yaml`, `src/agent/langgraph_sql_agent.py`, `README.md`, `evaluation/wuerth_local/golden_questions.yaml`
- Trigger: Questions that ask for unsupported KPIs or combined invoice/shipment metrics.
- Workaround: Return explicit limitation answers for unsupported KPIs and use pre-aggregated joins for invoice/shipment matching until the source CSV columns and join keys are confirmed.

**Postgres error messages can leak operational detail to users:**
- Symptoms: Postgres connection and execution errors are converted with `str(error)` and displayed through the CLI or Streamlit error flow.
- Files: `app/db.py`, `app/query_executor.py`, `src/backends/demo/postgres_adapter.py`, `src/agent/langgraph_sql_agent.py`, `streamlit_app.py`
- Trigger: Bad credentials, missing tables, syntax errors, permission errors, or backend outages.
- Workaround: Databricks errors are sanitized in `src/backends/databricks/databricks_adapter.py`; apply the same pattern to Postgres paths and keep raw errors only in private logs.

## Security Considerations

**Regex-based SQL safety is necessary but incomplete:**
- Risk: The validator checks destructive keywords, allowed table references, broad row-level limits, and some qualified columns, but it does not enforce an allowlist of SQL functions, cost limits, statement timeouts, or safe aggregate result sizes.
- Files: `src/agent/sql_validator.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `app/sql_validator.py`, `app/query_executor.py`
- Current mitigation: `src/agent/sql_validator.py` blocks common destructive keywords and unknown tables; `src/backends/demo/postgres_adapter.py` runs Postgres queries in a read-only transaction.
- Recommendations: Add backend statement timeouts, function allowlists or denylists for risky functions, row and cell-size budgets, and tests for validator bypass attempts. For Databricks, execute through a read-only warehouse or restricted principal and add server-side query limits.

**Databricks execution lacks the Postgres read-only guard:**
- Risk: The Databricks adapter executes the validated SQL directly and relies on validation plus warehouse permissions for safety.
- Files: `src/backends/databricks/databricks_adapter.py`, `src/backends/config.py`, `src/agent/sql_validator.py`
- Current mitigation: Allowed Databricks tables are normalized and constrained to the active scenario allowlist.
- Recommendations: Use a Databricks principal with read-only permissions, apply query timeout settings where supported, and add integration tests that verify forbidden writes fail at the warehouse permission layer.

**Raw prompts, SQL, answers, and feedback are written to CSV:**
- Risk: Query logs and feedback logs store user questions, generated SQL, final SQL, answer previews, comments, corrected SQL, and expected answers. CSV values are not redacted and not escaped against spreadsheet formula execution.
- Files: `src/agent/logging_utils.py`, `app/logging_utils.py`, `streamlit_app.py`, `logs/feedback.csv`
- Current mitigation: `.gitignore` ignores future `logs/*.csv` files, but `logs/feedback.csv` is already tracked.
- Recommendations: Remove tracked runtime logs, redact sensitive values before logging, add retention rules, and prefix CSV cells beginning with `=`, `+`, `-`, or `@` before export or log writing.

**Streamlit app exposes powerful actions without app-level auth:**
- Risk: The app can run generated SQL, view raw SQL, download results, approve templates, edit memory YAML, and run golden tests. Docker exposes Streamlit on `0.0.0.0`.
- Files: `Dockerfile`, `docker-compose.yml`, `streamlit_app.py`, `src/agent/memory_store.py`
- Current mitigation: The README describes a local prototype workflow and the Docker Compose setup is local-oriented.
- Recommendations: Do not expose this service beyond a trusted network without authentication, authorization for memory approval actions, audit identity, and per-user session isolation.

**Local Docker config uses fixed development database credentials:**
- Risk: The Docker workflow hardcodes local Postgres defaults in compose configuration and documents the same local defaults.
- Files: `docker-compose.yml`, `README.md`, `app/config.py`, `scripts/ingest_wuerth_csv_to_postgres.py`
- Current mitigation: The setup is documented as a local prototype and `.env` is ignored.
- Recommendations: Keep these credentials local-only, route all non-local deployments through secrets management, and avoid copying compose defaults into shared or production environments.

**PPTX template contains embedded OLE objects:**
- Risk: Package inspection of `assets/templates/PPT_Vorlage_Wuerth.pptx` detected embedded OLE object entries under the PPTX package. No `vbaProject.bin` or `TargetMode="External"` relationships were detected in the inspected package, but embedded objects still need review before automated generation or distribution.
- Files: `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Current mitigation: The template is only an asset; no generation path currently consumes it.
- Recommendations: Scan the PPTX in CI for macros, external relationships, embedded objects, and unexpected media. Store a checksum and require manual approval for binary template changes.

## Performance Bottlenecks

**SQL execution fetches full result sets into memory:**
- Problem: Backend execution uses `fetchall()`, then Streamlit converts full rows to a pandas DataFrame and offers CSV/XLSX exports. Chart rendering caps at 50 rows, but the table and exports remain full-result.
- Files: `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `src/agent/reporting_agent.py`, `streamlit_app.py`, `src/agent/visualization_spec.py`
- Cause: There is no backend-level max row count, max bytes, streaming cursor, or export-size guard.
- Improvement path: Apply global row/byte caps, stream large exports, show truncated previews, and require explicit user confirmation for large result downloads.

**No statement timeout or cost guard for generated SQL:**
- Problem: A syntactically valid aggregate over large joins can run for a long time even when it passes validation.
- Files: `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `src/agent/sql_validator.py`
- Cause: Validation checks shape and table allowlists, not estimated cost, time, join cardinality, or function runtime.
- Improvement path: Set Postgres `statement_timeout`, use Databricks warehouse query timeouts, inspect `EXPLAIN` cost where practical, and reject unbounded high-risk join patterns.

**Golden evaluation appends to an ever-growing JSONL artifact:**
- Problem: Each evaluation appends results to `evaluation/<scenario>/golden_results.jsonl`, and the demo artifact is already over 1 MB.
- Files: `src/agent/golden_test_runner.py`, `evaluation/demo/golden_results.jsonl`, `.gitignore`
- Cause: Results are append-only and the demo result artifact is tracked.
- Improvement path: Store evaluation outputs under ignored run directories, summarize current results separately, and keep only small curated fixtures in git.

**Wuerth CSV ingestion is full-drop/full-load:**
- Problem: The ingestion script drops and recreates target tables, then reloads all rows and indexes on every run.
- Files: `scripts/ingest_wuerth_csv_to_postgres.py`, `docker-compose.yml`
- Cause: The prototype loader optimizes for simplicity over incremental updates.
- Improvement path: Keep full reload for local demos, but add a guarded mode for shared databases, with staging tables, checksums, and explicit confirmation before replacing existing data.

**Schema and semantic context are rebuilt per run:**
- Problem: Each SQL-agent run loads schema context and semantic YAML before prompting.
- Files: `src/agent/langgraph_sql_agent.py`, `src/agent/db.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `src/config/scenarios.py`
- Cause: There is no cache keyed by scenario, schema version, and backend metadata.
- Improvement path: Cache schema context per scenario with invalidation after ingestion or scenario change.

## Fragile Areas

**Wuerth local join logic is business-sensitive:**
- Files: `semantic_layer/databricks/wuerth_semantic_layer.yaml`, `src/agent/langgraph_sql_agent.py`, `evaluation/wuerth_local/golden_questions.yaml`
- Why fragile: The key mapping uses `invoices.order_number = shipments.order_number`, `invoices.customer = shipments.shiptoparty`, and `invoices.material_price = shipments.customer_material`, while the semantic layer says the material mapping still needs business confirmation. Raw joins can multiply measures.
- Safe modification: Do not change Wuerth joins or KPI support without updating semantic guidance, scenario rules, golden questions, and ingestion validation together.
- Test coverage: `evaluation/test_wuerth_local_scenario.py` covers semantic constraints, but there is no committed end-to-end Wuerth CSV golden result baseline.

**Memory storage is file-based YAML with no locking:**
- Files: `src/agent/memory_store.py`, `src/agent/memory_retriever.py`, `memory/demo/memory_candidates.yaml`, `memory/demo/solution_templates.yaml`, `streamlit_app.py`
- Why fragile: Manual review edits, approval, candidate writes, backups, and audit logs operate on YAML/CSV files. Atomic replace helps single writes, but concurrent Streamlit users can still race.
- Safe modification: Add file locking or move memory state to a small database before multi-user use.
- Test coverage: There are no concurrency tests for memory review, approval, or template reactivation.

**Router context is preserved but not used by SQL generation:**
- Files: `src/agent/orchestrator.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/router.py`
- Why fragile: The router computes constraints and execution plan, but `src/agent/orchestrator.py` explicitly keeps those fields observable rather than influencing SQL.
- Safe modification: If router constraints should affect SQL, add a structured prompt contract and tests that verify time windows, grouping levels, and output mode behavior.
- Test coverage: `evaluation/test_orchestrator.py` verifies preservation, not semantic enforcement.

**Router template retrieval is a placeholder:**
- Files: `src/agent/router_template_retriever.py`, `src/agent/router.py`, `evaluation/test_router.py`
- Why fragile: The router advertises template candidates but always returns an empty list. Future retrieval can accidentally affect routing, prompt contents, or memory leakage.
- Safe modification: Keep router candidates metadata-only and ensure SQL generation still validates through `src/agent/sql_validator.py`.
- Test coverage: Existing tests assert the placeholder returns an empty list, so retrieval implementation will need new ranking, privacy, and scenario-isolation tests.

**PowerPoint generation from agent data is high-risk without a renderer contract:**
- Files: `assets/templates/PPT_Vorlage_Wuerth.pptx`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`
- Why fragile: Agent output can contain long labels, arbitrary SQL-derived values, empty results, ambiguous units, and chart truncation notes. A PPTX template can also change slide layout IDs or placeholders without readable git diffs.
- Safe modification: Create a deterministic slide model from `reporting_result`, sanitize all text, cap table rows, render sample decks in CI, and compare screenshots or extracted slide text.
- Test coverage: No tests or dependencies currently cover PPTX generation, binary template integrity, or visual output.

## Scaling Limits

**Single-machine prototype storage model:**
- Current capacity: Local Docker Postgres, local `logs/`, local `memory/`, and Streamlit session state.
- Limit: Multi-user access can race on memory files, expose shared feedback/history, and exhaust process memory with large query results.
- Scaling path: Use external Postgres schemas for app state, per-user authentication, server-side result pagination, and durable object storage for exports.
- Files: `docker-compose.yml`, `streamlit_app.py`, `src/agent/memory_store.py`, `src/agent/logging_utils.py`

**Flat YAML memory retrieval does linear matching:**
- Current capacity: Small demo memory files with a handful of templates and candidates.
- Limit: `src/agent/memory_retriever.py` loads all templates and scores tokens in memory; quality and speed degrade as templates grow.
- Scaling path: Use a small indexed store keyed by scenario/dataset/status, then add embeddings only after deterministic filters.
- Files: `src/agent/memory_retriever.py`, `memory/demo/solution_templates.yaml`, `memory/demo/memory_candidates.yaml`

**Large files are committed directly:**
- Current capacity: Demo CSVs and golden results are manageable but already include a 7.4 MB `lineitem.csv` and a 1 MB golden JSONL.
- Limit: Repo operations and reviews slow down as generated data and binary assets grow.
- Scaling path: Keep small deterministic fixtures in git; move generated results, large data extracts, and binary templates to versioned artifact storage with checksums.
- Files: `database/exports/lineitem.csv`, `database/exports/orders.csv`, `evaluation/demo/golden_results.jsonl`, `assets/templates/PPT_Vorlage_Wuerth.pptx`

## Dependencies at Risk

**LLM and orchestration packages can change behavior without warning:**
- Risk: Unpinned `langgraph`, `langchain-*`, `google-genai`, `ollama`, and `streamlit` versions can change invocation, response objects, retry behavior, or UI behavior.
- Impact: SQL generation, routing, fallback, and Streamlit rendering can regress after a rebuild.
- Migration plan: Pin versions in `requirements.txt`, add a lock file, and run smoke tests in CI against the pinned environment.
- Files: `requirements.txt`, `src/llm/model_adapter.py`, `src/agent/langgraph_sql_agent.py`, `streamlit_app.py`

**Model IDs are hardcoded in application code and compose config:**
- Risk: Provider-side model availability or names can change independently of this repo.
- Impact: Startup, routing, or fallback can fail even when code is unchanged.
- Migration plan: Move model defaults into validated config, keep provider-specific smoke tests, and make model fallback errors user-safe.
- Files: `src/llm/model_adapter.py`, `src/agent/orchestrator.py`, `docker-compose.yml`

**PowerPoint support dependency is absent:**
- Risk: Future PPT generation will need a library such as `python-pptx`, direct OOXML manipulation, or an external renderer, but no dependency or abstraction is present.
- Impact: Implementers may add ad hoc binary edits or fragile XML string manipulation.
- Migration plan: Choose a PPTX library, wrap it behind a small `src` service, add template validation, and write render/extract tests before exposing downloads.
- Files: `requirements.txt`, `assets/templates/PPT_Vorlage_Wuerth.pptx`

## Missing Critical Features

**PowerPoint export pipeline:**
- Problem: The repo has the Wuerth master template but no code to transform agent output into a safe, branded deck.
- Blocks: PowerPoint generation from `reporting_result`, chart specs, tables, caveats, and SQL audit data.
- Files: `assets/templates/PPT_Vorlage_Wuerth.pptx`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`

**Access control and audit identity:**
- Problem: Memory approval, template editing, feedback, query execution, and result downloads are available inside one Streamlit app with no app-level identity.
- Blocks: Safe shared use, accountable template approval, and production deployment.
- Files: `streamlit_app.py`, `src/agent/memory_store.py`, `src/agent/logging_utils.py`, `Dockerfile`

**Result governance:**
- Problem: There is no central policy for redaction, PII handling, log retention, export retention, or user-facing error redaction.
- Blocks: Use with sensitive business data or customer-specific extracts.
- Files: `src/agent/logging_utils.py`, `streamlit_app.py`, `src/backends/demo/postgres_adapter.py`, `app/db.py`

**Query budget controls:**
- Problem: The app lacks statement timeouts, result byte limits, user quotas, and export size limits.
- Blocks: Reliable multi-user demos and safe connection to larger warehouses.
- Files: `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `streamlit_app.py`

## Test Coverage Gaps

**PowerPoint generation and template integrity:**
- What's not tested: PPTX package safety, embedded OLE object policy, placeholder/layout compatibility, slide rendering, text overflow, chart insertion, and generated deck validation.
- Files: `assets/templates/PPT_Vorlage_Wuerth.pptx`, `requirements.txt`, `evaluation/test_reporting_agent.py`, `evaluation/test_visualization_spec.py`
- Risk: A future PPT export can produce broken, unsafe, or off-brand decks without failing tests.
- Priority: High

**SQL safety beyond basic validator cases:**
- What's not tested: Function abuse, long-running read-only queries, statement timeouts, unqualified column ambiguity, CSV/log formula injection, and Databricks permission enforcement.
- Files: `src/agent/sql_validator.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`, `evaluation/test_backend_config_and_validation.py`
- Risk: Unsafe or expensive SQL can pass local validation.
- Priority: High

**Legacy CLI path:**
- What's not tested: End-to-end behavior of `main.py`, `app/sql_validator.py`, `app/query_executor.py`, and `app/prompt_builder.py`.
- Files: `main.py`, `app/sql_validator.py`, `app/query_executor.py`, `app/prompt_builder.py`
- Risk: CLI behavior drifts from the Streamlit/orchestrator path and keeps weaker SQL rules alive.
- Priority: Medium

**Memory review concurrency and data integrity:**
- What's not tested: Concurrent approvals, stale YAML saves across sessions, backup restore failure, audit log consistency, and template reactivation races.
- Files: `src/agent/memory_store.py`, `streamlit_app.py`, `memory/demo/memory_candidates.yaml`, `memory/demo/solution_templates.yaml`
- Risk: Multi-user review can lose edits or approve stale templates.
- Priority: Medium

**Golden evaluation reliability:**
- What's not tested: Golden runs without approved memory by default, orchestrator path with injected schema/executor, and cleanup/rotation of generated JSONL.
- Files: `evaluation/run_evaluation.py`, `src/agent/golden_test_runner.py`, `evaluation/demo/golden_results.jsonl`, `memory/demo/solution_templates.yaml`
- Risk: Evaluation results are hard to interpret and can be biased by committed memory or stale artifacts.
- Priority: High

**Wuerth local end-to-end data flow:**
- What's not tested: Real local CSV ingestion followed by Wuerth golden SQL execution against the created `wuerth` schema.
- Files: `scripts/ingest_wuerth_csv_to_postgres.py`, `scripts/validate_wuerth_local_setup.py`, `evaluation/wuerth_local/golden_questions.yaml`, `semantic_layer/databricks/wuerth_semantic_layer.yaml`
- Risk: Semantic rules can pass unit checks while ingestion or real query execution still fails.
- Priority: High

---

*Concerns audit: 2026-06-21*
