"""
Response fingerprinting, baseline calibration and match/filter rules.

The one thing that separates a usable fuzzer from a noise generator is knowing what
the target answers for something that does *not* exist, before trusting any hit. A
site that serves 200 on every path (soft 404) would otherwise report every single
word in the wordlist as a finding, so that calibration lives here, right next to the
rules that consume it.
"""

import asyncio
import random
import re
import string
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# how far a response may drift from the calibrated baseline and still count as the
# same "not found" page: those pages embed timestamps, request ids, CSRF tokens...
# only used when the probes themselves disagreed (see Baseline.stable)
DRIFT_TOLERANCE = 0.05

# every probe uses a term of the same length on purpose: a 404 page that echoes the
# requested path ("/aXk93mz1q2w3e4r5 not found") then has a *constant* byte length
# across probes, so the baseline stays stable instead of looking dynamic
CALIBRATION_TOKEN_LENGTH = 16
DEFAULT_CALIBRATION_PROBES = 4

# what to report when calibration is off and the user set no matcher of their own
DEFAULT_MATCH_CODES = (200, 201, 202, 203, 204, 206,
                       301, 302, 307, 308,
                       401, 403, 405, 500)


@dataclass(frozen=True)
class ResponseSignature:
    """The comparable shape of a response, cheap enough to keep for every request."""

    status: Any  # int, or the string "Error" when the request never completed
    length: int
    words: int
    lines: int

    @classmethod
    def from_response(cls, response: Dict[str, Any]) -> "ResponseSignature":
        body = response.get('content') or ''
        length = len(body)

        if not body:
            # no body to measure: a HEAD, or a binary type http_request skipped.
            # Content-Length is the only size we have left
            try:
                length = int(response.get('headers', {}).get('content-length', 0))
            except (TypeError, ValueError):
                length = 0

        return cls(
            status=response.get('response_code'),
            length=length,
            words=len(body.split()),
            lines=body.count('\n'),
        )

    @property
    def shape(self) -> Tuple[Any, int, int]:
        # word and line counts survive a 404 page echoing the requested path, while
        # the byte length does not, so they make the sturdier identity
        return (self.status, self.words, self.lines)


def _within_tolerance(value: int, low: int, high: int) -> bool:
    return low * (1 - DRIFT_TOLERANCE) <= value <= high * (1 + DRIFT_TOLERANCE)


@dataclass
class Baseline:
    """What one directory answers for a path that does not exist."""

    statuses: Set[Any] = field(default_factory=set)
    shapes: Set[Tuple[Any, int, int]] = field(default_factory=set)
    length_range: Tuple[int, int] = (0, 0)
    word_range: Tuple[int, int] = (0, 0)
    probes: int = 0

    @property
    def stable(self) -> bool:
        """True when every probe came back with the same shape."""
        return len(self.shapes) == 1

    @classmethod
    def from_signatures(cls, signatures: Iterable[ResponseSignature]) -> Optional["Baseline"]:
        signatures = list(signatures)
        if not signatures:
            return None

        lengths = [s.length for s in signatures]
        words = [s.words for s in signatures]
        return cls(
            statuses={s.status for s in signatures},
            shapes={s.shape for s in signatures},
            length_range=(min(lengths), max(lengths)),
            word_range=(min(words), max(words)),
            probes=len(signatures),
        )

    def matches(self, signature: ResponseSignature) -> bool:
        """True when this response looks like the target's own 'not found' answer."""
        if signature.status not in self.statuses:
            return False
        if signature.shape in self.shapes:
            return True
        if self.stable:
            # the probes agreed, so anything with a different shape is a real
            # difference and deserves to be reported
            return False
        # the 404 page is dynamic: all we can honestly do is a tolerance band
        return (_within_tolerance(signature.length, *self.length_range)
                and _within_tolerance(signature.words, *self.word_range))

    def describe(self) -> str:
        statuses = ', '.join(str(s) for s in sorted(self.statuses, key=str))
        low, high = self.length_range
        size = f"{low}" if low == high else f"{low}-{high}"
        kind = "stable" if self.stable else "dynamic"
        return f"status {statuses}, size {size}, {kind} ({self.probes} probes)"


def random_token(length: int = CALIBRATION_TOKEN_LENGTH) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(random.choices(alphabet, k=length))


