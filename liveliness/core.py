"""
Is a civic tech project still alive?

Given what a project publishes, its website, code repository, feeds and social
accounts, this works out how recently anything moved and turns that into a
score from 0 to 100 with a line-by-line account of how it got there.

The score is only ever as good as what a project puts in public, so the whole
of the reasoning is returned alongside it. A number without its reasons cannot
be checked or improved on, and the projects being scored deserve both.

    from liveliness import Project, score_project

    result = score_project(Project(
        name="liveliness",
        website="https://github.com/Civic-Tech-Field-Guide/liveliness",
        repo="https://github.com/Civic-Tech-Field-Guide/liveliness",
    ))
    print(result["score"], result["activity_status"])
    print(result["breakdown"])

Two optional environment variables raise the ceiling on what can be checked:
GITHUB_TOKEN (60 API calls an hour becomes 5,000) and YOUTUBE_API_KEY (without
it, a YouTube channel is checked for reachability but not for its last upload).
"""

import json
import os
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser as _HTMLParser
from urllib.parse import urljoin, parse_qs, urlparse

import requests

try:
    import feedparser
except ImportError:
    raise ImportError(
        "feedparser is required. Without it every feed check returns nothing, "
        "so a project that posts weekly scores as though it has no blog at all, "
        "and that is a fact about the install being reported as a fact about "
        "the project. Install it with: pip install feedparser"
    )

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CURRENT_YEAR    = str(datetime.now().year)


# Progress reporting. A library that prints is a library that has decided what
# your terminal is for, so this does nothing until a caller asks for it.
_logger = None


def set_logger(fn):
    """Call fn(str) for each step as a project is scored. None turns it off."""
    global _logger
    _logger = fn


def _log(*args, **kwargs):
    if _logger is not None:
        _logger(" ".join(str(a) for a in args))


# ── HTTP session ──────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "civictech.guide timeliness-checker/1.0 (+https://civictech.guide)"})

# Project URLs come from public submissions — cap how much of any body we
# download so one hostile/broken site can't hang or OOM the run.
MAX_FETCH_BYTES  = 1_000_000
FETCH_DEADLINE_S = 20


class _LimitedResponse:
    """Snapshot of a response with the body capped at MAX_FETCH_BYTES."""

    def __init__(self, r, body):
        self.status_code = r.status_code
        self.headers     = r.headers
        self.url         = r.url
        self.content     = body
        self._encoding   = r.encoding or "utf-8"

    @property
    def text(self):
        return self.content.decode(self._encoding, errors="replace")


_PAGE_CACHE = {}


def get_page_cached(url):
    """
    (html, headers) for a URL, fetched at most once per record.

    The homepage is now read twice — once for social links, once for the dates
    the page states about itself — and neither is worth a second download.
    Cleared per record by compute_liveliness so a 200-record batch does not hold
    200 pages of up to MAX_FETCH_BYTES each.
    """
    if url in _PAGE_CACHE:
        return _PAGE_CACHE[url]
    try:
        r = get_limited(url)
        val = (r.text, dict(r.headers)) if r.status_code == 200 else (None, None)
    except Exception:
        val = (None, None)
    _PAGE_CACHE[url] = val
    return val


def get_limited(url, timeout=10, headers=None):
    """GET that stops reading at MAX_FETCH_BYTES or FETCH_DEADLINE_S of
    wall-clock time, whichever comes first. Raises like requests.get.
    A server dripping bytes too slowly to ever fill a chunk can still hold
    the read open — the per-record SIGALRM budget is the backstop there."""
    r = SESSION.get(url, timeout=timeout, allow_redirects=True, stream=True,
                    headers=headers)
    start, size, chunks = time.monotonic(), 0, []
    try:
        for chunk in r.iter_content(chunk_size=8192):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_FETCH_BYTES or time.monotonic() - start > FETCH_DEADLINE_S:
                break
    finally:
        r.close()
    return _LimitedResponse(r, b"".join(chunks))


# ── URL classification ────────────────────────────────────────────────────────

# Domains that are definitely not a project homepage
_ARTICLE_DOMAINS = {
    "techcrunch.com", "theverge.com", "wired.com", "bloomberg.com",
    "reuters.com", "theguardian.com", "nytimes.com", "washingtonpost.com",
    "forbes.com", "businessinsider.com", "politico.com", "npr.org",
    "bbc.com", "bbc.co.uk", "apnews.com", "axios.com", "vice.com",
    "fastcompany.com", "engadget.com", "gizmodo.com", "arstechnica.com",
    "theatlantic.com", "vox.com", "slate.com", "salon.com",
    "govtech.com", "statescoop.com", "fedscoop.com", "nextgov.com",
    "citylab.com", "smartcitiesdive.com", "govinsider.asia",
}

# Domains and patterns we should skip entirely (no useful signal)
_SKIP_DOMAINS = {"bing.com", "google.com"}

# Social media domains to look for when scanning a homepage for social links
_SOCIAL_DOMAINS = {
    "twitter.com", "x.com", "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "youtu.be", "bsky.app", "medium.com", "reddit.com",
    "substack.com", "tiktok.com",
}


def resolve_duckduckgo(url):
    """
    Follow a DuckDuckGo !ducky (I'm Feeling Ducky) URL to its final destination.
    Returns the resolved URL, or None if resolution failed or stayed on DuckDuckGo.
    """
    try:
        r = get_limited(url)
        final = r.url
        if "duckduckgo.com" not in final:
            return final
    except Exception:
        pass
    return None


def classify_url(url):
    """
    Returns one of: "skip", "article", "homepage".
    "skip"     → placeholder / search engine URL, ignore completely.
    "article"  → known media domain; try to find real URL.
    "homepage" → treat as the project's actual website.
    Note: DuckDuckGo URLs are resolved before this is called.
    """
    if not url:
        return "skip"
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().lstrip("www.")

    if netloc in _SKIP_DOMAINS:
        return "skip"

    if netloc in _ARTICLE_DOMAINS:
        return "article"

    return "homepage"


# ── Homepage discovery from article pages ─────────────────────────────────────

from html.parser import HTMLParser as _HTMLParser

class _LinkExtractor(_HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []  # list of (href, anchor_text)
        self._current_anchor = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_dict = dict(attrs)
            self._current_anchor = attrs_dict.get("href", "")

    def handle_data(self, data):
        if self._current_anchor is not None:
            self.links.append((self._current_anchor, data.strip()))

    def handle_endtag(self, tag):
        if tag == "a":
            self._current_anchor = None


_SKIP_LINK_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "instagram.com", "linkedin.com",
    "youtube.com", "tiktok.com", "google.com", "apple.com", "amazon.com",
    "duckduckgo.com", "bing.com",
}
_SKIP_LINK_DOMAINS |= _ARTICLE_DOMAINS


def find_homepage_in_article(article_url):
    """
    Fetch a news article and look for external links that are likely the
    project's actual homepage. Returns a URL string or None.
    """
    try:
        r = get_limited(article_url, timeout=12)
        if r.status_code != 200:
            return None

        article_domain = urlparse(article_url).netloc.lower().lstrip("www.")
        parser = _LinkExtractor()
        parser.feed(r.text)

        candidates = []
        for href, text in parser.links:
            if not href.startswith("http"):
                continue
            parsed_link = urlparse(href)
            link_domain = parsed_link.netloc.lower().lstrip("www.")

            # Must be a different domain from the article
            if link_domain == article_domain:
                continue
            # Skip known non-project domains
            if link_domain in _SKIP_LINK_DOMAINS:
                continue
            # Skip very long paths (probably deep links, not homepages)
            path_depth = len([p for p in parsed_link.path.strip("/").split("/") if p])
            if path_depth > 3:
                continue

            # Prefer anchor text that suggests it's a project link
            text_lower = text.lower()
            priority = 0
            if any(w in text_lower for w in ("website", "site", "platform", "tool",
                                              "project", "learn more", "visit", "here")):
                priority = 2
            elif path_depth <= 1:
                priority = 1  # short path = likely homepage

            candidates.append((priority, href))

        # Sort by priority descending, then check if alive
        candidates.sort(key=lambda x: -x[0])
        seen = set()
        for _, href in candidates[:10]:
            domain = urlparse(href).netloc.lower()
            if domain in seen:
                continue
            seen.add(domain)
            if check_url_alive(href) is True:
                return href
    except Exception:
        pass
    return None


# ── Individual signal checks ──────────────────────────────────────────────────

# Hosts that serve snapshots rather than a project. Landing on one of these
# means the original did not answer, whatever status code comes back.
#
# This list is closed. Do not extend it with institutional archives, however
# archive-like the hostname reads. Membership requires a parseable snapshot URL
# grammar, because _extract_archive_original() must be able to recover the
# original and re-check it, and a host recognised here without that grammar
# lands in the recognised-but-unparseable state that rules a listing dead
# without a single fetch. Hostnames matching the intuition are also often live
# canonical homes for real items: arXiv, SSRN, Zenodo, archive.org/details.
# A host outside this list that redirects into it is already handled, by the
# effective-URL check in _try_fetch() rather than by name.
ARCHIVE_HOSTS = (
    "web.archive.org", "waybackmachine.org",
    "archive.today", "archive.ph", "archive.is",
    "archive.li", "archive.vn", "archive.md",
)


def is_archive_host(url):
    """True if the URL's host serves archive snapshots."""
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in ARCHIVE_HOSTS)


def _extract_archive_original(url):
    """
    Extract the original URL from an archive link, or None.

    web.archive.org/web/20180217125651/http://example.org/  -> http://example.org/
    archive.today/?url=http://example.org/                  -> http://example.org/
    archive.ph/newest/http://example.org/                   -> http://example.org/

    Every archive host recognised by is_archive_host() must be parseable here.
    A host recognised as an archive but not parsed returns None, and the caller
    then rules the listing dead and archived without ever fetching anything,
    which is a confident wrong answer rather than a miss.
    """
    m = re.search(r'(?:web\.archive\.org|waybackmachine\.org)/web/\d+[^/]*/(.+)', url)
    if m:
        return m.group(1)
    q = parse_qs(urlparse(url).query).get("url")
    if q and q[0]:
        return q[0]
    m = re.search(r'archive\.(?:today|ph|is|li|vn|md)/(?:newest/|\d+/)?(https?://.+)', url)
    if m:
        return m.group(1)
    return None


WEBSITE_RETRY_DELAY_S = 2


def _try_fetch(url, attempt=1):
    """
    Attempt a GET and return (is_alive, exception_type).

    A hard connection error is retried once before the site is called dead.
    Resets, DNS blips and handshakes refused to a datacenter IP are transient
    or environmental rather than evidence a site is gone, and a single one of
    them costs a live listing 50 points. Timeouts already return None, so they
    need no retry.
    """
    try:
        r = SESSION.get(url, timeout=10, allow_redirects=True, stream=True)
        r.close()
        # A dead site whose owner points the domain at a snapshot of itself
        # answers 200 from an archive host. Judge the effective URL, not the
        # requested one. A domain that 302s to its own capture from years ago
        # answers 200, so reading the status code alone scores a tombstone as
        # a live site.
        if is_archive_host(r.url) and not is_archive_host(url):
            return False, "redirected_to_archive"
        # Bot-blocking responses are indeterminate — don't treat as dead
        if r.status_code in (403, 429):
            return None, "blocked"
        return (200 <= r.status_code < 400), None
    except requests.exceptions.SSLError:
        return True, None   # broken SSL but site exists
    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.TooManyRedirects:
        return None, "redirects"
    except Exception:
        if attempt == 1:
            time.sleep(WEBSITE_RETRY_DELAY_S)
            return _try_fetch(url, attempt=2)
        return False, "error"


