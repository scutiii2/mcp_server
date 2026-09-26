"""/api/config-issues: problems in ember_api's config and secret files
(config.issues.view). File and key names only, never secret values."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.config import Settings
from src.deps import get_settings, require_permission
from src.models import Account
from src.services.config_validation import collect_issues_async
from src.services.permissions import CONFIG_ISSUES_VIEW

router = APIRouter(prefix="/api/config-issues", tags=["config"])

require_config = require_permission(CONFIG_ISSUES_VIEW)


class ConfigIssueOut(BaseModel):
    file: str
    key: str
    message: str


@router.get("")
async def list_config_issues(
    _account: Account = Depends(require_config), settings: Settings = Depends(get_settings)
) -> list[ConfigIssueOut]:
    return [ConfigIssueOut(file=i.file, key=i.key, message=i.message) for i in await collect_issues_async(settings)]
