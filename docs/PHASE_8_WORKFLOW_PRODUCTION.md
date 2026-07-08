# Phase 8 - Workflow Productionization

## Scope

This phase turns the visual Workflow from a demo canvas into a safer task execution entry.

Implemented:

- Workflow validator with API endpoint `POST /api/v1/workflows/validate`.
- Node pre-run confirmation through `config.confirm_before_run`.
- Node retry through `config.retry_count`.
- Node input/output mapping through `config.input_from`, `config.input_path`, and `config.output_key`.
- Conditional edges through `condition`, `value`, and `source_path`.
- Parallel fan-out through multiple outgoing edges from the same source node.
- Checkpoint-backed approval resume for paused Workflow tasks.

## Runtime Semantics

- All edges are routed by the compiler, so pause checks, conditions, and parallel fan-out share one path.
- If a node has `confirm_before_run=true`, the workflow emits a `waiting_review` event, creates a `human_review_packet`, stores a `resume_checkpoint`, and stops downstream execution.
- When the task is approved through `POST /api/v1/tasks/{task_id}/approve`, the same task resumes from the paused node with the saved state.
- A normal `human_review` node also resumes from that node after approval and then continues to downstream nodes.
- If a node fails after retries, the default `fail_strategy` is `halt`; set `fail_strategy=continue` to allow downstream routing.
- Conditional edge types:
  - `always`
  - `contains`
  - `on_status`
  - `truthy_output`

## Resume Notes

The current implementation stores a compact JSON checkpoint in SQLite artifacts. It preserves workflow definition, paused node id, previous node outputs, tool calls, agent outputs, suggestions, and task context. It resumes by compiling the same Workflow with the paused node as the entry point and passing an approval map into graph state.
