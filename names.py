"""Name normalization shared by the stats refresh script and retrieval."""

import re
import unicodedata


def normalize_name(text: str) -> str:
    """Lowercase, remove accents and punctuation, and collapse spaces.

    "Nikola Jokić"            -> "nikola jokic"
    "Shai Gilgeous-Alexander" -> "shai gilgeous alexander"
    "D'Angelo Russell"        -> "d angelo russell"
    """
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", no_accents.lower()).strip()
