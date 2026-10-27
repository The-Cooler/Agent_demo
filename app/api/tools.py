from typing import Any

from fastapi import APIRouter, Depends

from app.deps import get_registry
from app.tools.base import ToolRegistry

router = APIRouter()


@router.get("/tools")
def list_tools(registry: ToolRegistry = Depends(get_registry)) -> list[dict[str, Any]]:
    return registry.schemas()
