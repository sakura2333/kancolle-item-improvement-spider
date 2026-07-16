import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lxml import etree

from service.akashi_list.akashi_detail_processor import DetailProcessor
from service.akashi_list.akashi_list_utils import convert_vo
from service.data_package.builder import build_data_package
from service.operator_stop import OperatorStopError, write_operator_stop
from service.data_package.equipment_bonus import SOURCE_URL as KC3_BONUS_URL
from service.data_package.equipment_drop_from import (
    EQUIPMENT_URL as KCWIKI_EQUIPMENT_URL,
    SHIP_URL as KCWIKI_SHIP_URL,
)
from service.source_validation.runner import run_source_validation
from service.source_validation.wikiwiki_jp import SOURCE_URL as WIKIWIKI_URL
from util.cache import fetch, mark_collection_completed
from util.export_utils import clear, export_data
from util.logger import simple_logger
from util.site_workers import SiteTask, run_site_tasks
from util.start2.start2_utils import update_start2_if_needed

AKASHI_URL = "https://akashi-list.me/"


def _collect_akashi():
    """Collect Akashi List serially inside its single website worker."""

    page = fetch(AKASHI_URL)
    page_node = etree.HTML(page)
    weapon_list = page_node.xpath("//div[@id='weapon-remodel']/div")

    detail_processor = DetailProcessor()
    for weapon in weapon_list:
        if weapon.xpath(".//div[@class='noremodel']"):
            continue
        weapon_id = weapon.attrib["id"]
        detail_page = fetch(f"https://akashi-list.me/detail/{weapon_id}.html")
        detail_processor.process_detail_page(page=detail_page)

    return convert_vo(detail_processor.result)


def _prefetch(url: str, *, require_fresh: bool | None = None):
    fetch(url, require_fresh=require_fresh)
    return url


def collect_akashi_source_records():
    """Public acquisition entry used by the source-bundle workflow."""
    return _collect_akashi()


def prefetch_source(url: str, *, require_fresh: bool | None = None):
    """Populate the shared source cache without producing projections."""
    return _prefetch(url, require_fresh=require_fresh)


def process(url=AKASHI_URL):
    # Concurrency scales only with the number of websites. Every request for a
    # particular hostname remains serial, avoiding bursts against Akashi List or
    # GitHub Raw while allowing independent sources to make progress together.
    tasks = [
        SiteTask("akashi-list", url, _collect_akashi),
        SiteTask("wikiwiki-jp", WIKIWIKI_URL, lambda: _prefetch(WIKIWIKI_URL)),
        SiteTask(
            "kcwiki-equipment",
            KCWIKI_EQUIPMENT_URL,
            lambda: _prefetch(KCWIKI_EQUIPMENT_URL, require_fresh=False),
        ),
        SiteTask(
            "kcwiki-ship",
            KCWIKI_SHIP_URL,
            lambda: _prefetch(KCWIKI_SHIP_URL, require_fresh=False),
        ),
        SiteTask("kc3-bonus", KC3_BONUS_URL, lambda: _prefetch(KC3_BONUS_URL)),
    ]
    results = run_site_tasks(tasks)
    optional_kcwiki_failures = {
        key: value
        for key, value in results.items()
        if key in {"kcwiki-equipment", "kcwiki-ship"}
        and isinstance(value, Exception)
    }
    for key, error in optional_kcwiki_failures.items():
        simple_logger.error(
            "[KCWIKI RAW UNAVAILABLE][NON-BLOCKING] "
            f"{key}: {type(error).__name__}: {error}"
        )

    failures = {
        key: value
        for key, value in results.items()
        if isinstance(value, Exception)
        and key not in optional_kcwiki_failures
    }
    if failures:
        summary = ", ".join(f"{key}: {error}" for key, error in failures.items())
        raise OperatorStopError(
            stop_reason="source-collection-retry-exhausted",
            message=f"网站数据源采集失败且自动重试已结束：{summary}",
            action="检查网络、代理和对应站点状态；修复后重新执行 ./flow run。",
            checkpoint=".flow/local/source-cache/_meta.json",
            details={
                key: f"{type(error).__name__}: {error}"
                for key, error in failures.items()
            },
        ) from next(iter(failures.values()))

    vo_list = results["akashi-list"]
    clear()
    export_data(vo_list)
    # Validation is a side channel: it writes only under dist/data-pipeline/sources and never
    # changes the public plugin projections generated above.
    run_source_validation(vo_list)
    mark_collection_completed("akashi-list")
    # Build the reusable npm data package after canonical output and audit data.
    # External dataset failures are non-fatal unless DATA_PACKAGE_STRICT=1.
    build_data_package()


def main() -> int:
    try:
        update_start2_if_needed()
        process()
    except OperatorStopError as exc:
        write_operator_stop(exc)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
