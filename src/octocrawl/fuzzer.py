"""
The fuzzing engine: a bounded queue fed from a streamed wordlist, N workers, and a
per-directory baseline so that only real differences get reported.

Shape of a run, one directory at a time:

    calibrate(dir) -> feed(dir) -> queue.join() barrier -> recurse into hits

The barrier is what makes this simple: a directory is fully drained before the next
one is calibrated, so each job always has its own baseline ready, the wordlist can be
re-read per directory, and termination is just "no directories left".
"""

import asyncio
import json
import random
import sys
import time

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from octocrawl.http_request import http_request, configure_client
from octocrawl.fuzz_rules import (DEFAULT_CALIBRATION_PROBES, DEFAULT_MATCH_CODES,
                                  Baseline, IntRangeSet, ResponseSignature, RuleSet,
                                  calibrate)
from octocrawl.ui import (clear_status_line, colored_text, format_fuzz_row,
                          gradient_text, print_fuzz_progress, print_report_box,
                          GREEN, LIGHT_PEACH, PURPLE)

# shared with the crawler: both engines throttle and detect blocking identically.
# these move to a common module if the queue/worker core ever gets extracted.
from octocrawl.crawler import (MAX_CRAWL_DELAY, RATE_HEURISTIC_THRESHOLD,
                               RATE_HEURISTIC_WINDOW, STEALTH_BACKOFF_SECONDS,
                               STEALTH_JITTER_RANGE, _CrawlDelayLimiter,
                               _parse_retry_after)

FUZZ_KEYWORD = "FUZZ"

# how many jobs may sit in the queue per worker. Small on purpose: this is the
# backpressure that keeps a 5-million-line wordlist from being loaded into RAM.
QUEUE_DEPTH_PER_WORKER = 4

# a fuzz run is two orders of magnitude louder than a crawl, so it gets a ceiling
# the user has to raise on purpose
DEFAULT_MAX_REQUESTS = 100_000

DEFAULT_WORKERS = 40
STEALTH_DEFAULT_WORKERS = 5

# a body given with no -X is a POST, which is what everyone means by it
DEFAULT_BODY_CONTENT_TYPE = "application/x-www-form-urlencoded"


@dataclass
class FuzzTarget:
    """One injection point being fuzzed: a request template plus its baselines."""

    url_template: str
    depth: int = 0
    # keyed by extension ('' for the bare word): /x.php and /x can have completely
    # different 'not found' answers, so they can't share one baseline
    baselines: Dict[str, Optional[Baseline]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.url_template


@dataclass
class FuzzResult:
    url: str
    term: str
    status: Any
    length: int
    words: int
    lines: int
    redirect: str = ""
    depth: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            'url': self.url,
            'term': self.term,
            'status': self.status,
            'length': self.length,
            'words': self.words,
            'lines': self.lines,
            'redirect': self.redirect,
            'depth': self.depth,
        }


