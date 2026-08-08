# ValuSee Business Scenarios

ValuSee is a project intelligence and engineering governance workbench. Its purpose is to help a software team make better decisions around an existing system, rather than act as a code-writing IDE.

## 1. PR Change Risk Review

### Problem

Reviewers often see only the changed lines. The real risk may be in a downstream service, an undocumented dependency, a missing test, or a project rule recorded in an old discussion.

### Workflow

```text
Repository / PR diff
  -> changed-file and call-chain analysis
  -> project rules and historical knowledge retrieval
  -> deterministic rule review + semantic review
  -> risk aggregation and human approval
  -> Chinese governance report and review actions
```

### Output

- change impact scope and affected modules;
- risk findings with severity, evidence, and source files;
- missing or weak test coverage;
- recommended validation steps;
- approval, rejection, or manual-review status.

### Value

The team can identify likely regressions before merge and give reviewers an evidence-based decision instead of another unstructured AI answer.

## 2. Project Onboarding

### Problem

New developers spend days locating the entry point, understanding module responsibilities, and discovering undocumented project conventions.

### Workflow

```text
Repository
  -> structure and technology analysis
  -> architecture and module knowledge ingestion
  -> role-based learning plan
  -> interactive project questions
  -> confirmed knowledge retained for the next teammate
```

### Output

- architecture overview and service entry points;
- module responsibilities and important files;
- dependency and request-flow explanations;
- staged learning plan;
- interactive follow-up questions based on the current project context.

### Value

The project becomes easier to hand over, and experienced engineers spend less time repeating the same architecture explanation.

## 3. Architecture and Technical Debt Governance

### Problem

Architecture drift and technical debt accumulate gradually. Teams usually notice them only after release failures, slow delivery, or a difficult refactor.

### Workflow

```text
Repository snapshots and project rules
  -> version-aware incremental indexing
  -> dependency, module, and policy analysis
  -> historical comparison and risk prioritization
  -> human review and governance report
  -> tracked follow-up actions
```

### Output

- architecture drift and policy deviations;
- high-coupling or high-change modules;
- dependency and security risk priorities;
- missing tests and maintainability concerns;
- concrete governance actions with evidence and owners.

### Value

The team gets a repeatable way to prioritize technical debt and improve architecture before problems become emergency work.

## Shared Governance Layer

All three workflows use the same project context and controls:

- LangGraph coordinates Planner, Analyzer, Reviewer, Supervisor, and Reporter agents;
- Harness Runtime persists task state, events, artifacts, review decisions, and resume checkpoints;
- RAG uses incremental indexing, document versions, ACL filtering, hybrid retrieval, reranking, and Gold Set evaluation;
- controlled long-term memory separates user, project, and team knowledge and supports confirmation, conflict replacement, and decay;
- Skills and MCP tools are permission-scoped and approval-scoped by execution identity;
- LLM traces, prompt versions, fallback events, token usage, and cost remain auditable.

## Recommended Adoption Path

1. Start with Project Onboarding to build the initial project knowledge base.
2. Add PR Change Risk Review when the team needs pre-merge governance.
3. Schedule Architecture and Technical Debt Governance for periodic project health checks.

This path lets a team gain value from one repository immediately while gradually introducing stronger governance.

## Run From API or UI

The Run page exposes all three scenarios under **业务场景**. Select one, confirm the repository path and click **运行当前业务场景**. The result uses the same timeline, human-review gate, report, history, and project-memory follow-up as a normal task.

The API is also available for CI or scheduled jobs:

```text
GET  /api/v1/business-scenarios
POST /api/v1/business-scenarios/run
POST /api/v1/business-scenarios/run/stream
```

Reproducible payloads are in `examples/business/`. PR review accepts `pr_base` and `pr_head`; when both are empty it reviews the current local working-tree diff.

## GitHub PR Integration

### Direct PR URL

Set `GITHUB_TOKEN` in `.env` with permission to read pull requests. Then call:

```json
POST /api/v1/business-scenarios/run
{
  "business_scenario": "pr_review",
  "pr_url": "https://github.com/owner/repository/pull/123",
  "require_human_review": true,
  "post_comment": true
}
```

The service downloads the PR metadata and unified diff through the GitHub API. With `post_comment: true`, the final Chinese governance report is posted to the PR conversation. Without a local `project_path`, URL mode performs diff-level deterministic review; providing both URL and local path additionally enables repository-level review context.

### Webhook

1. Set `GITHUB_TOKEN` and a random `GITHUB_WEBHOOK_SECRET` in `.env`.
2. In GitHub repository **Settings -> Webhooks**, use `https://your-host/api/v1/integrations/github/webhook`.
3. Select `application/json`, enter the same secret, and subscribe to **Pull requests**.
4. The service accepts `opened`, `reopened`, and `synchronize`, verifies `X-Hub-Signature-256`, creates a persisted PR review task in the background, and posts the result back to the PR.

The token needs pull-request read access and issue/pull-request comment write access. Invalid signatures return `401`; unsupported events are acknowledged but ignored.
