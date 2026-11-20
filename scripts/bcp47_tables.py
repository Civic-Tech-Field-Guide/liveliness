"""
Print the BCP 47 region, area and script tables that liveliness/core.py
carries, from the IANA Language Subtag Registry.

    python scripts/bcp47_tables.py > /tmp/tables.txt

Paste the output over the three tables in core.py and update the File-Date in
the comment above them. The registry is the source BCP 47 (RFC 5646) names for
its subtags; deprecated entries and private-use ranges are left out.
"""
import textwrap
import urllib.request

REGISTRY = "https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry"


def records(text):
    for block in text.split("\n%%\n"):
        fields = {}
        for line in block.split("\n"):
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields.setdefault(key, value)
        yield fields


def main():
    text = urllib.request.urlopen(REGISTRY, timeout=30).read().decode("utf-8")
    regions, areas, scripts = [], [], []
    for f in records(text):
        tag = f.get("Subtag", "")
        # Deprecated codes, private-use ranges and codes (AA, ZZ, Qaaa..Qabx),
        # and the placeholder scripts for unwritten, common and unknown text.
        if ("Deprecated" in f or ".." in tag or f.get("Description") == "Private use"
                or tag in ("Zxxx", "Zyyy", "Zzzz")):
            continue
        if f.get("Type") == "region":
            (areas if tag.isdigit() else regions).append(tag.lower())
        elif f.get("Type") == "script":
            scripts.append(tag.lower())
    print("# " + text.split("\n", 1)[0])
    for name, values in (("_BCP47_REGIONS", regions), ("_BCP47_AREAS", areas),
                         ("_BCP47_SCRIPTS", scripts)):
        print('%s = frozenset("""\n%s\n""".split())' % (
            name, "\n".join(textwrap.wrap(" ".join(sorted(values)), 84))))


if __name__ == "__main__":
    main()
