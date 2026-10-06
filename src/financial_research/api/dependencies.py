"""Replaceable factories; live providers are created lazily inside each build."""

from collections.abc import Callable
from typing import cast

from fastapi import Request

from financial_research.tools.service import ResearchTools

ToolsFactory = Callable[[], ResearchTools]


def get_research_tools(request: Request) -> ResearchTools:
    factory = cast(ToolsFactory, request.app.state.tools_factory)
    return factory()
