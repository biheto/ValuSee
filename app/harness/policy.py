from __future__ import annotations

from app.agents.marketplace_tools import check_permission


class ToolPolicy:
    def allow(self, agent_code: str, tool_code: str) -> bool:
        return check_permission(agent_code, tool_code)["allowed"]

    def require(self, agent_code: str, tool_code: str) -> None:
        if not self.allow(agent_code, tool_code):
            raise PermissionError(f"Tool {tool_code} is not allowed for agent {agent_code}")


tool_policy = ToolPolicy()