class Fuzzer:
    def __init__(self, url_template, wordlist, *, extensions=None, max_workers=DEFAULT_WORKERS,
                 timeout=10, cookies=None, extra_headers=None, method=None, body=None,
                 rules=None, calibration_probes=DEFAULT_CALIBRATION_PROBES, calibrate_enabled=True,
                 recursion=False, recursion_depth=1, max_requests=DEFAULT_MAX_REQUESTS,
                 stealth=False, random_agent=False, custom_agent=None, follow_redirects=False):
        self.url_template = url_template
        self.wordlist = wordlist
        self.extensions = list(extensions or [])
        self.max_workers = max_workers
        self.timeout = timeout
        self.cookies = cookies or {}
        self.extra_headers = dict(extra_headers or {})
        self.body = body
        self.rules = rules or RuleSet()
        self.calibration_probes = calibration_probes
        self.calibrate_enabled = calibrate_enabled
        self.recursion = recursion
        self.recursion_depth = recursion_depth
        self.max_requests = max_requests
        self.stealth = stealth
        self.random_agent = random_agent
        self.custom_agent = custom_agent
        self.follow_redirects = follow_redirects

        # a body with no explicit verb means POST, and a form body with no declared
        # type is the one default worth filling in for the user
        self.method = method
        if body is not None and method is None:
            self.method = "POST"
        if body is not None and not any(k.lower() == 'content-type' for k in self.extra_headers):
            self.extra_headers['Content-Type'] = DEFAULT_BODY_CONTENT_TYPE

        self._fuzz_in_url = FUZZ_KEYWORD in url_template
        self._fuzz_in_headers = any(FUZZ_KEYWORD in v for v in self.extra_headers.values())
        self._fuzz_in_body = bool(body) and FUZZ_KEYWORD in body

        self.queue = asyncio.Queue(maxsize=max(1, max_workers * QUEUE_DEPTH_PER_WORKER))
        configure_client(max_workers)
        self.worker_tasks: List[asyncio.Task] = []

        # only matches are retained. everything else is counted and dropped, which is
        # the whole difference from the crawler's keep-everything model
        self.results: List[FuzzResult] = []

        self.requests_sent = 0
        self.jobs_done = 0
        self.errors = 0
        self.filtered = 0
        self.interrupted = False
        self.stop_reason = ""

        self._stopped = False
        self._queued = 0
        self._start_time = 0.0
        self._buffered_terms: Optional[List[str]] = None
        self._per_target_jobs = 0
        self._targets_seen = 1
        self._pending_targets: List[FuzzTarget] = []
        self._known_templates = {url_template}

        # a fuzz run is mostly 'not found' answers, so the crawler's flat
        # {403, 429, 5xx} rule would fire on the first window against any target that
        # answers 403 for missing paths. calibration tells us what normal looks like.
        self._baseline_statuses: set = set()
        self.recent_outcomes = deque(maxlen=RATE_HEURISTIC_WINDOW)
        self.heuristic_triggered_ratio = None
        self.rate_limiter = None
        self.rate_limited_urls = set()
        self.retry_after_values = set()

        if wordlist == '-':
            self._buffered_terms = self._clean_terms(sys.stdin.read().splitlines())

    # ------------------------------------------------------------------ wordlist

    @staticmethod
    def _clean_terms(lines) -> List[str]:
        terms = []
        for line in lines:
            term = line.strip()
            if not term or term.startswith('#'):
                continue
            # a leading slash is never meaningful in a path position and plenty of
            # public wordlists ship with them
            terms.append(term.lstrip('/'))
        return terms

    def _iter_terms(self):
        if self._buffered_terms is not None:
            yield from self._buffered_terms
            return
        with open(self.wordlist, encoding='utf-8', errors='replace') as handle:
            for line in handle:
                term = line.strip()
                if not term or term.startswith('#'):
                    continue
                yield term.lstrip('/')

    def _iter_jobs(self):
        """(term, extension-key) pairs: the bare word, then one per -e extension."""
        for term in self._iter_terms():
            yield term, ''
            for extension in self.extensions:
                yield term + extension, extension

    def count_terms(self) -> int:
        if self._buffered_terms is not None:
            return len(self._buffered_terms)
        try:
            with open(self.wordlist, 'rb') as handle:
                return sum(1 for line in handle
                           if line.strip() and not line.strip().startswith(b'#'))
        except OSError:
            return 0

    # ------------------------------------------------------------------ requests

    def _build_request(self, target: FuzzTarget, term: str) -> Tuple[str, Dict[str, str], Optional[str]]:
        url = target.url_template.replace(FUZZ_KEYWORD, term) if self._fuzz_in_url else target.url_template
        headers = ({k: v.replace(FUZZ_KEYWORD, term) for k, v in self.extra_headers.items()}
                   if self._fuzz_in_headers else self.extra_headers)
        body = self.body.replace(FUZZ_KEYWORD, term) if self._fuzz_in_body else self.body
        return url, headers, body

    async def _request(self, target: FuzzTarget, term: str) -> Dict[str, Any]:
        if self.rate_limiter:
            await self.rate_limiter.wait()
        if self.stealth:
            await asyncio.sleep(random.uniform(*STEALTH_JITTER_RANGE))

        url, headers, body = self._build_request(target, term)
        self.requests_sent += 1
        return await http_request(
            url,
            timeout=self.timeout,
            cookies=self.cookies,
            random_agent=self.random_agent,
            custom_agent=self.custom_agent,
            extra_headers=headers,
            # never let the extension decide GET vs HEAD here: the size and word
            # filters need a body, and '-e .jpg' would otherwise go out as a HEAD
            force_get=True,
            follow_redirects=self.follow_redirects,
            method=self.method,
            content=body,
        )

    # --------------------------------------------------------------- calibration

    async def _calibrate(self, target: FuzzTarget) -> None:
        for extension in [''] + self.extensions:
            def factory(token, suffix=extension):
                return self._request(target, token + suffix)

            baseline = await calibrate(factory, self.calibration_probes)
            target.baselines[extension] = baseline

            if baseline is None:
                self.log(f"calibration failed for {extension or 'bare terms'} "
                         f"(no probe completed), reporting everything the rules allow",
                         warn=True)
                continue

            self._baseline_statuses.update(s for s in baseline.statuses if isinstance(s, int))
            label = extension or 'bare terms'
            self.log(f"baseline [{label}]: {baseline.describe()}")

    # ----------------------------------------------------------- blocking signals

    def _is_blocking(self, code) -> bool:
        if code == 429:
            return True
        if not isinstance(code, int):
            return True
        if code in self._baseline_statuses:
            # this is simply what the target answers for something missing
            return False
        return code == 403 or code >= 500

    def _engage_backoff(self, seconds: float) -> None:
        seconds = min(seconds, MAX_CRAWL_DELAY)
        if self.rate_limiter is None or seconds > self.rate_limiter.interval:
            self.rate_limiter = _CrawlDelayLimiter(seconds)

    def _on_rate_limited(self, url: str, retry_after) -> None:
        first_hit = not self.rate_limited_urls
        self.rate_limited_urls.add(url)
        if retry_after:
            self.retry_after_values.add(str(retry_after))
        if not first_hit:
            return

        message = f"⚠️  Rate limiting detected (HTTP 429) on {url}"
        if retry_after:
            message += f", Retry-After: {retry_after}"
        backoff = _parse_retry_after(retry_after) or STEALTH_BACKOFF_SECONDS
        self._engage_backoff(backoff)
        message += f", backing off to {min(backoff, MAX_CRAWL_DELAY):.0f}s between requests"
        self.log(message, warn=True)

    def _record_outcome(self, code) -> None:
        self.recent_outcomes.append(self._is_blocking(code))
        if self.heuristic_triggered_ratio is not None or len(self.recent_outcomes) < self.recent_outcomes.maxlen:
            return

        ratio = sum(self.recent_outcomes) / len(self.recent_outcomes)
        if ratio < RATE_HEURISTIC_THRESHOLD:
            return

        self.heuristic_triggered_ratio = ratio
        message = (f"⚠️  Possible blocking: {ratio:.0%} of the last {RATE_HEURISTIC_WINDOW} "
                   f"requests were refused in a way the baseline does not explain")
        if self.stealth:
            self._engage_backoff(STEALTH_BACKOFF_SECONDS)
            message += f", backing off to {STEALTH_BACKOFF_SECONDS:.0f}s between requests"
        self.log(message, warn=True)

    # -------------------------------------------------------------------- workers

    async def _worker(self) -> None:
        while True:
            job = None
            try:
                job = await self.queue.get()
                await self._process(job)
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.errors += 1
                clear_status_line()
                print(f"[!] {type(error).__name__} on '{job[1] if job else '?'}': {error}",
                      file=sys.stderr)
            finally:
                # only a job actually taken off the queue needs acknowledging; being
                # cancelled while waiting in queue.get() leaves job as None
                if job is not None:
                    self.queue.task_done()

    async def _process(self, job) -> None:
        target, term, extension = job
        response = await self._request(target, term)
        signature = ResponseSignature.from_response(response)

        self.jobs_done += 1
        if not isinstance(signature.status, int):
            self.errors += 1
        elif signature.status == 429:
            self._on_rate_limited(response.get('final_url', term), response['headers'].get('retry-after'))
        self._record_outcome(signature.status)

        self._report_progress()

        baseline = target.baselines.get(extension)
        if baseline is not None and baseline.matches(signature):
            self.filtered += 1
            return

        body = response.get('content') or ''
        if not self.rules.keep(signature, body):
            self.filtered += 1
            return

        url, _, _ = self._build_request(target, term)
        result = FuzzResult(
            url=url,
            term=term,
            status=signature.status,
            length=signature.length,
            words=signature.words,
            lines=signature.lines,
            redirect=response.get('headers', {}).get('location', ''),
            depth=target.depth,
        )
        self.results.append(result)
        self._print_result(result)

        if self.recursion:
            self._queue_recursion(target, result)

    # ------------------------------------------------------------------ recursion

    def _queue_recursion(self, target: FuzzTarget, result: FuzzResult) -> None:
        if target.depth >= self.recursion_depth or not self._fuzz_in_url:
            return
        if not self._looks_like_directory(result):
            return

        template = target.url_template.replace(FUZZ_KEYWORD, f"{result.term}/{FUZZ_KEYWORD}")
        if template in self._known_templates:
            return
        self._known_templates.add(template)
        self._pending_targets.append(FuzzTarget(template, target.depth + 1))

    @staticmethod
    def _looks_like_directory(result: FuzzResult) -> bool:
        status = result.status
        if not isinstance(status, int):
            return False
        # the classic directory handler answer: /admin -> 301 /admin/
        if 300 <= status < 400 and result.redirect:
            path = urlparse(urljoin(result.url, result.redirect)).path
            return path.endswith('/') and path.rstrip('/').endswith(result.term.rstrip('/'))
        if 200 <= status < 300:
            return result.url.endswith('/')
        return False

    # ----------------------------------------------------------------- the engine

    async def _feed(self, target: FuzzTarget) -> None:
        for term, extension in self._iter_jobs():
            if self._stopped:
                return
            if self._queued >= self.max_requests:
                self._stop(f"request cap reached ({self.max_requests})")
                return
            self._queued += 1
            # blocks once the queue is full: this is the backpressure that keeps the
            # wordlist streaming instead of being buffered
            await self.queue.put((target, term, extension))

    def _stop(self, reason: str) -> None:
        if not self._stopped:
            self._stopped = True
            self.stop_reason = reason
            self.log(f"stopping: {reason}", warn=True)

    async def _shutdown(self) -> None:
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

    async def run(self) -> List[FuzzResult]:
        self._start_time = time.monotonic()
        self._per_target_jobs = self.count_terms() * (1 + len(self.extensions))
        self.worker_tasks = [asyncio.create_task(self._worker()) for _ in range(self.max_workers)]

        pending = deque([FuzzTarget(self.url_template)])
        try:
            while pending and not self._stopped:
                target = pending.popleft()
                if target.depth:
                    self.log(f"recursing into {target.label}")
                if self.calibrate_enabled:
                    await self._calibrate(target)

                await self._feed(target)
                # barrier: this directory is fully drained before the next one is
                # calibrated, so a job's baseline is always the right one
                await self.queue.join()

                if self._pending_targets:
                    pending.extend(self._pending_targets)
                    self._targets_seen += len(self._pending_targets)
                    self._pending_targets = []
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.interrupted = True
            self.stop_reason = "interrupted by user"
        finally:
            await self._shutdown()

        self.elapsed = time.monotonic() - self._start_time
        return self.results

    # -------------------------------------------------------------------- output

    def log(self, message: str, warn: bool = False) -> None:
        clear_status_line()
        print(gradient_text(message) if not warn else colored_text(message, LIGHT_PEACH))

    def _report_progress(self) -> None:
        total = self._per_target_jobs * self._targets_seen if self._per_target_jobs else 0
        print_fuzz_progress(self.jobs_done, total, max(time.monotonic() - self._start_time, 1e-9),
                            len(self.results), self.errors)

    def _print_result(self, result: FuzzResult) -> None:
        note = f"-> {result.redirect}" if result.redirect else ""
        clear_status_line()
        print(format_fuzz_row(result.term, result.status, result.length,
                              result.words, result.lines, note))

    @property
    def summary(self) -> Dict[str, Any]:
        elapsed = getattr(self, 'elapsed', time.monotonic() - self._start_time)
        data = {
            "Requests sent": self.requests_sent,
            "Duration": f"{elapsed:.1f}s",
            "Throughput": f"{self.requests_sent / elapsed:.0f} req/s" if elapsed > 0 else "n/a",
            "Hits": len(self.results),
            "Filtered": self.filtered,
        }
        if self.errors:
            data["Errors"] = self.errors
        if self.rate_limited_urls:
            data["429 Responses"] = len(self.rate_limited_urls)
            if self.retry_after_values:
                data["Retry-After seen"] = ', '.join(sorted(self.retry_after_values))
        if self.heuristic_triggered_ratio is not None:
            data["Blocking spike"] = f"{self.heuristic_triggered_ratio:.0%} of a {RATE_HEURISTIC_WINDOW}-request window"
        if self.stop_reason:
            data["Stopped"] = self.stop_reason
        return data

    def save(self, output_file: str) -> None:
        try:
            if output_file.lower().endswith('.json'):
                payload = {
                    'target': self.url_template,
                    'wordlist': self.wordlist,
                    'summary': self.summary,
                    'results': [r.as_dict() for r in self.results],
                }
                with open(output_file, 'w', encoding='utf-8') as handle:
                    json.dump(payload, handle, indent=2)
            else:
                with open(output_file, 'w', encoding='utf-8') as handle:
                    for result in self.results:
                        handle.write(f"{result.status}\t{result.length}\t{result.url}"
                                     f"{chr(9) + result.redirect if result.redirect else ''}\n")
            print(f"Results saved to {output_file}")
        except OSError as error:
            print(f"\nError saving results to {output_file}: {error}", file=sys.stderr)


def build_rules(args) -> RuleSet:
    """Turn the -m*/-f* flags into a RuleSet, filling in a default matcher if needed."""
    import re

    match_codes = IntRangeSet.parse(args.match_code)
    # with calibration on, the baseline already removes the noise, so an explicit
    # status matcher is optional. Without it, fall back to the interesting statuses.
    if match_codes is None and args.no_calibrate:
        match_codes = IntRangeSet.of(DEFAULT_MATCH_CODES)

    return RuleSet(
        match_codes=match_codes,
        match_sizes=IntRangeSet.parse(args.match_size),
        match_words=IntRangeSet.parse(args.match_words),
        match_lines=IntRangeSet.parse(args.match_lines),
        match_regex=re.compile(args.match_regex) if args.match_regex else None,
        filter_codes=IntRangeSet.parse(args.filter_code),
        filter_sizes=IntRangeSet.parse(args.filter_size),
        filter_words=IntRangeSet.parse(args.filter_words),
        filter_lines=IntRangeSet.parse(args.filter_lines),
        filter_regex=re.compile(args.filter_regex) if args.filter_regex else None,
    )
