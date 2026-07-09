# DevAgent Studio Implementation Timeline

This document records the implementation history, MVP scope, priority order, and current completion status for DevAgent Studio. It is written for GitHub review, project interviews, and future milestone tracking.

## Product Positioning

DevAgent Studio is a multi-agent workbench for software project understanding and engineering governance. It uses FastAPI and LangGraph to orchestrate project analysis, code review, RAG knowledge processing, learning coaching, MCP tools, visual workflows, human review, LLM governance, and benchmark evaluation.

The project is intentionally not positioned as a code-writing IDE. Its core value is helping users understand a software project, identify risks, preserve project knowledge, review engineering quality, and interact with agents through traceable workflows.

## MVP Definition

The MVP goal was to build an end-to-end agent workbench that can:

1. Accept a local project path and user goal.
2. Analyze project structure and technical stack.
3. Review code risks and generate governance suggestions.
4. Process project knowledge for RAG-style retrieval.
5. Run multi-agent collaboration through LangGraph.
6. Support human review and task persistence.
7. Provide a usable web UI with visual workflow execution.

The MVP was considered complete once a user could run a project understanding task from the UI, see execution events, inspect agent outputs, review the final report, and reopen historical tasks.

## Chronological Milestones

| Date | Priority | Milestone | Status | Summary |
| --- | --- | --- | --- | --- |
| 2026-07-02 | P0 | Project foundation and positioning | Completed | Created the FastAPI + LangGraph project structure, initial design docs, project analyzer graph, schemas, and basic API surface. |
| 2026-07-02 | P0 | Core agent MVP | Completed | Added Project Analysis Agent, Code Review Agent, RAG Processing Agent, Learning Coach Agent, MCP-shaped tools, visual workflow API, and collaboration graph prototypes. |
| 2026-07-03 | P0 | Web workbench MVP | Completed | Added React + TypeScript workbench with task form, event timeline, final report, history replay, and visual workflow canvas. |
| 2026-07-04 | P0 | Workflow runtime integration | Completed | Made visual workflows a real task execution entry instead of a demo canvas. Added left menu, timeline, graph execution view, right-side state panels, and report tabs. |
| 2026-07-04 | P1 | Visual workflow production features | Completed | Added workflow validation, graph execution mapping, node state display, task mode handling, and workflow-to-LangGraph compilation flow. |
| 2026-07-06 | P1 | Runtime hardening | Completed | Added Skill abstraction, Harness Runtime, true collaboration graph execution, SQLite task persistence, unified task API, and task event storage. |
| 2026-07-06 | P1 | RAG persistence with pgvector | Completed | Added PostgreSQL + pgvector-backed RAG store, document ingestion, retrieval APIs, Docker Compose setup, and database inspection guidance. |
| 2026-07-06 | P1 | Human review resume flow | Completed | Added checkpoint/resume style workflow behavior, node-level human approval, rejection handling, retry behavior, and visual resume information. |
| 2026-07-07 | P2 | LLM governance | Completed | Added LLM trace table, per-agent model configuration, prompt version management, token/cost usage dashboard, Prompt A/B test support, and LLM console UI. |
| 2026-07-08 | P2 | Real MCP client | Completed | Added real stdio MCP server configuration, tool discovery, tool registry, enable/disable controls, approval management, call logs, and workflow MCP tool execution. |
| 2026-07-08 | P2 | MCP management UI | Completed | Added MCP page for server configuration, discover, approval, test calls, expandable JSON logs, and real filesystem/memory MCP examples. |
| 2026-07-09 | P3 | Benchmark MVP | Completed | Added MCP benchmark runner, benchmark persistence tables, benchmark APIs, benchmark UI, metrics dashboard, historical runs, and result details. |

## Priority Breakdown

### P0: MVP Execution Loop

The first priority was to make the product usable end to end.

Implemented:

