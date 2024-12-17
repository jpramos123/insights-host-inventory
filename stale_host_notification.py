#!/usr/bin/python
import sys
from datetime import datetime
from datetime import timezone
from functools import partial

from sqlalchemy import ColumnElement
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.auth.identity import create_mock_identity_with_org_id
from app.auth.identity import to_auth_header
from app.instrumentation import log_host_stale_notification_succeeded
from app.logging import get_logger
from app.logging import threadctx
from app.models import Host
from app.models import HostInventoryMetadata
from app.models import Staleness
from app.queue.host_mq import OperationResult
from app.queue.notifications import NotificationType
from app.queue.notifications import send_notification
from jobs.common import excepthook
from jobs.common import main
from lib.host_repository import find_stale_host_sys_default_staleness
from lib.host_repository import find_stale_hosts
from lib.metrics import stale_host_notification_count
from lib.metrics import stale_host_notification_fail_count
from lib.metrics import stale_host_notification_processing_time

LOGGER_NAME = "stale_host_notification"
PROMETHEUS_JOB = "inventory-stale-host-notification"
COLLECTED_METRICS = (
    stale_host_notification_count,
    stale_host_notification_processing_time,
    stale_host_notification_fail_count,
)


def _create_host_operation_result(host, identity, logger):
    return OperationResult(
        host,
        {"b64_identity": to_auth_header(identity)} if identity else None,
        None,
        None,
        None,
        partial(log_host_stale_notification_succeeded, logger, host.id, control_rule="HOST_STALE_NOTIFICATION"),
    )


def _create_host_stale_metadata_in_db(session: Session) -> HostInventoryMetadata:
    # Create host_stale metadata
    try:
        host_inv_metadata = HostInventoryMetadata(name="host_stale", type="job")
        session.add(host_inv_metadata)
        session.commit()
    except Exception as e:
        logger.error(e)
        raise
    return host_inv_metadata


def _query_or_create_host_stale(session: Session) -> HostInventoryMetadata:
    try:
        stale_host_timestamp = (
            session.query(HostInventoryMetadata)
            .where(HostInventoryMetadata.name == "host_stale", HostInventoryMetadata.type == "job")
            .one()
        )
    except NoResultFound:
        stale_host_timestamp = _create_host_stale_metadata_in_db(session)

    return stale_host_timestamp


def _last_run_time_diff_in_sec(session, stale_host_timestamp):
    # Find the difference between the last succesful run and now in seconds
    now = datetime.now(timezone.utc)
    last_update = stale_host_timestamp.last_update
    last_run_diff = now - last_update
    return int(last_run_diff.total_seconds())


def _find_stale_hosts_using_custom_staleness(logger, session, last_run_secs) -> ColumnElement:
    staleness_objects = session.query(Staleness).all()
    org_ids = []

    query_filters = []
    for staleness_obj in staleness_objects:
        # Validate which host types for a given org_id never get deleted
        logger.debug(f"Looking for hosts from org_id {staleness_obj.org_id} that use custom staleness")
        org_ids.append(staleness_obj.org_id)
        identity = create_mock_identity_with_org_id(staleness_obj.org_id)
        query_filters.append(
            and_(
                (Host.org_id == staleness_obj.org_id),
                find_stale_hosts(identity, last_run_secs),
            )
        )
    return query_filters, org_ids


def _find_stale_hosts_using_sys_default_staleness(logger, org_ids, last_run_secs) -> ColumnElement:
    # Use the hosts_ids_list to exclude hosts that were found with custom staleness
    logger.debug("Looking for hosts that use system default staleness")
    return and_(~Host.org_id.in_(org_ids), find_stale_host_sys_default_staleness(last_run_secs))


def _find_stale_hosts(logger, session, stale_host_timestamp):
    last_run_secs = _last_run_time_diff_in_sec(session, stale_host_timestamp)

    # Find all host ids that are using custom staleness
    query_filters, org_ids = _find_stale_hosts_using_custom_staleness(logger, session, last_run_secs)

    # Find all host ids that are not using custom staleness,
    # excluding the hosts for the org_ids that use custom staleness
    query_filters.append(_find_stale_hosts_using_sys_default_staleness(logger, org_ids, last_run_secs))

    return query_filters


@stale_host_notification_fail_count.count_exceptions()
def run(logger, session, notification_event_producer, shutdown_handler, application):
    with application.app.app_context(), stale_host_notification_processing_time.time():
        stale_host_timestamp = _query_or_create_host_stale(session)
        filter_stale_hosts = _find_stale_hosts(logger, session, stale_host_timestamp)

        query = session.query(Host).filter(or_(False, *filter_stale_hosts))
        stale_hosts = query.all()
        if len(stale_hosts) > 0:
            logger.info("%s hosts found as stale", len(stale_hosts))
            for host in stale_hosts:
                identity = create_mock_identity_with_org_id(host.org_id)
                result = _create_host_operation_result(host, identity, logger)
                try:
                    send_notification(
                        notification_event_producer, NotificationType.system_became_stale, vars(result.host_row)
                    )

                    stale_host_timestamp._update_last_update()
                    session.commit()
                    stale_host_notification_count.inc()
                    result.success_logger()

                except Exception:
                    logger.error("Error when sending notification")
        else:
            logger.info("No hosts found as stale")


if __name__ == "__main__":
    logger = get_logger(LOGGER_NAME)
    job_type = "Stale host notification"
    sys.excepthook = partial(excepthook, logger, job_type)

    threadctx.request_id = None
    _, logger, session, _, notification_event_producer, shutdown_handler, application = main(
        logger, COLLECTED_METRICS, PROMETHEUS_JOB
    )
    run(logger, session, notification_event_producer, shutdown_handler, application)