def check_website(url):
    """
    Returns (is_alive: bool | None, is_archived: bool, reason: str | None).

    For web archive URLs, tries the original URL first; only treats as
    archived/dead if the original URL also fails.
    None means we couldn't determine (timeout / network error).

    `reason` carries _try_fetch()'s word for why, and the one that matters is
    "blocked": a 403 or 429 is a wall in front of the page, not a fact about
    the project, and a browser gets past most of them. A timeout is not the
    same thing and reading it the same way would send us to render sites that
    are simply slow.
    """
    if not url:
        return None, False, None

    is_archive_url = is_archive_host(url)

    if is_archive_url:
        original = _extract_archive_original(url)
        if original:
            _log(f"    website  → archive URL, trying original: {original[:60]}")
            alive, why = _try_fetch(original)
            if alive is True:
                return True, False, None   # original site is live — not archived
            if alive is None:
                return None, True, why     # couldn't determine
        # Original is down or couldn't be extracted — genuinely archived
        return False, True, None

    alive, why = _try_fetch(url)
    return alive, False, why


# find_wayback_url() was removed with the Website URL replacement it fed. Picking
# a snapshot belongs to the curator's dead-link triage, which chooses the one
# nearest the project's last known activity rather than the newest (the newest is
# often already a parked-domain page) and rate-limits itself to Wayback's ~15
# requests/minute. Nothing in this scorer should reintroduce it.


# ── Telling a dead project from a moved page ──────────────────────────────────
#
# A failed fetch is not one finding, it is several, and they call for opposite
# rulings. The host not resolving at all means the thing is gone. The listed
# page answering 404 while its own host answers fine means the page moved and
# the organisation carried on, which the codebook calls a relink and which is
# the commonest case of the two. Scoring both as "website did not respond" and
# subtracting 50 buries the difference, and the relink cases are exactly the
# listings most worth keeping, since only the link is stale.
#
# Three pages out of ten sampled on 2026-09-16 were relinks: a competition
# whose host had moved, a feature page on a large NGO's site, and a country
# page on another. All three organisations were live, and reading the move as
# an ending would have retired all three.

RELINK_PENALTY = 15   # the listed page is gone, but the site it sat on is not


def host_resolves(url):
    """
    False only when the hostname genuinely does not resolve.

    A dangling CNAME looks like this: the record exists and points somewhere
    that no longer does, so a lookup succeeds with no address. Any error other
    than "no such host" is treated as unknown rather than absent, since a
    resolver problem is not evidence about the project.
    """
    host = (urlparse(url).hostname or "").strip()
    if not host:
        return None
    try:
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False
    except Exception:
        return None


def site_root(url):
    """The scheme and host of a URL, or None when it has no path of its own."""
    p = urlparse(url)
    if not p.netloc or p.path.strip("/") == "":
        return None
    return "%s://%s/" % (p.scheme or "https", p.netloc)


def probe_site(url):
    """
    What a failed fetch actually means.

    Returns (alive, archived, verdict) where verdict is one of:
      "ok"         the listed page answered
      "relink"     the page is gone but its host answers, so the link is stale
                   rather than the project being over
      "no-host"    the hostname does not resolve
      "gone"       the page failed and its host gives nothing better
      "unknown"    nothing could be determined
    """
    alive, archived, why = check_website(url)
    if alive is True:
        return True, archived, "ok"
    if alive is None:
        # A wall is worth another attempt through a browser; a timeout is not.
        return None, archived, "blocked" if why == "blocked" else "unknown"

    if host_resolves(url) is False:
        return False, archived, "no-host"

    root = site_root(url)
    if root:
        root_alive, _, _ = check_website(root)
        if root_alive is True:
            return None, archived, "relink"

    return False, archived, "gone"


class GitHubRateLimited(Exception):
    """
    GitHub refused a call because the rate limit is spent.

    Raised rather than returned so it cannot be mistaken for "this project has
    no repo". Nothing in the scoring path catches it; main() stops the run,
    leaving the current record and the rest of the batch unstamped so they come
    back round on the next run instead of being written up from a failed look.
    """

    def __init__(self, reset_at=None):
        self.reset_at = reset_at
        super().__init__(
            "GitHub rate limit exhausted"
            + (f", resets {reset_at:%H:%M:%S} UTC" if reset_at else "")
        )


def _gh_rate_limited(response):
    """
    True if this refusal is the rate limiter rather than an ordinary denial.

    A 403 also covers a private or blocked repo, which IS a real absence, so
    the status code alone is not enough. GitHub marks the primary limit with
    x-ratelimit-remaining: 0 and a secondary limit with retry-after.
    """
    if response.status_code not in (403, 429):
        return False
    if response.headers.get("x-ratelimit-remaining") == "0":
        return True
    return "retry-after" in response.headers


def _gh_limit_reset(response):
    """When the limit lifts, as a datetime, or None if GitHub didn't say."""
    reset = response.headers.get("x-ratelimit-reset")
    if reset:
        try:
            return datetime.fromtimestamp(int(reset), timezone.utc)
        except (ValueError, OverflowError):
            pass
    retry = response.headers.get("retry-after")
    if retry:
        try:
            return datetime.now(timezone.utc) + timedelta(seconds=int(retry))
        except ValueError:
            pass
    return None


