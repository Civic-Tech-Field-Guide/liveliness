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
    home = '<a href="/about/">Example Daily News Network</a><a href="/news/">News</a>'
    assert core.find_news_pages(home, "https://x.org/") == ["https://x.org/news/"]


def test_a_page_with_one_date_is_not_a_page_of_items(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    about = "<html><body><p>We started on 30 May 2013.</p></body></html>"
    monkeypatch.setattr(core, "get_page_cached", lambda u: (about, {}))
    assert core.news_page_dates("https://x.org/about/", now) == []


def _no_local_dns(monkeypatch, core):
    import socket
    def fail(*a, **k):
        raise socket.gaierror(8, "nodename nor servname provided")
    monkeypatch.setattr(core.socket, "getaddrinfo", fail)


def test_a_host_public_dns_can_find_is_not_gone(monkeypatch):
    from liveliness import core
    _no_local_dns(monkeypatch, core)
    monkeypatch.setattr(core, "_doh_resolves", lambda h: True)
    assert core.host_resolves("https://datos.example.gov.py/") is None


def test_a_host_nobody_can_find_is_gone(monkeypatch):
    from liveliness import core
    _no_local_dns(monkeypatch, core)
    monkeypatch.setattr(core, "_doh_resolves", lambda h: False)
    assert core.host_resolves("https://gone.example/") is False


def test_an_unsettled_host_is_not_ruled_dead(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "check_website", lambda u: (False, False, None))
    monkeypatch.setattr(core, "host_resolves", lambda u: None)
    assert core.probe_site("https://x.example/") == (None, False, "unknown")


def test_a_malformed_link_is_skipped_not_fatal():
    from liveliness import core
    home = '<a href="https://[broken/news/">News</a><a href="/news/">News</a>'
    assert core.find_news_pages(home, "https://x.org/") == ["https://x.org/news/"]


def test_a_malformed_or_bare_link_does_not_cost_the_page_its_social_links(monkeypatch):
    from liveliness import core
    home = ('<a href>Menu</a><a href="https://[broken/">x</a>'
            '<a href="https://bsky.app/profile/example">Bluesky</a>')
    monkeypatch.setattr(core, "get_page_cached", lambda u: (home, {}))
    assert core.discover_social_links("https://x.org/") == ["https://bsky.app/profile/example"]


def test_unparseable_supplied_urls_are_dropped_before_scoring():
    from liveliness import core
    p = Project(
        name="x",
        website="https://example.org]/",
        repo="https://[github.com/x",
        feeds=["https://[blog.example/feed", "https://x.org/feed"],
        links=[{"url": "https://[broken/"}, {"url": "https://bsky.app/profile/x"}],
    )
    clean = core._without_unparseable_urls(p)
    assert clean.website is None and clean.repo is None
    assert clean.feeds == ["https://x.org/feed"]
    assert clean.links == [{"url": "https://bsky.app/profile/x"}]
    assert core._without_unparseable_urls(clean) == clean


def _offline(monkeypatch):
    import requests, socket
    def boom(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "head", boom)
    def no_dns(*a, **k):
        raise socket.gaierror("offline")
    monkeypatch.setattr(socket, "getaddrinfo", no_dns)


def test_score_project_survives_malformed_and_missing_urls(monkeypatch):
    from liveliness import core
    _offline(monkeypatch)
    p = Project(name="x", website="https://example.org]/", repo="https://[github.com/x",
                feeds=None, links=[{"url": "https://[broken/"}, {"type": "twitter"}, {"url": None},
                                   {"url": ["https://x.org"]}, "https://[bare/", None])
    result = core.score_project(p)
    assert result["activity_status"] == "Unknown"
    assert "malformed" in result["breakdown"]


def test_only_a_leading_www_is_removed_from_a_domain():
    from liveliness import core
    assert core.classify_url("https://wired.com/story/x") == "article"
    assert core.classify_url("https://www.washingtonpost.com/a") == "article"


# ── Sitemap dates ─────────────────────────────────────────────────────────────

def _now():
    from datetime import datetime, timezone
    return datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def test_the_activity_bands_are_public():
    from liveliness import score_to_activity_status
    assert [score_to_activity_status(s) for s in (70, 45, 20, 19)] == [
        "Active", "Likely Active", "Possibly Inactive", "Inactive"]


def test_a_sitemap_is_dated_by_its_newest_entry():
    from datetime import datetime, timezone
    from liveliness import core
    text = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://x.org/</loc><lastmod>2026-03-02T10:00:00+00:00</lastmod></url>'
            '<url><loc>https://x.org/about</loc><lastmod>2026-07-14</lastmod></url>'
            '<url><loc>https://x.org/team</loc></url></urlset>')
    kind, entries = core.parse_sitemap(text)
    assert kind == "urlset" and len(entries) == 3
    assert core.sitemap_newest_date(entries, _now()) == datetime(2026, 7, 14, tzinfo=timezone.utc)


