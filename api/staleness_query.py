from sqlalchemy.orm.exc import NoResultFound

from api.cache import get_cached_staleness
from api.cache import set_cached_staleness
from app.common import inventory_config
from app.logging import get_logger
from app.models import Staleness
from app.models import db
from app.staleness_serialization import AttrDict
from app.staleness_serialization import build_serialized_acc_staleness_obj
from app.staleness_serialization import build_staleness_sys_default

logger = get_logger(__name__)


def get_staleness_obj(org_id: str) -> AttrDict:
    # Try cache first
    cached = get_cached_staleness(org_id)
    if cached is not None:
        logger.debug(f"Cache hit for staleness org_id={org_id}")
        return cached

    try:
        staleness = db.session.query(Staleness).filter(Staleness.org_id == org_id).one()
        logger.info(f"Using custom staleness for org {org_id}.")
        staleness = build_serialized_acc_staleness_obj(staleness)
    except NoResultFound:
        logger.debug(f"No custom staleness data found for org {org_id}, using system default values instead.")
        staleness = build_staleness_sys_default(org_id)
        return staleness

    # Cache the custom staleness record
    try:
        config = inventory_config()
        set_cached_staleness(org_id, staleness, config.staleness_cache_timeout)
    except Exception:
        logger.exception(f"Failed to cache staleness for org_id={org_id}")

    return staleness
