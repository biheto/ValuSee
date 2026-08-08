from pathlib import Path

from app.business_scenarios import run_business_scenario


ROOT = Path(__file__).resolve().parents[1]


def test_pr_review_scenario_returns_merge_gate_report():
    result = run_business_scenario({
        "business_scenario": "pr_review",
        "project_path": str(ROOT),
        "goal": "review local changes",
        "max_files": 20,
        "require_human_review": True,
    })["result"]
    assert result["business_scenario"] == "pr_review"
    assert result["final_report"]
    assert "risk_level" in result
    assert result["human_review_packet"]["status"] == "pending"


def test_onboarding_scenario_returns_learning_artifacts():
    result = run_business_scenario({
        "business_scenario": "onboarding",
        "project_path": str(ROOT),
        "goal": "understand this repository",
        "max_files": 20,
        "require_human_review": False,
    })["result"]
    assert result["business_scenario"] == "onboarding"
    assert result["onboarding_artifacts"]["learning_path"]
    assert result["final_report"]


def test_governance_scenario_returns_governance_artifacts():
    result = run_business_scenario({
        "business_scenario": "governance",
        "project_path": str(ROOT),
        "goal": "identify technical debt",
        "max_files": 20,
        "require_human_review": False,
    })["result"]
    assert result["business_scenario"] == "governance"
    assert "debt_register" in result["governance_artifacts"]
    assert result["final_report"]
