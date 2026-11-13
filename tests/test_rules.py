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

def _newest_date(entries, now=None, prefix="", hosts=None, builds=None):
    """The date from sitemap_newest_entry(), or None."""
    from liveliness import core
    found = core.sitemap_newest_entry(entries, now or _now(), prefix, hosts, builds)
    return found[0] if found else None



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
    assert _newest_date(entries, _now()) == datetime(2026, 7, 14, tzinfo=timezone.utc)


def test_a_sitemap_stamp_of_today_or_yesterday_is_the_servers_clock():
    from liveliness import core
    entries = [("https://x.org/", "2026-11-10"), ("https://x.org/a", "2026-11-09T23:00:00Z")]
    assert _newest_date(entries, _now()) is None
    entries.append(("https://x.org/b", "2026-11-08"))
    assert _newest_date(entries, _now()).day == 8


def test_a_sitemap_with_one_stamp_on_every_entry_is_a_build_not_a_change():
    from liveliness import core
    entries = [("https://x.org/%d" % i, "2026-10-01T08:00:00Z") for i in range(6)]
    assert _newest_date(entries, _now()) is None
    # A handful of pages edited on one day is not enough to call it a build.
    by_day = [("https://x.org/%d" % i, "2026-10-01") for i in range(3)]
    assert _newest_date(by_day, _now()) is not None


def test_a_listing_deep_in_a_site_is_dated_by_its_own_section():
    from liveliness import core
    entries = [("https://uni.edu/news/today", "2026-10-30"),
               ("https://uni.edu/labs/civic/", "2024-05-01"),
               ("https://uni.edu/labs/civic/people", "2025-01-20"),
               ("https://uni.edu/labs/civics-other", "2026-10-29")]
    dt = _newest_date(entries, _now(), core._path_prefix("https://uni.edu/labs/civic/"))
    assert (dt.year, dt.month) == (2025, 1)
    assert _newest_date(entries, _now(), "/labs/nothing") is None
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
    def get(url, timeout=10, headers=None, deadline_s=None, max_bytes=None):
        seen.append(url)
        page = pages.get(url)
        if page is None:
            return _FakeResponse(url, "<html>not found</html>", 404)
        body, final = page if isinstance(page, tuple) else (page, url)
        return _FakeResponse(final, body)
    monkeypatch.setattr(core, "get_limited", get)
    # The fake web resolves every name, so no test does a real lookup.
    monkeypatch.setattr(core, "host_resolves", lambda url, timeout=None: True)
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
    dt, src, *_ = core.sitemap_date("https://x.org/", _now())
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
    dt, src, *_ = core.sitemap_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2025, 8) and src == "https://x.org/sitemap.xml"


def test_a_site_that_redirects_is_dated_by_the_host_it_lands_on(monkeypatch):
    # A sitemap address that redirects within the same registered domain is
    # the site; another domain is not, whatever the homepage's title says.
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    _fake_web(monkeypatch, core, {
        "http://oldname.org/sitemap.xml": (
            '<urlset><url><loc>https://www.oldname.org/about</loc><lastmod>2026-03-01</lastmod></url>'
            '<url><loc>/team</loc><lastmod>2026-05-01</lastmod></url></urlset>',
            "https://www.oldname.org/sitemap.xml")})
    dt, src, *_ = core.sitemap_date("http://oldname.org/", _now())
    assert (dt.year, dt.month) == (2026, 5) and src == "https://www.oldname.org/sitemap.xml"


def test_a_truncated_gzip_sitemap_is_still_read(monkeypatch):
    # Downloads stop at MAX_FETCH_BYTES, so a large .xml.gz arrives cut short.
    import gzip
    from liveliness import core
    entries = "".join('<url><loc>https://x.org/p/%d</loc><lastmod>2025-%02d-01</lastmod></url>'
                      % (i, 1 + i % 12) for i in range(3000))
    whole = gzip.compress(('<urlset>%s</urlset>' % entries).encode())
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": whole[: len(whole) // 2]})
    dt, *_ = core.sitemap_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2025, 12)


def test_a_sitemap_stamp_on_nearly_every_entry_is_a_build(monkeypatch):
    # A deploy restamps the generated pages; the few hand-dated ones remain.
    from liveliness import core
    entries = [("https://x.org/p/%d" % i, "2026-08-30T0%d:00:00Z" % (i % 10)) for i in range(18)]
    entries += [("https://x.org/", "2026-09-05"), ("https://x.org/about", "2025-06-01")]
    dt = _newest_date(entries, _now())
    assert (dt.year, dt.month, dt.day) == (2026, 9, 5)
    # A build that is the newest thing in the file is a recent deploy, and counts.
    assert _newest_date(entries[:18], _now()).day == 30


def test_a_sitemap_stamped_to_the_same_second_is_a_build_once_it_has_five_entries():
    from liveliness import core
    stamp = "2026-11-07T23:00:47+00:00"
    entries = [("https://x.org/%d" % i, stamp) for i in range(5)]
    assert _newest_date(entries, _now()) is None
    # Three pages are too few to tell a generator from one sitting of edits.
    assert _newest_date(entries[:3], _now()) is not None
    # Two pages edited on the same day, dated without a time, are just that.
    assert _newest_date([("https://x.org/a", "2026-10-05"),
                                     ("https://x.org/b", "2026-10-05")], _now()) is not None


def test_a_date_only_build_day_is_set_aside_even_when_newest():
    from liveliness import core
    # Twenty entries share the date, enough for a bare-date build.
    entries = [("https://x.org/p/%d" % i, "2026-10-20") for i in range(20)]
    entries += [("https://x.org/", "2025-09-05"), ("https://x.org/about", "2025-06-01")]
    dt = _newest_date(entries, _now())
    assert (dt.year, dt.month, dt.day) == (2025, 9, 5)


def test_each_sitemap_fetch_is_held_to_the_time_left(monkeypatch):
    import time
    from liveliness import core
    caps = []
    def get(url, timeout=10, headers=None, deadline_s=None, max_bytes=None):
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
    dt, settled, reason = core.wayback_change_from_captures(rows)
    assert settled and reason is None and (dt.year, dt.month) == (2025, 6)


def test_a_page_whose_hash_changes_on_every_capture_dates_nothing():
    from liveliness import core
    rows = [["2026%02d01000000" % m, "H%d" % m] for m in range(1, 11)]
    assert core.wayback_change_from_captures(rows) == (None, True, "noise")


def test_a_page_flipping_between_two_versions_dates_nothing():
    from liveliness import core
    rows = [["20260101000000", "A"], ["20260201000000", "A"], ["20260301000000", "B"],
            ["20260401000000", "B"], ["20260501000000", "A"]]
    assert core.wayback_change_from_captures(rows) == (None, True, "noise")


def test_unchanged_across_every_capture_is_not_settled():
    from liveliness import core
    rows = [["20260101000000", "A"], ["20260201000000", "A"], ["20260301000000", "A"]]
    dt, settled, reason = core.wayback_change_from_captures(rows)
    assert not settled and reason == "unsettled" and dt.month == 1


def test_a_page_unchanged_across_every_capture_dates_nothing(monkeypatch):
    # The change is somewhere before the window, which is only a bound, and the
    # archive is never allowed to push a listing down on a bound.
    from liveliness import core
    calls = []
    def cdx(params, **k):
        calls.append(params)
        return [["20260101000000", "A", "9000"], ["20260201000000", "A", "9100"],
                ["20260301000000", "A", "9050"]]
    monkeypatch.setattr(core, "_cdx", cdx)
    assert core.wayback_change_date("https://x.org/", _now()) is None
    assert len(calls) == 1 and calls[0]["url"] == "x.org/"


def test_an_archive_change_over_a_year_old_dates_nothing(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params, **k: [
        ["20250101000000", "A", "9000"], ["20250601000000", "B", "9000"],
        ["20251201000000", "B", "9000"], ["20260901000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_a_recent_archive_change_is_a_date(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params, **k: [
        ["20260101000000", "A", "9000"], ["20260201000000", "A", "9000"],
        ["20260301000000", "A", "9000"], ["20260601000000", "B", "9000"],
        ["20260701000000", "B", "9000"], ["20260801000000", "B", "9000"],
        ["20260901000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()).month == 6


def test_an_archive_answering_with_a_server_error_is_paused(monkeypatch):
    from liveliness import core
    class R:
        status_code, headers, url, encoding = 502, {}, "https://web.archive.org/cdx", "utf-8"
        def iter_content(self, chunk_size=8192):
            yield b""
        def close(self):
            pass
    monkeypatch.setattr(core.SESSION, "get", lambda *a, **k: R())
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    assert core._cdx({"url": "x.org/"}) is None
    assert core._wayback_paused_till > core.time.monotonic()


def test_an_archive_that_stopped_capturing_the_page_dates_nothing(monkeypatch):
    # The page may have changed every week since; the archive has not looked.
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params, **k: [
        ["20241101000000", "A", "9000"], ["20241201000000", "B", "9000"],
        ["20241215000000", "B", "9000"], ["20241220000000", "B", "9000"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_getting_past_a_bot_check_is_not_a_content_change(monkeypatch):
    # Small captures are the archive being shown a challenge page. The page
    # behind it appearing in a later capture is not the site changing.
    from liveliness import core
    monkeypatch.setattr(core, "_cdx", lambda params, **k: [
        ["20260101000000", "WALL", "300"], ["20260201000000", "WALL", "545"],
        ["20260301000000", "WALL", "550"], ["20260520000000", "PAGE", "23745"]])
    assert core.wayback_change_date("https://x.org/", _now()) is None


def test_a_sitemap_of_another_site_says_nothing_about_this_one():
    from liveliness import core
    entries = [("https://news.example/story/1", "2026-11-01"), ("https://www.x.org/", "2025-02-01")]
    dt = _newest_date(entries, _now(), "", {"x.org"})
    assert (dt.year, dt.month) == (2025, 2)
    assert _newest_date(entries[:1], _now(), "", {"x.org"}) is None


def test_a_sitemap_that_lists_bare_paths_is_read_as_its_own_site(monkeypatch):
    from liveliness import core
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml":
              '<urlset><url><loc>/orgs/a/</loc><lastmod>2026-01-12T22:57:14+00:00</lastmod>'
              '</url></urlset>'})
    dt, *_ = core.sitemap_date("https://x.org/", _now())
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: core.SitemapFind(when, "https://x.org/sitemap.xml"))
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=10))
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=100))
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
    def never(*a, **k):
        raise AssertionError("not asked behind a wall")
    monkeypatch.setattr(core, "sitemap_date", never)
    asked = []
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: asked.append(u) or None)
    core.score_project(Project(name="x", website="https://x.org/"))
    assert asked == ["https://x.org/"]