def test_a_sitemap_stamp_of_today_or_yesterday_is_the_servers_clock():
    from liveliness import core
    entries = [("https://x.org/", "2026-11-10"), ("https://x.org/a", "2026-11-09T23:00:00Z")]
    assert core.sitemap_newest_date(entries, _now()) is None
    entries.append(("https://x.org/b", "2026-11-08"))
    assert core.sitemap_newest_date(entries, _now()).day == 8


def test_a_sitemap_with_one_stamp_on_every_entry_is_a_build_not_a_change():
    from liveliness import core
    entries = [("https://x.org/%d" % i, "2026-10-01T08:00:00Z") for i in range(6)]
    assert core.sitemap_newest_date(entries, _now()) is None
    # A handful of pages edited on one day is not enough to call it a build.
    by_day = [("https://x.org/%d" % i, "2026-10-01") for i in range(3)]
    assert core.sitemap_newest_date(by_day, _now()) is not None


def test_a_listing_deep_in_a_site_is_dated_by_its_own_section():
    from liveliness import core
    entries = [("https://uni.edu/news/today", "2026-10-30"),
               ("https://uni.edu/labs/civic/", "2024-05-01"),
               ("https://uni.edu/labs/civic/people", "2025-01-20"),
               ("https://uni.edu/labs/civics-other", "2026-10-29")]
    dt = core.sitemap_newest_date(entries, _now(), core._path_prefix("https://uni.edu/labs/civic/"))
    assert (dt.year, dt.month) == (2025, 1)
    assert core.sitemap_newest_date(entries, _now(), "/labs/nothing") is None
    assert core._path_prefix("https://x.org/index.html") == ""
    assert core._path_prefix("https://x.org/lab/default.aspx") == "/lab"


class _FakeResponse:
    def __init__(self, url, body, status=200):
        self.url = url
        self.status_code = status
        self.content = body.encode() if isinstance(body, str) else body
        self.headers = {}

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")


def _fake_web(monkeypatch, core, pages):
    """
    Serve `pages` in place of the network: {url: body} or {url: (body, final url)}.
    Anything else answers 404. Returns the list of URLs requested.
    """
    seen = []
    def get(url, timeout=10, headers=None, deadline_s=None):
        seen.append(url)
        page = pages.get(url)
        if page is None:
            return _FakeResponse(url, "<html>not found</html>", 404)
        body, final = page if isinstance(page, tuple) else (page, url)
        return _FakeResponse(final, body)
    monkeypatch.setattr(core, "get_limited", get)
    return seen


def test_a_sitemap_index_is_followed_to_its_children(monkeypatch):
    from liveliness import core
    index = ('<sitemapindex><sitemap><loc>https://x.org/post-sitemap.xml</loc>'
             '<lastmod>2026-09-01</lastmod></sitemap>'
             '<sitemap><loc>https://x.org/page-sitemap.xml</loc></sitemap></sitemapindex>')
    posts = '<urlset><url><loc>https://x.org/p/1</loc><lastmod>2026-08-31</lastmod></url></urlset>'
    pages = '<urlset><url><loc>https://x.org/about</loc><lastmod>2021-01-01</lastmod></url></urlset>'
    seen = _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": index,
                                         "https://x.org/post-sitemap.xml": posts,
                                         "https://x.org/page-sitemap.xml": pages})
    dt, src = core.sitemap_date("https://x.org/", _now())
    assert (dt.month, dt.day) == (8, 31) and src.endswith("post-sitemap.xml")
    assert seen == ["https://x.org/robots.txt", "https://x.org/sitemap.xml",
                    "https://x.org/post-sitemap.xml", "https://x.org/page-sitemap.xml"]


