from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.code_review_tools import review_project
from app.agents.learning_tools import build_learning_plan
from app.agents.rag_tools import process_knowledge
from app.agents.workflow_tools import run_workflow
from app.skills.base import SkillContext


@dataclass
class ProjectCodeReviewSkill:
    code: str = "code.review"
    name: str = "代码规则审查"
    description: str = "扫描项目源码，基于确定性规则发现安全、可靠性和可维护性问题。"

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        return review_project(input_data["project_path"], input_data.get("max_files", 500))


@dataclass
class RagKnowledgeProcessSkill:
    code: str = "rag.process"
    name: str = "RAG 知识加工"
    description: str = "抽取文档、切片、关键词和 FAQ，为后续向量入库做准备。"

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        return process_knowledge(input_data["project_path"], input_data.get("max_files", 300))


@dataclass
class LearningCoachSkill:
    code: str = "learning.plan"
    name: str = "学习陪练计划"
    description: str = "根据主题、水平、周期和目标生成学习计划。"

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        return build_learning_plan(
            input_data["topic"],
            input_data.get("level", "beginner"),
            input_data.get("days", 7),
            input_data.get("goal"),
        )


@dataclass
class WorkflowRunSkill:
    code: str = "workflow.run"
    name: str = "工作流运行"
    description: str = "运行线性 Workflow MVP，并返回节点事件和最终输出。"

    def execute(self, context: SkillContext, input_data: dict[str, Any]) -> dict[str, Any]:
        return run_workflow(
            input_data.get("workflow_name", "custom_workflow"),
            input_data.get("input_text", ""),
            input_data.get("nodes", []),
        )


def builtin_skills() -> list:
    return [
        ProjectCodeReviewSkill(),
        RagKnowledgeProcessSkill(),
        LearningCoachSkill(),
        WorkflowRunSkill(),
    ]