def test_a_site_that_did_not_answer_is_not_dated_by_the_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "unknown"))
    def never(*a, **k):
        raise AssertionError("a site that timed out is not looked up")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["activity_status"] == "Unknown"


def test_an_archive_capture_is_not_written_as_the_projects_last_activity(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=10))
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
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=100))
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    def never(*a, **k):
        raise AssertionError("the archive cannot add to the copyright floor")
    monkeypatch.setattr(core, "wayback_change_date", never)
    assert core.score_project(Project(name="x", website="https://x.org/"))["score"] == 45


def test_a_dead_site_is_not_dated_by_the_archive(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "probe_site", lambda u: (False, False, "gone"))
    monkeypatch.setattr(core, "check_website", lambda u: (False, False, None))
    def never(*a, **k):
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
    def never(*a, **k):
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
    entries = [("https://x.org/p/%d" % i, "2026-10-20T%02d:00:00Z" % i) for i in range(18)]
    entries += [("https://x.org/now", "2026-11-10T09:00:00Z"), ("https://x.org/about", "2025-06-01")]
    dt = _newest_date(entries, _now())
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: asked.append(u) or None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: None)
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
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
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    def never(*a, **k):
        raise AssertionError("a script shell is not dated by the archive")
    monkeypatch.setattr(core, "wayback_change_date", never)
    core.score_project(Project(name="x", website="https://x.org/"))


def test_the_archive_is_asked_for_its_latest_captures_the_fast_way(monkeypatch):
    from liveliness import core
    seen = []
    def cdx(params, **k):
        seen.append(params)
        return []
    monkeypatch.setattr(core, "_cdx", cdx)
    core.wayback_change_date("https://x.org/", _now())
    assert seen[0]["fastLatest"] == "true"
    # One capture a day, and enough of them for the whole lookback window.
    assert abs(seen[0]["limit"]) >= core.WAYBACK_LOOKBACK_DAYS


def test_small_captures_are_dropped_before_the_window_is_cut(monkeypatch):
    # Twenty bot-check captures at the end must not crowd out the real page.
    from liveliness import core
    real = [["2026%02d01000000" % m, "A" if m < 6 else "B", "9000"] for m in range(1, 10)]
    walls = [["202610%02d000000" % d, "W%d" % d, "350"] for d in range(1, 21)]
    monkeypatch.setattr(core, "_cdx", lambda params, **k: real + walls)
    dt = core.wayback_change_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2026, 6)


def test_too_few_real_captures_date_nothing(monkeypatch):
    from liveliness import core
    # Three days of captures are too few; four are enough.
    rows = [["20260301000000", "A", "9000"],
            ["20260601000000", "B", "9000"], ["20260801000000", "B", "9000"]]
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
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


# ── Fourth review ─────────────────────────────────────────────────────────────

def test_a_change_after_a_long_gap_in_captures_is_not_dated_recent():
    # The archive did not look for years, so the change could have come any
    # time in that gap.
    from liveliness import core
    rows = [["2016%02d01000000" % m, "A"] for m in range(1, 10)] + [["20260901000000", "B"]]
    assert core.wayback_change_from_captures(rows, _now()) == (None, True, "stale")
    near = [["2026%02d01000000" % m, "A"] for m in range(1, 8)] + [["20260901000000", "B"]]
    dt, settled, _ = core.wayback_change_from_captures(near, _now())
    assert settled and (dt.year, dt.month) == (2026, 9)


def test_one_date_on_every_sitemap_entry_is_a_build():
    from liveliness import core
    entries = [("https://x.org/%d" % i, "2026-06-01") for i in range(50)]
    assert _newest_date(entries, _now()) is None


def test_a_build_stamp_on_nearly_every_entry_is_set_aside_even_when_newest():
    from datetime import datetime, timezone
    from liveliness import core
    entries = [("https://x.org/%d" % i, "2026-06-01T12:00:00Z") for i in range(50)]
    entries.append(("https://x.org/about", "2024-01-01"))
    assert _newest_date(entries, _now()) == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_a_sitemap_date_alone_does_not_set_status_active(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    when = datetime.now(timezone.utc) - timedelta(days=60)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: core.SitemapFind(when, "https://x.org/sitemap.xml"))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["score"] == 85 and r["activity_status"] == "Active"
    assert r["status"] is None


def test_an_article_whose_homepage_is_walled_says_it_rests_on_the_archive(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "classify_url", lambda u: "article")
    monkeypatch.setattr(core, "find_homepage_in_article", lambda u: "https://x.org/")
    monkeypatch.setattr(core, "probe_site", lambda u: (None, False, "blocked"))
    monkeypatch.setattr(core, "render_page_text", lambda u: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=100))
    r = core.score_project(Project(name="x", website="https://news.example/story"))
    assert "no homepage could be found" not in r["breakdown"]
    assert "rests on the Wayback Machine" in r["breakdown"]


# ── Fifth review ──────────────────────────────────────────────────────────────

def test_one_generator_pass_is_one_stamp_to_the_minute():
    from datetime import datetime, timezone
    from liveliness import core
    same = [("https://x.org/%d" % i, "2026-06-01T12:00:%02d.%03dZ" % (i, i * 7)) for i in range(6)]
    assert _newest_date(same, _now()) is None
    pass_ = [("https://x.org/%d" % i, "2026-06-01T12:00:%02dZ" % (i % 60)) for i in range(50)]
    pass_.append(("https://x.org/about", "2024-01-01"))
    assert _newest_date(pass_, _now()) == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_build_stamps_are_judged_across_a_whole_sitemap_index(monkeypatch):
    from liveliness import core
    stamp = "2026-06-01T12:00:00Z"
    index = ('<sitemapindex>' + "".join(
        '<sitemap><loc>https://x.org/s%d.xml</loc></sitemap>' % i for i in range(3)) + '</sitemapindex>')
    child = lambda i: ('<urlset>' + "".join(
        '<url><loc>https://x.org/%d/%d</loc><lastmod>%s</lastmod></url>' % (i, j, stamp)
        for j in range(2)) + '</urlset>')
    _fake_web(monkeypatch, core, dict({"https://x.org/sitemap.xml": index},
                                      **{"https://x.org/s%d.xml" % i: child(i) for i in range(3)}))
    # One pass across the children: a publish, never a page's own date.
    found = core.sitemap_date("https://x.org/", _now())
    assert found is not None and found.build


def test_a_page_named_by_its_query_or_fragment_skips_the_sitemap(monkeypatch):
    from liveliness import core
    seen = _fake_web(monkeypatch, core, {})
    assert core.sitemap_date("https://x.org/project.php?id=12", _now()) is None
    assert core.sitemap_date("https://x.org/#/projects/12", _now()) is None
    assert seen == []


def test_the_archive_is_asked_about_the_page_with_its_query(monkeypatch):
    from liveliness import core
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params["url"]) or None)
    core.wayback_change_date("https://x.org/project.php?id=12", _now())
    assert asked[0] == "x.org/project.php?id=12"


def test_where_robots_txt_redirects_is_not_the_site(monkeypatch):
    from liveliness import core
    robots = ("Sitemap: https://other.org/sitemap.xml\n", "https://other.org/robots.txt")
    theirs = '<urlset><url><loc>https://other.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://x.org/robots.txt": robots,
                                  "https://other.org/sitemap.xml": theirs})
    assert core.sitemap_date("https://x.org/", _now()) is None


def test_a_page_dated_only_by_a_last_resort_is_still_read(monkeypatch):
    # A homepage rewritten to announce a closure is exactly what the archive
    # sees change, so a last-resort date does not settle the page.
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "ADJUDICATE", True)
    when = datetime.now(timezone.utc) - timedelta(days=40)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: core.SitemapFind(when, "https://x.org/sitemap.xml"))
    assert core.score_project(Project(name="x", website="https://x.org/"))["adjudication"] is not None
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: when)
    assert core.score_project(Project(name="x", website="https://x.org/"))["adjudication"] is not None
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: None)
    assert core.score_project(Project(name="x", website="https://x.org/"))["adjudication"] is not None



# ── Sixth review ──────────────────────────────────────────────────────────────

def test_revisits_and_small_real_pages_count_as_captures(monkeypatch):
    # The shape the archive returns for info.cern.ch: 200 captures of about
    # 800 bytes, and warc/revisit rows with status "-" carrying the same digest.
    from liveliness import core
    rows = [["2026%02d01000000" % m, "A", "800", "200", "text/html"] for m in range(1, 6)]
    rows += [["20260601000000", "B", "810", "200", "text/html"]]
    rows += [["2026%02d01000000" % m, "B", "550", "-", "warc/revisit"] for m in range(7, 11)]
    rows += [["20261005000000", "W", "300", "200", "text/html"]]
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params) or rows)
    dt = core.wayback_change_date("https://info.cern.ch/", _now())
    assert dt is not None and (dt.year, dt.month) == (2026, 6)
    assert "statuscode:200" not in str(asked[0].get("filter"))


