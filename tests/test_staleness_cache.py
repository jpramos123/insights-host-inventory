import json
from datetime import UTC
from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch

from sqlalchemy.orm.exc import NoResultFound

from api.cache import _deserialize_staleness_dict
from api.cache import _staleness_json_default
from api.cache import get_cached_staleness
from api.cache import set_cached_staleness
from api.staleness_query import get_staleness_obj
from app.staleness_serialization import AttrDict

SAMPLE_ORG_ID = "test_org_123"
SAMPLE_CREATED_ON = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
SAMPLE_MODIFIED_ON = datetime(2025, 2, 20, 14, 45, 0, tzinfo=UTC)
SAMPLE_STALENESS = AttrDict(
    {
        "id": "some-uuid-1234",
        "org_id": SAMPLE_ORG_ID,
        "conventional_time_to_stale": 86400,
        "conventional_time_to_stale_warning": 604800,
        "conventional_time_to_delete": 1209600,
        "immutable_time_to_stale": 86400,
        "immutable_time_to_stale_warning": 604800,
        "immutable_time_to_delete": 1209600,
        "created_on": SAMPLE_CREATED_ON,
        "modified_on": SAMPLE_MODIFIED_ON,
    }
)


def _make_mock_staleness_model():
    mock = MagicMock()
    mock.id = "db-uuid-5678"
    mock.org_id = SAMPLE_ORG_ID
    mock.conventional_time_to_stale = 86400
    mock.conventional_time_to_stale_warning = 604800
    mock.conventional_time_to_delete = 1209600
    mock.created_on = SAMPLE_CREATED_ON
    mock.modified_on = SAMPLE_MODIFIED_ON
    return mock


def _mock_redis():
    mock_client = MagicMock()
    return patch("api.cache._get_redis_client", return_value=mock_client), mock_client


def _redis_config(cache_type="RedisCache"):
    return patch("api.cache.CACHE_CONFIG", {"CACHE_TYPE": cache_type})


def test_datetime_serialization_roundtrip():
    serialized = json.dumps(dict(SAMPLE_STALENESS), default=_staleness_json_default)
    result = _deserialize_staleness_dict(json.loads(serialized))
    assert result["created_on"] == SAMPLE_CREATED_ON
    assert result["modified_on"] == SAMPLE_MODIFIED_ON
    # Also verify None dates survive roundtrip
    data = dict(SAMPLE_STALENESS, created_on=None, modified_on=None)
    result = _deserialize_staleness_dict(json.loads(json.dumps(data, default=_staleness_json_default)))
    assert result["created_on"] is None


def test_get_and_set_cached_staleness():
    redis_patch, mock_client = _mock_redis()
    with redis_patch, _redis_config():
        # Set
        set_cached_staleness(SAMPLE_ORG_ID, SAMPLE_STALENESS, 3600)
        assert mock_client.set.call_args[1]["ex"] == 3600
        # Get hit
        mock_client.get.return_value = mock_client.set.call_args[0][1]
        result = get_cached_staleness(SAMPLE_ORG_ID)
        assert result["org_id"] == SAMPLE_ORG_ID
        assert result["created_on"] == SAMPLE_CREATED_ON
        # Get miss
        mock_client.get.return_value = None
        assert get_cached_staleness(SAMPLE_ORG_ID) is None


def test_redis_down_degrades_gracefully():
    redis_patch, mock_client = _mock_redis()
    with redis_patch, _redis_config():
        mock_client.get.side_effect = ConnectionError("Redis unavailable")
        assert get_cached_staleness(SAMPLE_ORG_ID) is None


@patch("api.staleness_query.set_cached_staleness")
@patch("api.staleness_query.db")
@patch("api.staleness_query.get_cached_staleness")
def test_get_staleness_obj_cache_hit_skips_db(mock_get_cache, mock_db, _mock_set_cache):
    mock_get_cache.return_value = SAMPLE_STALENESS
    result = get_staleness_obj(SAMPLE_ORG_ID)
    assert result is SAMPLE_STALENESS
    mock_db.session.query.assert_not_called()


@patch("api.staleness_query.inventory_config")
@patch("api.staleness_query.set_cached_staleness")
@patch("api.staleness_query.db")
@patch("api.staleness_query.get_cached_staleness")
def test_get_staleness_obj_cache_miss_populates(mock_get_cache, mock_db, mock_set_cache, mock_config):
    mock_get_cache.return_value = None
    mock_db.session.query.return_value.filter.return_value.one.return_value = _make_mock_staleness_model()
    mock_config.return_value.staleness_cache_timeout = 3600
    result = get_staleness_obj(SAMPLE_ORG_ID)
    assert result["org_id"] == SAMPLE_ORG_ID
    mock_set_cache.assert_called_once()


@patch("api.staleness_query.build_staleness_sys_default")
@patch("api.staleness_query.set_cached_staleness")
@patch("api.staleness_query.db")
@patch("api.staleness_query.get_cached_staleness")
def test_get_staleness_obj_no_record_does_not_cache(mock_get_cache, mock_db, mock_set_cache, mock_build_default):
    mock_get_cache.return_value = None
    mock_db.session.query.return_value.filter.return_value.one.side_effect = NoResultFound()
    mock_build_default.return_value = AttrDict({"id": "system_default", "org_id": SAMPLE_ORG_ID})
    result = get_staleness_obj(SAMPLE_ORG_ID)
    assert result["id"] == "system_default"
    mock_set_cache.assert_not_called()


@patch("api.staleness._async_update_host_staleness")
@patch("api.staleness.delete_cached_staleness")
def test_create_staleness_invalidates_cache(
    mock_delete_cached,
    _mock_async,  # noqa: ARG001
    api_create_staleness,
    db_get_staleness_culling,  # noqa: ARG001
):
    data = {
        "conventional_time_to_stale": 1,
        "conventional_time_to_stale_warning": 604800,
        "conventional_time_to_delete": 1209600,
    }
    status, resp = api_create_staleness(data)
    if status == 201:
        mock_delete_cached.assert_called_once_with(resp["org_id"])
