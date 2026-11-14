"""Words that never appear in any artifact: code, docs, site copy, drafts, data, commit messages.

Three lists:
* verdict words (an accusation about a party's conduct), carried over from the author's earlier project;
* trade-direction and advice words: this project measures markets and never tells anyone what to do
  in them, so the coverage work speaks of "liquidation flow", "downward depth" and "token-to-USDC swaps";
* names: the earlier project's planned public name, which this project never uses.

Words are stored reversed so that this file passes its own scan. Matching is case-insensitive: verdict
words match at a word start (as before), the others as whole words with their inflections listed.
"""

from __future__ import annotations

import re

_VERDICT = ('duarf', 'macs', 'ekaf', 'redart hsaw', 'gnidart hsaw')
_DIRECTION = (
    'yub', 'syub', 'gniyub', 'reyub', 'sreyub',
    'lles', 'slles', 'gnilles', 'relles', 'srelles',
    'gnol og', 'sgnol', 'noitisop gnol', 'trohs og', 'strohs', 'gnitrohs', 'noitisop trohs',
    'dnemmocer', 'sdnemmocer', 'dednemmocer', 'gnidnemmocer', 'noitadnemmocer', 'snoitadnemmocer',
    'hsillub', 'hsiraeb', 'deulavrednu', 'deulavrevo', 'tegrat ecirp', 'mrofreptuo', 'mrofreprednu',
    'efas', 'efasnu', 'yksir',
)
_NAMES = ('yrtemelttes',)

VERDICT = tuple(w[::-1] for w in _VERDICT)
DIRECTION = tuple(w[::-1] for w in _DIRECTION)
NAMES = tuple(w[::-1] for w in _NAMES)

_VERDICT_RX = re.compile(r"\b(" + "|".join(re.escape(w) for w in VERDICT) + r")", re.IGNORECASE)
_WORD_RX = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(DIRECTION + NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def scan(text: str) -> list[tuple[int, str]]:
    """(line number, matched text) for every forbidden word in `text`."""
    hits = []
    for rx in (_VERDICT_RX, _WORD_RX):
        for m in rx.finditer(text):
            hits.append((text.count("\n", 0, m.start()) + 1, m.group(0)))
    return sorted(hits)