def _gh_get(path, params=None):
    """
    GET a GitHub API path; returns parsed JSON, or None when there is genuinely
    nothing there. Raises GitHubRateLimited when the call was refused over the
    rate limit, which is a fact about the run and not about the project.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = requests.get(f"https://api.github.com{path}", headers=headers,
                         params=params or {}, timeout=10)
    except requests.RequestException:
        return None

    if r.status_code == 200:
        try:
            return r.json()
        except ValueError:
            return None

    # A refusal over the rate limit is not an absence of data. Returning None
    # for both would score the project as having no GitHub activity at all,
    # write that to Airtable, and exit green: an active project can drop from
    # 100/Active to 25/Possibly Inactive purely on when the run hit the ceiling.
    if _gh_rate_limited(r):
        raise GitHubRateLimited(_gh_limit_reset(r))

    return None


FUTURE_GRACE_DAYS = 1


def reject_future(dt):
    """
    Drop a date more than FUTURE_GRACE_DAYS ahead of now.

    Commit dates, RSS pubDates and social post dates are all set by whoever
    published them, so any of the three can land in the future through a wrong
    clock or a deliberate stamp. recency_base_score floors age at 0 days, so a
    future date would score the maximum forever and would also be written to
    Airtable as the last activity date. The grace day absorbs clock skew.
    """
    if dt is None:
        return None
    if (dt - datetime.now(timezone.utc)).days >= FUTURE_GRACE_DAYS:
        return None
    return dt


def _gh_dt(s):
    """Parse a GitHub ISO-8601 timestamp into a timezone-aware datetime."""
    if not s:
        return None
    try:
        return reject_future(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


_GH_MAINTAINER_ROLES = {"OWNER", "MEMBER", "COLLABORATOR"}

# How far back the issue/PR resolution rate is read. The rate has to be
# time-boxed to say anything about now: an all-time closed-to-open ratio never
# decays, so a repo that closed 900 issues between 2015 and 2020 and nothing
# since still scores as well maintained. Six months is long enough that a
# volunteer project going quiet for a summer is not read as abandoned.
ISSUE_RESOLUTION_WINDOW_DAYS = 180

# Below this many items touched inside the window there is not enough tracker
# traffic to read either way, and no adjustment is made. A live two-person
# project with three issues a year would otherwise be marked unattended for
# having nothing to close.
ISSUE_RESOLUTION_MIN_SAMPLE = 5


def _gh_issue_activity(owner, repo):
    """
    Returns (best_date, resolution).

    best_date is the most recent *maintainer* activity on issues/PRs, or None.
    Outsiders filing or commenting on issues doesn't count — a dead repo
    still accumulates those. Counts only:
      - merged PRs (merging needs write access)
      - issues/PRs authored by the owner / org members / collaborators
      - an outsider's issue closed by someone other than its author

    resolution is {"touched": n, "resolved": n} over the items updated inside
    ISSUE_RESOLUTION_WINDOW_DAYS, or None when the sample is too small to read.
    It answers a different question from best_date: not when the tracker was
    last touched, but whether what came in is being dealt with.

    Both come out of the same request, so the resolution rate costs no calls.
    """
    issues = _gh_get(f"/repos/{owner}/{repo}/issues",
                     {"state": "all", "sort": "updated", "direction": "desc", "per_page": 20})
    if not issues:
        return None, None

    window_start = datetime.now(timezone.utc) - timedelta(days=ISSUE_RESOLUTION_WINDOW_DAYS)
    touched = resolved = 0

    dates = []
    outsider_closed = []  # closed, outsider-authored: self-closed or maintainer-closed?
    for it in issues:
        merged_at = _gh_dt((it.get("pull_request") or {}).get("merged_at"))
        closed_at = _gh_dt(it.get("closed_at"))

        # Resolution rate, over the items the window can actually speak about.
        if (upd := _gh_dt(it.get("updated_at"))) and upd >= window_start:
            touched += 1
            ended = merged_at or closed_at
            if ended and ended >= window_start:
                resolved += 1

        if merged_at:
            dates.append(merged_at)
        if it.get("author_association") in _GH_MAINTAINER_ROLES:
            for key in ("created_at", "closed_at"):
                if (dt := _gh_dt(it.get(key))):
                    dates.append(dt)
        elif closed_at:
            outsider_closed.append((closed_at, it))

    # Check who closed the most recent outsider-authored issue, but only if
    # that could improve on what we already have (costs one extra API call).
    if outsider_closed:
        dt, it = max(outsider_closed, key=lambda pair: pair[0])
        if not dates or dt > max(dates):
            detail = _gh_get(f"/repos/{owner}/{repo}/issues/{it.get('number')}")
            closed_by = ((detail or {}).get("closed_by") or {}).get("login")
            author    = (it.get("user") or {}).get("login")
            if closed_by and closed_by != author:
                dates.append(dt)

    resolution = ({"touched": touched, "resolved": resolved}
                  if touched >= ISSUE_RESOLUTION_MIN_SAMPLE else None)
    return (max(dates) if dates else None), resolution


def _check_github_repo(owner, repo):
    """
    Gather activity signals for one repo. Returns a dict:
        best_date  – most recent across all signals (or None)
        archived   – repo is archived (read-only)
        dates      – {signal: datetime} for push / release / commit / issue_pr
        resolution – recent issue/PR resolution counts, or None
    or None if the repo can't be fetched.
    """
    info = _gh_get(f"/repos/{owner}/{repo}")
    if info is None:
        return None

    dates = {}
    if (dt := _gh_dt(info.get("pushed_at"))):
        dates["push"] = dt

    rel = _gh_get(f"/repos/{owner}/{repo}/releases/latest")
    if rel and (dt := _gh_dt(rel.get("published_at"))):
        dates["release"] = dt

    commits = _gh_get(f"/repos/{owner}/{repo}/commits", {"per_page": 1})
    if commits:
        commit_date = (commits[0].get("commit", {}).get("committer") or {}).get("date")
        if (dt := _gh_dt(commit_date)):
            dates["commit"] = dt

    # Issue/PR activity, restricted to signals of maintainer involvement
    issue_date, resolution = _gh_issue_activity(owner, repo)
    if issue_date:
        dates["issue_pr"] = issue_date

    return {
        "best_date":  max(dates.values()) if dates else None,
        "archived":   bool(info.get("archived")),
        "dates":      dates,
        "resolution": resolution,
    }


def check_github(url):
    """
    GitHub activity signals: pushes, releases, commits, issue/PR activity,
    and archived status. Handles repo URLs (github.com/org/repo) and org/user
    profile URLs (checked via their most recently pushed repo).
    Returns the dict from _check_github_repo, or None.
    """
    if not url:
        return None

    parsed = urlparse(url)
    if "github.com" not in parsed.netloc:
        return None

    parts = [p for p in parsed.path.strip("/").split("/") if p]

    if len(parts) >= 2:
        return _check_github_repo(parts[0], re.sub(r"\.git$", "", parts[1]))

    if len(parts) == 1:
        owner = parts[0]
        for entity in ("orgs", "users"):
            repos = _gh_get(f"/{entity}/{owner}/repos",
                            {"sort": "pushed", "per_page": 1})
            if repos:
                name = repos[0].get("name")
                if name:
                    return _check_github_repo(owner, name)
                break

    return None


def check_blog_feed(url):
    """Returns most recent post date as a timezone-aware datetime, or None."""
    return _parse_feed_latest(url) if url else None


def latest_blog_date(stored_feeds, website_url, url_class):
    """
    The newest post date across a project's feeds, or None.

    A stored feed is tried first. When nothing is stored, the homepage is
    searched for one. A stored feed that yields no date is searched from as
    well, because the field often holds the blog's own HTML page rather than
    its feed: /blog/ parses to no entries, and before this the stored value
    stopped discovery from running at all, so a WordPress site advertising a
    feed on every page scored as having no blog.
    """
    stored = list(filter(None, stored_feeds or []))
    feeds  = list(stored)
    if not feeds and website_url and url_class == "homepage":
        auto_feed = discover_feed_url(website_url)
        if auto_feed:
            _log(f"    blog     → auto-discovered feed: {auto_feed}")
            feeds = [auto_feed]

    def newest(urls, best):
        for feed_url in urls:
            d = reject_future(check_blog_feed(feed_url))
            if d and (best is None or d > best):
                best = d
        return best

    blog_date = newest(feeds, None)
    if blog_date is None and stored:
        tried = set(feeds)
        pages = stored + ([website_url] if website_url and url_class == "homepage" else [])
        for page in pages:
            found = discover_feed_url(page)
            if found and found not in tried:
                tried.add(found)
                _log(f"    blog     → stored feed gave no date; found {found}")
                blog_date = newest([found], blog_date)
    return blog_date


def check_url_alive(url):
    """Quick HEAD check. Returns True / False / None (error)."""
    if not url:
        return None
    try:
        r = SESSION.head(url, timeout=5, allow_redirects=True)
        return 200 <= r.status_code < 400
    except Exception:
        return None


def discover_feed_url(website_url):
    """
    Try to find an RSS/Atom feed URL for a site when none is explicitly stored.
    1. Fetch homepage and look for <link rel="alternate" type="application/rss+xml|atom+xml">
    2. Try common feed paths (/feed, /rss, /feed.xml, etc.)
    Returns a feed URL string or None.
    """
    if not website_url:
        return None
    parsed = urlparse(website_url)
    base   = f"{parsed.scheme}://{parsed.netloc}"

    # Step 1: autodiscovery link tag in homepage HTML
    try:
        r = get_limited(website_url)
        if r.status_code == 200:
            # Match <link ... type="application/rss+xml" ... href="..."> in either attribute order
            for pattern in (
                re.compile(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']', re.I),
                re.compile(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\']', re.I),
            ):
                m = pattern.search(r.text)
                if m:
                    href = m.group(1)
                    return href if href.startswith("http") else base + (href if href.startswith("/") else "/" + href)
    except Exception:
        pass

    # Step 2: try common feed paths
    for path in ("/feed", "/rss", "/feed.xml", "/atom.xml", "/rss.xml", "/blog/feed"):
        try:
            url = base + path
            r   = get_limited(url, timeout=8)
            ct  = r.headers.get("content-type", "")
            if r.status_code == 200 and any(s in ct for s in ("xml", "rss", "atom")):
                return url
        except Exception:
            continue

    # Step 3: feedparser fallback for /feed and /rss — handles platforms like
    # Substack where the page is JS-rendered (no autodiscovery link) and the
    # feed endpoint may not return an XML content-type header.
    for path in ("/feed", "/rss"):
        try:
            url = base + path
            r   = get_limited(url, timeout=8)
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
                if feed.entries:
                    return url
        except Exception:
            continue

    return None


def discover_social_links(website_url):
    """
    Fetch website homepage and extract social media profile links.
    Returns a list of URL strings, one per domain (de-duplicated).
    """
    if not website_url:
        return []
    try:
        html, _ = get_page_cached(website_url)
        if not html:
            return []
        parser = _LinkExtractor()
        parser.feed(html)
        found = {}
        for href, _ in parser.links:
            if not href.startswith("http"):
                continue
            netloc = urlparse(href).netloc.lower().lstrip("www.")
            if netloc in _SOCIAL_DOMAINS and netloc not in found:
                found[netloc] = href
        return list(found.values())
    except Exception:
        return []




# ── Social recency checkers ───────────────────────────────────────────────────

def _parse_feed_latest(url, extra_headers=None):
    """Fetch a feed URL and return the most recent entry datetime, or None."""
    try:
        headers = dict(extra_headers) if extra_headers else None
        r = get_limited(url, headers=headers)
        if r.status_code != 200:
            return None
        feed   = feedparser.parse(r.content)
        latest = None
        for entry in feed.entries:
            for attr in ("published_parsed", "updated_parsed"):
                t = getattr(entry, attr, None)
                if t:
                    dt = datetime(*t[:6], tzinfo=timezone.utc)
                    if latest is None or dt > latest:
                        latest = dt
        # Fall back to channel-level date (lastBuildDate / updated) if no entry dates
        if latest is None:
            for attr in ("updated_parsed", "published_parsed"):
                t = getattr(feed.feed, attr, None)
                if t:
                    latest = datetime(*t[:6], tzinfo=timezone.utc)
                    break
        return latest
    except Exception:
        return None


def _check_youtube(parsed):
    """Return most recent video date from a YouTube channel, or None."""
    if not YOUTUBE_API_KEY:
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return None

    try:
        # Determine how to look up the channel
        if parts[0] == "channel" and len(parts) >= 2:
            chan_params = {"id": parts[1], "part": "contentDetails", "key": YOUTUBE_API_KEY}
        elif parts[0].startswith("@"):
            chan_params = {"forHandle": parts[0][1:], "part": "contentDetails", "key": YOUTUBE_API_KEY}
        elif parts[0] in ("c", "user") and len(parts) >= 2:
            chan_params = {"forUsername": parts[1], "part": "contentDetails", "key": YOUTUBE_API_KEY}
        else:
            return None

        r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                         params=chan_params, timeout=10)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None

        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        r2 = requests.get("https://www.googleapis.com/youtube/v3/playlistItems",
                          params={"playlistId": uploads_id, "part": "snippet",
                                  "maxResults": 1, "key": YOUTUBE_API_KEY},
                          timeout=10)
        if r2.status_code != 200:
            return None
        items2 = r2.json().get("items", [])
        if not items2:
            return None
        pub = items2[0]["snippet"].get("publishedAt")
        if pub:
            return datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _check_bluesky(path):
    """Return most recent post date from a Bluesky profile, or None."""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2 or parts[0] != "profile":
        return None
    actor = parts[1]
    try:
        r = requests.get(
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            params={"actor": actor, "limit": 1},
            timeout=10,
        )
        if r.status_code == 200:
            feed = r.json().get("feed", [])
            if feed:
                indexed_at = feed[0].get("post", {}).get("indexedAt")
                if indexed_at:
                    return datetime.fromisoformat(indexed_at.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _check_medium(url, parsed):
    """Return most recent post date from a Medium profile/publication, or None."""
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if parts and parts[0].startswith("@"):
        feed_url = f"https://medium.com/feed/{parts[0]}"
    elif parsed.netloc != "medium.com":
        feed_url = f"{parsed.scheme}://{parsed.netloc}/feed"
    else:
        feed_url = f"https://medium.com/feed/{parsed.path.strip('/')}"
    return _parse_feed_latest(feed_url)


def _check_reddit(parsed):
    """Return most recent post date from a Reddit subreddit or user page, or None."""
    clean_path = parsed.path.rstrip("/")
    feed_url   = f"https://www.reddit.com{clean_path}.rss"
    return _parse_feed_latest(feed_url)


def _check_substack(parsed):
    """Return most recent post date from a Substack newsletter, or None."""
    feed_url = f"{parsed.scheme}://{parsed.netloc}/feed"
    return _parse_feed_latest(feed_url)


def _check_fediverse(url):
    """Return most recent post date from a Mastodon/fediverse profile, or None."""
    feed_url = url.rstrip("/") + ".rss"
    return _parse_feed_latest(feed_url)


# Domains where we know RSS / API isn't available (check alive only)
_NO_DATE_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "linkedin.com", "tiktok.com", "signal.org",
}

# Regex for fediverse-style /@username paths
_FEDIVERSE_PATH = re.compile(r"/+@[^/]+/?$")


def check_social_recency(url):
    """
    Try to retrieve the most recent post date from a social URL.
    Returns (datetime | None, platform_label: str | None).
    """
    if not url:
        return None, None

    parsed = urlparse(url)
    netloc = parsed.netloc.lower().lstrip("www.")

    if "youtube.com" in netloc or "youtu.be" in netloc:
        return _check_youtube(parsed), "YouTube"

    if "bsky.app" in netloc:
        return _check_bluesky(parsed.path), "Bluesky"

    if "medium.com" in netloc or netloc.endswith(".medium.com"):
        return _check_medium(url, parsed), "Medium"

    if "reddit.com" in netloc:
        return _check_reddit(parsed), "Reddit"

    if "substack.com" in netloc:
        return _check_substack(parsed), "Substack"

    # Fediverse: any /@username URL on a domain not in the known-no-date list
    if netloc not in _NO_DATE_DOMAINS and _FEDIVERSE_PATH.search(parsed.path):
        return _check_fediverse(url), "Fediverse"

    return None, None


# ── Scoring ───────────────────────────────────────────────────────────────────

# A social page that loads says nothing about whether anything was posted to it,
# so reachability is weak evidence and is capped to a nudge. At 10 points per
# link up to three it was worth +30, enough to carry a listing with no dated
# signal anywhere past a threshold: a live homepage and three loading social
# pages scored 45 and read Likely Active on nothing but pages existing. Posting
# recency is scored separately by social_recency_score(), which is unaffected.
SOCIAL_REACHABLE_BONUS_MAX = 10

# A listing added to the directory recently, with the launch field filled in, is
# very likely still running whatever dated signals exist for it. Treated as a
# floor rather than a cap: real measured evidence above this still wins.
RECENT_LAUNCH_DAYS  = 274   # ~9 months
RECENT_LAUNCH_SCORE = 60    # lands in the "Likely Active" band

# A live homepage is only evidence of current work alongside something dated and
# recent. A site that loads while the newest signal is over a year old earns the
# reduced bonus: enough to keep the listing off the dead-site penalty, not enough
# to carry stale work upward. Abre Alcaldias read 100/Active off a 698-day-old
# blog post plus a live site, because 55 + 15 lands exactly on the Active line.
# What a footer copyright naming this year or last is worth. A floor rather than
# a bonus: added to a score it would stack on top of stale evidence and lift a
# project whose last real output was years ago into Active, which is the
# opposite of what the copyright is being read for. As a floor it decides only
# the case it is evidence about — a site being kept up with nothing dated on it
# — and never overrules a dated signal that scored higher on its own.
COPYRIGHT_FRESH_FLOOR     = 45   # the foot of the "Likely Active" band
# Below this, a Last-Modified header is the server's clock rather than the age
# of anything on the page.
LAST_MODIFIED_MIN_AGE_DAYS = 2
# Under this many characters of readable text, a page that answered is a
# JavaScript shell rather than a page. CTFG-curator uses the same threshold in
# maybeRenderThinPage() before it re-reads the page through a browser.
MIN_READABLE_PAGE_CHARS = 200
# How long to wait before re-checking a site that failed, when the failure is
# about to be written as a permanent verdict.
RECHECK_PAUSE_S = 5
# What a listing scores once its own page says it has finished. Matches the cap
# an archive snapshot gets: both are the page telling us the thing is over.
CLOSED_CAP = 10

# Where the finding came from is part of the finding. A wording match is a rule
# anyone can check; a reading is a judgement, and the breakdown says which one
# this was, so a project that disagrees knows exactly what to take up. Written
# here as one sentence with two openings because the same breakdown line is
# rebuilt when a reading is accepted hours later, and two copies of this
# wording would drift.
CLOSURE_SOURCE_WORDING = "The project's own page says"
CLOSURE_SOURCE_READING = "A reading of the project's own page finds"


def closure_sentence(source, phrase, capped=""):
    """The breakdown line for a page that says the thing it describes is over."""
    # The sentence supplies the quotation marks, so a phrase that arrives
    # already quoted must not bring its own. A reading often quotes the page
    # itself, and nesting the two produced a breakdown that opened on a double
    # quote mark and read as a typo to anyone looking at the profile page.
    phrase = re.sub(r'^[\s"\u201c\u201d\u00ab\u00bb\u2018\u2019]+|'
                    r'[\s"\u201c\u201d\u00ab\u00bb\u2018\u2019]+$', "", str(phrase or ""))
    phrase = phrase.replace('"', "\u201d")
    return ('%s it has finished ("%s"), so it is not scored on how recently '
            'that page changed%s' % (source, phrase, capped))


WEBSITE_ALIVE_BONUS       = 15
WEBSITE_ALIVE_BONUS_STALE = 5
WEBSITE_BONUS_FRESH_DAYS  = 365


# Whether the issue tracker is being worked, as a tiebreaker on the dated
# signals rather than a score of its own. Worth 5 points and no more, for two
# reasons: it correlates with the issue_pr date that may already have set the
# base score, and it can be inflated without anyone meaning to, by a stale bot
# closing everything untouched for 60 days. Telling a bot's closure from a
# maintainer's costs one API call per issue, which a 200-record batch cannot
# afford, so that false positive is priced in at 5 points instead of chased.
ISSUE_RESOLUTION_BONUS      = 5
ISSUE_RESOLUTION_PENALTY    = 5
ISSUE_RESOLUTION_GOOD_RATIO = 0.5


def issue_resolution_adjustment(resolution):
    """
    Points for how much of the recent issue/PR traffic got resolved, as
    (points, label for the breakdown), for _adjustment() to render. (0, None)
    when there is nothing worth saying: too small a sample, or a middling rate.

    Only a tracker with traffic and nothing closed is penalised. A backlog of
    old issues left open is not evidence of anything on its own, since a
    maintained project that triages carefully carries one and a project that
    runs a stale bot does not.
    """
    if not resolution:
        return 0, None

    touched, resolved = resolution["touched"], resolution["resolved"]
    window = f"{ISSUE_RESOLUTION_WINDOW_DAYS // 30} months"

    if resolved == 0:
        return -ISSUE_RESOLUTION_PENALTY, (
            f"None of the {touched} issues and pull requests active in the last "
            f"{window} were closed")

    if resolved / touched >= ISSUE_RESOLUTION_GOOD_RATIO:
        return ISSUE_RESOLUTION_BONUS, (
            f"{resolved} of the {touched} issues and pull requests active in the "
            f"last {window} were closed or merged")

    return 0, None


# Wording for the public score breakdown. The scorer keeps GitHub sub-signals
# apart because they mean different things to a reader: a release is a decision
# to ship, a push is only that somebody touched the repo.
GH_SIGNAL_LABELS = {
    "push":     "GitHub push",
    "release":  "GitHub release",
    "commit":   "GitHub commit",
    "issue_pr": "GitHub issue and pull request activity",
}


def describe_age(dt, now):
    """Age of a signal in words, for the breakdown shown on the profile page."""
    days = max(0, (now - dt).days)
    if days == 0:  return "today"
    if days == 1:  return "yesterday"
    if days < 60:  return f"{days} days ago"
    if days < 365: return f"{min(11, round(days / 30.44))} months ago"
    years = max(1, round(days / 365.25))
    return f"{years} year{'' if years == 1 else 's'} ago"


def _adjustment(label, nominal, applied):
    """
    One breakdown line, reporting the points actually applied rather than the
    points the rule nominally offers. The two differ whenever the 100 ceiling or
    the 0 floor bites, and a public breakdown whose figures do not add up to its
    own total is worse than no breakdown at all.
    """
    if applied == nominal:
        return f"{label} ({applied:+g})"
    limit = "above 100" if nominal > 0 else "below 0"
    if applied == 0:
        return f"{label} (no change, the score cannot go {limit})"
    return f"{label} ({applied:+g}, because the score cannot go {limit})"


# Types that mean something is still running, whatever else sits on the record.
# Legislation is here on purpose: a law is in force or it is repealed, so it
# takes Active or Inactive like anything else rather than N/A.
ONGOING_TYPES = {
    "project", "organization", "tool or platform", "campaign", "media", "event",
    "network", "program", "space", "publication", "database", "course", "game",
    "legislation",
}


def is_finished_work(project):
    """
    True when this is a finished piece of work rather than something that runs.

    A book or a report does not go stale, so asking how recently it moved is
    the wrong question and the answer is N/A rather than a low score.

    A finished piece of work is only finished when nothing ongoing sits beside
    it. Something typed both Organization and Document is an organization that
    published something, and the organization is still there. Without this the
    rule reads the document and retires the organization.
    """
    names = [str(t).strip().lower() for t in (project.types or [])]
    if any(n in ONGOING_TYPES for n in names):
        return False
    if any("document" in n for n in names):
        return True
    return any(str(f).strip().lower() == "books" for f in (project.formats or []))


def recently_launched(project, now):
    """
    True when the listing was added in the last RECENT_LAUNCH_DAYS and carries
    anything in the "New launch?" field.

    Distinct from the is_excluded() launch rule, which drops a record from
    scoring entirely and needs both an "x" and a launch date in the current
    year. This is deliberately looser: any non-empty value plus a recent
    createdTime is evidence the project is still there, and evidence is what
    the undated case is short of.
    """
    if not str(project.launch_flag or "").strip():
        return False
    created = project.added
    if not created:
        return False
    try:
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days <= RECENT_LAUNCH_DAYS


# ── What the page says about itself ───────────────────────────────────────────
#
# Until now the only dated signals were GitHub, a blog feed and social posts, so
# a project with a plain website could not produce a date however plainly the
# page stated one. check_website() fetched the page and kept only alive/dead.
#
# _decode_entities, _clean, meta_content and readable_page are ports of
# CTFG-curator lib/page-fetch.mjs, which already solved the two awkward parts:
# reading a <meta> whichever order its attributes come in, and isolating
# <footer>/<address> from the body. The footer split is what makes a copyright
# line readable — as CTFG-curator's own project-status.mjs puts it, "a year
# anywhere in the page text is the copyright line as often as it is the date of
# the thing", so the year is only trusted where copyright lines actually live.

_NAMED_ENTITIES = {"lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
                   "copy": "\u00a9", "reg": "\u00ae", "mdash": "\u2014",
                   "ndash": "\u2013", "rsquo": "\u2019", "lsquo": "\u2018"}


def _decode_entities(s):
    s = str(s or "")
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), s)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    for name, ch in _NAMED_ENTITIES.items():
        s = s.replace("&%s;" % name, ch)
    return s.replace("&amp;", "&")   # last, so &amp;#39; does not double-decode


def _clean(s):
    return re.sub(r"\s+", " ", _decode_entities(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def meta_content(html, prop):
    """A <meta> content value by property or name, either attribute order."""
    for pattern in (r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']*)["\']',
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']%s["\']'):
        m = re.search(pattern % re.escape(prop), html, re.I)
        if m and m.group(1).strip():
            return _decode_entities(m.group(1).strip())
    return None


def readable_page(html, text_cap=12000, footer_cap=800):
    """Strip a page to its own words, keeping the footer separate."""
    stripped = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    stripped = re.sub(r"<style[\s\S]*?</style>", " ", stripped, flags=re.I)
    stripped = re.sub(r"<!--[\s\S]*?-->", " ", stripped)
    stripped = re.sub(r"<nav\b[\s\S]*?</nav>", " ", stripped, flags=re.I)
    footer = "\n".join(
        _clean(m.group(1))
        for m in re.finditer(r"<(?:footer|address)[^>]*>([\s\S]*?)</(?:footer|address)>",
                             stripped, re.I)
    )[:footer_cap]
    return {"footer": footer or None, "text": _clean(stripped)[:text_cap]}


# Month names in the languages this directory actually meets. A date is a
# recency signal whatever language the page is written in, and reading only
# English ones meant a federal ministry publishing several times a week and a
# département running a 2026 budget consultation were both recorded as pages
# with no date on them at all.
#
# West and South Slavic month names are deliberately absent. They collide
# across languages in the one way that matters: "listopad" is November in
# Polish and October in Croatian, "srpanj" is July in Croatian while Czech
# "srpen" is August, and nothing on the page says which language it is. Finding
# no date is a safe answer and is already handled everywhere downstream. A date
# eleven months out is not, because it is indistinguishable from a real one.
_MONTH_NAMES = {
    1:  "January enero janeiro janvier Januar Jänner gennaio januari januar "
        "tammikuu Ocak ianuarie gener",
    2:  "February febrero fevereiro février Februar febbraio februari februar "
        "helmikuu Şubat februarie febrer",
    3:  "March marzo março mars März marzo maart mars marts maaliskuu Mart "
        "martie març",
    4:  "April abril avril aprile april huhtikuu Nisan aprilie",
    5:  "May mayo maio mai Mai maggio mei maj toukokuu Mayıs mayis maig",
    6:  "June junio junho juin Juni giugno juni kesäkuu Haziran iunie juny",
    7:  "July julio julho juillet Juli luglio juli heinäkuu Temmuz iulie juliol",
    8:  "August agosto agosto août August agosto augustus augusti elokuu "
        "Ağustos august agost",
    9:  "September septiembre setiembre setembro septembre September settembre "
        "syyskuu Eylül septembrie setembre",
    10: "October octubre outubro octobre Oktober ottobre oktober lokakuu Ekim "
        "octombrie octubre",
    11: "November noviembre novembro novembre November novembre marraskuu "
        "Kasım kasim noiembrie novembre",
    12: "December diciembre dezembro décembre Dezember dicembre december "
        "desember joulukuu Aralık aralik decembrie desembre",
}

_MONTHS = {}
for _i, _names in _MONTH_NAMES.items():
    for _n in _names.split():
        _MONTHS[_n.lower()] = _i

# Three-letter forms, generated rather than listed, then any that two different
# months both claim is dropped. French "juin" and "juillet" both shorten to
# "jui", and Finnish "marraskuu" collides with every language's March; keeping
# either would turn a date the page states plainly into a wrong one.
_prefixes = {}
for _n, _i in _MONTHS.items():
    if len(_n) > 3:
        _prefixes.setdefault(_n[:3], set()).add(_i)
for _p, _months in _prefixes.items():
    if len(_months) == 1 and _p not in _MONTHS:
        _MONTHS[_p] = next(iter(_months))

# English abbreviations put back by hand, because the rule above drops "mar" to
# protect against Finnish "marraskuu" and "Mar" is the single most common
# abbreviation on the web. No Finnish page writes November as "mar"; Finnish
# abbreviates its months as numbers.
for _abbr, _i in {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                  "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
                  "nov": 11, "dec": 12}.items():
    _MONTHS[_abbr] = _i

# A wrong month is worse than no month, so the table is checked at import rather
# than trusted. Anything that would resolve two ways is a bug in the lists above.
assert len(_MONTHS) == len(set(_MONTHS)), "duplicate month key"

# Any Unicode letter, so "février", "März" and "Ağustos" are month names rather
# than gibberish. [A-Za-z] silently truncated every accented name to the run of
# plain letters inside it.
_L = r"[^\W\d_]"

# The day, with whatever a language puts after it: a dot in German and Finnish,
# an ordinal suffix in English, "er" in French, a masculine ordinal in Iberian
# and Italian writing.
_DAY = r"(\d{1,2})(?:\.|st|nd|rd|th|er|º|°|ª)?"
# "16 de septiembre de 2026", "16 di settembre", "16th of March".
_OF = r"(?:\s+(?:de|di|of|d'))?"


def _parse_date_loose(raw, now):
    """
    A date from any of the shapes a page states one in, or None.

    Rejects anything in the future or before 2000: a page carrying a 1970 epoch
    stamp or a 2031 copyright is stating a template default, not activity.
    """
    s = _clean(raw)[:60]
    if not s:
        return None

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)                       # ISO
    if m:
        y, mo, d = (int(g) for g in m.groups())
    else:
        # 20 March 2026 / 16. September 2026 / 16 de septiembre de 2026
        m = re.search(r"%s%s\s+(%s{3,12})\.?%s\s+(\d{4})" % (_DAY, _OF, _L, _OF), s, re.U)
        if m and m.group(2).lower() in _MONTHS:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        else:
            m = re.search(r"(%s{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})" % _L, s, re.U)  # March 20, 2026
            if m and m.group(1).lower() in _MONTHS:
                mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
            else:
                parsed = _parse_numeric_date(s)
                if not parsed:
                    return None
                y, mo, d = parsed
    try:
        dt = datetime(y, mo, d, tzinfo=timezone.utc)
    except ValueError:
        return None
    if dt > now + timedelta(days=1) or dt.year < 2000:
        return None
    return dt


def _parse_numeric_date(s):
    """
    (y, m, d) from an all-digits date, or None when the order cannot be known.

    16.09.2026 is read as day first. The dot form is European convention and is
    not written the American way round, so it is safe to read on sight.

    16/09/2026 is not. The slash form is day-first across most of the world and
    month-first in the United States, and 05/06/2026 is a real date in both
    readings, eleven months of error apart. So it is read only when one of the
    first two numbers is over 12 and can therefore only be a day. An ambiguous
    one returns None, which leaves the listing exactly where it would have been
    before any of this existed.
    """
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", s)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        return (y, mo, d) if 1 <= mo <= 12 else None

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", s)
    if m:
        a, b, y = (int(g) for g in m.groups())
        if a > 12 and 1 <= b <= 12:
            return (y, b, a)          # first number cannot be a month
        if b > 12 and 1 <= a <= 12:
            return (y, a, b)          # second cannot be, so the first is
        return None                   # both under 13: unknowable, so not read
    return None


# Where a page states its own date, best evidence first.
_META_DATE_PROPS = ["article:modified_time", "og:updated_time", "article:published_time",
                    "dateModified", "datePublished", "last-modified", "DC.date", "date"]

# The words a page puts in front of its own date, in the languages above. The
# capture is a lookahead so the match itself ends at the keyword. A page that
# prints "Published: 6 January 2026 Last updated: 20 March 2026" as two stacked
# lines collapses to one line of text once the tags are stripped, and a
# consuming capture swallowed the second label with the first date, reporting
# the older of the two as the page's date.
#
# Longest first, so "last updated" is not matched as "updated" and "última
# atualização" is not matched as "atualizado".
_DATE_LABELS = "|".join([
    r"last\s+updated", r"last\s+modified", r"updated\s+on", r"published\s+on",
    r"published", r"posted", r"updated",
    r"zuletzt\s+aktualisiert", r"veröffentlicht\s+am", r"aktualisiert\s+am",
    r"geändert\s+am", r"veröffentlicht", r"aktualisiert",
    r"derni[èe]re\s+mise\s+[àa]\s+jour", r"mis\s+[àa]\s+jour\s+le",
    r"mis\s+[àa]\s+jour", r"publi[ée]\s+le", r"modifi[ée]\s+le",
    r"[úu]ltima\s+actualizaci[óo]n", r"actualizado\s+el", r"publicado\s+el",
    r"modificado\s+el", r"actualizado", r"publicado",
    r"[úu]ltima\s+atualiza[çc][ãa]o", r"atualizado\s+em", r"publicado\s+em",
    r"ultimo\s+aggiornamento", r"aggiornato\s+il", r"pubblicato\s+il",
    r"laatst\s+bijgewerkt", r"bijgewerkt\s+op", r"gepubliceerd\s+op",
    r"senast\s+uppdaterad", r"uppdaterad", r"publicerad",
    r"sist\s+oppdatert", r"oppdatert", r"publisert",
    r"senest\s+opdateret", r"opdateret", r"offentliggjort",
    r"p[äa]ivitetty", r"julkaistu",
    r"son\s+g[üu]ncelleme", r"g[üu]ncellendi", r"yay[ıi]nland[ıi]",
    r"ultima\s+actualizare", r"actualizat", r"publicat",
])

_TEXT_DATE_RE = re.compile(
    r"(%s)\s*[:\-–]?\s*(?=([0-9%s][^<\n|·•]{5,32}))" % (_DATE_LABELS, _L[1:-1]),
    re.I | re.U)


def page_date_signals(html, headers, now, text=None):
    """
    Every date the page states about itself, as (datetime, label) pairs.

    `text` replaces the page's own words when they only exist after rendering.
    The markup sources above it still read the static html, which is where
    meta tags and ld+json live whether or not the body was painted by script.
    """
    out = []

    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
                            html, re.I)[:5]:
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        stack, seen = [data], 0
        while stack and seen < 200:
            node = stack.pop()
            seen += 1
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                for key in ("dateModified", "datePublished"):
                    dt = _parse_date_loose(node.get(key), now)
                    if dt:
                        out.append((dt, "the page's own %s" % key))
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))

    for prop in _META_DATE_PROPS:
        dt = _parse_date_loose(meta_content(html, prop), now)
        if dt:
            out.append((dt, "the page's %s tag" % prop))

    for raw in re.findall(r'<time[^>]+datetime=["\']([^"\']+)["\']', html, re.I)[:20]:
        dt = _parse_date_loose(raw, now)
        if dt:
            out.append((dt, "a date marked up on the page"))

    words = text if text is not None else readable_page(html)["text"]
    for m in _TEXT_DATE_RE.finditer(words[:4000]):
        dt = _parse_date_loose(m.group(2), now)
        if dt:
            out.append((dt, 'the page\'s "%s" line' % _clean(m.group(1)).lower()))

    # Last-Modified, but only when it is not simply the server's clock. A page
    # generated per request carries the time of the request, so a page can
    # answer with the current second and score as though the project had been
    # worked on that day. A real static mtime is days or months old; a stamp
    # inside LAST_MODIFIED_MIN_AGE_DAYS says nothing about the content, so it is
    # dropped rather than believed.
    dt = _parse_date_loose((headers or {}).get("Last-Modified"), now)
    if dt and (now - dt).days >= LAST_MODIFIED_MIN_AGE_DAYS:
        out.append((dt, "the server's Last-Modified header"))

    return out


# ── The project's own news, blog and events pages ────────────────────────────
#
# A homepage often carries no date at all while the page one click away lists
# every post with its date. Reading only the homepage and a feed missed those:
# a WordPress lab whose blog stopped in 2020 scored Likely Active on a footer
# copyright year, because the blog page itself was never opened. So the links a
# homepage gives to its own news, blog, updates and events pages are followed,
# a few of them, and the newest date listed there is a signal like a blog post.

# Path segments and anchor words that name a page of dated items, across the
# languages the directory covers. Matched against the last path segment or the
# anchor text, whole-word, case-insensitively.
_NEWS_WORDS = (
    r"blog|blogs|news|updates|press|newsroom|stories|articles|posts|"
    r"events|event|calendar|announcements|"
    r"noticias|novedades|prensa|eventos|agenda|actualidad|"
    r"not[íi]cias|novidades|imprensa|"
    r"actualit[ée]s|nouvelles|[ée]v[ée]nements|"
    r"nachrichten|neuigkeiten|aktuelles|veranstaltungen|termine|"
    r"notizie|eventi|nieuws|evenementen|nyheter|uutiset|haberler|"
    r"berita|kegiatan|acara|artikel|habari|matukio|"
    r"新闻|消息|活动|動態|お知らせ|ニュース|イベント|活動報告|소식|뉴스|행사"
)
_NEWS_RE = re.compile(r"(?:^|[\W_])(?:%s)(?:$|[\W_])" % _NEWS_WORDS, re.I | re.U)

# Pages followed per record. Each costs one fetch inside the per-record time
# budget, and the first two nearly always include the one that matters.
NEWS_PAGES_MAX = 2

# Distinct dates a page has to list before it counts as a page of dated items.
NEWS_MIN_DATES = 2

# A date with a day, a month name and a year, standing on its own in the text:
# "October 7, 2020", "7 October 2020", "7 de octubre de 2020". An index page
# lists its items like this without a label in front, which is exactly what
# page_date_signals does not read, since on an ordinary page an unlabelled date
# is as likely to be a founding date as a post. On a page of dated items the
# newest one is the signal; an old founding date loses to it by construction.
_BARE_DATE_RE = re.compile(
    r"(?:%s%s\s+%s{3,12}\.?%s\s+\d{4})|(?:%s{3,12}\.?\s+\d{1,2},?\s+\d{4})"
    % (r"\d{1,2}", r"(?:\.|\s+de|\s+of)?", r"[^\W\d_]", r"(?:\s+de)?", r"[^\W\d_]"),
    re.U)


def find_news_pages(html, base_url, limit=NEWS_PAGES_MAX):
    """
    Links on the homepage to the site's own news, blog or events pages.

    Same host only: a link out to Medium is a feed or a social account, and is
    already handled as one. Blog and news are preferred to events, since an
    events page can list an annual meeting that says little about the rest.
    """
    if not html:
        return []
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []
    found = {}
    for href, text in parser.links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower().removeprefix("www.") != host:
            continue
        if re.search(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|svg|mp[34])$", parsed.path, re.I):
            continue
        last = [seg for seg in parsed.path.split("/") if seg][-1:] or [""]
        # Anchor text only counts when it is short. A long anchor is usually
        # the organization's own name ("Te Hiku Media", "Kloop News Agency")
        # linking to its About page, which lists a founding date, not posts.
        short_text = text if text and len(text.split()) <= 3 else ""
        if not (_NEWS_RE.search(last[0]) or _NEWS_RE.search(short_text)):
            continue
        if url.rstrip("/") == base_url.rstrip("/") or url in found:
            continue
        events = bool(re.search(r"event|agenda|calendar|evento|[ée]v[ée]nement|veranstaltung|termine|acara|イベント|活动|행사", url + " " + (text or ""), re.I))
        found[url] = 1 if events else 0
    return sorted(found, key=lambda u: found[u])[:limit]


def news_page_dates(url, now):
    """(datetime, label) pairs for the dated items one news or events page lists."""
    html, headers = get_page_cached(url)
    if not html:
        return []
    out = [(dt, lbl) for dt, lbl in page_date_signals(html, headers, now)
           if lbl != "the server's Last-Modified header"]
    words = readable_page(html)["text"]
    for raw in _BARE_DATE_RE.findall(words[:12000]):
        dt = _parse_date_loose(raw, now)
        # Today's date, unlabelled, is a header widget far more often than a
        # post: news templates print the current date above the masthead, and
        # believing it would score every such site as updated this morning.
        if dt and (now - dt).days >= 2:
            out.append((dt, "a dated item"))
    out = [(dt, lbl) for dt, lbl in out if reject_future(dt)]
    # A page of dated items lists more than one. A single date is an About
    # page's founding year or one article's byline, and on its own it is too
    # thin to say when the project was last active.
    if len({dt.date() for dt, _ in out}) < NEWS_MIN_DATES:
        return []
    return out


def latest_news_date(html, base_url, now):
    """The newest date on the site's own news, blog or events pages, and where."""
    best = None
    for url in find_news_pages(html, base_url):
        dates = news_page_dates(url, now)
        if dates:
            dt = max(d for d, _ in dates)
            _log(f"    news     → {url}: newest item {dt:%Y-%m-%d}")
            if best is None or dt > best[0]:
                best = (dt, url)
        else:
            _log(f"    news     → {url}: nothing dated")
    return best