- FastAPI service foundation.
- LangGraph-based project analysis graph.
- Project analyzer, code reviewer, RAG processor, learning coach, supervisor, and reporter roles.
- Unified task run API.
- React web workbench.
- Execution timeline.
- Markdown report rendering.
- Historical task replay.
- Visual workflow canvas.

Completion state: closed for MVP.

Remaining follow-up: improve evaluation quality and production observability.

### P1: Runtime and Workflow Productionization

The second layer focused on making the system behave like a real agent runtime instead of isolated demos.

Implemented:

- Skill abstraction.
- Harness Runtime.
- Collaboration graph wrapper.
- SQLite task persistence.
- Workflow JSON validation.
- Workflow JSON to LangGraph compilation.
- Human review and resume behavior.
- Node retry and rejection behavior.
- pgvector-backed RAG persistence.

Completion state: closed for current production baseline.

Remaining follow-up: add deeper workflow input/output mapping and advanced branching UX.

### P2: Governance and Tooling

The third layer focused on observability, model governance, and real tool integration.

Implemented:

- LLM call trace.
- Token and cost dashboard.
- Prompt version management.
- Prompt editing.
- Prompt A/B testing.
- Per-agent model configuration.
- Real MCP provider.
- MCP server registry.
- MCP tool registry.
- MCP approval records.
- MCP call logs.
- MCP management page.

Completion state: closed for MVP governance.

Remaining follow-up: add prompt quality scoring datasets and richer MCP marketplace packaging.

### P3: Evaluation and Benchmark

The fourth layer focused on making the platform measurable.

Implemented:

- Benchmark run table.
- Benchmark result table.
- MCP benchmark runner.
- Default MCP benchmark cases.
- Success rate, average latency, P95 latency, failure count, and per-case metrics.
- Benchmark history and result detail UI.

Completion state: MCP benchmark MVP is closed.

Remaining follow-up:

- LLM benchmark for prompt/model comparison.
- RAG benchmark for retrieval quality.
- Workflow benchmark for reliability and latency.
- Multi-agent benchmark for report quality and governance coverage.

## Current Benchmark Dataset

The first benchmark dataset is an MCP tool dataset. Each case has a fixed tool, fixed arguments, and repeatable iterations.

Default cases:

- `fs_read_readme`: read the project README through filesystem MCP.
- `fs_list_project`: list the project root through filesystem MCP.
- `fs_search_mcp`: search MCP-related Python files.
- `memory_search_project`: query project memory through memory MCP.
- `memory_read_graph`: read the memory graph.

Metrics:

- Total calls.
- Completed calls.
- Failed calls.
- Success rate.
- Average latency.
- P95 latency.
- Minimum latency.
- Maximum latency.
- Per-case breakdown.

This benchmark is intended to answer whether MCP tools are stable, approved correctly, discoverable, and fast enough for workflow execution.

## Suggested Git Commit Plan

Because the current workspace did not have a valid historical Git repository, exact historical code snapshots cannot be reconstructed honestly. The recommended GitHub submission strategy is:

1. `chore: initialize DevAgent Studio repository`
   - Add project scaffold, configuration, setup scripts, Docker Compose, and documentation.
2. `feat: add LangGraph multi-agent MVP`
   - Add backend agents, graphs, schemas, API routes, and runtime foundation.
3. `feat: add web workbench and visual workflow execution`
   - Add React UI, task execution page, workflow canvas, reports, history, and interaction pages.
4. `feat: add RAG persistence and real MCP integration`
   - Add pgvector RAG store, MCP provider, MCP scripts, tool discovery, approval, and logs.
5. `feat: add LLM governance and prompt management`
   - Add LLM traces, usage dashboard, prompt versions, prompt editing, and A/B testing.
6. `feat: add benchmark runner and evaluation dashboard`
   - Add benchmark persistence, MCP benchmark APIs, benchmark UI, and metrics.
7. `docs: document implementation timeline and priorities`
   - Add this timeline and completion summary.

For open-source presentation, keep commits grouped by capability so that reviewers can follow the architecture, runtime, UI, governance, and benchmark evolution clearly.
