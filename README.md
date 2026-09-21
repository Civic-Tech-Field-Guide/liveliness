# liveliness

Works out whether a project is still alive from what it publishes: its website, its code repository, its feeds and its social accounts. Returns a score from 0 to 100 and the reasoning that produced it.

This is the algorithm behind the activity scores on the [Civic Tech Field Guide](https://civictech.guide), extracted so anyone can read it, run it on their own data, and argue with it. The directory it was built for is not in here. What is in here is how a project gets judged.

## Why the reasoning comes back with the score

A number on its own cannot be argued with. If a project is marked inactive and disagrees, the only useful answer is the specific thing that was looked at and the date that was found, so `breakdown` carries every line of that and is meant to be shown to the project being scored.

## Install

Not on PyPI yet.

```sh
pip install git+https://github.com/Civic-Tech-Field-Guide/liveliness
```

Two optional environment variables raise the ceiling on what can be checked. `GITHUB_TOKEN` takes the GitHub API from 60 calls an hour to 5,000, and a repository costs 4 to 6 calls. `YOUTUBE_API_KEY` is what makes a YouTube channel's last upload readable; without it the channel is checked only for being reachable.

Reading pages that build their text in the browser needs a browser: `python -m playwright install chromium`. About one reachable site in ten needs this. Without it those pages are recorded as unread rather than as empty, so nothing is scored wrongly, there is just less to go on.

## Use

```python
from liveliness import Project, score_project

result = score_project(Project(
    name="Example Project",
    website="https://example.org",
    repo="https://github.com/example/example",
    links=[{"url": "https://example.social/@example", "type": "mastodon"}],
))

result["score"]               # 0 to 100, or None when there was nothing to go on
result["activity_status"]     # Active | Likely Active | Possibly Inactive | Inactive | Unknown
result["last_activity_date"]  # the most recent date found, ISO 8601, or None
result["status"]              # Active | Inactive | N/A, only where it is unambiguous
result["breakdown"]           # the reasoning, line by line
result["adjudication"]        # set when the rules could not settle the page
```

The examples here are not real projects, and this file states no verdict about any project that is. What the scorer says about a real one depends on what that project publishes on the day it is asked, which is the point.

To watch it work, hand it somewhere to write:

```python
from liveliness import set_logger
set_logger(print)
```

`Project` takes only a name; everything else is used if present. See `liveliness/project.py` for what each field means.

## What it will not do

It does not decide anything it cannot show you. Where the wording rules find nothing and no date can be read, the result carries an `adjudication` entry rather than a guess, and the score stands as though no reading had happened. What to do with that is the caller's call: the Field Guide sends those pages to a language model and holds any reading that would retire a project until a person accepts it. See `eval/README.md` for how well that works and where it has not been measured.

It does not judge quality, popularity or worth. It reads recency, and recency is not the same as mattering.

## Signals

| Source | What is checked |
| --- | --- |
| Website | Responds at all. 403 and 429 count as indeterminate, not dead, because they are usually bot blocking. A hard connection error is retried once before the site is called dead. An article URL is followed to find the project homepage. If the Website URL already points at an archive snapshot, the original URL is extracted and tried first, and the project counts as live if the original answers. Liveness is judged by where a fetch lands, not by the status code alone: a domain whose owner has pointed it at a snapshot of itself answers 200 from an archive host, and does not count as live. |
| GitHub | Last push, latest release, last commit, maintainer activity on issues and PRs, how much of the recent issue traffic got resolved, and whether the repo is archived. A profile URL is resolved to that account's most recently pushed repo. |
| Blog | Latest entry in an RSS or Atom feed, either one you supply or one discovered on the homepage. |
| Social | Last post date for YouTube, Bluesky, Medium, Reddit, Substack and Mastodon. Twitter/X, LinkedIn, Facebook and Instagram are checked for reachability only, since neither exposes a post date. Links come from the ones you supply and from scraping the homepage. |
| The page itself | What the site says about its own age: schema.org `dateModified` and `datePublished`, the usual meta tags, `time` elements, and visible lines such as "Last updated: 20 March 2026". A footer copyright naming this year or last is read separately as weak evidence that the site is being kept up. A page that says the thing has closed is read as an ending rather than a date. |

Maintainer activity on issues counts merged PRs, anything opened by an owner, member or
collaborator, and an outsider's issue closed by somebody other than its author. An outsider
merely filing an issue does not count, because a dead repo keeps collecting those.

The resolution rate answers a different question from that date: not when the tracker was last
touched, but whether what came in is being dealt with. Of the 20 most recently updated issues
and PRs, it counts the ones updated in the last 180 days and how many of those were closed or
merged inside the same window. It is read from the request the issue dates already need, so it
costs no extra API calls. Below 5 items in the window there is too little traffic to read and
nothing is applied, which keeps a live two-person project with three issues a year from being
marked unattended for having nothing to close.

The window matters. An all-time ratio of closed to open issues never decays, so a repo that
closed 900 issues between 2015 and 2020 and nothing since still reads as well maintained, which
is the opposite of what this tool is for.

Until September 2026 the site was fetched only to see whether it answered, and the page
itself was thrown away. A project whose homepage plainly stated when it was last updated
produced no date at all, and scored as though nothing had been found. Across thirty sampled
projects, 52% of reachable sites state a date that can now be read.

The server's `Last-Modified` header is believed only when it is at least two days old. A page
built fresh for each request answers with the time of the request, so one project reached the
top of the scale on a header that echoed the current second. A real file timestamp is days or
months old; a server clock never is.

About one reachable site in ten serves a shell to a plain fetch and paints its text afterwards
in the browser. Those are re-read through a headless browser, and only those. One project's
page carried twenty-seven characters of static text, and the notice that it had stopped taking
reports existed only once its script had run. Where a page cannot be read even after that, the
project is recorded as unread rather than as a page that said nothing, and its footer
copyright does not count: a shell's footer is not the project's.

Any date more than a day in the future is discarded. Commit dates, RSS pubDates and social
post dates are all set by whoever published them, so a wrong clock or a deliberate stamp can
otherwise make a stale project score full marks forever.

## Scoring

A GitHub or blog date sets a base score by age: 85 within 90 days, 80 within 180, 70 within a
year, 55 within eighteen months, 35 within three years, 15 within five, 5 beyond that. That
boundary sat at two years until September 2026, which meant a project whose last blog post was
in October 2024 still read as Likely Active most of the way through 2026. A date the page
states about itself uses the same shape capped at 70: under the 85 a commit earns, because a
content system stamps `dateModified` when a template changes and a hand-written "last updated"
line goes stale in place, and over the 55 a social post earns, because it is the project
talking about itself on its own site. Social dates use the same
brackets capped at 55 and drop to 0 past a year. An archived GitHub repo caps its own
contribution at 15, since the maintainers said in as many words that they stopped.

The best single date sets the base score, then the website adjusts it: a live site adds 15 when
the newest dated signal is within a year and 5 when it is older or absent, a dead one subtracts
50, and a project a curator has already pointed at an archive snapshot, whose original URL no
longer answers, is capped at 10. A homepage that loads is evidence of current work only
alongside something dated and recent, so on its own it earns the reduced bonus. Reachable social links add 10 in total,
however many there are.

A live site with no dated signal at all used to get a floor of 25. That floor was never a
measurement, and 25 sits in the Possibly Inactive band, so a working site with no
machine-readable timestamp anywhere was published as possibly inactive on no evidence. In
September 2026 that was 64% of every scored project. It now reports Unknown instead, and the
breakdown says nothing dated was found rather than implying the project was measured and found
wanting.

Three things count as evidence in that otherwise empty case, and each is a floor rather than a
bonus, so none of them stacks on top of stale evidence to lift an old project into Active:

- A footer copyright naming this year or last floors the score at 45. The site is being kept
  up even though nothing on it is dated.
- A project added to your directory within the last nine months whose launch flag is
  filled in floors at 60. It does not apply where the site failed to answer or the address is
  an archive snapshot: being added in March says nothing about a domain that stopped answering
  in August, and the archive cap exists for that reason and was being undone by the floor.
- A page that says the thing has closed caps the score at 10 instead, the same as an archive
  snapshot, and outranks everything above it including a recent launch. Something added in
  March and closed in July was both.

The issue tracker adjusts the score by 5 either way, and only at the ends of the range: closing
or merging at least half of the recent traffic adds 5, and closing none of it subtracts 5. A
backlog of old issues left open on its own is worth nothing in either direction, since a project
that triages carefully carries one and a project running a stale bot does not. The adjustment is
small because it overlaps the issue and PR date that may already have set the base score, and
because a stale bot closing everything untouched for 60 days inflates it. Telling a bot's
closure from a maintainer's costs one API call per issue, which a 200-record batch cannot
afford. An archived repo is skipped: nothing can be closed in one.

A social link counts for reachability only, and that is capped at 10 per project because a page
that loads says nothing about whether anything was posted to it. Posting recency is scored
separately and is worth up to 55. Before the cap, three loading social pages were worth 30,
enough to lift a project with no dated signal anywhere to 45 and report it as Likely Active.

| Score | Activity status |
| --- | --- |
| 70 and above | Active |
| 45 to 69 | Likely Active |
| 20 to 44 | Possibly Inactive |
| below 20 | Inactive |
| nothing checkable | Unknown |

## The reading pass

Some pages do not reduce to a keyword. A conference closes registration because it is about to happen; a consultation closes because it is over. Both write "closed" on the page, and a word list that tells them apart for one gets the other wrong.

Those pages come back with `adjudication` set instead of being decided. In the Field Guide they go to a local language model, and a reading that would retire a project waits for a person to accept it. `eval/README.md` records how that was measured: on 35 labelled pages the model agreed with the label 26 times and proposed retiring nothing that was still running. Recall rests on a single page in that set and is not a rate. Read it as an anecdote.

The eval set itself is not published. It holds copies of other people's pages, and what this repository publishes is the method rather than the material.

## Contributing

The scoring rules are opinions about evidence, and opinions can be wrong. If a project of yours is scored in a way you cannot account for from its `breakdown`, that is worth an issue.

## Licence

MIT.