async def calibrate(probe_coroutine_factory, probes: int = DEFAULT_CALIBRATION_PROBES,
                    concurrency: int = 4) -> Optional[Baseline]:
    """
    Probe a target with random terms and build the Baseline from what comes back.

    `probe_coroutine_factory(term)` must return an awaitable yielding an
    http_request()-shaped dict. Probes that never completed are dropped: a timeout
    says nothing about what a missing page looks like.
    """
    tokens = [random_token() for _ in range(max(1, probes))]
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def probe(term):
        async with semaphore:
            return await probe_coroutine_factory(term)

    responses = await asyncio.gather(*(probe(token) for token in tokens))
    signatures = [ResponseSignature.from_response(r) for r in responses
                  if isinstance(r.get('response_code'), int)]
    return Baseline.from_signatures(signatures)


class IntRangeSet:
    """
    A comma-separated spec of integers and ranges: "200,301,400-499", or "all".

    Kept as ranges rather than an expanded set so that "-fs 0-100000" costs nothing.
    """

    def __init__(self, singles: Set[int], ranges: List[Tuple[int, int]], wildcard: bool = False):
        self.singles = singles
        self.ranges = ranges
        self.wildcard = wildcard

    @classmethod
    def parse(cls, spec: Optional[str]) -> Optional["IntRangeSet"]:
        if spec is None:
            return None
        spec = spec.strip()
        if not spec:
            return None
        if spec.lower() == 'all':
            return cls(set(), [], wildcard=True)

        singles: Set[int] = set()
        ranges: List[Tuple[int, int]] = []
        for part in spec.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part[1:]:
                low, _, high = part.partition('-')
                ranges.append((int(low), int(high)))
            else:
                singles.add(int(part))
        return cls(singles, ranges)

    @classmethod
    def of(cls, values: Iterable[int]) -> "IntRangeSet":
        return cls(set(values), [])

    def contains(self, value: Any) -> bool:
        if self.wildcard:
            return True
        if not isinstance(value, int):
            return False
        if value in self.singles:
            return True
        return any(low <= value <= high for low, high in self.ranges)

    def __str__(self) -> str:
        if self.wildcard:
            return "all"
        parts = [str(v) for v in sorted(self.singles)]
        parts += [f"{low}-{high}" for low, high in self.ranges]
        return ','.join(parts)


@dataclass
class RuleSet:
    """
    Match and filter rules, applied on top of the baseline.

    Filters win over matchers: anything a filter catches is dropped, whatever the
    matchers say. Within one rule the values are OR'd, across rules they are AND'd,
    which is the ffuf semantics people already have in their fingers.
    """

    match_codes: Optional[IntRangeSet] = None
    match_sizes: Optional[IntRangeSet] = None
    match_words: Optional[IntRangeSet] = None
    match_lines: Optional[IntRangeSet] = None
    match_regex: Optional[re.Pattern] = None

    filter_codes: Optional[IntRangeSet] = None
    filter_sizes: Optional[IntRangeSet] = None
    filter_words: Optional[IntRangeSet] = None
    filter_lines: Optional[IntRangeSet] = None
    filter_regex: Optional[re.Pattern] = None

    @property
    def has_explicit_matcher(self) -> bool:
        return any((self.match_codes, self.match_sizes, self.match_words,
                    self.match_lines, self.match_regex))

    def keep(self, signature: ResponseSignature, body: str = "") -> bool:
        if self._filtered_out(signature, body):
            return False
        return self._matched(signature, body)

    def _filtered_out(self, signature: ResponseSignature, body: str) -> bool:
        if self.filter_codes and self.filter_codes.contains(signature.status):
            return True
        if self.filter_sizes and self.filter_sizes.contains(signature.length):
            return True
        if self.filter_words and self.filter_words.contains(signature.words):
            return True
        if self.filter_lines and self.filter_lines.contains(signature.lines):
            return True
        if self.filter_regex and body and self.filter_regex.search(body):
            return True
        return False

    def _matched(self, signature: ResponseSignature, body: str) -> bool:
        if self.match_codes and not self.match_codes.contains(signature.status):
            return False
        if self.match_sizes and not self.match_sizes.contains(signature.length):
            return False
        if self.match_words and not self.match_words.contains(signature.words):
            return False
        if self.match_lines and not self.match_lines.contains(signature.lines):
            return False
        if self.match_regex and not self.match_regex.search(body or ""):
            return False
        return True

    def describe(self) -> str:
        parts = []
        for label, rule in (("mc", self.match_codes), ("ms", self.match_sizes),
                            ("mw", self.match_words), ("ml", self.match_lines),
                            ("fc", self.filter_codes), ("fs", self.filter_sizes),
                            ("fw", self.filter_words), ("fl", self.filter_lines)):
            if rule:
                parts.append(f"{label}={rule}")
        if self.match_regex:
            parts.append(f"mr={self.match_regex.pattern}")
        if self.filter_regex:
            parts.append(f"fr={self.filter_regex.pattern}")
        return ', '.join(parts) if parts else "none"
