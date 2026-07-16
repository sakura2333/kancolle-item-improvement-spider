from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, Generic, Iterable, List, TypeVar
from urllib.parse import urlparse

from util.logger import simple_logger

T = TypeVar("T")


@dataclass(frozen=True)
class SiteTask(Generic[T]):
    """A unit of work associated with one remote website.

    Tasks sharing a hostname are always executed serially. Different hostnames
    receive at most one worker each, so adding more URLs from one source never
    increases request concurrency against that source.
    """

    key: str
    url: str
    callback: Callable[[], T]

    @property
    def site(self) -> str:
        return urlparse(self.url).netloc or f"task:{self.key}"


def _run_group(tasks: List[SiteTask[T]]) -> Dict[str, T | Exception]:
    results: Dict[str, T | Exception] = {}
    for task in tasks:
        try:
            results[task.key] = task.callback()
        except Exception as exc:  # caller decides whether a source is optional
            results[task.key] = exc
    return results


def run_site_tasks(tasks: Iterable[SiteTask[T]]) -> Dict[str, T | Exception]:
    task_list = list(tasks)
    keys = [task.key for task in task_list]
    if len(keys) != len(set(keys)):
        raise ValueError("site task keys must be unique")

    grouped: Dict[str, List[SiteTask[T]]] = defaultdict(list)
    for task in task_list:
        grouped[task.site].append(task)
    if not grouped:
        return {}

    simple_logger.info(
        f"[site workers] running {len(task_list)} task(s) with "
        f"{len(grouped)} website worker(s)"
    )
    results: Dict[str, T | Exception] = {}
    with ThreadPoolExecutor(
        max_workers=len(grouped),
        thread_name_prefix="source-site",
    ) as executor:
        futures = {
            executor.submit(_run_group, site_tasks): site
            for site, site_tasks in grouped.items()
        }
        for future in as_completed(futures):
            results.update(future.result())
    return results