def test_a_sitemap_named_in_robots_txt_is_read_first(monkeypatch):
    from liveliness import core
    seen = _fake_web(monkeypatch, core, {
        "https://x.org/robots.txt": "User-agent: *\nSitemap: https://cdn.x.org/maps/main.xml\n",
        "https://cdn.x.org/maps/main.xml":
            '<urlset><url><loc>https://x.org/</loc><lastmod>2026-02-01</lastmod></url></urlset>'})
    assert core.sitemap_date("https://x.org/", _now()) is not None
    assert seen == ["https://x.org/robots.txt", "https://cdn.x.org/maps/main.xml"]


def test_a_sitemap_with_nothing_usable_does_not_end_the_search(monkeypatch):
    # robots.txt names another site's sitemap. Every entry in it is filtered
    # out, and the site's own /sitemap.xml still has to be read.
    from liveliness import core
    _fake_web(monkeypatch, core, {
        "https://x.org/robots.txt": "Sitemap: https://news.example/sitemap.xml\n",
        "https://news.example/sitemap.xml":
            '<urlset><url><loc>https://news.example/a</loc><lastmod>2026-11-01</lastmod></url></urlset>',
        "https://x.org/sitemap.xml":
            '<urlset><url><loc>https://x.org/</loc><lastmod>2025-08-01</lastmod></url></urlset>'})
    dt, src = core.sitemap_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2025, 8) and src == "https://x.org/sitemap.xml"


def test_a_site_that_redirects_is_dated_by_the_host_it_lands_on(monkeypatch):
    from liveliness import core
    _fake_web(monkeypatch, core, {
        "http://oldname.org/sitemap.xml": (
            '<urlset><url><loc>https://www.newname.org/about</loc><lastmod>2026-03-01</lastmod></url>'
            '<url><loc>/team</loc><lastmod>2026-05-01</lastmod></url></urlset>',
            "https://www.newname.org/sitemap.xml")})
    dt, src = core.sitemap_date("http://oldname.org/", _now())
    assert (dt.year, dt.month) == (2026, 5) and src == "https://www.newname.org/sitemap.xml"


def test_a_truncated_gzip_sitemap_is_still_read(monkeypatch):
    # Downloads stop at MAX_FETCH_BYTES, so a large .xml.gz arrives cut short.
    import gzip
    from liveliness import core
    entries = "".join('<url><loc>https://x.org/p/%d</loc><lastmod>2025-%02d-01</lastmod></url>'
                      % (i, 1 + i % 12) for i in range(3000))
    whole = gzip.compress(('<urlset>%s</urlset>' % entries).encode())
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": whole[: len(whole) // 2]})
    dt, _ = core.sitemap_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2025, 12)


def test_a_sitemap_stamp_on_nearly_every_entry_is_a_build(monkeypatch):
    # A deploy restamps the generated pages; the few hand-dated ones remain.
    from liveliness import core
    entries = [("https://x.org/p/%d" % i, "2026-08-30T0%d:00:00Z" % (i % 10)) for i in range(18)]
    entries += [("https://x.org/", "2026-09-05"), ("https://x.org/about", "2025-06-01")]
    dt = core.sitemap_newest_date(entries, _now())
    assert (dt.year, dt.month, dt.day) == (2026, 9, 5)
    # A build that is the newest thing in the file is a recent deploy, and counts.
    assert core.sitemap_newest_date(entries[:18], _now()).day == 30


def test_a_sitemap_stamped_to_the_same_second_is_a_build_once_it_has_five_entries():
    from liveliness import core
    stamp = "2026-11-07T23:00:47+00:00"
    entries = [("https://x.org/%d" % i, stamp) for i in range(5)]
    assert core.sitemap_newest_date(entries, _now()) is None
    # Three pages are too few to tell a generator from one sitting of edits.
    assert core.sitemap_newest_date(entries[:3], _now()) is not None
    # Two pages edited on the same day, dated without a time, are just that.
    assert core.sitemap_newest_date([("https://x.org/a", "2026-10-05"),
                                     ("https://x.org/b", "2026-10-05")], _now()) is not None


