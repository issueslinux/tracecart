"""Non-authoritative destination hint from the browser's language-region tag.

A language alone (e.g. 'pl') does not identify a delivery country.
The suggestion is editable and is never treated as verified location.
"""
import re

_REGION = re.compile(r"^[a-zA-Z]{2,3}-([a-zA-Z]{2})$")


def suggested_country(accept_language):
    if not isinstance(accept_language, str):
        return None
    for item in accept_language[:512].split(",")[:12]:
        tag = item.split(";", 1)[0].strip()
        match = _REGION.fullmatch(tag)
        if match:
            return match.group(1).upper()
    return None
