"""Vercel ASGI entrypoint for the ValuSee API project.

The consumer Web is deployed as a separate Vite project. Stateful production
dependencies remain external; Vercel's ephemeral filesystem is preview-only.
"""

from app.main import app

__all__ = ["app"]
