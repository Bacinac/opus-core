"""How a name is filed, whichever module is sorting a shelf of them."""

import re
import unicodedata


# The Croatian alphabet, in its own order — č and ć between c and d, š after s,
# ž last — with the letters foreign titles bring with them slotted into their
# Latin places. Codepoint order puts all five of those after z, and Šehić and
# Žmegač past the end of the shelf.
_ALPHABET = [
    "a", "b", "c", "č", "ć", "d", "dž", "đ", "e", "f", "g", "h", "i", "j", "k",
    "l", "lj", "m", "n", "nj", "o", "p", "q", "r", "s", "š", "t", "u", "v", "w",
    "x", "y", "z", "ž",
]
_RANK = {letter: place for place, letter in enumerate(_ALPHABET)}
_DIGRAPHS = ("dž", "lj", "nj")

# what sits either side of the alphabet: the punctuation a title starts with
# first, then anything that is a number, then the letters, and a script this
# alphabet has no place for after all of them
_MARK = -2
_DIGIT = -1
_FOREIGN = len(_ALPHABET)
_ARTICLE = re.compile(r"^the\s+", re.IGNORECASE)


def croatian(text: str) -> list[tuple[int, str]]:
    """A sort key that reads the way the alphabet is recited, whoever is
    looking: the three digraphs are single letters, a number is compared as a
    number, so 300 sorts before 1917, and the English article a name is written
    with is not what it files under — The Doors stand under D."""
    lowered = unicodedata.normalize("NFC", _ARTICLE.sub("", (text or "").strip()).casefold())
    key: list[tuple[int, str]] = []
    at = 0
    while at < len(lowered):
        letter = lowered[at]

        if "0" <= letter <= "9":
            run = at
            while run < len(lowered) and "0" <= lowered[run] <= "9":
                run += 1
            number = lowered[at:run].lstrip("0") or "0"
            key.append((_DIGIT, f"{len(number):04d}{number}"))
            at = run
            continue

        pair = lowered[at:at + 2]
        if pair in _DIGRAPHS:
            key.append((_RANK[pair], pair))
            at += 2
            continue

        at += 1
        if letter in _RANK:
            key.append((_RANK[letter], letter))
            continue
        stripped = unicodedata.normalize("NFD", letter)[0]
        if stripped in _RANK:
            key.append((_RANK[stripped], letter))
        elif letter.isalnum():
            key.append((_FOREIGN, letter))
        else:
            key.append((_MARK, letter))
    return key