def test_a_hash_route_skips_both_last_resorts(monkeypatch):
    from liveliness import core
    seen = _fake_web(monkeypatch, core, {})
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params) or None)
    assert core.sitemap_date("https://x.org/#!/projects/12", _now()) is None
    assert core.wayback_change_date("https://x.org/#/projects/12", _now()) is None
    assert core.wayback_change_date("https://x.org/#!/projects/12", _now()) is None
    assert seen == [] and asked == []


def test_a_generator_pass_spread_over_minutes_is_one_pass():
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    start = datetime(2026, 6, 1, 12, 0, 0)
    # 25 minutes of stamps, inside the half-hour a pass may span.
    entries = [("https://x.org/%d" % i, (start + timedelta(seconds=50 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"))
               for i in range(30)]
    entries.append(("https://x.org/about", "2024-01-01"))
    assert _newest_date(entries, _now()) == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_a_capture_with_a_bad_timestamp_is_skipped():
    from liveliness import core
    rows = [["2026%02d01000000" % m, "A"] for m in range(1, 6)] + [["garbage", "A"], ["20260901000000", "B"]]
    dt, settled, _ = core.wayback_change_from_captures(rows, _now())
    assert settled and (dt.year, dt.month) == (2026, 9)


def test_one_index_under_two_names_is_read_once(monkeypatch):
    from liveliness import core
    index = ('<sitemapindex><sitemap><loc>https://x.org/a.xml</loc></sitemap></sitemapindex>')
    child = '<urlset><url><loc>https://x.org/p</loc></url></urlset>'
    seen = _fake_web(monkeypatch, core, {
        "https://x.org/sitemap.xml": (index, "https://x.org/sitemap_index.xml"),
        "https://x.org/sitemap_index.xml": index,
        "https://x.org/a.xml": child})
    core.sitemap_date("https://x.org/", _now())
    assert seen.count("https://x.org/a.xml") == 1


def test_index_children_matching_the_listing_section_come_first(monkeypatch):
    from liveliness import core
    others = "".join('<sitemap><loc>https://x.org/news-%d.xml</loc><lastmod>2026-10-0%d</lastmod></sitemap>'
                     % (i, i + 1) for i in range(5))
    index = ('<sitemapindex>' + others +
             '<sitemap><loc>https://x.org/labs-sitemap.xml</loc><lastmod>2025-01-01</lastmod></sitemap>'
             '</sitemapindex>')
    seen = _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": index})
    core.sitemap_date("https://x.org/labs/civic/", _now())
    assert "https://x.org/labs-sitemap.xml" in seen



# ── Seventh review ────────────────────────────────────────────────────────────

def test_a_homepage_moved_to_another_domain_is_not_dated_by_its_sitemap(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    robots = ("Sitemap: https://newname.org/sitemap.xml\n", "https://newname.org/robots.txt")
    theirs = '<urlset><url><loc>https://newname.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://x.org/": ("<html><title>Newname</title></html>", "https://newname.org/"),
                                  "https://x.org/robots.txt": robots,
                                  "https://newname.org/sitemap.xml": theirs})
    core.get_page_cached("https://x.org/")
    # Another registered domain is never trusted, whatever its title says.
    assert core.sitemap_date("https://x.org/", _now()) is None


def test_an_archived_repo_does_not_stop_an_undated_page_being_read(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "ADJUDICATE", True)
    when = _now() - timedelta(days=30)
    monkeypatch.setattr(core, "check_github", lambda u: {
        "best_date": when, "archived": True, "dates": {"push": when}, "resolution": None})
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: None)
    r = core.score_project(Project(name="x", website="https://x.org/",
                                   repo="https://github.com/x/x"))
    assert r["adjudication"] is not None


def test_the_archive_is_asked_about_where_the_homepage_landed(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    _fake_web(monkeypatch, core, {"https://x.org/": ("<html></html>", "https://www.x.org/home")})
    core.get_page_cached("https://x.org/")
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params["url"]) or None)
    core.wayback_change_date("https://x.org/", _now())
    assert asked[0] == "www.x.org/home"


def test_an_archive_only_score_does_not_say_nothing_recent_was_found(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: None)
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=10))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert "nothing dated and recent" not in r["breakdown"]
    assert "Wayback Machine" in r["breakdown"].split("Website is responding", 1)[1].splitlines()[0]


def test_a_section_matches_whole_words_in_child_names(monkeypatch):
    from liveliness import core
    news = "".join('<sitemap><loc>https://x.org/news-%d.xml</loc><lastmod>2026-10-0%d</lastmod></sitemap>'
                   % (i, i + 1) for i in range(4))
    index = ('<sitemapindex>' + news +
             '<sitemap><loc>https://x.org/collaboration-sitemap.xml</loc><lastmod>2025-01-01</lastmod></sitemap>'
             '</sitemapindex>')
    seen = _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": index})
    core.sitemap_date("https://x.org/lab/", _now())
    assert "https://x.org/collaboration-sitemap.xml" not in seen


def test_robots_sitemaps_returns_only_the_list(monkeypatch):
    import time
    from liveliness import core
    _fake_web(monkeypatch, core, {"https://x.org/robots.txt": "Sitemap: https://x.org/s.xml\n"})
    assert core._robots_sitemaps("https://x.org", time.monotonic() + 10) == ["https://x.org/s.xml"]


# ── Measured on live listings ─────────────────────────────────────────────────

def _churny_rows(now, n=12):
    # A capture every three weeks over the last eight months, each with its own
    # hash, which is what 48 of 60 sampled undated listings looked like in the archive.
    from datetime import timedelta
    return [[(now - timedelta(days=21 * (n - i))).strftime("%Y%m%d%H%M%S"), "H%d" % i, "40000",
             "200", "text/html"] for i in range(n)]


def test_a_churning_hash_falls_back_to_comparing_the_text(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    old = {"civic", "theatre", "workshop", "spring", "season"} | {"word%s" % c for c in "abcdefghijkl"}
    new = {"civic", "theatre", "workshop", "autumn", "festival"} | {"term%s" % c for c in "abcdefghijkl"}
    # The text changed at capture 8: every capture from there on reads `new`.
    monkeypatch.setattr(core, "_archived_words",
                        lambda ts, target, **k: new if ts >= rows[8][0] else old)
    dt = core.wayback_change_date("https://x.org/", now)
    # Four reads bound the change: the date is the first capture after the
    # last one read with the old text, never later than the real change.
    assert dt is not None and dt.strftime("%Y%m%d%H%M%S") <= rows[8][0]


def test_a_churning_hash_with_unchanged_text_dates_nothing(monkeypatch):
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_cdx", lambda params, **k: _churny_rows(now))
    same = {"word%d" % i for i in range(60)}
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: same)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_an_unreadable_or_walled_capture_dates_nothing(monkeypatch):
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_cdx", lambda params, **k: _churny_rows(now))
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: None)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_archived_words_refuse_a_bot_wall(monkeypatch):
    from liveliness import core
    wall = "<html><body><h1>Just a moment...</h1>" + "<p>Checking your browser before accessing</p>" * 10 + "</body></html>"
    monkeypatch.setattr(core, "_wayback_get", lambda url, params=None, deadline=None: _FakeResponse(url, wall))
    assert core._archived_words("20260101000000", "x.org/") is None


def test_a_language_root_is_the_whole_site():
    from liveliness import core
    assert core._path_prefix("https://mcube-cluster.de/en/") == ""
    assert core._path_prefix("https://x.org/pt-br/") == ""
    assert core._path_prefix("https://x.org/labs/") == "/labs"