def test_a_build_day_that_is_the_newest_day_still_counts():
    from liveliness import core
    entries = [("https://x.org/p/%d" % i, "2026-10-20") for i in range(18)]
    entries += [("https://x.org/", "2025-09-05"), ("https://x.org/about", "2025-06-01")]
    dt = core.sitemap_newest_date(entries, _now())
    assert (dt.year, dt.month, dt.day) == (2026, 10, 20)


def test_each_sitemap_fetch_is_held_to_the_time_left(monkeypatch):
    import time
    from liveliness import core
    caps = []
    def get(url, timeout=10, headers=None, deadline_s=None):
        caps.append((timeout, deadline_s))
        return _FakeResponse(url, "<html>not found</html>", 404)
    monkeypatch.setattr(core, "get_limited", get)
    core._sitemap_body("https://x.org/sitemap.xml", time.monotonic() + 3)
    timeout, deadline_s = caps[0]
    assert timeout <= 3 and deadline_s is not None and deadline_s <= 3


def test_an_image_address_inside_an_entry_is_not_the_entry():
    from liveliness import core
    text = ('<urlset><url><image:image><image:loc>https://cdn.example/a.png</image:loc></image:image>'
            '<loc>https://x.org/page</loc><lastmod>2026-01-01</lastmod></url></urlset>')
    assert core.parse_sitemap(text)[1] == [("https://x.org/page", "2026-01-01")]


# ── Wayback Machine change dates ──────────────────────────────────────────────

def test_the_first_capture_of_the_current_content_dates_the_change():
    from liveliness import core
    rows = [["20250101000000", "A"], ["20250301000000", "A"], ["20250601000000", "B"],
            ["20250901000000", "B"], ["20260101000000", "B"]]
    dt, settled = core.wayback_change_from_captures(rows)
    assert settled and (dt.year, dt.month) == (2025, 6)


def test_a_page_whose_hash_changes_on_every_capture_dates_nothing():
    from liveliness import core
    rows = [["2026%02d01000000" % m, "H%d" % m] for m in range(1, 11)]
    assert core.wayback_change_from_captures(rows) == (None, True)


def test_a_page_flipping_between_two_versions_dates_nothing():
    from liveliness import core
    rows = [["20260101000000", "A"], ["20260201000000", "A"], ["20260301000000", "B"],
            ["20260401000000", "B"], ["20260501000000", "A"]]
    assert core.wayback_change_from_captures(rows) == (None, True)


def test_unchanged_across_every_capture_is_not_settled():
    from liveliness import core
    rows = [["20260101000000", "A"], ["20260201000000", "A"], ["20260301000000", "A"]]
    dt, settled = core.wayback_change_from_captures(rows)
    assert not settled and dt.month == 1


def test_a_page_unchanged_across_every_capture_dates_nothing(monkeypatch):
    # The change is somewhere before the window, which is only a bound, and the
    # archive is never allowed to push a listing down on a bound.
    from liveliness import core
    calls = []
    def cdx(params):
        calls.append(params)
        return [["20260101000000", "A", "9000"], ["20260201000000", "A", "9100"],
                ["20260301000000", "A", "9050"]]
    monkeypatch.setattr(core, "_cdx", cdx)
    assert core.wayback_change_date("https://x.org/", _now()) is None
    assert len(calls) == 1 and calls[0]["url"] == "x.org/"