def footer_copyright_year(html):
    """
    The newest year in a copyright line in the footer, or None.

    Only the footer, and only next to a copyright mark. A bare year in body text
    is as likely to be a citation as a sign of life, and this is weak enough
    evidence already.
    """
    footer = (readable_page(html) or {}).get("footer")
    if not footer:
        return None
    years = []
    for m in re.finditer(r"(?:©|\(c\)|copyright)[^0-9]{0,20}((?:19|20)\d{2})"
                         r"(?:\s*[-–—]\s*((?:19|20)\d{2}))?", footer, re.I):
        years.extend(int(g) for g in m.groups() if g)
    return max(years) if years else None


# ── Reading a page that builds itself in the browser ──────────────────────────
#
# Roughly a tenth of reachable project sites serve a shell to a plain fetch and
# paint everything that matters after the JavaScript runs — including, on one
# consultation, the notice that it had closed months earlier. Those pages are
# re-read through a real browser, and only those: rendering every page would
# multiply the run for no gain on the nine in ten that are already readable.
#
# Ported from CTFG-curator server.js (renderPageText / maybeRenderThinPage),
# including the resource blocking, the bounded networkidle wait and the settle
# afterwards. Everything here fails soft: no Playwright, no browser, a crash
# mid-render — all return None and leave the listing recorded as unread, which
# is what it was before this existed.

