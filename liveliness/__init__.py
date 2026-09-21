"""
Work out whether a civic tech project is still alive.

    from liveliness import Project, score_project

    result = score_project(Project(name="Example", website="https://example.org"))

`score_project` returns a dict with `score` (0 to 100, or None when there was
nothing to go on), `activity_status`, `last_activity_date`, `status`, and
`breakdown`, which is the reasoning in full and is meant to be shown to whoever
is being scored.
"""

from .core import ONGOING_TYPES, is_finished_work, score_project, set_logger
from .project import Project

__all__ = [
    "Project",
    "score_project",
    "set_logger",
    "is_finished_work",
    "ONGOING_TYPES",
]
