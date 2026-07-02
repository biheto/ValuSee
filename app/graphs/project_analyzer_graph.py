from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.project_tools import (
    analyze_modules,
    extract_api_hints,
    generate_findings,
    generate_report,
    identify_tech_stack,
    quality_score,
    scan_project,
)


class ProjectAnalyzerState(TypedDict, total=False):
    project_path: str
    max_files: int
    scan: dict[str, Any]
    tech_stack: list[str]
    modules: list[str]
    api_hints: list[str]
    risks: list[str]
    suggestions: list[str]
    quality_score: int
    report_markdown: str


def scan_project_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    scan = scan_project(state["project_path"], state.get("max_files", 500))
    return {**state, "scan": scan}


def identify_stack_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    tech_stack = identify_tech_stack(state["scan"])
    return {**state, "tech_stack": tech_stack}


def analyze_structure_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    modules = analyze_modules(state["scan"])
    api_hints = extract_api_hints(state["scan"])
    return {**state, "modules": modules, "api_hints": api_hints}


def generate_findings_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    risks, suggestions = generate_findings(
        state["scan"], state.get("tech_stack", []), state.get("modules", [])
    )
    return {**state, "risks": risks, "suggestions": suggestions}


def supervise_report_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    score = quality_score(state["scan"], state.get("tech_stack", []), state.get("risks", []))
    return {**state, "quality_score": score}


def generate_report_node(state: ProjectAnalyzerState) -> ProjectAnalyzerState:
    report = generate_report(
        state["scan"],
        state.get("tech_stack", []),
        state.get("modules", []),
        state.get("api_hints", []),
        state.get("risks", []),
        state.get("suggestions", []),
        state.get("quality_score", 0),
    )
    return {**state, "report_markdown": report}


def build_project_analyzer_graph():
    graph = StateGraph(ProjectAnalyzerState)
    graph.add_node("scan_project", scan_project_node)
    graph.add_node("identify_stack", identify_stack_node)
    graph.add_node("analyze_structure", analyze_structure_node)
    graph.add_node("generate_findings", generate_findings_node)
    graph.add_node("supervise_report", supervise_report_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("scan_project")
    graph.add_edge("scan_project", "identify_stack")
    graph.add_edge("identify_stack", "analyze_structure")
    graph.add_edge("analyze_structure", "generate_findings")
    graph.add_edge("generate_findings", "supervise_report")
    graph.add_edge("supervise_report", "generate_report")
    graph.add_edge("generate_report", END)
    return graph.compile()


project_analyzer_graph = build_project_analyzer_graph()