RENDER_THIN_PAGES = os.environ.get("RENDER_THIN_PAGES", "1") != "0"
RENDER_GOTO_MS    = 15_000
RENDER_SETTLE_MS  = 2_500
RENDER_TEXT_CAP   = 12_000

# Headless Chromium says so in its own User-Agent, and a great many WAFs refuse
# on that string alone. Measured on 20 sites that each returned 403 to a plain
# fetch: with Playwright's default User-Agent, 6 of 20 rendered real content;
# with this one, 13 of 20. The only difference is not announcing ourselves as a
# headless browser. Nothing else here is disguised, the crawler is not pretending
# to be a person, and a site that still says no is left alone.
RENDER_USER_AGENT = os.environ.get(
    "RENDER_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# The wall's own words. A challenge page is not short: the five that stayed
# blocked in that test rendered between 256 and 686 characters, all of it above
# MIN_READABLE_PAGE_CHARS, so length cannot tell a wall from a page. Reading one
# as the project's own text would score Cloudflare's copyright year and
# Cloudflare's wording as the project's.
_BOT_WALL_RE = re.compile(
    r"just a moment|checking your browser|enable javascript and cookies|"
    r"verify (?:you are human|yourself)|are you a robot|access denied|"
    r"attention required|performing security verification|"
    r"you have been blocked|unusual traffic|ddos protection|"
    r"request unsuccessful|pardon our interruption|"
    r"security service to protect", re.I)


def looks_like_bot_wall(text):
    """True when the rendered text is the challenge page rather than the site."""
    return bool(text) and bool(_BOT_WALL_RE.search(text[:1500]))

_BROWSER = None
_BROWSER_FAILED = False
_PLAYWRIGHT = None

# Matched against the HOST, never the whole URL. A path-wide match blocked a
# first-party bundle chunk that happened to be named analytics.js, and the app
# it belonged to then rendered nothing at all — a page that reads as empty for
# the same reason a dead site does.
_RENDER_BLOCKED_HOSTS = re.compile(
    r"(?:^|\.)(?:googletagmanager\.com|google-analytics\.com|analytics\.google\.com|"
    r"hotjar\.com|hotjar\.io|intercom\.io|intercomcdn\.com|hubspot\.com|hs-scripts\.com|"
    r"segment\.io|segment\.com|doubleclick\.net|facebook\.net|mixpanel\.com|"
    r"plausible\.io|matomo\.cloud|clarity\.ms|fullstory\.com)$", re.I)


def _render_should_block(request):
    """True for a request that cannot affect the page's words."""
    if request.resource_type in ("media", "font", "image"):
        return True
    host = (urlparse(request.url).hostname or "").lower()
    return bool(_RENDER_BLOCKED_HOSTS.search(host))


def _get_browser():
    """One chromium for the whole run, or None if it cannot be had."""
    global _BROWSER, _BROWSER_FAILED, _PLAYWRIGHT
    if _BROWSER is not None or _BROWSER_FAILED:
        return _BROWSER
    try:
        from playwright.sync_api import sync_playwright
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    except Exception as e:
        _BROWSER_FAILED = True
        _log(f"    render   → unavailable ({type(e).__name__}); thin pages stay unread")
    return _BROWSER


def close_browser():
    global _BROWSER, _PLAYWRIGHT
    try:
        if _BROWSER:
            _BROWSER.close()
        if _PLAYWRIGHT:
            _PLAYWRIGHT.stop()
    except Exception:
        pass
    _BROWSER, _PLAYWRIGHT = None, None


def render_page_text(url):
    """The page's visible text once its JavaScript has run, or None."""
    if not RENDER_THIN_PAGES:
        return None
    browser = _get_browser()
    if browser is None:
        return None
    page = None
    try:
        page = browser.new_page(user_agent=RENDER_USER_AGENT)

        def _route(route):
            # Both calls have to swallow their own errors. A route that has
            # already been handled, or one whose request died with the frame,
            # raises here, and an exception escaping this handler takes the
            # whole navigation down with it — the page then renders nothing at
            # all, which looks exactly like a site with no content.
            try:
                if _render_should_block(route.request):
                    route.abort()
                else:
                    route.continue_()
            except Exception:
                pass

        page.route("**/*", _route)
        # networkidle can hang on a page holding a socket open, so the wait is
        # bounded and a timeout reads whatever painted rather than failing.
        try:
            page.goto(url, timeout=RENDER_GOTO_MS, wait_until="networkidle")
        except Exception as e:
            if "imeout" not in str(e):
                raise
        # A short settle lets late client-side renders paint. Deliberately not
        # cut short on a length threshold: nav chrome and a cookie banner clear
        # any low bar well before the content does.
        page.wait_for_timeout(RENDER_SETTLE_MS)
        text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        return re.sub(r"\s+", " ", text).strip()[:RENDER_TEXT_CAP] or None
    except Exception as e:
        _log(f"    render   → failed ({type(e).__name__})")
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


# ── Pages the rules cannot settle ─────────────────────────────────────────────
#
# Some questions do not reduce to a keyword. A conference closes registration
# because it is about to happen; a consultation closes because it is over. Both
# write "closed" on the page, and a subject list that tells them apart for one
# gets the other wrong: a list containing "registration" retired a live
# conference, and removing it lost a genuinely finished initiative whose page
# said "Public voting closed on December 31, 2021".
#
# Those pages need reading, and reading is a model's job. It does not have to
# happen while the sweep is running, though, and there are good reasons for it
# not to. A call in the middle of scoring puts a paid API on the critical path
# of a 200-record run, makes the run's cost a function of how many odd pages it
# happened to meet, and gives the model's answer the same authority as a
# regexp, written to Airtable in the same second with nothing between it and a
# listing being retired.
#
# So this returns the page instead. One the rules cannot settle comes back in
# result["adjudication"], carrying its text and what the scoring made of it
# without any reading, and the scoring carries on. Reading it is a separate
# pass the caller runs, and a verdict that would retire a project is worth
# holding for review rather than writing.
#
# The record's own score is unaffected by the queueing: it is scored exactly as
# it would have been had no model existed, which is also what it keeps if the
# pass is never run. Nothing in the public breakdown mentions a pending
# reading, deliberately: a line saying a verdict is coming would sit on the
# profile page forever if the pass never came.

ADJUDICATE          = os.environ.get("ADJUDICATE", "1") != "0"
ADJUDICATE_PAGE_CAP = 6000


def adjudication_candidate(name, url, text):
    """
    The page as a queue row, or None when there is nothing worth asking about.

    Only the page and its address. What the scoring made of it is added at the
    end of score_project(), where the arithmetic is still in scope.
    """
    if not (ADJUDICATE and text and text.strip()):
        return None
    return {"name": name, "url": url, "text": text[:ADJUDICATE_PAGE_CAP]}




# ── Pages that say the thing is over ──────────────────────────────────────────
#
# A date is not automatically a sign of life. "This questionnaire closed on
# July 2, 2026" is the page saying it has finished, and read as a recency signal
# it would score the consultation as freshly active — the opposite of what it
# says. Same shape as CTFG-curator's isPastEvent(), which rules that an event
# naming a year now past has happened.
#
# The wording has to carry both a subject that can close and a closing verb.
# "Closed" alone is far too common to trust: closed source, closed beta, closed
# captions, closed loop, a closed Facebook group. So the subject is named
# explicitly, and the generic patterns underneath require the sentence to be
# about the thing itself having ended.

# Only subjects whose closing means the thing itself is over. An intake window
# shutting says nothing: a healthy conference closes registration precisely
# because it is about to happen, and TrustCon was driven from 45 to 10 by its
# own "Registration is Closed" banner while the site served fine and its footer
# read 2026. Applications, nominations, entries, submissions, voting and
# registration all close on schedule every year on programmes that are running,
# so none of them belongs here.
_CLOSED_SUBJECTS = (r"questionnaire|survey|consultation|"
                    r"programme|program|project|pilot|initiative|campaign|"
                    r"competition|contest|challenge|fund|service|platform|tool|site")

_CLOSURE_PATTERNS = [
    # "This questionnaire closed on July 2, 2026" / "applications closed 1 March 2025"
    re.compile(r"\b(?:this |the )?(?:%s)\s+(?:has |have |was |were |is |are )?"
               r"(?:now )?(?:closed|ended|finished|concluded)\b" % _CLOSED_SUBJECTS, re.I),
    # "no longer accepting submissions", "we are no longer taking applications"
    re.compile(r"\bno longer (?:accepting|taking|open to|receiving)\b", re.I),
    # A passed deadline is an intake window closing, not the thing ending, so it
    # is no longer read as a closure on its own.
    # "this project has ended", "the programme is now closed"
    re.compile(r"\bthis (?:project|programme|program|pilot|initiative|campaign)\s+"
               r"(?:has |had )?(?:ended|closed|finished|concluded|wound down)\b", re.I),
    # "applications are now closed" written the other way round
    re.compile(r"\b(?:%s)\s+(?:are|is)\s+(?:now\s+)?closed\b" % _CLOSED_SUBJECTS, re.I),
]

# A closure sentence often names the date it closed. Read it only to confirm the
# closing is in the past; a date still ahead means the thing is open until then.
_CLOSURE_DATE_RE = re.compile(r"(?:closed|ended|closes|ends|deadline)[^.]{0,40}?"
                              r"((?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})|"
                              r"(?:[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})|"
                              r"(?:\d{4}-\d{2}-\d{2}))", re.I)


def page_says_closed(html, now, text=None):
    """
    (closed, phrase) when the page says the thing it describes has finished.

    Only the page's own words, and only the first stretch of them: a closure
    notice is put at the top, while further down "applications closed" is as
    likely to be describing a past round in a history section.
    """
    text = (text if text is not None else readable_page(html)["text"])[:3000]
    if not text:
        return False, None
    for pattern in _CLOSURE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        # If the sentence names a date, believe the closure only once that date
        # has actually arrived.
        window = text[m.start():m.start() + 160]
        dm = _CLOSURE_DATE_RE.search(window)
        if dm:
            dt = _parse_date_loose(dm.group(1), now)
            if dt and dt > now:
                continue
        return True, re.sub(r"\s+", " ", m.group(0)).strip()[:80]
    return False, None


def page_recency_score(dt, now):
    """
    Score 0–70 for a date the project's own page states about itself.

    Under recency_base_score's 85 because a page date is easier to be wrong
    about: a CMS stamps dateModified when a template changes, and a hand-written
    "last updated" line goes stale in place. Over social_recency_score's 55
    because it is the project talking about itself on its own site.
    """
    if dt is None:
        return 0
    age_days = max(0, (now - dt).days)
    if age_days <= 90:   return 70
    if age_days <= 180:  return 65
    if age_days <= 365:  return 55
    if age_days <= STALE_AFTER_DAYS: return 40
    if age_days <= 1095: return 25
    if age_days <= 1825: return 10
    return 3


def website_alive_bonus(best_date, now):
    """Points a reachable website earns, given the newest dated signal."""
    if best_date is None:
        return WEBSITE_ALIVE_BONUS_STALE
    if (now - best_date).days <= WEBSITE_BONUS_FRESH_DAYS:
        return WEBSITE_ALIVE_BONUS
    return WEBSITE_ALIVE_BONUS_STALE


# Where "a while ago" stops meaning likely active. At two years, a project
# silent since its last post still scored into the Likely Active band, so a
# listing whose last blog post was in 2024 read as likely running well into
# 2026. Anything past this now has to clear Possibly Inactive on other evidence.
STALE_AFTER_DAYS = 548   # eighteen months


def recency_base_score(dt, now):
    """
    Score 0–85 for GitHub / blog signals based on recency.
    Primary tunable parameter of the algorithm.
    """
    if dt is None:
        return 0
    age_days = max(0, (now - dt).days)
    if age_days <= 90:   return 85
    if age_days <= 180:  return 80
    if age_days <= 365:  return 70
    if age_days <= STALE_AFTER_DAYS: return 55
    if age_days <= 1095: return 35
    if age_days <= 1825: return 15
    return 5


def social_recency_score(dt, now):
    """
    Score 0–55 for social media signals. Same time brackets as recency_base_score
    but capped at 55 and zeroed beyond 1 year.
    """
    if dt is None:
        return 0
    age_days = max(0, (now - dt).days)
    if age_days <= 90:  return 55
    if age_days <= 180: return 50
    if age_days <= 365: return 45
    return 0  # beyond 1 year: no social score


def score_to_activity_status(score):
    """Full 5-value scale for the Activity status field."""
    if score >= 70: return "Active"
    if score >= 45: return "Likely Active"
    if score >= 20: return "Possibly Inactive"
    return "Inactive"


def score_to_status(score):
    """
    Definitive write to the existing Status field.
    Only returns a value when confidence is high; None = don't touch Status.
    """
    if score >= 70: return "Active"
    if score < 20:  return "Inactive"
    return None


# ── Main computation ──────────────────────────────────────────────────────────

def score_project(project):
    """
    Runs all signal checks and returns:
      score (float), last_activity_date (ISO str | None), status (str)
    """
    name   = project.name
    now    = datetime.now(timezone.utc)
    _PAGE_CACHE.clear()

    _log(f"\n  [{name}]")

    # ── Website ──────────────────────────────────────────────────────────────
    raw_url = project.website
    if raw_url and "duckduckgo.com" in raw_url and "!ducky" in raw_url:
        resolved = resolve_duckduckgo(raw_url)
        if resolved:
            _log(f"    website  → resolved DDG URL to: {resolved[:70]}")
            raw_url = resolved
        else:
            _log(f"    website  → DDG URL could not be resolved, skipping")
            raw_url = None
    url_class  = classify_url(raw_url)
    website_url = raw_url
    discovered_url = None

    if url_class == "skip":
        _log(f"    website  → no usable URL ({(raw_url or 'none')[:60]})")
        website_alive, is_archived, site_verdict = None, False, "unknown"
    elif url_class == "article":
        _log(f"    website  → article URL detected, searching for homepage…")
        discovered_url = find_homepage_in_article(raw_url)
        if discovered_url:
            _log(f"    website  → found homepage: {discovered_url}")
            website_url = discovered_url
            website_alive, is_archived, site_verdict = probe_site(discovered_url)
        else:
            _log(f"    website  → could not find homepage from article")
            website_alive, is_archived, site_verdict = None, False, "unknown"
    else:
        website_alive, is_archived, site_verdict = probe_site(raw_url)
        _log(f"    website  → alive={website_alive}  archived={is_archived}  {site_verdict}")

    # A dead site is NOT looked up in the Wayback Machine and its Website URL is
    # never replaced with a snapshot. Swapping in an archive link is the
    # graveyard ruling from the dead-link triage codebook, and it is written as
    # one unit with the Graveyard category and Status: Inactive by a curator who
    # has first ruled out relink (the project moved and is live elsewhere, which
    # is the common case). A failed fetch cannot tell relink from graveyard, and
    # writing one third of the ruling leaves a record in a state the codebook
    # has no name for: an archive URL, no Graveyard tag, Status still Active.
    # A snapshot merely existing is also no evidence a project is dead.
    # is_archived stays set only by check_website, for a Website URL that a
    # curator already pointed at an archive and whose original no longer answers.

    # ── GitHub ───────────────────────────────────────────────────────────────
    gh = check_github(project.repo)
    github_date     = gh["best_date"] if gh else None
    github_archived = bool(gh and gh["archived"])
    if gh:
        detail = "  ".join(f"{k}={v.date()}" for k, v in sorted(gh["dates"].items()))
        flag   = "ARCHIVED  " if github_archived else ""
        if (res := gh.get("resolution")):
            detail += f"  resolved={res['resolved']}/{res['touched']}"
        _log(f"    github   → {flag}{detail or 'no dated activity'}")
    else:
        _log(f"    github   → no data")
    time.sleep(0.3)  # respect GitHub rate limits

    # ── Blog feeds ───────────────────────────────────────────────────────────
    blog_date = latest_blog_date(project.feeds, website_url, url_class)
    _log(f"    blog     → latest post: {blog_date}")

    # ── Social links: recency + accessibility ────────────────────────────────
    # Links arrive already resolved. In the Field Guide they live in a second
    # table, but that is one deployment's storage rather than anything the
    # scoring needs to know, so the caller hands over a list of
    # {"url", "type"} and this stays out of it.
    link_items = list(project.links)
    all_social_urls = [item["url"] for item in link_items]
    _log(f"    links    → {len(link_items)} link(s) supplied")

    # Auto-discover social links from the website homepage
    if website_url and url_class == "homepage":
        discovered_social = discover_social_links(website_url)
        if discovered_social:
            existing_domains = {urlparse(u).netloc.lower().lstrip("www.") for u in all_social_urls}
            added = []
            for su in discovered_social:
                domain = urlparse(su).netloc.lower().lstrip("www.")
                if domain not in existing_domains:
                    all_social_urls.append(su)
                    existing_domains.add(domain)
                    added.append(su)
            if added:
                _log(f"    links    → auto-discovered {len(added)} social link(s) from homepage")

    accessible_count  = 0
    social_dated      = []  # list of (datetime, platform_label)

    for url in all_social_urls:
        alive = check_url_alive(url)
        if alive is True:
            accessible_count += 1
        dt, platform = check_social_recency(url)
        dt = reject_future(dt)
        if dt:
            social_dated.append((dt, platform))
            _log(f"    social   → {platform}: last post {dt.date()}")

    # No cap on the count here: SOCIAL_REACHABLE_BONUS_MAX already caps what
    # reachability is worth, so capping the count too changed no score and only
    # made the breakdown under-report how many accounts were actually reached.

    # ── Combine all signals ───────────────────────────────────────────────────
    # Every dated signal becomes a (points, date, label) candidate. The score is
    # the single best of these and never their sum, which is exactly the part a
    # reader cannot infer from the final number, so the breakdown has to name
    # which signal won and show the others as also-rans.
    candidates = []

    if github_date:
        s = recency_base_score(github_date, now)
        if github_archived:
            s = min(s, 15)  # maintainers explicitly stopped work on the repo
        kind = next((k for k, v in gh["dates"].items() if v == github_date), None)
        candidates.append((s, github_date, GH_SIGNAL_LABELS.get(kind, "GitHub activity")))

    if blog_date:
        candidates.append((recency_base_score(blog_date, now), blog_date, "Blog post"))

    for dt, platform in social_dated:
        candidates.append((social_recency_score(dt, now), dt, f"{platform} post"))

    # What the project's own page says about itself. The page was already
    # downloaded for the social-link scrape, so this costs no extra request.
    page_copyright_year = None
    page_unreadable = False
    page_closed, page_closed_phrase = False, None
    pending_adjudication = None

    # A site behind a bot wall answered 403 or 429, which is the wall talking
    # and says nothing about the project. Roughly two thirds of them serve their
    # real page to a browser, so those get one, and what comes back is only
    # believed when it is not the challenge page itself. A site that still says
    # no stays exactly where it was: unread, and recorded as unread.
    #
    # This is the only place the browser is used on a page that did not answer.
    # It is deliberately not extended to a timeout or a connection error, where
    # there is nothing to render and the wait would be paid twice.
    blocked_text = None
    if website_url and site_verdict == "blocked" and not is_archived:
        _log(f"    website  → behind a bot check; trying a browser")
        candidate = render_page_text(website_url)
        if candidate and looks_like_bot_wall(candidate):
            _log(f"    render   → got the bot wall, not the site; left unread")
        elif candidate and len(candidate) >= MIN_READABLE_PAGE_CHARS:
            blocked_text = candidate
            website_alive = True
            _log(f"    render   → {len(candidate)} chars past the wall")
        elif candidate:
            _log(f"    render   → only {len(candidate)} chars past the wall; left unread")

    if website_url and website_alive is True:
        page_html, page_headers = get_page_cached(website_url)
        # A page reached only through the browser has no HTML here: the fetch
        # that would have filled the cache is the one the wall refused. Its
        # rendered words are all there is, so they stand in for the page and the
        # markup-based checks below simply find nothing, which is accurate.
        if page_html is None and blocked_text:
            page_html, page_headers = "", {}
        if page_html is not None:
            # A site can answer and still say nothing. An app that paints itself
            # in the browser serves a shell: the questionnaire, the dates, the
            # notice that it closed months ago all arrive with the JavaScript,
            # and none of it is in the HTML. Reading no date off a shell is not
            # the same finding as reading no date off a page, so it is recorded
            # as its own fact rather than left to look like an absence.
            readable = blocked_text or readable_page(page_html)["text"]
            page_unreadable = len(readable) < MIN_READABLE_PAGE_CHARS

            # A shell is worth a second look through a browser, where the words
            # actually exist. Only a shell: the nine in ten pages that already
            # read fine would pay for a render that told us nothing new. A page
            # already rendered past a wall is not re-rendered.
            rendered = blocked_text
            if blocked_text is None and page_unreadable and not is_archived:
                _log(f"    page     → only {len(readable)} chars of text; rendering")
                rendered = render_page_text(website_url)
                if rendered and len(rendered) >= MIN_READABLE_PAGE_CHARS:
                    page_unreadable = False
                    _log(f"    render   → {len(rendered)} chars of text")

            page_signals = page_date_signals(page_html, page_headers, now, text=rendered)
            if page_signals:
                pdt, plabel = max(page_signals, key=lambda c: c[0])
                candidates.append((page_recency_score(pdt, now), pdt, plabel))
                _log(f"    page     → {plabel}: {pdt:%Y-%m-%d}")
            news = latest_news_date(page_html, website_url, now) if page_html else None
            if news:
                candidates.append((recency_base_score(news[0], now), news[0],
                                   "Newest item on the site's own news page"))
            page_closed, page_closed_phrase = page_says_closed(page_html, now, text=rendered)
            if page_closed:
                _log(f"    page     → says it has closed: {page_closed_phrase!r}")
            elif not page_unreadable and not page_signals and not news:
                # The wording check found nothing and neither did any date. This
                # is the narrow band the rules cannot settle, so it is the only
                # band worth queueing for a reading. The run does not wait for
                # one: it scores this record as though no reading existed.
                words = rendered if rendered is not None else readable
                pending_adjudication = adjudication_candidate(name, website_url, words)
                if pending_adjudication:
                    _log(f"    page     → nothing the rules can settle; queued for reading")
            if page_unreadable:
                _log(f"    page     → still unread after rendering")
            else:
                page_copyright_year = footer_copyright_year(page_html)
                if page_copyright_year:
                    _log(f"    page     → footer copyright {page_copyright_year}")

    best_score = max((c[0] for c in candidates), default=0)
    best_date  = max((c[1] for c in candidates), default=None)

    score = float(best_score)

    # The public explanation, written to Airtable and shown on the profile page.
    # Built alongside the arithmetic rather than reconstructed afterwards: a 70
    # could be a 300-day-old commit or social posting plus a live site, and the
    # score on its own cannot tell those apart.
    why = []

    if candidates:
        winner = max(candidates, key=lambda c: (c[0], c[1]))
        why.append(f"Strongest signal: {winner[2]}, {describe_age(winner[1], now)} ({winner[0]})")
        others = sorted((c for c in candidates if c is not winner),
                        key=lambda c: c[0], reverse=True)
        if others:
            why.append("Also found: " + ", ".join(
                f"{c[2]} {describe_age(c[1], now)} ({c[0]})" for c in others))
        if github_archived:
            why.append("The GitHub repository is archived, so however recent its last "
                       "activity is, it counts for at most 15")
    else:
        why.append("No dated activity found in code, feeds, social posts or on the "
                   "project's own page (0)")

    # Issue tracker responsiveness. A tiebreaker on the dated signals above,
    # never a base score, so it is applied after the winner is chosen. Skipped
    # for an archived repo: nothing can be closed in one, and the archive cap
    # has already said what needs saying.
    if gh and not github_archived:
        resolution_adj, resolution_label = issue_resolution_adjustment(gh.get("resolution"))
        if resolution_label:
            before = score
            score  = max(0.0, min(score + resolution_adj, 100))
            why.append(_adjustment(resolution_label, resolution_adj, score - before))

    # Website modifiers
    if is_archived:
        score = min(score, 10)      # almost certainly dead if pointing to web archive
        why.append("The listed address is an archive snapshot and the original no "
                   "longer answers (score capped at 10)")
    elif website_alive is True:
        bonus  = website_alive_bonus(best_date, now)
        before = score
        score  = min(score + bonus, 100)
        why.append(_adjustment(
            "Website is responding" if bonus == WEBSITE_ALIVE_BONUS
            else "Website is responding, but nothing dated and recent was found to go "
                 "with it",
            bonus, score - before))
    elif site_verdict == "relink":
        # The page is gone and its host is not. That is a stale link, not a
        # dead project, and the two want opposite rulings, so it takes a much
        # smaller penalty and says what a curator has to decide.
        before = score
        score  = max(score - RELINK_PENALTY, 0)
        why.append(_adjustment(
            "The page listed here is gone, but the site it sat on still answers, so "
            "the link needs checking rather than the project being counted as over",
            -RELINK_PENALTY, score - before))
    elif site_verdict == "no-host":
        before = score
        score  = max(score - 50, 0)
        why.append(_adjustment("The web address does not exist any more", -50, score - before))
    elif website_alive is False:
        before = score
        score  = max(score - 50, 0)  # strong signal of death
        why.append(_adjustment("Website did not respond", -50, score - before))
    elif url_class == "article":
        why.append("The listed address is an article about the project rather than the "
                   "project itself, and no homepage could be found from it")
    elif not raw_url:
        why.append("No website address on this listing to check")
    elif url_class == "skip":
        why.append("The listed address is not one that can be checked")
    elif site_verdict == "blocked":
        # Said out loud because it is a fact about the wall, not about the
        # project, and a reader comparing two low scores should be able to tell
        # "we could not look" from "we looked and found nothing".
        why.append("The site is behind a bot check that refused both an ordinary "
                   "request and a browser, so nothing on it could be read. This is "
                   "not evidence either way about the project")
    else:
        why.append("Website could not be checked: it timed out or refused the request")

    # Social presence bonus, capped: a page that loads says nothing about whether
    # anything was ever posted to it.
    social_bonus = min(accessible_count * 10, SOCIAL_REACHABLE_BONUS_MAX)
    before = score
    score  = min(score + social_bonus, 100)
    if social_bonus:
        why.append(_adjustment(
            f"{accessible_count} social account"
            f"{'' if accessible_count == 1 else 's'} reachable",
            social_bonus, score - before))

    # A footer copyright naming this year or last. Weak on its own — plenty of
    # templates render the year server-side or in JS on a site nobody has touched
    # in years — so it is worth a little and never a date. It does count as
    # evidence, though, which is enough to keep the listing out of Unknown: a
    # page that is being rebuilt each year is not a page nothing is known about.
    if page_unreadable:
        why.append("The website answers, but its text is built in the browser, so "
                   "nothing on the page could be read without running it")

    fresh_copyright = (page_copyright_year is not None
                       and page_copyright_year >= now.year - 1)
    if fresh_copyright:
        before = score
        score  = max(score, COPYRIGHT_FRESH_FLOOR)
        if score > before:
            why.append(_adjustment(
                "The site's footer copyright reads %d, so it is being kept up even "
                "though nothing on it is dated" % page_copyright_year,
                COPYRIGHT_FRESH_FLOOR - before, score - before))
        else:
            why.append("The site's footer copyright reads %d, which the signals above "
                       "already account for" % page_copyright_year)

    # A recent launch is evidence in its own right, and the only positive
    # evidence available for a listing with nothing dated anywhere. Applied as a
    # floor so a measured score above it is left alone.
    recent_launch = recently_launched(project, now)
    # A launch flag cannot outvote the site being gone. Added to the directory in
    # March says nothing about a domain that stopped answering in August, and an
    # address that now resolves to an archive snapshot has already been capped
    # for exactly that reason — the floor would undo the cap.
    if recent_launch and (website_alive is False or is_archived):
        why.append("Added to the directory in the last nine months and marked as a "
                   "launch, but %s, which is the better evidence"
                   % ("its address is an archive snapshot" if is_archived
                      else "its website no longer answers"))
        recent_launch = False
    if recent_launch:
        before = score
        score  = max(score, RECENT_LAUNCH_SCORE)
        if score > before:
            why.append(_adjustment(
                "Added to the directory in the last nine months and marked as a launch, "
                "so it is very likely still running",
                RECENT_LAUNCH_SCORE - before, score - before))
        else:
            why.append("Added to the directory in the last nine months and marked as a "
                       "launch, but the signals found already score higher than that on "
                       "their own")

    # The page saying it has finished outranks everything above it, including a
    # recent launch: something added to the directory in March and closed in July
    # was both. Applied last so nothing can lift it back up.
    if page_closed:
        before = score
        score  = min(score, CLOSED_CAP)
        capped = "" if score == before else " (capped at %g)" % CLOSED_CAP
        why.append(closure_sentence(CLOSURE_SOURCE_WORDING, page_closed_phrase, capped))

    # Fully unknown: nothing could be checked at all
    no_signals = (best_date is None and website_alive is None and accessible_count == 0)

    # Nothing dated was found anywhere. A reachable website says the address still
    # resolves, not that anyone is still behind it, so this reports Unknown rather
    # than a floor score. A floor reads as a measurement to whoever sees the
    # profile, and "we found nothing" is not the same claim as "this looks
    # inactive". A site that failed to respond, an archive snapshot and a recent
    # launch all carry real evidence, so none of them land here.
    undated = (best_date is None
               and not page_closed
               and not recent_launch
               and not fresh_copyright
               and not is_archived
               and website_alive is not False)

    unknown = no_signals or undated

    score  = round(score, 1)
    activity_status = "Unknown" if unknown else score_to_activity_status(score)
    status          = None      if unknown else score_to_status(score)

    # A finished piece of work is N/A, and it outranks anything the signals say.
    # A report does not stop being a report because the site hosting it went
    # down, and Inactive on one reads as a project that ended, which is a claim
    # about something that was never running in the first place. This used to be
    # decided only by a sweep over the first hundred rows of the table, so a
    # report outside that page was scored like a project and retired like one.
    #
    # is_na_candidate() carries the guard that keeps an organization which
    # published something out of this: an ongoing type beside the Document wins.
    if is_finished_work(project):
        status = "N/A"
        why.append("This listing is a finished piece of work rather than something "
                   "that runs, so it is recorded as not applicable instead of being "
                   "scored on how recently anything happened")

    # Status "Inactive" is a claim that the thing is over, so it needs one of
    # two kinds of evidence: it cannot be reached, or it says itself that it has
    # finished. A page announcing that it has closed is the clearest signal
    # there is and counts on its own, whatever the site still serves.
    #
    # Age is not that evidence. Plenty of listings are static resources — a
    # guide, a dataset, a reference site — unchanged for years and perfectly
    # usable because they are still up. A low score is the right reading of how
    # much is happening there, and Activity status keeps carrying it; the score
    # exists precisely so that case does not have to collapse into a binary.
    if status == "Inactive":
        says_finished = page_closed
        # A relink is the one failure that is explicitly not a verdict: the
        # organisation is still answering and only the link is stale, which is
        # a curator's call to make and not one to write permanently.
        unreachable   = ((website_alive is False) or is_archived or no_signals) \
                        and site_verdict != "relink"

        # A single failed fetch is not proof a site has gone. _try_fetch()
        # already retries a connection error once, and a blip lasting seconds
        # survives that: a federal ministry's site was recorded as not
        # responding on one run and answered normally minutes later. Since this
        # verdict removes the record from the queue for good, an unreachable
        # site is checked once more before it counts, far enough after the first
        # attempt to outlast a blip. Only the handful of records heading for
        # Inactive pay for it.
        if unreachable and website_alive is False and website_url:
            time.sleep(RECHECK_PAUSE_S)
            again, _, _ = check_website(website_url)
            if again is not False:
                why.append("The website did not answer when it was first checked but "
                           "answered when it was tried again, so this is not recorded "
                           "as inactive")
                unreachable = False

        if not (says_finished or unreachable):
            why.append("The score is low, but the site still answers and nothing on it "
                       "says the project has finished, so it is not recorded as "
                       "inactive: a resource that is still up is still usable")
            status = None
    # What a "finished" verdict would make of this record, worked out here where
    # the rest of the arithmetic is still in scope. The reading happens hours
    # later against nothing but the queue file, so the alternative has to travel
    # with the row: a score alone cannot be turned back into one, because a
    # closure does not only cap the number. It also settles the question Unknown
    # was reported for, so a record with nothing dated stops being Unknown and
    # becomes a measurement. Only a listing with nothing checkable at all stays
    # Unknown, and that is what no_signals already means.
    if pending_adjudication is not None:
        closed_score = round(min(score, CLOSED_CAP), 1)
        pending_adjudication.update({
            "score":                  None if unknown else score,
            # The number before Unknown could clear it and before any cap, which
            # is what tells the applier whether the closure cap actually moved
            # anything or the score was already under it.
            "raw_score":              score,
            "activity_status":        activity_status,
            "status":                 status,
            # The reasons as they stand here, which is deliberately before the
            # closing lines: the "nothing dated was found" paragraph and the
            # Total are both answers to questions a closure re-opens, and a
            # rebuilt breakdown wants them written fresh rather than stripped.
            "reasons":                list(why),
            "closed_score":           None if no_signals else closed_score,
            "closed_activity_status": "Unknown" if no_signals
                                      else score_to_activity_status(closed_score),
            # A page that says it has finished is the evidence the Inactive
            # guard above asks for, so score_to_status() is not second-guessed
            # here the way it is for a low score with no such statement.
            "closed_status":          None if no_signals
                                      else score_to_status(closed_score),
        })

    if unknown:
        score = None            # clears the field rather than publishing a number

    if no_signals and site_verdict == "blocked":
        # Distinct from the message below it on purpose. "No working website
        # address" is false here: the address works and a wall is standing in
        # front of it, which is a different thing for a curator to act on.
        why = ["The website is behind a bot check that refused both an ordinary "
               "request and a browser, and there is no code repository, feed or "
               "reachable social account to go on instead. Nothing here is "
               "evidence about whether the project is running."]
    elif no_signals and is_archived:
        why = ["The address on this listing is an archive snapshot, and the original "
               "could not be reached to see whether the project is still there."]
    elif no_signals:
        why = ["Nothing on this listing could be checked: no working website address, "
               "no code repository, no feed and no reachable social accounts."]
    elif undated:
        why.append("Nothing dated was found in code, feeds or social posts, so there is "
                   "no evidence either way about whether this project is still running. "
                   "A reachable website only shows the address still resolves. Reported "
                   "as Unknown rather than scored.")
    else:
        why.append(f"Total: {score:g} out of 100 - {activity_status}")
    breakdown = "\n".join(why)

    last_activity_str = best_date.strftime("%Y-%m-%d") if best_date else None
    _log(f"    → score={'(cleared)' if score is None else score}  activity={activity_status}  "
          f"status={status or '(no change)'}  last_activity={last_activity_str}")
    if discovered_url:
        _log(f"    → discovered homepage: {discovered_url}  (original was article URL)")

    return {
        "score":              score,
        "last_activity_date": last_activity_str,
        "activity_status":    activity_status,
        "status":             status,
        "breakdown":          breakdown,
        "discovered_url":     discovered_url,
        "adjudication":       pending_adjudication,
    }
