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
    assert core.sitemap_newest_date(entries[:3], _now()) is not None


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


def test_a_sitemap_index_is_followed_to_its_children(monkeypatch):
    from liveliness import core
    index = ('<sitemapindex><sitemap><loc>https://x.org/post-sitemap.xml</loc>'
             '<lastmod>2026-09-01</lastmod></sitemap>'
             '<sitemap><loc>https://x.org/page-sitemap.xml</loc></sitemap></sitemapindex>')
    posts = '<urlset><url><loc>https://x.org/p/1</loc><lastmod>2026-08-31</lastmod></url></urlset>'
    pages = '<urlset><url><loc>https://x.org/about</loc><lastmod>2021-01-01</lastmod></url></urlset>'
    bodies = {"https://x.org/sitemap.xml": index,
              "https://x.org/post-sitemap.xml": posts,
              "https://x.org/page-sitemap.xml": pages}
    seen = []
    def body(url, deadline):
        seen.append(url)
        return bodies.get(url)
    monkeypatch.setattr(core, "_sitemap_body", body)
    monkeypatch.setattr(core, "_robots_sitemaps", lambda root, deadline: [])
    dt, src = core.sitemap_date("https://x.org/", _now())
    assert (dt.month, dt.day) == (8, 31) and src.endswith("post-sitemap.xml")
    assert len(seen) == 3


def test_a_sitemap_named_in_robots_txt_is_read_first(monkeypatch):
    from liveliness import core
    seen = []
    def body(url, deadline):
        seen.append(url)
        return '<urlset><url><loc>https://x.org/</loc><lastmod>2026-02-01</lastmod></url></urlset>'
    monkeypatch.setattr(core, "_sitemap_body", body)
    monkeypatch.setattr(core, "_robots_sitemaps",
                        lambda root, deadline: ["https://cdn.x.org/maps/main.xml"])
    assert core.sitemap_date("https://x.org/", _now()) is not None
    assert seen == ["https://cdn.x.org/maps/main.xml"]


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


def test_unchanged_across_every_capture_needs_the_older_record():
    from liveliness import core
    rows = [["20260101000000", "A"], ["20260201000000", "A"], ["20260301000000", "A"]]
    dt, settled = core.wayback_change_from_captures(rows)
    assert not settled and dt.month == 1


def test_an_unchanged_page_is_dated_by_when_its_content_first_appeared(monkeypatch):
    from liveliness import core
    calls = []
    def cdx(params):
        calls.append(params)
        if params.get("limit") == 1:
            assert "digest:A" in params["filter"]
            return [["20190405000000", "A", "9000"]]
        return [["20260101000000", "A", "9000"], ["20260201000000", "A", "9100"],
                ["20260301000000", "A", "9050"]]
    monkeypatch.setattr(core, "_cdx", cdx)
    dt = core.wayback_change_date("https://x.org/", _now())
    assert (dt.year, dt.month) == (2019, 4) and len(calls) == 2
    assert calls[0]["url"] == "x.org/"


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
    dt = core.sitemap_newest_date(entries, _now(), "", "x.org")
    assert (dt.year, dt.month) == (2025, 2)
    assert core.sitemap_newest_date(entries[:1], _now(), "", "x.org") is None


def test_a_sitemap_that_lists_bare_paths_is_read_as_its_own_site(monkeypatch):
    from liveliness import core
    monkeypatch.setattr(core, "_robots_sitemaps", lambda root, deadline: [])
    monkeypatch.setattr(core, "_sitemap_body", lambda url, deadline:
                        '<urlset><url><loc>/orgs/a/</loc><lastmod>2019-12-12T22:57:14+00:00</lastmod>'
                        '</url></urlset>')
    dt, _ = core.sitemap_date("https://x.org/", _now())
    assert dt.year == 2019


def test_an_archive_that_cannot_be_asked_is_no_evidence(monkeypatch):
    import requests
    from liveliness import core
    def stall(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(core.SESSION, "get", stall)
    monkeypatch.setattr(core, "_wayback_paused_till", 0.0)
    monkeypatch.setattr(core, "_wayback_last_call", 0.0)
    assert core.wayback_change_date("https://x.org/") is None
    # And a stalled archive is not asked again for every later record.
    def never(*a, **k):
        raise AssertionError("asked again while paused")
    monkeypatch.setattr(core.SESSION, "get", never)
    assert core.wayback_change_date("https://y.org/") is None


def test_an_archive_change_scores_like_the_footer_copyright():
    from datetime import timedelta
    from liveliness import core
    now = _now()
    assert core.wayback_recency_score(now - timedelta(days=30), now) == core.COPYRIGHT_FRESH_FLOOR
    assert core.wayback_recency_score(now - timedelta(days=500), now) == 25
    assert core.wayback_recency_score(now - timedelta(days=4000), now) == 3


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
