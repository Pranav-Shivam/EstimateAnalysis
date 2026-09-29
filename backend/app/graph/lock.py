import zlib

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.graph.constant import REBUILD_LOCK_CLASSID


def _lock_objid(ns: str) -> int:
    return zlib.crc32(ns.encode("utf-8")) & 0x7FFFFFFF


def try_lock_rebuild(session: Session, ns: str) -> bool:
    """Take the session-level rebuild lock for one namespace without waiting. False when another session holds it."""
    return bool(session.scalar(
        text("SELECT pg_try_advisory_lock(:classid, :objid)"), {"classid": REBUILD_LOCK_CLASSID, "objid": _lock_objid(ns)},
    ))


def unlock_rebuild(session: Session, ns: str) -> None:
    session.execute(
        text("SELECT pg_advisory_unlock(:classid, :objid)"), {"classid": REBUILD_LOCK_CLASSID, "objid": _lock_objid(ns)},
    )
