import json
from unittest import mock

import pytest

from app.logging import threadctx
from app.models import Host
from app.models import db
from host_synchronizer import run as host_synchronizer_run
from tests.helpers.db_utils import minimal_db_host
from tests.helpers.mq_utils import assert_synchronize_event_is_valid
from tests.helpers.test_utils import get_staleness_timestamps


@pytest.mark.parametrize("ungrouped", [True, False])
@pytest.mark.host_synchronizer
def test_synchronize_host_event(
    event_producer_mock,
    event_datetime_mock,
    db_create_host,
    db_create_group,
    db_create_host_group_assoc,
    db_get_host,
    inventory_config,
    ungrouped,
):
    staleness_timestamps = get_staleness_timestamps()

    host = minimal_db_host(stale_timestamp=staleness_timestamps["culled"], reporter="some reporter")
    created_host = db_create_host(host=host)

    created_group = db_create_group("sync-test-group", ungrouped=ungrouped)
    db_create_host_group_assoc(created_host.id, created_group.id)

    assert db_get_host(created_host.id)

    threadctx.request_id = None
    host_synchronizer_run(
        inventory_config,
        mock.Mock(),
        db.session,
        event_producer_mock,
        shutdown_handler=mock.Mock(**{"shut_down.return_value": False}),
    )

    # check if host exist thought event synchronizer must find it to produce an update event.
    assert db_get_host(created_host.id)

    assert_synchronize_event_is_valid(
        event_producer=event_producer_mock,
        key=str(created_host.id),
        host=created_host,
        groups=[created_group],
        timestamp=event_datetime_mock,
    )


@pytest.mark.host_synchronizer
def test_synchronize_multiple_host_events(event_producer, db_create_multiple_hosts, inventory_config):
    host_count = 25

    db_create_multiple_hosts(how_many=host_count)

    threadctx.request_id = None
    inventory_config.script_chunk_size = 3

    event_count = host_synchronizer_run(
        inventory_config,
        mock.Mock(),
        db.session,
        event_producer,
        shutdown_handler=mock.Mock(**{"shut_down.return_value": False}),
    )

    assert event_count == host_count
    assert event_producer._kafka_producer.produce.call_count == host_count


@pytest.mark.host_synchronizer
def test_synchronizer_update_null_groups(mocker, event_producer, db_create_multiple_hosts, inventory_config):
    host_count = 25
    mocker.patch.object(event_producer, "write_event")

    hosts = db_create_multiple_hosts(how_many=host_count)
    # Set each one's groups field to null
    db.session.query(Host).filter(Host.id.in_([h.id for h in hosts])).update(
        {"groups": None}, synchronize_session="fetch"
    )
    db.session.commit()

    threadctx.request_id = None
    inventory_config.script_chunk_size = 3

    event_count = host_synchronizer_run(
        inventory_config,
        mock.Mock(),
        db.session,
        event_producer,
        shutdown_handler=mock.Mock(**{"shut_down.return_value": False}),
    )

    # Verify that the hosts' "groups" fields were updated in the DB
    synced_hosts = db.session.query(Host).filter(Host.id.in_([h.id for h in hosts]))
    for h in synced_hosts:
        assert h.groups == []

    assert event_count == host_count
    assert event_producer.write_event.call_count == host_count
    for call_arg in event_producer.write_event.call_args_list:
        host = json.loads(call_arg[0][0])["host"]
        assert host["groups"] == []


@pytest.mark.parametrize("ungrouped", [True, False])
@pytest.mark.host_synchronizer
def test_synchronize_grouped_host_event(
    event_producer_mock,
    event_datetime_mock,
    db_create_host,
    db_create_group,
    db_create_host_group_assoc,
    db_get_group_by_id,
    db_get_host,
    inventory_config,
    ungrouped,
):
    staleness_timestamps = get_staleness_timestamps()

    host = minimal_db_host(stale_timestamp=staleness_timestamps["culled"], reporter="some reporter")
    created_host = db_create_host(host=host)
    created_host_id = created_host.id

    created_group = db_create_group("sync-test-group", ungrouped=ungrouped)
    created_group_id = created_group.id

    db_create_host_group_assoc(created_host_id, created_group_id)

    # Overwrite Host.groups data
    db.session.query(Host).filter(Host.id == created_host_id).update({"groups": []})
    db.session.commit()

    retrieved_host = db_get_host(created_host_id)
    retrieved_group = db_get_group_by_id(created_group_id)

    assert retrieved_host
    assert retrieved_group
    assert retrieved_host.groups == []

    threadctx.request_id = None
    host_synchronizer_run(
        inventory_config,
        mock.Mock(),
        db.session,
        event_producer_mock,
        shutdown_handler=mock.Mock(**{"shut_down.return_value": False}),
    )

    # check if host exist thought event synchronizer must find it to produce an update event.
    assert db_get_host(retrieved_host.id)

    assert_synchronize_event_is_valid(
        event_producer=event_producer_mock,
        key=str(retrieved_host.id),
        host=retrieved_host,
        groups=[retrieved_group],
        timestamp=event_datetime_mock,
    )
