"""The rules that can be checked without asking the internet anything."""

import sys

sys.path.insert(0, "..")

from liveliness import ONGOING_TYPES, Project, is_finished_work


def test_a_document_is_finished_work():
    assert is_finished_work(Project(name="A report", types=["Document"]))


def test_a_book_is_finished_work():
    assert is_finished_work(Project(name="A book", formats=["books"]))


def test_an_organization_that_published_something_is_not_finished():
    # The whole point of the ongoing-type guard. Without it the rule reads the
    # document and retires the organization that wrote it.
    assert not is_finished_work(
        Project(name="A think tank", types=["Organization", "Document"])
    )
    assert not is_finished_work(
        Project(name="A publisher", types=["Organization"], formats=["books"])
    )


def test_legislation_is_judged_like_anything_else():
    # A law is in force or it is repealed. It does not get to be N/A.
    assert "legislation" in ONGOING_TYPES
    assert not is_finished_work(Project(name="An act", types=["Legislation"]))


def test_types_are_matched_case_and_space_insensitively():
    assert not is_finished_work(Project(name="x", types=["  ORGANIZATION  "]))


def test_nothing_known_is_not_finished_work():
    assert not is_finished_work(Project(name="Unknown"))


def test_a_project_needs_only_a_name():
    p = Project(name="Minimal")
    assert p.website is None
    assert p.feeds == [] and p.links == [] and p.types == []


def test_two_projects_do_not_share_their_default_lists():
    a, b = Project(name="a"), Project(name="b")
    a.feeds.append("https://example.org/feed")
    assert b.feeds == []


def test_a_stored_blog_page_is_searched_for_its_feed(monkeypatch):
    # The Blog feed field often holds the blog's HTML page, which parses to no
    # entries. The feed that page advertises is what carries the dates.
    from datetime import datetime, timezone
    from liveliness import core
    posted = datetime(2020, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(core, "check_blog_feed",
                        lambda u: posted if u == "https://x.org/feed/" else None)
    monkeypatch.setattr(core, "discover_feed_url", lambda u: "https://x.org/feed/")
    assert core.latest_blog_date(["https://x.org/blog/"], "https://x.org/", "homepage") == posted


def test_a_stored_feed_that_works_is_not_second_guessed(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    posted = datetime(2026, 9, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(core, "check_blog_feed", lambda u: posted)
    def no_discovery(u):
        raise AssertionError("discovery should not run")
    monkeypatch.setattr(core, "discover_feed_url", no_discovery)
    assert core.latest_blog_date(["https://x.org/feed/"], "https://x.org/", "homepage") == posted