def test_a_recent_whole_site_publish_counts_as_weak_evidence(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    now = _now()
    base = now - timedelta(days=3)
    stamps = [(base + timedelta(seconds=8 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z") for i in range(9)]
    body = ('<urlset><url><loc>https://x.org</loc></url>' + "".join(
        '<url><loc>https://x.org/p%d</loc><lastmod>%s</lastmod></url>' % (i, s)
        for i, s in enumerate(stamps)) + '</urlset>')
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": body})
    found = core.sitemap_date("https://x.org/", now)
    assert found is not None and found.build and found[0].date() == base.date()


def test_a_publish_scores_like_an_archive_change(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    when = datetime.now(timezone.utc) - timedelta(days=3)
    monkeypatch.setattr(core, "sitemap_date",
                        lambda u, now, **k: core.SitemapFind(when, "https://x.org/sitemap.xml", build=True))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["score"] == 50 and r["status"] is None and r["last_activity_date"] is None
    assert core.SITEMAP_BUILD_LABEL in r["breakdown"]


def test_a_deep_page_keeps_to_the_hash_method(monkeypatch):
    # A deep page on an institution's site shares its news box with the whole
    # site, so its text changing is the host's news, not the listing's.
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_cdx", lambda params, **k: _churny_rows(now))
    def never(ts, target, **k):
        raise AssertionError("a deep page's text is not compared")
    monkeypatch.setattr(core, "_archived_words", never)
    assert core.wayback_change_date("https://www.parlamento.pt/EspacoCidadao/Paginas/x.aspx", now) is None
    assert core.wayback_change_date("https://x.gov.br/projetos/opa/", now) is None
    # A language root is the homepage, and keeps the fallback.
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: None)
    assert core.wayback_change_date("https://x.org/en/", now) is None



# ── Review of 023cdd8 ─────────────────────────────────────────────────────────

def test_an_archive_snapshot_address_skips_both_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    def never(*a, **k):
        raise AssertionError("an archive snapshot is not dated by the last resorts")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    core.score_project(Project(name="x", website="https://web.archive.org/web/2020/https://x.org/"))


def test_only_real_language_codes_are_language_roots():
    from liveliness import core
    for path in ("/en/", "/de", "/pt-br/", "/zh-hant/"):
        assert core._path_prefix("https://x.org" + path) == "", path
    for path in ("/ai/", "/us/", "/hr/", "/dc/", "/go/"):
        assert core._path_prefix("https://x.org" + path) != "", path


def test_a_server_error_on_one_capture_does_not_pause_the_archive(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    monkeypatch.setattr(core, "get_limited",
                        lambda url, timeout=10, headers=None, deadline_s=None, max_bytes=None:
                        _FakeResponse(url, "oops", 503))
    assert core._archived_words("20260101000000", "x.org/") is None
    assert core._wayback_paused_till == 0.0


def test_archived_pages_are_read_with_the_byte_cap(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    calls = []
    page = "<html><body>" + " ".join("word%s" % c for c in "abcdefghijklmnopqrstuvwxyz") * 3 + "</body></html>"
    def limited(url, timeout=10, headers=None, deadline_s=None, max_bytes=None):
        calls.append(url)
        return _FakeResponse(url, page)
    monkeypatch.setattr(core, "get_limited", limited)
    def no_session(*a, **k):
        raise AssertionError("page reads go through get_limited")
    monkeypatch.setattr(core.SESSION, "get", no_session)
    core._archived_words("20260101000000", "x.org/")
    assert calls and "id_/" in calls[0]


def test_the_sitemap_is_read_where_the_homepage_landed(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    # The apex's front page moved into its own subdomain.
    theirs = '<urlset><url><loc>https://home.x.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://x.org/": ("<html><title>X</title></html>", "https://home.x.org/"),
                                  "https://home.x.org/sitemap.xml": theirs})
    core.get_page_cached("https://x.org/")
    dt, *_ = core.sitemap_date("https://x.org/", _now())
    assert (dt.month, dt.day) == (9, 1)


def test_the_sitemap_age_limit_is_the_stale_limit():
    from liveliness import core
    assert core.SITEMAP_MAX_AGE_DAYS == core.STALE_AFTER_DAYS


def test_a_large_sitemap_is_read_past_the_page_cap(monkeypatch):
    import time
    from liveliness import core
    filler = "".join('<url><loc>https://x.org/p%d</loc><lastmod>2020-01-01</lastmod></url>' % i
                     for i in range(25000))
    body = ('<urlset>' + filler +
            '<url><loc>https://x.org/new</loc><lastmod>2026-09-01</lastmod></url></urlset>').encode()
    assert len(body) > core.MAX_FETCH_BYTES

    class Stream:
        status_code, headers, url, encoding = 200, {}, "https://x.org/sitemap.xml", "utf-8"
        def iter_content(self, chunk_size=8192):
            for i in range(0, len(body), chunk_size):
                yield body[i:i + chunk_size]
        def close(self):
            pass
    monkeypatch.setattr(core.SESSION, "get", lambda *a, **k: Stream())
    text, *_ = core._sitemap_body("https://x.org/sitemap.xml", time.monotonic() + 30)
    assert "https://x.org/new" in text


def test_text_fallback_skips_rows_with_bad_timestamps(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now) + [["garbage", "Z", "40000", "200", "text/html"]]
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: None)
    assert core.wayback_text_change(rows, "x.org/", now) is None


def test_a_page_picked_out_by_its_query_is_not_a_homepage(monkeypatch):
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_cdx", lambda params, **k: _churny_rows(now))
    def never(ts, target, **k):
        raise AssertionError("a query-named page's text is not compared")
    monkeypatch.setattr(core, "_archived_words", never)
    assert core.wayback_change_date("https://x.org/?page=12", now) is None
    # Tracking parameters do not make a page of the homepage.
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: None)
    assert core.wayback_change_date("https://x.org/?utm_source=mail", now) is None


# ── Review of 94fa810 ─────────────────────────────────────────────────────────

def test_a_redirected_listing_keeps_its_own_path_for_the_sitemap(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    body = ('<urlset><url><loc>https://www.x.org/labs/a</loc><lastmod>2026-09-01</lastmod></url>'
            '<url><loc>https://www.x.org/other</loc><lastmod>2026-10-01</lastmod></url></urlset>')
    _fake_web(monkeypatch, core, {"https://x.org/labs/": ("<html></html>", "https://www.x.org/labs/"),
                                  "https://www.x.org/sitemap.xml": body})
    core.get_page_cached("https://x.org/labs/")
    dt, *_ = core.sitemap_date("https://x.org/labs/", _now())
    assert (dt.month, dt.day) == (9, 1)


def test_the_listed_address_decides_whether_it_is_a_homepage(monkeypatch):
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://www.x.org/"})
    rows = _churny_rows(now)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    old = {"word%d" % i for i in range(40)}
    new = {"term%d" % i for i in range(40)}
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: new if ts >= rows[8][0] else old)
    assert core.wayback_change_date("https://x.org/", now) is not None


def test_a_carousel_that_changes_every_capture_dates_nothing(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    base = {"word%d" % i for i in range(40)}
    def carousel(ts, target, **k):
        n = [r[0] for r in rows].index(ts)
        return base | {"slide%d_%d" % (n, k) for k in range(12)}
    monkeypatch.setattr(core, "_archived_words", carousel)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_a_move_to_another_organizations_domain_is_not_trusted(monkeypatch):
    from liveliness import core
    project_name = "Civic Widget"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<title>Big Funder Foundation</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://funder.org/grants"})
    assert core.landed_url("https://x.org/") == "https://x.org/"
    # The same organization's other host is trusted.
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://www.x.org/home"})
    assert core.landed_url("https://x.org/") == "https://www.x.org/home"
    # Down from the apex into its own subdomain is trusted without the name.
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.co.uk/": "https://new.x.co.uk/"})
    assert core.landed_url("https://x.co.uk/") == "https://new.x.co.uk/"
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://a.co.uk/": "https://b.co.uk/"})
    assert core.landed_url("https://a.co.uk/") == "https://a.co.uk/"
    # A new domain is not trusted even when its page names the project.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<title>Civic Widget | Home</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://civicwidget.io/"})
    assert core.landed_url("https://x.org/") == "https://x.org/"


def test_only_a_page_that_answered_records_where_it_landed(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    monkeypatch.setattr(core, "get_limited",
                        lambda url, **k: _FakeResponse("https://elsewhere.x.org/blocked", "no", 403))
    core.get_page_cached("https://x.org/")
    assert core.landed_url("https://x.org/") == "https://x.org/"


def test_an_old_sitemap_date_still_asks_the_archive(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    old = datetime.now(timezone.utc) - timedelta(days=400)
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: core.SitemapFind(old, "s.xml"))
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, **k: datetime.now(timezone.utc) - timedelta(days=20))
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert core.WAYBACK_LABEL in r["breakdown"] and r["score"] >= 45


def test_the_root_tag_is_found_after_a_long_preamble(monkeypatch):
    import time
    from liveliness import core
    body = ('<?xml version="1.0"?>\n<?xml-stylesheet href="/s.xsl"?>\n<!--' + "x" * 6000 + '-->\n'
            '<urlset><url><loc>https://x.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>')
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": body})
    got = core._sitemap_body("https://x.org/sitemap.xml", time.monotonic() + 10)
    assert got is not None and core.parse_sitemap(got[0])[0] == "urlset"
    page = '<!doctype html><html><body>' + "y" * 6000 + '<urlset></urlset></body></html>'
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": page})
    assert core._sitemap_body("https://x.org/sitemap.xml", time.monotonic() + 10) is None


def test_the_last_resorts_stop_at_the_record_deadline(monkeypatch):
    import time
    from liveliness import core
    seen = _fake_web(monkeypatch, core, {})
    assert core.sitemap_date("https://x.org/", _now(), deadline=time.monotonic() - 1) is None
    assert seen == []
    def never(params, **k):
        raise AssertionError("past the deadline")
    monkeypatch.setattr(core, "_cdx", never)
    assert core.wayback_change_date("https://x.org/", _now(), deadline=time.monotonic() - 1) is None


def test_score_project_passes_its_deadline_to_the_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    got = {}
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, deadline=None, **k: got.__setitem__("s", deadline))
    monkeypatch.setattr(core, "wayback_change_date",
                        lambda u, now=None, deadline=None, **k: got.__setitem__("w", deadline))
    core.score_project(Project(name="x", website="https://x.org/"), budget_s=50)
    assert got.get("s") is not None and got.get("w") is not None


def test_the_newest_sitemap_entry_comes_with_its_file():
    from datetime import datetime, timezone
    from liveliness import core
    entries = [("https://x.org/a", "2026-09-01", "s1.xml"), ("https://x.org/b", "2026-01-01", "s2.xml")]
    assert core.sitemap_newest_entry(entries, _now()) == (datetime(2026, 9, 1, tzinfo=timezone.utc), "s1.xml")
    assert core.SitemapFind._fields == ("date", "source", "build", "page_date")


# ── Follow-ups from the 60-listing rerun ──────────────────────────────────────

def test_cms_default_pages_do_not_date_a_site():
    from liveliness import core
    entries = [("https://x.org/sample-page/", "2025-09-12"), ("https://x.org/hello-world/", "2025-09-12"),
               ("https://x.org/category/uncategorized/", "2025-09-12")]
    assert _newest_date(entries, _now()) is None
    entries.append(("https://x.org/about/", "2024-03-01"))
    assert _newest_date(entries, _now()).year == 2024


def test_a_day_with_a_thousand_entries_and_half_the_file_is_a_build():
    from datetime import datetime, timezone
    from liveliness import core
    # Spread over the day, so no single run of times covers 80%.
    big = [("https://x.org/a%d" % i, "2026-11-08T%02d:%02d:00Z" % (i % 24, (i * 7) % 60))
           for i in range(1200)]
    rest = [("https://x.org/b%d" % i, "2026-%02d-15" % (1 + i % 9)) for i in range(1000)]
    rest.append(("https://x.org/post", "2026-10-01"))
    dt = _newest_date(big + rest, _now())
    assert dt == datetime(2026, 10, 1, tzinfo=timezone.utc)
    # Below a thousand entries the day stands.
    small = big[:600] + rest[:400]
    assert _newest_date(small, _now()).date().isoformat() == "2026-11-08"


def test_build_passes_are_judged_on_the_whole_site_not_the_section():
    from liveliness import core
    # A platform regenerated every entry in one run; the listing is one page of it.
    entries = [("https://c.example.org/p%d" % i, "2026-11-08T03:%02d:%02dZ" % (i // 60 % 60, i % 60))
               for i in range(1500)]
    entries.append(("https://c.example.org/home", "2026-11-08T03:10:00Z"))
    builds = []
    assert core.sitemap_newest_entry(entries, _now(), "/home", None, builds) is None
    assert builds and builds[0][0].date().isoformat() == "2026-11-08"


# ── Review of df34a06 ─────────────────────────────────────────────────────────

def test_a_projects_own_title_does_not_vouch_for_another_domains_sitemap(monkeypatch):
    from liveliness import core
    project_name = "Civic Widget"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<title>Civic Widget</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    theirs = '<urlset><url><loc>https://other.com/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": (theirs, "https://other.com/sitemap.xml")})
    assert core.sitemap_date("https://x.org/", _now()) is None


def test_a_parked_or_for_sale_landing_is_never_trusted(monkeypatch):
    from liveliness import core
    project_name = "Civic Widget"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://civicwidget.org/": (
        "<title>civicwidget.org is for sale | Civic Widget</title><p>Buy this domain</p>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://civicwidget.org/": "https://www.civicwidget.org/lander"})
    assert core.landed_url("https://civicwidget.org/") == "https://civicwidget.org/"
    # Off the site onto another domain's for-sale page.
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://civicwidget.org/": "https://civicwidget.net/lander"})
    assert core.landed_url("https://civicwidget.org/") == "https://civicwidget.org/"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://civicwidget.org/": ("<title>Civic Widget</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://civicwidget.org/": "https://sedo.com/search/details/?domain=civicwidget.org"})
    assert core.landed_url("https://civicwidget.org/") == "https://civicwidget.org/"


def test_a_name_match_always_needs_a_distinctive_word(monkeypatch):
    from liveliness import core
    # The whole name matching is not enough without a word of four letters.
    project_name = "Vox AI"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<title>Vox AI</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://other.com/"})
    assert core.landed_url("https://x.org/") == "https://x.org/"


def test_shared_hosting_tenants_are_separate_sites():
    from liveliness import core
    assert core._registrable("alice.github.io") != core._registrable("bob.github.io")
    assert core._registrable("www.alice.github.io") == core._registrable("alice.github.io")
    assert core._registrable("x.netlify.app") == "x.netlify.app"
    assert core._registrable("news.x.org") == "x.org"


def test_the_text_is_compared_only_when_the_landed_page_is_a_homepage_too(monkeypatch):
    from liveliness import core
    now = _now()
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://www.x.org/about/history"})
    monkeypatch.setattr(core, "_cdx", lambda params, **k: _churny_rows(now))
    def never(ts, target, **k):
        raise AssertionError("the landed page is not a homepage")
    monkeypatch.setattr(core, "_archived_words", never)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_the_text_fallback_reads_at_most_four_archived_pages(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now, n=18)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    reads = []
    old = {"word%d" % i for i in range(40)}
    new = {"term%d" % i for i in range(40)}
    def words(ts, target, **k):
        reads.append(ts)
        return new if ts >= rows[14][0] else old
    monkeypatch.setattr(core, "_archived_words", words)
    dt = core.wayback_change_date("https://x.org/", now)
    assert dt is not None and len(reads) <= 4


def test_score_project_always_passes_a_deadline(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    got = []
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, deadline, **k: got.append(deadline))
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now, deadline, **k: got.append(deadline))
    core.score_project(Project(name="x", website="https://x.org/"))
    # With no budget, the last resorts get their own LAST_RESORTS_S.
    assert len(got) == 2 and None not in got


# ── Review of 073d209 ─────────────────────────────────────────────────────────

def test_without_a_budget_the_last_resorts_get_forty_seconds(monkeypatch):
    import time
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    got = []
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, deadline, **k: got.append(deadline))
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now, deadline, **k: got.append(deadline))
    before = time.monotonic()
    core.score_project(Project(name="x", website="https://x.org/"))
    assert len(got) == 2 and all(d is not None for d in got)
    # The sitemap gets at most 15 of the 40 seconds; the archive keeps the rest.
    sitemap_d, archive_d = got
    assert sitemap_d <= time.monotonic() + 15.5
    assert before + 35 <= archive_d <= time.monotonic() + 41


