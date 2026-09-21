"""What the scorer needs to know about a project before it can judge one."""

from dataclasses import dataclass, field


@dataclass
class Project:
    """
    Everything a project publishes that says whether it is still going.

    Only `name` is required. Every other field is something the scorer will use
    if it has it and work without if it does not, which is the ordinary case:
    most projects publish a website and nothing else. A field left empty is not
    counted against the project, because an absent signal is a fact about what
    was published rather than a fact about the project.
    """

    name: str

    #: The project's home on the web. An article about the project works too:
    #: the scorer follows it to find the homepage.
    website: str | None = None

    #: A code repository, or an account whose most recently pushed repository
    #: should be read. GitHub is the only host read for dates.
    repo: str | None = None

    #: RSS or Atom feed URLs. The scorer also looks for a feed on the homepage,
    #: so this is for feeds that are not linked from there.
    feeds: list[str] = field(default_factory=list)

    #: Social and other accounts as {"url": str, "type": str}. `type` is a free
    #: label kept for the caller's own use; the scorer reads the URL. Accounts
    #: found on the homepage are added to these rather than replacing them.
    links: list[dict] = field(default_factory=list)

    #: What kind of thing this is, in plain words, for example "organization"
    #: or "document". A finished piece of work such as a report scores N/A
    #: rather than badly. See `core.ONGOING_TYPES`.
    types: list[str] = field(default_factory=list)

    #: Publication formats in plain words. "books" means a finished work.
    formats: list[str] = field(default_factory=list)

    #: Anything non-empty marks this as a recent launch, which counts as weak
    #: evidence the project is still there when nothing else is dated. It only
    #: applies alongside a recent `added` date.
    launch_flag: str | None = None

    #: When this project was added to your own directory, ISO 8601. Used only
    #: with `launch_flag`.
    added: str | None = None
