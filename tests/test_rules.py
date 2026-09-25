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


NEWS_HOME = """<html><body><nav>
<a href="/about/">About</a><a href="/blog/">Blog</a><a href="/events">Events</a>
<a href="https://medium.com/@x">Medium</a><a href="/files/report.pdf">Annual news report</a>
</nav></body></html>"""


def test_the_homepage_links_to_its_own_news_pages_are_found():
    from liveliness import core
    pages = core.find_news_pages(NEWS_HOME, "https://x.org/")
    assert pages == ["https://x.org/blog/", "https://x.org/events"]


def test_the_newest_listed_item_dates_a_news_page(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    blog = "<html><body><p>Founded 3 March 2005.</p><h2>Post</h2><p>October 7, 2020</p>" \
           "<h2>Post</h2><p>10 November 2020</p></body></html>"
    monkeypatch.setattr(core, "get_page_cached", lambda u: (blog, {}))
    dt, _ = max(core.news_page_dates("https://x.org/blog/", now))
    assert dt == datetime(2020, 11, 10, tzinfo=timezone.utc)


def test_an_undated_stamp_of_today_is_not_a_post(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    page = "<html><body><header>Friday, September 25, 2026</header><p>March 2, 2019</p><p>January 5, 2019</p></body></html>"
    monkeypatch.setattr(core, "get_page_cached", lambda u: (page, {}))
    dt, _ = max(core.news_page_dates("https://x.org/news/", now))
    assert dt.year == 2019


def test_the_organizations_own_name_is_not_a_news_link():
    from liveliness import core
    home = '<a href="/about/">Te Hiku Media</a><a href="/news/">News</a>'
    assert core.find_news_pages(home, "https://x.org/") == ["https://x.org/news/"]


def test_a_page_with_one_date_is_not_a_page_of_items(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    about = "<html><body><p>We started on 30 May 2013.</p></body></html>"
    monkeypatch.setattr(core, "get_page_cached", lambda u: (about, {}))
    assert core.news_page_dates("https://x.org/about/", now) == []
