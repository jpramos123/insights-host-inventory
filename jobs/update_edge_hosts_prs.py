#!/usr/bin/python
import sys
from functools import partial
from logging import Logger

import sqlalchemy as sa
from connexion import FlaskApp
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import orm
from sqlalchemy.orm import Session

from app.environment import RuntimeEnvironment
from app.logging import get_logger
from app.models import Host
from jobs.common import excepthook
from jobs.common import job_setup

PROMETHEUS_JOB = "inventory-update-edge-hosts-prs"
LOGGER_NAME = "update-edge-hosts-prs"
RUNTIME_ENVIRONMENT = RuntimeEnvironment.JOB


@sa.event.listens_for(Host, "before_update")
def receive_before_update(mapper, connection, target):  # noqa: ARG001
    # Make sure that the modified_on field is not
    # updated in the table
    insp = sa.inspect(target)
    flag_changed, _, _ = insp.attrs.per_reporter_staleness.history
    if flag_changed:
        orm.attributes.flag_modified(target, "modified_on")


def run(logger: Logger, session: Session, application: FlaskApp):
    with application.app.app_context():
        logger.info("Starting job to update per_reporter_staleness field")

        # We only want to update Edge hosts, as other hosts are going to update
        # this value during host check in.
        reporters_list = [
            "cloud-connector",
            "puptoo",
            "rhsm-conduit",
            "rhsm-system-profile-bridge",
            "yuptoo",
            "discovery",
            "satellite",
        ]
        query_filter = and_(
            Host.system_profile_facts.has_key("host_type"),
            or_(~Host.per_reporter_staleness[reporter].has_key("culled_timestamp") for reporter in reporters_list),
        )
        query = session.query(Host).filter(query_filter)
        num_edge_hosts = query.count()

        if num_edge_hosts > 0:
            logger.info(f"There are still {num_edge_hosts} to be updated")
            for host in query.order_by(Host.org_id).yield_per(500):
                host._update_all_per_reporter_staleness()
            session.commit()


if __name__ == "__main__":
    logger = get_logger(LOGGER_NAME)
    job_type = "Update host per_reporter_staleness field for edge hosts"
    sys.excepthook = partial(excepthook, logger, job_type)

    _, session, event_producer, _, _, application = job_setup(tuple(), PROMETHEUS_JOB)
    session.expire_on_commit = False
    run(logger, session, application)