def test_a_page_alternating_between_two_versions_dates_nothing(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    a = {"word%d" % i for i in range(40)}
    b = {"term%d" % i for i in range(40)}
    order = [r[0] for r in rows]
    # Stable for most of the year, then flipping between two versions at the end.
    def words(ts, target, **k):
        i = order.index(ts)
        return (b if i % 2 else a) if i >= 9 else a
    monkeypatch.setattr(core, "_archived_words", words)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_a_real_homepage_selling_tickets_is_not_parked(monkeypatch):
    from liveliness import core
    long_page = ("<title>Civic Widget</title><body>" + "<p>We build tools for neighbourhoods and city councils.</p>" * 40
                 + "<p>Tickets for sale now for our spring summit.</p></body>")
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": (long_page, {})})
    assert not core._looks_parked("https://x.org/", "https://www.x.org/")
    short = "<title>x.org</title><body><p>This domain is for sale. Make an offer.</p><script>var a='" + "z" * 5000 + "';</script></body>"
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": (short, {})})
    assert core._looks_parked("https://x.org/", "https://www.x.org/")


def test_the_archive_is_asked_for_one_capture_a_day_over_the_last_400_days(monkeypatch):
    from liveliness import core
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params) or None)
    core.wayback_change_date("https://x.org/", _now())
    assert asked[0].get("collapse") == "timestamp:8"
    assert asked[0].get("from") == "20251006"


def test_a_recent_publish_beats_an_old_page_date(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    now = _now()
    stamps = [(now - timedelta(days=20, seconds=-8 * i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(9)]
    body = ('<urlset><url><loc>https://x.org/old</loc><lastmod>%s</lastmod></url>'
            % (now - timedelta(days=450)).strftime("%Y-%m-%d") + "".join(
        '<url><loc>https://x.org/p%d</loc><lastmod>%s</lastmod></url>' % (i, s)
        for i, s in enumerate(stamps)) + '</urlset>')
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": body})
    found = core.sitemap_date("https://x.org/", now)
    assert found is not None and found.build


def test_the_same_capture_is_not_read_twice(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now, n=4)   # captures 84, 63, 42 and 21 days ago
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    reads = []
    same = {"word%d" % i for i in range(40)}
    monkeypatch.setattr(core, "_archived_words", lambda ts, target, **k: reads.append(ts) or same)
    core.wayback_text_change(rows, "x.org/", now)
    assert len(reads) == len(set(reads))


def test_a_partner_that_cannot_be_read_says_why(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now)
    logged = []
    monkeypatch.setattr(core, "_log", logged.append)
    a = {"word%d" % i for i in range(40)}
    b = {"term%d" % i for i in range(40)}
    def words(ts, target, **k):
        i = [r[0] for r in rows].index(ts)
        if i >= 9:
            return b
        return None if i in (4, 6, 2, 3, 5, 7) else a
    monkeypatch.setattr(core, "_archived_words", words)
    core.wayback_text_change(rows, "x.org/", now)
    assert not any("changes on every capture" in m for m in logged)
    assert any("could not be read" in m or "no time" in m or "read limit" in m for m in logged)


def test_four_days_of_captures_are_enough(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    now = _now()
    day = lambda d: (now - timedelta(days=d)).strftime("%Y%m%d120000")
    rows = [[day(200), "A", "9000", "200", "text/html"], [day(150), "A", "9000", "200", "text/html"],
            [day(60), "B", "9000", "200", "text/html"], [day(20), "B", "9000", "200", "text/html"]]
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows)
    dt = core.wayback_change_date("https://x.org/", now)
    assert dt is not None and dt.strftime("%Y%m%d120000") == day(60)
    monkeypatch.setattr(core, "_cdx", lambda params, **k: rows[1:])
    assert core.wayback_change_date("https://x.org/", now) is None


# ── Review of 38646fa ─────────────────────────────────────────────────────────

def test_the_archive_query_covers_the_whole_year_of_daily_captures(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    now = _now()
    asked = []
    # A page archived every day for 300 days, changed 200 days ago.
    rows = [[(now - timedelta(days=d)).strftime("%Y%m%d120000"), "A" if d > 200 else "B",
             "9000", "200", "text/html"] for d in range(300, 0, -1)]
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params) or rows)
    dt = core.wayback_change_date("https://x.org/", now)
    assert abs(int(asked[0]["limit"])) >= core.WAYBACK_LOOKBACK_DAYS
    assert dt is not None and (now - dt).days == 200


def test_one_generator_run_across_midnight_or_timezones_is_one_pass():
    from liveliness import core
    keys = core._build_passes(["2026-06-01T23:59:30Z", "2026-06-02T00:00:30Z", "2026-06-02T00:01:40Z"])
    assert len(set(keys)) == 1
    keys = core._build_passes(["2026-06-01T12:00:00+02:00", "2026-06-01T10:00:30Z", "2026-06-01T10:01:00Z"])
    assert len(set(keys)) == 1


def _slow_session(monkeypatch, core):
    """A server that holds every connection for the full timeout, then drips."""
    import time as _t

    class Slow:
        status_code, headers, encoding = 200, {}, "utf-8"
        def __init__(self, url):
            self.url = url
        def iter_content(self, chunk_size=8192):
            while True:
                _t.sleep(0.2)
                yield b" "
        def close(self):
            pass

    def get(url, timeout=None, **k):
        t = timeout[0] if isinstance(timeout, tuple) else timeout
        _t.sleep(min(t or 0, 30))
        return Slow(url)
    monkeypatch.setattr(core.SESSION, "get", get)


def test_the_budget_is_a_hard_stop_for_the_archive(monkeypatch):
    import time
    from liveliness import core
    _slow_session(monkeypatch, core)
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    start = time.monotonic()
    # Long enough for a request to start, so the request itself must stop in time.
    core.wayback_change_date("https://x.org/", _now(), deadline=start + 16)
    assert time.monotonic() - start <= 17


def test_the_budget_is_a_hard_stop_for_the_sitemap(monkeypatch):
    import time
    from liveliness import core
    _slow_session(monkeypatch, core)
    start = time.monotonic()
    core.sitemap_date("https://x.org/", _now(), deadline=start + 3)
    assert time.monotonic() - start <= 4


def test_a_move_onto_a_query_named_page_skips_the_sitemap(monkeypatch):
    from liveliness import core
    seen = _fake_web(monkeypatch, core, {})
    assert core.sitemap_date("https://x.org/", _now(), landed="https://www.x.org/index.php?page=7") is None
    assert seen == []


def test_score_project_hands_the_landing_to_the_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    got = {}
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: got.setdefault("s", k) and None)
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now, **k: got.setdefault("w", k) and None)
    core.score_project(Project(name="Civic Widget", website="https://x.org/"))
    assert got["s"].get("landed") == "https://x.org/" and got["w"].get("landed") == "https://x.org/"