def test_an_archive_change_over_a_year_old_dates_nothing(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params: [
        ["20250101000000", "A", "9000"], ["20250601000000", "B", "9000"],
        ["20251201000000", "B", "9000"], ["20260901000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_a_recent_archive_change_is_a_date(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params: [
        ["20260101000000", "A", "9000"], ["20260201000000", "A", "9000"],
        ["20260301000000", "A", "9000"], ["20260601000000", "B", "9000"],
        ["20260701000000", "B", "9000"], ["20260801000000", "B", "9000"],
        ["20260901000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()).month == 6


def test_an_archive_answering_with_a_server_error_is_paused(monkeypatch):
    from liveliness import core
    class R:
        status_code = 502
        text = ""
    monkeypatch.setattr(core.SESSION, "get", lambda *a, **k: R())
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core._cdx({"url": "x.org/"}) is None
    assert core._wayback_paused_till > core.time.monotonic()


def test_an_archive_that_stopped_capturing_the_page_dates_nothing(monkeypatch):
    # The page may have changed every week since; the archive has not looked.
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params: [
        ["20241101000000", "A", "9000"], ["20241201000000", "B", "9000"],
        ["20241215000000", "B", "9000"], ["20241220000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_getting_past_a_bot_check_is_not_a_content_change(monkeypatch):
    # Small captures are the archive being shown a challenge page. The page
    # behind it appearing in a later capture is not the site changing.
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params: [
        ["20260101000000", "WALL", "300"], ["20260201000000", "WALL", "545"],
        ["20260301000000", "WALL", "550"], ["20260520000000", "PAGE", "23745"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_a_sitemap_of_another_site_says_nothing_about_this_one():
    from liveliness import core
    entries = [("https://news.example/story/1", "2026-11-01"), ("https://www.x.org/", "2025-02-01")]
    dt = core.sitemap_newest_date(entries, _now(), "", {"x.org"})
    assert (dt.year, dt.month) == (2025, 2)
    assert core.sitemap_newest_date(entries[:1], _now(), "", {"x.org"}) is None


def test_a_sitemap_that_lists_bare_paths_is_read_as_its_own_site(monkeypatch):
    from liveliness import core
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml":
              '<urlset><url><loc>/orgs/a/</loc><lastmod>2026-01-12T22:57:14+00:00</lastmod>'
              '</url></urlset>'})
    dt, _ = core.sitemap_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2026, 1)


def test_an_archive_that_cannot_be_asked_is_no_evidence(monkeypatch):
    import requests
    from liveliness import core
    def stall(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(core.SESSION, "get", stall)
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core, "_wayback_timeouts", 0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core.wayback_change_date("https://x.org/") is None
    assert core.wayback_change_date("https://w.org/") is None
    # And an archive that stalled twice is not asked again for every later record.
    asked = []
    monkeypatch.setattr(core.SESSION, "get", lambda *a, **k: asked.append(1))
    assert core.wayback_change_date("https://y.org/") is None
    assert asked == []


def test_an_archive_change_scores_like_the_footer_copyright():
    from datetime import timedelta
    from liveliness import core
    now = _now()
    assert core.wayback_recency_score(now - timedelta(days=30), now) == core.COPYRIGHT_FRESH_FLOOR
    assert core.wayback_recency_score(now - timedelta(days=500), now) == 0


def _undated_live_site(monkeypatch, core):
    monkeypatch.setattr(core, "probe_site", lambda u: (True, False, "ok"))
    monkeypatch.setattr(core, "check_github", lambda u: None)
    monkeypatch.setattr(core, "latest_blog_date", lambda *a: None)
    monkeypatch.setattr(core, "discover_social_links", lambda u: [])
    monkeypatch.setattr(core, "latest_news_date", lambda *a: None)
    page = "<html><body>" + "<p>We help cities listen to residents.</p>" * 20 + "</body></html>"
    monkeypatch.setattr(core, "get_page_cached", lambda u: (page, {}))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)


def test_an_undated_site_with_a_sitemap_date_is_scored(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    when = datetime.now(timezone.utc) - timedelta(days=40)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: (when, "https://x.org/sitemap.xml"))
    def no_archive(u, now=None):
        raise AssertionError("the archive is not asked once the sitemap answered")
    monkeypatch.setattr(core, "wayback_change_date", no_archive)
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["score"] == 85 and r["activity_status"] == "Active"
    assert core.SITEMAP_LABEL in r["breakdown"]


def test_an_archive_change_alone_never_reaches_active(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "discover_social_links", lambda u: ["https://bsky.app/profile/x"])
    monkeypatch.setattr(core, "check_url_alive", lambda u: True)
    monkeypatch.setattr(core, "check_social_recency", lambda u: (None, "Bluesky"))
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None: datetime.now(timezone.utc) - timedelta(days=10))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    # 45 for the change, 5 because the site's own dates are not recent, 10 social.
    assert r["score"] == 60 and r["activity_status"] == "Likely Active"
    assert core.WAYBACK_LABEL in r["breakdown"]


def test_a_bot_walled_site_can_be_dated_by_the_archive(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "blocked"))
    monkeypatch.setattr(core, "render_page_text", lambda u: None)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None: datetime.now(timezone.utc) - timedelta(days=100))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["score"] == 45 and r["activity_status"] == "Likely Active"
    assert r["status"] is None


def test_a_bot_walled_site_is_not_asked_for_its_sitemap(monkeypatch):
    # The wall that refused the homepage refuses the sitemap as well.
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "blocked"))
    monkeypatch.setattr(core, "render_page_text", lambda u: None)
    def never(*a):
        raise AssertionError("not asked behind a wall")
    monkeypatch.setattr(core, "sitemap_date", never)
    asked = []
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None: asked.append(u) or None)
    core.score_project(Project(name="x", website="https://x.org/"))
    assert asked == ["https://x.org/"]


