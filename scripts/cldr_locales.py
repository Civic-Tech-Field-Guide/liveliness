"""
Print the _CLDR_LOCALES table that liveliness/core.py carries, from the
Unicode CLDR's published data.

    python scripts/cldr_locales.py 49.0.0 > /tmp/locales.txt

Paste the output over the table in core.py and update the CLDR version in the
comment above it. The table holds every BCP 47 locale with a script or region
that CLDR lists as available, plus the default regions and scripts its likely
subtags leave implicit (pt-br, it-it, sr-latn-rs), all in lower case.
"""
import json
import sys
import textwrap
import urllib.request

BASE = "https://cdn.jsdelivr.net/npm/cldr-core@%s/"


def fetch(version, path):
    with urllib.request.urlopen(BASE % version + path, timeout=30) as r:
        return json.load(r)


def main(version):
    full = fetch(version, "availableLocales.json")["availableLocales"]["full"]
    likely = fetch(version, "supplemental/likelySubtags.json")["supplemental"]["likelySubtags"]
    pairs = set()
    for loc in full:
        parts = loc.lower().split("-")
        if len(parts[0]) != 2 or len(parts) == 1:
            continue
        pairs.add("-".join(parts))
        if len(parts) == 3:
            pairs.add(parts[0] + "-" + parts[2])
    for key, value in likely.items():
        if len(key.split("-")[0]) != 2:
            continue
        v = value.lower().split("-")
        if len(v) == 3:
            pairs.update({v[0] + "-" + v[2], v[0] + "-" + v[1], "-".join(v)})
    # A language written in a second script keeps its usual region: sr-latn-rs.
    region_of = {k.lower(): v.lower().split("-")[2] for k, v in likely.items()
                 if "-" not in k and len(v.split("-")) == 3}
    for p in list(pairs):
        parts = p.split("-")
        if len(parts) == 2 and len(parts[1]) == 4 and parts[0] in region_of:
            pairs.add(p + "-" + region_of[parts[0]])
    print('_CLDR_LOCALES = frozenset("""\n%s\n""".split())'
          % "\n".join(textwrap.wrap(" ".join(sorted(pairs)), 84)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "49.0.0")