def test_an_empty_answer_to_a_heavy_query_is_retried_smaller(monkeypatch):
    # A heavily archived site can make the year-long query time out inside the
    # archive, which answers 200 with an empty body. That is not "no captures".
    from datetime import timedelta
    from liveliness import core
    now = _now()
    rows = [[(now - timedelta(days=d)).strftime("%Y%m%d120000"), "A" if d > 30 else "B",
             "9000", "200", "text/html"] for d in range(60, 0, -1)]
    asked = []
    def cdx(params, **k):
        asked.append(params["limit"])
        return None if abs(params["limit"]) >= core.WAYBACK_LOOKBACK_DAYS else rows
    monkeypatch.setattr(core, "_cdx", cdx)
    dt = core.wayback_change_date("https://x.org/", now)
    assert len(asked) == 2 and dt is not None and (now - dt).days == 30


def test_an_empty_cdx_body_is_not_an_empty_list(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_get", lambda url, params=None, deadline=None, *a: _FakeResponse(url, ""))
    assert core._cdx({"url": "x.org/"}) is None
    monkeypatch.setattr(core, "_wayback_get", lambda url, params=None, deadline=None, *a: _FakeResponse(url, "[]"))
    assert core._cdx({"url": "x.org/"}) == []


# ── Review of 8a630ae ─────────────────────────────────────────────────────────

def test_a_failed_year_query_does_not_pause_the_archive(monkeypatch):
    import requests
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core, "_wayback_timeouts", 1)   # one earlier stall already
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    asked = []
    def get(url, timeout=None, **k):
        asked.append(url)
        raise requests.Timeout("slow")
    monkeypatch.setattr(core.SESSION, "get", get)
    core.wayback_change_date("https://x.org/", _now())
    # The year query failing did not pause the archive, so the fallback ran.
    assert len(asked) == 2


def test_a_request_we_cut_short_does_not_count_toward_the_pause(monkeypatch):
    import time
    import requests
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core, "_wayback_timeouts", 0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    def get(url, timeout=None, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(core.SESSION, "get", get)
    for _ in range(3):
        core._cdx({"url": "x.org/"}, deadline=time.monotonic() + 8)
    assert core._wayback_paused_till == 0.0


def test_the_sitemap_gets_at_most_fifteen_seconds_of_the_last_resorts(monkeypatch):
    import time
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    got = {}
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, deadline, **k: got.__setitem__("s", deadline))
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now, deadline, **k: got.__setitem__("w", deadline))
    start = time.monotonic()
    core.score_project(Project(name="x", website="https://x.org/"))
    assert got["s"] <= time.monotonic() + 15.5 and got["w"] - got["s"] >= 24


def test_one_top_sitemap_with_any_date_ends_the_search(monkeypatch):
    from liveliness import core
    old = '<urlset><url><loc>https://x.org/a</loc><lastmod>2020-01-01</lastmod></url></urlset>'
    new = '<urlset><url><loc>https://x.org/b</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    seen = _fake_web(monkeypatch, core, {"https://x.org/robots.txt": "Sitemap: https://x.org/s1.xml\n",
                                         "https://x.org/s1.xml": old, "https://x.org/sitemap.xml": new})
    assert core.sitemap_date("https://x.org/", _now()) is None
    assert "https://x.org/sitemap.xml" not in seen


def test_sitemap_locations_are_xml_unescaped():
    from liveliness import core
    text = '<urlset><url><loc>https://x.org/p?a=1&amp;b=2</loc><lastmod>2026-01-01</lastmod></url></urlset>'
    assert core.parse_sitemap(text)[1] == [("https://x.org/p?a=1&b=2", "2026-01-01")]


