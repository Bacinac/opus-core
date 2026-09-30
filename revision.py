"""Which build a module is: its version, the commit, and when it was made.

The stamp is ``backend/revision.json``, written from git by ``ops/revision.sh``:
by the hooks in a checkout, and by the deploy into what it ships. It is read on
every request rather than once, so a commit in a dev checkout is what the next
answer says, without a restart.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

log = logging.getLogger(__name__)

STAMP = Path(__file__).resolve().parent.parent / "revision.json"


def revision(stamp: Path | None = None) -> dict | None:
    try:
        return json.loads((stamp or STAMP).read_text())
    except (OSError, ValueError):
        return None


def router(product: str, stamp: Path | None = None) -> APIRouter:
    """``GET /version``, answered as ``product`` so a peer can tell the modules
    apart."""
    routes = APIRouter()

    @routes.get("/version")
    async def version():
        found = revision(stamp)
        if found is None:
            log.error("%s carries no revision stamp at %s", product, stamp or STAMP)
            raise HTTPException(404, "this build carries no revision stamp")
        return {"product": product, **found}

    return routes
