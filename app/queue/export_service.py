from http import HTTPStatus

from app import RbacPermission
from app import RbacResourceType
from app.logging import get_logger
from lib.middleware import rbac

logger = get_logger(__name__)


# This function is used by create_export
def _handle_rbac_to_export(func, org_id, rbac_request_headers):
    logger.debug("Getting RBAC data")
    rbac_result = rbac(
        RbacResourceType.HOSTS, RbacPermission.READ, org_id=org_id, rbac_request_headers=rbac_request_headers
    )
    filter_func = rbac_result(func)
    filter = filter_func()
    return filter


def create_export(export_svc_data, org_id, operation_args={}, rbac_filter=None):
    # Here we make the DB call and create the export
    # Check PoC reference:
    # https://github.com/RedHatInsights/insights-host-inventory/pull/1671/files#diff-13296d264df528a2181ea43f8fa5ebaed8a5f66b06767e5e75bbc3549ac0f29aR30-R88
    logger.info("Creating export for HBI")
    return True


# This function is used by create_export, needs improvement
def _handle_export_response(response, exportFormat, exportUUID):
    if response.status_code != HTTPStatus.ACCEPTED:
        raise Exception(response.text)
    else:
        logger.info(f"{response.text} for export ID {exportUUID} in {exportFormat.upper()} format")