def test_a_site_that_did_not_answer_is_not_dated_by_the_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "unknown"))
    def never(*a):
        raise AssertionError("a site that timed out is not looked up")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["activity_status"] == "Unknown"


def test_an_archive_capture_is_not_written_as_the_projects_last_activity(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None: datetime.now(timezone.utc) - timedelta(days=10))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["score"] == 50
    assert r["last_activity_date"] is None


def test_a_walled_site_scored_from_the_archive_says_so(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "blocked"))
    monkeypatch.setattr(core, "render_page_text", lambda u: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None: datetime.now(timezone.utc) - timedelta(days=100))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert "not evidence either way" not in r["breakdown"]
    assert "rests on the Wayback Machine" in r["breakdown"]


def test_a_fresh_footer_copyright_makes_the_archive_moot(monkeypatch):
    from datetime import datetime, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    year = datetime.now(timezone.utc).year
    page = ("<html><body>" + "<p>We help cities listen to residents.</p>" * 20 +
            "<footer>&copy; %d Example</footer></body></html>" % year)
    monkeypatch.setattr(core, "get_page_cached", lambda u: (page, {}))
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    def never(*a, **k):
        raise AssertionError("the archive cannot add to the copyright floor")
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["score"] == 45


def test_a_dead_site_is_not_dated_by_the_archive(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (False, False, "gone"))
    monkeypatch.setattr(core, "check_website", lambda u: (False, False, None))
    def never(*a):
        raise AssertionError("a gone site is not looked up")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["activity_status"] == "Inactive"


def test_a_site_that_dates_itself_is_not_sent_to_the_sitemap(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    page = ('<html><head><meta property="article:modified_time" content="2026-06-01"></head>'
            '<body>' + "<p>words</p>" * 60 + '</body></html>')
    monkeypatch.setattr(core, "get_page_cached", lambda u: (page, {}))
    def never(*a):
        raise AssertionError("not needed")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["score"] is not None



# ── Third review ──────────────────────────────────────────────────────────────

def test_an_old_sitemap_date_lifts_nothing_and_leaves_room_for_the_archive(monkeypatch):
    # A 2017 lastmod on a live site would score 3 + 5 = Inactive. The sitemap
    # may only lift a listing, so a date that old says nothing at all.
    from liveliness import core
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml":
              '<urlset><url><loc>https://x.org/</loc><lastmod>2017-03-01</lastmod></url></urlset>'})
    assert core.sitemap_date("https://x.org/", _now()) is None


def test_a_sitemap_date_within_eighteen_months_counts(monkeypatch):
    from liveliness import core
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml":
              '<urlset><url><loc>https://x.org/</loc><lastmod>2025-07-01</lastmod></url></urlset>'})
    assert core.sitemap_date("https://x.org/", _now())[0].year == 2025