def test_titles_are_html_unescaped(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<title>Caf&eacute; Civique &amp; Co</title>", {})})
    assert core._page_titles("https://x.org/") == ["Café Civique & Co"]


def test_xhtml_captures_count_as_pages():
    from liveliness import core
    assert core._real_capture(["20260101000000", "A", "9000", "200", "application/xhtml+xml"])


def test_a_hanging_name_lookup_does_not_hold_the_sitemap_past_its_deadline(monkeypatch):
    import socket
    import time
    from liveliness import core
    def slow_lookup(*a, **k):
        time.sleep(5)
        raise socket.gaierror("timed out")
    monkeypatch.setattr(core.socket, "getaddrinfo", slow_lookup)
    start = time.monotonic()
    assert core.sitemap_date("https://slow-dns.example/", _now(), deadline=start + 2) is None
    assert time.monotonic() - start <= 3


# ── Review of b180128 ─────────────────────────────────────────────────────────

def test_on_the_default_path_a_hanging_archive_is_paused_after_two_searches(monkeypatch):
    import time
    import requests
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core, "_wayback_timeouts", 0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    def get(url, timeout=None, **k):
        raise requests.Timeout("hung")
    monkeypatch.setattr(core.SESSION, "get", get)
    for _ in range(2):
        core.wayback_change_date("https://x.org/", _now(), deadline=time.monotonic() + 40)
    assert core._wayback_paused_till > time.monotonic()


def test_a_server_error_on_the_year_query_does_not_pause_before_the_fallback(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    asked = []
    def limited(url, **k):
        asked.append(url)
        return _FakeResponse(url, "", 503) if "limit=-410" in url else _FakeResponse(url, "[]")
    monkeypatch.setattr(core, "get_limited", limited)
    core.wayback_change_date("https://x.org/", _now())
    assert len(asked) == 2 and core._wayback_paused_till == 0.0


def test_an_old_page_date_is_still_reported_when_a_publish_outscores_it(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    now = datetime.now(timezone.utc)
    build, page = now - timedelta(days=20), now - timedelta(days=450)
    monkeypatch.setattr(core, "sitemap_date",
                        lambda u, now, **k: core.SitemapFind(build, "s.xml", build=True, page_date=page))
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: None)
    r = core.score_project(Project(name="x", website="https://x.org/"))
    assert r["last_activity_date"] == page.strftime("%Y-%m-%d")
    assert core.SITEMAP_LABEL in r["breakdown"] and core.SITEMAP_BUILD_LABEL in r["breakdown"]


def test_the_public_suffix_list_decides_what_was_registered():
    from liveliness import core
    assert core._registrable("news.x.gov.br") == "x.gov.br"
    assert core._registrable("a.b.x.com.au") == "x.com.au"
    assert core._registrable("alice.pages.dev") == "alice.pages.dev"
    assert core._registrable("alice.substack.com") == "alice.substack.com"
    # A suffix of three labels a hand-made list misses.
    assert core._registrable("school.k12.ca.us") == "school.k12.ca.us"


def test_a_sitemap_redirect_is_judged_on_where_it_landed(monkeypatch):
    from liveliness import core
    # The homepage itself reads like a for-sale page; the sitemap it redirects
    # to, on the same domain, is a real sitemap and is trusted.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<p>This domain is for sale.</p>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    body = '<urlset><url><loc>https://blog.x.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": (body, "https://blog.x.org/sitemap.xml")})
    found = core.sitemap_date("https://x.org/", _now())
    assert found is not None and found.date.month == 9


def test_no_lookup_for_a_host_the_homepage_already_reached(monkeypatch):
    import socket
    from liveliness import core
    def never(*a, **k):
        raise AssertionError("already resolved")
    monkeypatch.setattr(core.socket, "getaddrinfo", never)
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://x.org/"})
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<html></html>", {})})
    # The sitemap search goes ahead without a lookup; it finds nothing here.
    _fake_web(monkeypatch, core, {})
    monkeypatch.setattr(core, "host_resolves", never)
    assert core.sitemap_date("https://x.org/", _now()) is None


def test_hung_lookups_hold_at_most_the_pool(monkeypatch):
    import threading
    import time
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    monkeypatch.setattr(core.socket, "getaddrinfo", lambda *a, **k: time.sleep(3))
    before = threading.active_count()
    for i in range(4):
        core.host_resolves("https://slow%d.example/" % i, timeout=0.1)
    assert threading.active_count() - before <= core.LOOKUP_WORKERS


def test_request_caps_is_one_number():
    from liveliness import core
    assert core.request_caps(40, 10) == 10
    assert core.request_caps(8, 10) == 2


# ── Review of c9fe653 ─────────────────────────────────────────────────────────

def test_a_move_up_to_the_parent_site_is_never_trusted(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://civiclab.uni.edu/": ("<title>Civic Lab</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://civiclab.uni.edu/": "https://www.uni.edu/"})
    assert core.landed_url("https://civiclab.uni.edu/") == "https://civiclab.uni.edu/"
    # www and no-www, and the same host, are the same site.
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/": "https://www.x.org/"})
    assert core.landed_url("https://x.org/") == "https://www.x.org/"
    # A sibling subdomain is never trusted, whatever its title says.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://blog.x.org/": ("<title>Civic Widget portal</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://blog.x.org/": "https://portal.x.org/"})
    assert core.landed_url("https://blog.x.org/") == "https://blog.x.org/"


def test_a_page_that_redirects_to_its_sites_root_was_removed(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://cfa.org/projects/foo": ("<title>Code for America</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://cfa.org/projects/foo": "https://cfa.org/"})
    assert core.landed_url("https://cfa.org/projects/foo") == "https://cfa.org/projects/foo"
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params["url"]) or None)
    core.wayback_change_date("https://cfa.org/projects/foo", _now())
    assert asked and all(a == "cfa.org/projects/foo" for a in asked)


def test_a_bare_date_build_needs_twenty_entries():
    from liveliness import core
    ten = [("https://x.org/%d" % i, "2026-06-01") for i in range(10)]
    assert _newest_date(ten) is not None
    twenty = [("https://x.org/%d" % i, "2026-06-01") for i in range(20)]
    assert _newest_date(twenty) is None
    # Timed stamps still need only five.
    timed = [("https://x.org/%d" % i, "2026-06-01T12:00:0%dZ" % i) for i in range(5)]
    assert _newest_date(timed) is None


def test_host_resolves_takes_a_timeout_and_cancels(monkeypatch):
    import time
    from liveliness import core
    monkeypatch.setattr(core.socket, "getaddrinfo", lambda *a, **k: time.sleep(2))
    start = time.monotonic()
    assert core.host_resolves("https://slow.example/", timeout=0.2) is None
    assert time.monotonic() - start < 1
    assert not hasattr(core, "resolves_within")


def test_a_parked_title_or_og_name_counts(monkeypatch):
    from liveliness import core
    page = '<head><meta property="og:site_name" content="This domain is for sale"></head><body><p>Hello</p></body>'
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": (page, {})})
    assert core._looks_parked("https://x.org/", "https://www.x.org/")


def test_an_old_signal_does_not_keep_the_last_resorts_away(monkeypatch):
    from datetime import timedelta
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    old = _now().replace(year=2023)
    monkeypatch.setattr(core, "check_github", lambda u: {
        "best_date": old, "archived": False, "dates": {"push": old}, "resolution": None})
    asked = []
    monkeypatch.setattr(core, "sitemap_date", lambda u, now, **k: asked.append(u))
    monkeypatch.setattr(core, "wayback_change_date", lambda u, now=None, **k: None)
    core.score_project(Project(name="x", website="https://x.org/", repo="https://github.com/x/x"))
    assert asked == ["https://x.org/"]


def test_default_ports_and_path_case_do_not_split_a_site():
    from liveliness import core
    assert core._same_site("https://x.org:443/a", {"x.org"})
    assert core._same_site("http://x.org:80/a", {"x.org"})
    assert core._within("https://x.org/Labs/Civic/page", "/labs/civic")


def test_a_language_root_is_skipped_when_picking_the_section():
    from liveliness import core
    assert core._section_word("/en/labs/civic") == "labs"
    assert core._section_word("/labs/civic") == "labs"
    assert core._section_word("") == ""


def test_the_sitemap_body_says_what_kind_it_is(monkeypatch):
    import time
    from liveliness import core
    body = '<sitemapindex><sitemap><loc>https://x.org/a.xml</loc></sitemap></sitemapindex>'
    _fake_web(monkeypatch, core, {"https://x.org/sitemap.xml": body})
    text, final, kind = core._sitemap_body("https://x.org/sitemap.xml", time.monotonic() + 10)
    assert kind == "sitemapindex"
    assert not hasattr(core, "sitemap_newest_date")


def test_a_move_down_from_the_apex_into_a_subdomain_is_trusted(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://www.x.org/": ("<title>XP Portal</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://www.x.org/": "https://portal.x.org/"})
    assert core.landed_url("https://www.x.org/") == "https://portal.x.org/"
    # Sibling to sibling still needs the name.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://blog.x.org/": ("<title>XP Portal</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://blog.x.org/": "https://portal.x.org/"})
    assert core.landed_url("https://blog.x.org/") == "https://blog.x.org/"


# ── Review of a023bfb ─────────────────────────────────────────────────────────

def test_a_sitemap_win_over_an_old_commit_does_not_set_status_active(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=730)
    monkeypatch.setattr(core, "check_github", lambda u: {
        "best_date": old, "archived": False, "dates": {"push": old}, "resolution": None})
    monkeypatch.setattr(core, "sitemap_date",
                        lambda u, now, **k: core.SitemapFind(now - timedelta(days=60), "s.xml"))
    r = core.score_project(Project(name="x", website="https://x.org/", repo="https://github.com/x/x"))
    assert r["activity_status"] == "Active" and r["status"] is None


def test_candidates_say_whether_they_are_the_projects_own_evidence():
    from liveliness import core
    c = core.Candidate(70, _now(), "Blog post", core.OWN)
    assert c.own and not core.Candidate(45, _now(), core.WAYBACK_LABEL, core.WAYBACK).own


def test_a_deep_page_on_the_apex_sent_to_a_subdomain_root_was_removed(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/projects/foo": ("<title>X</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/projects/foo": "https://portal.x.org/"})
    assert core.landed_url("https://x.org/projects/foo") == "https://x.org/projects/foo"


def test_a_sitemap_sent_to_a_sibling_subdomain_is_not_trusted(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://blog.x.org/": ("<title>Something else</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    body = '<urlset><url><loc>https://news.x.org/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://blog.x.org/sitemap.xml": (body, "https://news.x.org/sitemap.xml")})
    assert core.sitemap_date("https://blog.x.org/", _now()) is None
    # Not even with the name on the homepage: it says nothing about the sibling's list.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://blog.x.org/": ("<title>Civic Widget blog</title>", {})})
    assert core.sitemap_date("https://blog.x.org/", _now()) is None


def test_busy_lookup_workers_answer_unknown_at_once(monkeypatch):
    import threading
    import time
    from liveliness import core
    release = threading.Event()
    monkeypatch.setattr(core.socket, "getaddrinfo", lambda *a, **k: release.wait(5))
    try:
        for i in range(core.LOOKUP_WORKERS):
            core.host_resolves("https://hung%d.example/" % i, timeout=0.05)
        start = time.monotonic()
        assert core.host_resolves("https://next.example/", timeout=2) is None
        assert time.monotonic() - start < 0.2
    finally:
        release.set()
        time.sleep(0.1)


def test_a_cdx_answer_that_is_not_a_list_is_no_answer(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_get",
                        lambda url, params=None, deadline=None, *a: _FakeResponse(url, '{"error": "busy"}'))
    assert core._cdx({"url": "x.org/"}) is None


def test_an_unreadable_six_month_capture_falls_through_to_the_year(monkeypatch):
    from liveliness import core
    now = _now()
    rows = _churny_rows(now, n=17)    # 357 days back to 21 days back
    old = {"word%d" % i for i in range(40)}
    new = {"term%d" % i for i in range(40)}
    six = min(range(len(rows) - 2), key=lambda k: abs((now - core._cdx_time(rows[k][0])).days - 182))
    def words(ts, target, **k):
        i = [r[0] for r in rows].index(ts)
        if i == six:
            return None
        return new if i >= 14 else old
    monkeypatch.setattr(core, "_archived_words", words)
    assert core.wayback_text_change(rows, "x.org/", now) is not None


def test_request_caps_names_one_body_deadline():
    from liveliness import core
    assert core.body_deadline(40, core.request_caps(40, 10)) == 10
    assert core.body_deadline(8, core.request_caps(8, 10)) == 2


def test_social_links_are_deduplicated_by_site(monkeypatch):
    from liveliness import core
    page = ('<a href="https://TWITTER.com/x">t</a><a href="https://www.twitter.com:443/x">t2</a>'
            '<a href="https://bsky.app/profile/x">b</a>')
    monkeypatch.setattr(core, "get_page_cached", lambda u: (page, {}))
    links = core.discover_social_links("https://x.org/")
    assert len(links) == 2 and links[0] == "https://TWITTER.com/x"


# ── Review of 2dc55f0 ─────────────────────────────────────────────────────────

def test_the_website_bonus_follows_the_newest_date_not_the_winner(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    now = datetime.now(timezone.utc)
    commit = now - timedelta(days=400)
    monkeypatch.setattr(core, "check_github", lambda u: {
        "best_date": commit, "archived": False, "dates": {"push": commit}, "resolution": None})
    monkeypatch.setattr(core, "discover_social_links", lambda u: ["https://bsky.app/profile/x"])
    monkeypatch.setattr(core, "check_url_alive", lambda u: False)
    monkeypatch.setattr(core, "check_social_recency", lambda u: (now - timedelta(days=150), "Bluesky"))
    r = core.score_project(Project(name="x", website="https://x.org/", repo="https://github.com/x/x"))
    assert "Website is responding (+15)" in r["breakdown"]
    assert r["status"] == "Active"


def test_a_build_needs_enough_entries_sharing_the_stamp():
    from liveliness import core
    # 16 of 20 share a bare date: 80%, but under twenty entries share it.
    entries = [("https://x.org/a%d" % i, "2026-06-01") for i in range(16)]
    entries += [("https://x.org/b%d" % i, "2025-0%d-15" % (1 + i)) for i in range(4)]
    assert _newest_date(entries).isoformat()[:10] == "2026-06-01"


def test_lookups_run_on_daemon_threads_and_give_their_slot_back(monkeypatch):
    import threading
    import time
    from liveliness import core
    # Earlier tests can leave hung lookups holding slots; wait for them to end.
    held = [core._LOOKUP_SLOTS.acquire(timeout=10) for _ in range(core.LOOKUP_WORKERS)]
    for ok in held:
        if ok:
            core._LOOKUP_SLOTS.release()
    release = threading.Event()
    names = []
    def hang(*a, **k):
        names.append(threading.current_thread())
        release.wait(5)
    monkeypatch.setattr(core.socket, "getaddrinfo", hang)
    assert core.host_resolves("https://hung.example/", timeout=0.05) is None
    assert names and names[0].daemon
    release.set()
    time.sleep(0.2)
    # Every slot is free again once the hung lookup ends.
    got = [core._LOOKUP_SLOTS.acquire(blocking=False) for _ in range(core.LOOKUP_WORKERS)]
    for ok in got:
        if ok:
            core._LOOKUP_SLOTS.release()
    assert all(got)


def test_a_deep_page_sent_to_a_subdomain_front_page_is_removed_whatever_its_title(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/projects/widget": ("<title>Civic Widget</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://x.org/projects/widget": "https://widget.x.org/"})
    assert core.landed_url("https://x.org/projects/widget") == "https://x.org/projects/widget"


def test_a_same_site_move_is_judged_on_the_landed_page_alone(monkeypatch):
    from liveliness import core
    # A real short homepage: the move to https is the same site.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"http://x.org/": ("<title>X</title><p>Small project.</p>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"http://x.org/": "https://x.org/"})
    assert core.landed_url("http://x.org/") == "https://x.org/"
    # The page the move landed on reads as parked: not trusted, same site or not.
    monkeypatch.setattr(core, "_PAGE_CACHE", {"http://x.org/": ("<p>This domain is for sale.</p>", {})})
    assert core.landed_url("http://x.org/") == "http://x.org/"
    # A parking host is never the same site anyway, and stays rejected.
    monkeypatch.setattr(core, "_PAGE_FINAL", {"http://x.org/": "https://sedo.com/x.org"})
    assert core.landed_url("http://x.org/") == "http://x.org/"


def test_og_names_are_read_in_either_order_and_with_apostrophes(monkeypatch):
    from liveliness import core
    page = ('<meta content="Bob\'s Widget" property="og:site_name">'
            "<meta property='og:title' content=\"Bob's Widget home\">")
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": (page, {})})
    assert core._page_titles("https://x.org/") == ["Bob's Widget", "Bob's Widget home"]


def test_sitemap_moves_use_trusted_move():
    from liveliness import core
    assert not hasattr(core, "_sitemap_move_trusted")


# ── Review of 6c3e057 ─────────────────────────────────────────────────────────

def test_a_sitemap_sent_to_a_sibling_is_never_trusted_on_a_name(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://civiclab.uni.edu/": ("<title>Civic Lab</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {})
    body = '<urlset><url><loc>https://news.uni.edu/a</loc><lastmod>2026-09-01</lastmod></url></urlset>'
    _fake_web(monkeypatch, core, {"https://civiclab.uni.edu/sitemap.xml": (body, "https://news.uni.edu/sitemap.xml")})
    assert core.sitemap_date("https://civiclab.uni.edu/", _now()) is None


def test_a_listed_homepage_that_reads_as_parked_skips_the_last_resorts(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    monkeypatch.setattr(core, "get_page_cached", lambda u: ("<p>This domain is for sale. Make an offer.</p>", {}))
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<p>This domain is for sale. Make an offer.</p>", {})})
    def never(*a, **k):
        raise AssertionError("a parked homepage is not dated")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    core.score_project(Project(name="x", website="https://x.org/"))


def test_the_section_comes_from_the_listing_or_where_a_deep_page_landed(monkeypatch):
    from liveliness import core
    cases = [
        # (listed, landed, title, entries, expected month)
        ("https://x.org/tools/foo", "https://x.org/projects/foo", "X",
         [("https://x.org/projects/foo/a", "2026-08-01"), ("https://x.org/other", "2026-10-01")], 8),
        # A listed front page: the whole site where it landed, here its own subdomain.
        ("https://oldname.org/", "https://home.oldname.org/start", "X",
         [("https://home.oldname.org/news/a", "2026-07-01")], 7),
    ]
    for listed, landed, title, entries, month in cases:
        monkeypatch.setattr(core, "_PAGE_CACHE", {listed: ("<title>%s</title>" % title, {})})
        monkeypatch.setattr(core, "_PAGE_FINAL", {listed: landed})
        root = "https://" + core.urlparse(landed).netloc
        body = "<urlset>" + "".join("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % e for e in entries) + "</urlset>"
        _fake_web(monkeypatch, core, {root + "/sitemap.xml": body})
        found = core.sitemap_date(listed, _now())
        assert found is not None and found.date.month == month, listed


def test_the_archive_query_filters_to_real_html_captures(monkeypatch):
    from liveliness import core
    asked = []
    monkeypatch.setattr(core, "_cdx", lambda params, **k: asked.append(params) or None)
    core.wayback_change_date("https://x.org/", _now())
    filters = asked[0]["filter"]
    assert "statuscode:(200|-)" in filters
    assert any(f.startswith("mimetype:") and "text/html" in f for f in filters)


def test_a_lookup_thread_that_will_not_start_gives_its_slot_back(monkeypatch):
    from liveliness import core
    def boom(self):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(core.threading.Thread, "start", boom)
    for _ in range(core.LOOKUP_WORKERS + 1):
        assert core.host_resolves("https://x.example/", timeout=0.1) is None
    assert core._LOOKUP_SLOTS.acquire(blocking=False)
    core._LOOKUP_SLOTS.release()


def test_get_within_fits_one_request_to_the_time_left(monkeypatch):
    import time
    from liveliness import core
    got = {}
    monkeypatch.setattr(core, "get_limited", lambda url, **k: got.update(k) or _FakeResponse(url, "ok"))
    core.get_within("https://x.org/", time.monotonic() + 8, 10)
    assert got["timeout"] <= 2.1 and got["deadline_s"] <= 2.1


# ── Review of bfb085a: no name-based trust ────────────────────────────────────

def test_a_move_to_another_registered_domain_is_never_trusted(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://www.delphi.ai/": ("<title>Delphi AI</title>", {})})
    monkeypatch.setattr(core, "_PAGE_FINAL", {"https://www.delphi.ai/": "https://www.delphi.co/"})
    assert core.landed_url("https://www.delphi.ai/") == "https://www.delphi.ai/"
    assert not hasattr(core, "_page_names_project")


def test_the_parked_gate_sees_the_lander_host(monkeypatch):
    from liveliness import core
    _undated_live_site(monkeypatch, core)
    page = "<title>x.org</title>" + "<p>Some words about many different things here.</p>" * 40
    def fetch(u):
        core._PAGE_FINAL[u] = "https://www.sedo.com/lander?d=x.org"
        return page, {}
    monkeypatch.setattr(core, "get_page_cached", fetch)
    def never(*a, **k):
        raise AssertionError("a parked lander is not dated")
    monkeypatch.setattr(core, "sitemap_date", never)
    monkeypatch.setattr(core, "wayback_change_date", never)
    core.score_project(Project(name="x", website="https://x.org/"))


def test_parked_wording_has_to_be_about_the_domain(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<p>Bikes for sale. Make an offer!</p>", {})})
    assert not core._looks_parked("https://x.org/", "https://x.org/")
    monkeypatch.setattr(core, "_PAGE_CACHE", {"https://x.org/": ("<p>This domain may be for sale.</p>", {})})
    assert core._looks_parked("https://x.org/", "https://x.org/")


def test_an_archive_that_has_not_looked_for_ninety_days_dates_nothing():
    from datetime import timedelta
    from liveliness import core
    now = _now()
    day = lambda d: (now - timedelta(days=d)).strftime("%Y%m%d120000")
    rows = [[day(300), "A"], [day(250), "A"], [day(200), "B"], [day(120), "B"]]
    assert core.wayback_change_from_captures(rows, now)[0] is None


def test_a_build_pass_spans_at_most_thirty_minutes():
    from liveliness import core
    # A stamp every minute for fifty minutes: two passes, not one.
    stamps = ["2026-06-01T12:%02d:00Z" % m for m in range(50)]
    assert len(set(core._build_passes(stamps))) >= 2


def test_the_sixty_day_fallback_does_not_compare_text(monkeypatch):
    from liveliness import core
    now = _now()
    from datetime import timedelta
    rows = [[(now - timedelta(days=d)).strftime("%Y%m%d120000"), "H%d" % d, "9000", "200", "text/html"]
            for d in range(59, 0, -3)]
    monkeypatch.setattr(core, "_cdx", lambda params, **k: None if abs(params["limit"]) > 100 else rows)
    def never(*a, **k):
        raise AssertionError("no text comparison on the short window")
    monkeypatch.setattr(core, "_archived_words", never)
    assert core.wayback_change_date("https://x.org/", now) is None


def test_the_archive_request_uses_one_timeout(monkeypatch):
    import time
    from liveliness import core
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    got = {}
    def within(url, deadline, cap, **k):
        got.update(k)
        return _FakeResponse(url, "[]")
    monkeypatch.setattr(core, "get_within", within)
    core._cdx({"url": "x.org/"}, deadline=time.monotonic() + 40)
    assert "timeout" in got
