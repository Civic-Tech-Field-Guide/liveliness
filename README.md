# liveliness

Estimates whether a project is still active from what it publishes: its website, code repository, feeds and social accounts. It returns a score from 0 to 100 and a line-by-line breakdown of how the score was reached.

The [Civic Tech Field Guide](https://civictech.guide) uses it to score the projects in its directory. We publish it so people can see how their project was scored, run it on their own data, and suggest fixes. This repository contains only the scoring code, not the directory.

Every score comes with its `breakdown`, which lists each signal checked, the date found and the points it added. If a project thinks its score is wrong, the breakdown shows what to dispute.

## Install

```sh
pip install git+https://github.com/Civic-Tech-Field-Guide/liveliness
```

It is not on PyPI yet.

Optional:

- `GITHUB_TOKEN`: a personal access token raises the GitHub API limit from 60 calls an hour to 5,000. Each repository takes 4 or 5 calls, plus one or two when you pass an account instead of a repository.
- `YOUTUBE_API_KEY`: needed to read a YouTube channel's last upload. Without it, the channel is only checked for being reachable.
- `python -m playwright install chromium`: needed to read pages that build their text in the browser. Without it, those pages are recorded as unread, not as empty.

## Use

```python
from liveliness import Project, score_project

result = score_project(Project(
    name="liveliness",
    website="https://github.com/Civic-Tech-Field-Guide/liveliness",
    repo="https://github.com/Civic-Tech-Field-Guide/liveliness",
))

result["score"]               # 0 to 100, or None when there was nothing to go on
result["activity_status"]     # Active | Likely Active | Possibly Inactive | Inactive | Unknown
result["last_activity_date"]  # the most recent date the project itself left, ISO 8601, or None
result["status"]              # Active | Inactive | N/A, only where it is unambiguous
result["breakdown"]           # the reasoning, line by line
result["discovered_url"]      # the homepage, when the website given was an article about the project
result["adjudication"]        # set when the rules could not settle the page
```

To log each step:

```python
from liveliness import set_logger
set_logger(print)
```

`Project` requires only a name. Other fields are used when present, and an empty field never lowers the score. `liveliness/project.py` documents each one.

| Field | What it is |
| --- | --- |
| `website` | The project's homepage. A link to an article about the project also works: the scorer follows its links to find the homepage. |
| `repo` | A GitHub repository, or a GitHub account, in which case its most recently pushed repository is used. |
| `feeds` | RSS or Atom feeds. The scorer also looks for one on the homepage. |
| `links` | Social and other accounts, as `{"url": ..., "type": ...}`. Accounts linked from the homepage are added. |
| `types`, `formats` | What kind of thing the project is. A finished piece of work, such as a report or a book, gets N/A instead of a score. |
| `launch_flag`, `added` | Whether the project recently launched, and when it was added to your directory. |

## Limits

The scorer measures how recently a project showed activity. It does not measure quality, popularity or impact.

When the rules find no date and no statement that a project has ended, the scorer does not guess. It returns an `adjudication` entry and scores the project as if that page had not been read. The caller decides what to do with it. The Field Guide sends those pages to a language model, and a person must approve any reading that would mark a project inactive. `eval/README.md` describes how that was tested and what has not been tested.

## Signals

| Source | What is checked |
| --- | --- |
| Website | Whether it responds, and where the request ends up. |
| GitHub | Last push, latest release, last commit, maintainer activity on issues and pull requests, how much recent issue traffic was resolved, and whether the repository is archived. |
| Blog | The newest entry in an RSS or Atom feed, either supplied or found on the homepage. If a supplied link is the blog page rather than its feed, the scorer looks for the feed that page lists. |
| News pages | Up to two of the site's own blog, news, updates or events pages, found through the homepage's links. The newest dated item counts like a blog post. |
| Social | Last post date for YouTube, Bluesky, Medium, Reddit, Substack, and Mastodon or other fediverse accounts. X, LinkedIn, Facebook, Instagram, TikTok and Signal don't expose post dates, so they are only checked for being reachable. |
| The page itself | Dates the homepage gives for itself, a recent copyright year in the footer, and any statement that the project has closed. |

### Website

A success or a redirect counts as live. A certificate error also counts as live.

A 403 or 429 usually means bot blocking, so it doesn't count as down. The scorer tries once more with a headless browser and counts the site as live only if it gets the real page and not the bot check. A timeout or redirect loop is left undetermined. A connection error is retried once, after two seconds.

When a request fails, the scorer checks why:

- If the hostname doesn't resolve, the scorer looks it up again through Cloudflare's and Google's public DNS over HTTPS. If they find it, the site is left undetermined. If not, the address no longer exists.
- If the listed page fails but the site's root answers, the page has moved. This scores as a stale link, not a dead site.
- Otherwise the site did not respond.

If a request ends up on a web archive when the address given was not an archive, the owner has redirected the domain to a snapshot, and the site does not count as live. If the address given is an archive snapshot, the scorer tries the original address inside it first, and the project counts as live if that answers.

Search engine addresses are skipped. A DuckDuckGo "I'm feeling lucky" link is followed to its destination first.

### GitHub

The GitHub signal is the newest of the push, release, commit and issue dates.

Issue dates count only maintainer activity: merged pull requests, anything opened or closed by an owner, member or collaborator, and an outside contributor's issue closed by someone other than its author. An outsider opening an issue doesn't count, because abandoned repositories keep receiving them.

The resolution rate looks at the 20 most recently updated issues and pull requests, keeps those updated in the last 180 days, and counts how many of them were closed or merged in that window. It needs at least 5 items in the window, or it is not applied. It uses the same API request as the issue dates.

### Pages

On the homepage, these count as dates the page gives for itself: schema.org `dateModified` and `datePublished`, common date meta tags, `time` elements, and labeled lines such as "Last updated: 20 March 2026" in the directory's main languages. The server's `Last-Modified` header counts only if it is at least two days old, because a page generated on each request reports the request time.

A news page counts when it lists at least two different dates. The scorer follows only links on the same site, prefers blog and news pages over events pages, skips links to files, and only considers link text of three words or fewer. The link words cover the directory's main languages, for example noticias, actualités, berita, habari and お知らせ. An unlabeled date of today or yesterday is ignored, because many news templates print the current date in the header.

A footer copyright counts when it names this year or last year.

The scorer looks for a closure notice in the first 3,000 characters of the page text, with wording such as "this project has ended" or "no longer accepting submissions". A closure dated in the future is ignored. Registration, applications, nominations, submissions or voting closing don't count, because active projects close those on a schedule.

About one in ten reachable sites sends an empty shell and builds its text in the browser. A page with fewer than 200 characters of readable text is read again with a headless browser. If it still can't be read, it is recorded as unread, and its footer copyright doesn't count.

### Last resorts

Two more sources are asked only when nothing else dated was found: no code, feed, social post, news page or date on the page. Both cost extra requests, and both are weaker than any of those, so a listing with a dated signal never reaches them. Neither is asked for a site that did not respond, a page that has moved or an archive snapshot, since what they would date is no longer the project. A site behind a bot check is asked only about the archive, because the check that refused the homepage refuses the sitemap too.

**Sitemap.** The sitemaps named in the site's `robots.txt` are read first, then `/sitemap.xml`, `/sitemap_index.xml` and `/wp-sitemap.xml`, and the first one that yields a date is the one used. A sitemap index is followed two levels down, reading at most four child sitemaps from each, newest first, with at most eight requests and 25 seconds for the whole search. When the listed address points into a section of a site, only entries at or under that address count, so a lab's page on a university site is dated by the lab's pages rather than by the university's news. Entries on another site are skipped, since a `robots.txt` can name a sitemap that belongs to a different site entirely. Entries on a host the site redirects to still count, so a site that moved to a new name is read under that name. The newest `lastmod` counts like a date the page states about itself. Two kinds of `lastmod` are ignored. One from today or yesterday is the server's clock, by the same reasoning as the `Last-Modified` header, since a sitemap built for each request stamps every entry with the time of the request. And when one day carries at least 80% of five or more entries, that day is when the site was last built, so those entries are set aside and the rest date the site. A sitemap whose every entry carries one timestamp to the second was written in one pass by a generator, however few entries it has, and is ignored.

**Wayback Machine.** The Internet Archive records a hash of every capture it makes, so a change in the hash is a change in the content. The 20 most recent successful captures of the listed address are read, and the first capture of the current content dates the last change the archive saw. When the content has not changed across all 20, one more request finds the archive's earliest capture with the same hash. Captures under 1,500 bytes are skipped, because those are the archive being shown a bot check or a redirect, and getting past the check later is not the site changing. When the newest capture is over a year old, the archive has stopped looking and cannot say whether the page has changed since, so it is not used. Many pages change their hash on every capture, from a rotating banner, a form token or a clock, and for those the last change is only the last capture. When over half of the recent captures differ from the one before, or the page flips back to an earlier version, the archive is not used. The archive reaches sites that turn this checker away at a bot check, which is the main reason to ask it. It is weak evidence, scored like the footer copyright. It never counts toward the bonus for a responding website, and it is not reported as the project's last activity date, because it records when the archive looked rather than anything the project did. The archive limits clients to about 15 requests a minute, so requests are spaced four seconds apart, and an archive that refuses or does not answer within ten seconds is left alone for the next ten minutes and counts as no evidence.

### Dates

Dates more than a day in the future, or before 2000, are discarded. Publishers set their own commit, feed and post dates, and a wrong clock would otherwise keep a score at the top.

## Scoring

![The most points each factor can add: newest dated activity 85, website responding 15, social accounts reachable 10, issues being closed 5. They total 115 and the score is capped at 100.](docs/factors.png)

`docs/factors_chart.py` draws the chart from the package's own numbers.

Each dated signal gets points by age. The best single signal sets the base score. Signals are not added together.

| Age of the date | GitHub, blog, news page | The page's own date, sitemap | Social post | Wayback Machine change |
| --- | --- | --- | --- | --- |
| 90 days or less | 85 | 70 | 55 | 45 |
| 180 days or less | 80 | 65 | 50 | 45 |
| 1 year or less | 70 | 55 | 45 | 45 |
| 18 months or less | 55 | 40 | 0 | 25 |
| 3 years or less | 35 | 25 | 0 | 15 |
| 5 years or less | 15 | 10 | 0 | 5 |
| Older | 5 | 3 | 0 | 3 |

A date the page gives for itself scores lower than a commit, because content systems update `dateModified` when a template changes and hand-written "last updated" lines go stale. It scores higher than a social post because it comes from the project's own site. An archived GitHub repository counts for at most 15.

The scorer then adjusts the base score in this order, keeping it between 0 and 100:

1. **Issue resolution.** Closing or merging at least half of recent issue traffic adds 5. Closing none subtracts 5. Anything in between changes nothing. Archived repositories are skipped.
2. **Website.** One of these applies:
   - The address is an archive snapshot and the original doesn't answer: capped at 10.
   - The site responds: plus 15 if the newest dated signal is within a year, plus 5 if it is older or there is none.
   - The listed page has moved but the site still answers: minus 15.
   - The address no longer exists: minus 50.
   - The site did not respond: minus 50.
3. **Social reachability.** Any reachable social or other account adds 10 in total.
4. **Footer copyright.** A copyright line naming this year or last raises the score to at least 45.
5. **Recent launch.** A project added to your directory in the last nine months with its launch flag set is raised to at least 60. This doesn't apply when the site did not respond or the address is an archive snapshot.
6. **Closure.** A page saying the project has closed caps the score at 10. This step runs last.

The floors at 45 and 60 only raise scores. They never lower a higher one.

| Score | Activity status |
| --- | --- |
| 70 and above | Active |
| 45 to 69 | Likely Active |
| 20 to 44 | Possibly Inactive |
| below 20 | Inactive |

### Unknown

When the scorer finds no dates, and no closure, recent launch, recent copyright or archive snapshot, the result is Unknown and `score` is `None`. A website that loads only shows the address still works, so it isn't scored on its own. A site that doesn't respond is scored, not Unknown.

### Status

`status` is stricter than `activity_status` and is only set at the ends of the range:

- **Active** at 70 and above.
- **Inactive** below 20, and only when the site can't be reached or the page says the project has closed. The scorer checks an unreachable site once more, after five seconds. A moved page never counts as unreachable. A low score on a site that still loads leaves `status` empty, because an old guide or dataset is still usable while it's online.
- **N/A** for a finished piece of work, such as a report or a book. A project that also has an ongoing type, such as an organization that published a report, is scored normally.
- Empty otherwise.

## The breakdown

`breakdown` is plain text. It names the signal that set the base score, lists the other dated signals, and gives each adjustment with its points:

```
Strongest signal: GitHub push, 8 months ago (70)
Also found: Bluesky post 30 days ago (55)
11 of the 20 issues and pull requests active in the last 6 months were closed or merged (+5)
Website is responding (+15)
1 social account reachable (+10)
Total: 100 out of 100 - Active
```

Each line shows the points actually applied, so the lines add up to the total. When the 0 or 100 limit cuts an adjustment short, the line says so.

## The reading pass

Some pages need reading, not keyword matching. A conference closes registration because it is about to happen, and a consultation closes because it is over. Both pages say "closed".

When the scorer can read a page but finds no date, no news page and no closure, it sets `adjudication` to the project's name, address and up to 6,000 characters of page text. The score doesn't change. The Field Guide sends these pages to a language model, and a person must approve any reading that would mark a project inactive. `eval/README.md` describes the testing.

The evaluation set is not published because it contains copies of other people's web pages.

## Settings

| Environment variable | Effect |
| --- | --- |
| `GITHUB_TOKEN` | Raises the GitHub API limit. |
| `YOUTUBE_API_KEY` | Reads YouTube upload dates. |
| `RENDER_THIN_PAGES=0` | Never uses the headless browser. |
| `ADJUDICATE=0` | Never sets `adjudication`. |

## Contributing

If your project's score doesn't match what its `breakdown` shows, or you think a rule is wrong, please open an issue.

## License

MIT.