def test_a_server_clock_entry_does_not_hide_a_recent_build():
    from liveliness import core
    entries = [("https://x.org/p/%d" % i, "2026-10-20") for i in range(18)]
    entries += [("https://x.org/now", "2026-11-10T09:00:00Z"), ("https://x.org/about", "2025-06-01")]
    dt = core.sitemap_newest_date(entries, _now())
    assert (dt.year, dt.month, dt.day) == (2026, 10, 20)


def test_a_stale_social_post_does_not_keep_the_last_resorts_away(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "discover_social_links", lambda u: ["https://bsky.app/profile/x"])
    monkeypatch.setattr(core, "check_url_alive", lambda u: True)
    old = datetime.now(timezone.utc) - timedelta(days=900)
    monkeypatch.setattr(core, "check_social_recency", lambda u: (old, "Bluesky"))
    asked = []
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: asked.append(u) or None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None: None)
    core.score_project(Project(name="x", website="https://x.org/"))
    assert asked == ["https://x.org/"]


def test_a_page_built_in_the_browser_is_not_dated_by_the_archive(monkeypatch):
    # Every redeploy changes the script bundle's name in the shell, so the
    # archive sees a new hash with nothing on the page having changed.
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "get_page_cached",
                        lambda u: ('<html><body><div id="root"></div>'
                                   '<script src="/app.3f9c.js"></script></body></html>', {}))
    monkeypatch.setattr(core, "render_page_text", lambda u: None)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    def never(*a, **k):
        raise AssertionError("a script shell is not dated by the archive")
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["activity_status"] == "Unknown"


def test_a_shell_rendered_into_words_is_not_dated_by_the_archive_either(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "get_page_cached",
                        lambda u: ('<html><body><div id="root"></div></body></html>', {}))
    monkeypatch.setattr(core, "render_page_text", lambda u: "We help cities listen. " * 30)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now: None)
    def never(*a, **k):
        raise AssertionError("a script shell is not dated by the archive")
    monkeypatch.setattr(core, "wayback_change_date", never)
    core.score_project(Project(name="x", website="https://x.org/"))


def test_the_archive_is_asked_for_its_latest_captures_the_fast_way(monkeypatch):
    from liveliness import core
    seen = []
    def cdx(params):
        seen.append(params)
        return []
    monkeypatch.setattr(core, "_cdx", cdx)
    core.wayback_change_date("https://x.org/", _now())
    assert seen[0]["fastLatest"] == "true"
    assert seen[0]["limit"] == -core.WAYBACK_FETCH_ROWS
    assert core.WAYBACK_FETCH_ROWS > core.WAYBACK_WINDOW


def test_small_captures_are_dropped_before_the_window_is_cut(monkeypatch):
    # Twenty bot-check captures at the end must not crowd out the real page.
    from liveliness import core
    real = [["2026%02d01000000" % m, "A" if m < 6 else "B", "9000"] for m in range(1, 10)]
    walls = [["202610%02d000000" % d, "W%d" % d, "400"] for d in range(1, 21)]
    monkeypatch.setattr(core, "_cdx", lambda params: real + walls)
    dt = core.wayback_change_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2026, 6)


def test_too_few_real_captures_date_nothing(monkeypatch):
    from liveliness import core
    rows = [["20260101000000", "A", "9000"], ["20260301000000", "A", "9000"],
            ["20260601000000", "B", "9000"], ["20260801000000", "B", "9000"]]
    monkeypatch.setattr(core, "_cdx", lambda params: rows)
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_one_slow_answer_does_not_pause_the_archive(monkeypatch):
    import requests
    from liveliness import core
    calls = []
    def slow(*a, **k):
        calls.append(1)
        raise requests.Timeout("slow")
    monkeypatch.setattr(core.SESSION, "get", slow)
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core, "_wayback_timeouts", 0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core._cdx({"url": "x.org/"}) is None
    assert core._wayback_paused_till == 0.0
    assert core._cdx({"url": "y.org/"}) is None
    assert core._wayback_paused_till > 0.0
    assert core._cdx({"url": "z.org/"}) is None
    assert len(calls) == 2
