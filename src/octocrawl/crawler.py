import asyncio
import json
import random
import sys
import time
import bs4

from collections import deque
from urllib.parse import urlparse, urlunparse, parse_qsl
from octocrawl.http_request import http_request, configure_client
from octocrawl.parser import html_parser, json_parser, dir_listing_parser, canonical_host, same_site, search_text_for_keywords
from octocrawl.tree_maker import TreeMaker
from octocrawl.ui import print_status_line, gradient_text, whole_line
from octocrawl.fingerprint import fingerprint_technologies
from octocrawl.robots_sitemap import check_robots_txt, check_sitemaps, discover_sitemaps


# robots.txt is attacker-controlled input, cap whatever Crawl-delay it asks for
MAX_CRAWL_DELAY = 30.0

# a lot of WAFs don't bother with a clean 429, they just fail most requests once
# they decide you're a bot - catch that by watching the failure rate over a window
RATE_HEURISTIC_WINDOW = 20
RATE_HEURISTIC_THRESHOLD = 0.7
# 404s (and the like) are normal while crawling - especially since we probe parent
# directories and robots.txt paths - only these codes look like a WAF pushing back
BLOCKING_STATUS_CODES = {403, 429}

STEALTH_DEFAULT_WORKERS = 10
STEALTH_JITTER_RANGE = (0.2, 0.8)
STEALTH_BACKOFF_SECONDS = 5.0


def _parse_retry_after(value):
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class _CrawlDelayLimiter:
    # keeps requests spaced `interval` seconds apart across all workers combined
    def __init__(self, interval: float):
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next_allowed_time = 0.0

    async def wait(self):
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            delay = self._next_allowed_time - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = loop.time()
            self._next_allowed_time = now + self.interval


def _is_blocking_signal(code):
    return not isinstance(code, int) or code in BLOCKING_STATUS_CODES or code >= 500


def _parse_content(content, content_type, base_url, parser_engine, keywords, headers):
    # runs in a worker thread (see worker()), this is CPU-bound and would
    # otherwise stall the event loop for every other in-flight request
    found_tech = fingerprint_technologies(headers, content)
    parser = None

    if 'html' in content_type:
        soup = bs4.BeautifulSoup(content, parser_engine)
        # .string is None for an empty <title> (or one with nested tags)
        is_listing = soup.title is not None and "Index of /" in soup.title.get_text()
        parser = (dir_listing_parser(content, base_url, soup=soup, parser=parser_engine)
                  if is_listing else
                  html_parser(content, base_url, soup=soup, parser=parser_engine))
    elif 'json' in content_type:
        parser = json_parser(content, base_url)

    if not parser:
        # non-parsed body (css/js/txt/...): still keyword-search it if asked,
        # otherwise it was fetched for nothing (and usually it wasn't fetched at all)
        found_keywords = search_text_for_keywords(content, keywords) if keywords else {}
        return [], found_keywords, found_tech

    links = parser.internal_links
    found_keywords = parser.find_keywords(keywords) if keywords else {}
    return links, found_keywords, found_tech


class crawler:
    def __init__(self, start_url, max_workers=50, timeout=5, cookies=None, parser="lxml", random_agent=False, custom_agent=None, stealth=False):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.timeout = timeout
        self.cookies = cookies if cookies is not None else {}
        self.parser_engine = parser
        
        self.queue = asyncio.Queue()
        self.visited_urls = {self._dedup_key(start_url)}
        self.gathered_urls = {}
        self.sitemap = {}

        # names of every query parameter seen in a link, since queries are
        # stripped from the URLs we crawl (see _normalize_url)
        self.query_params = set()
        # response headers of every crawled HTML page, for header-level analysis
        self.page_headers = {}
        self.interrupted = False

        # note: no locks around the shared state below. everything runs on one
        # event loop thread and none of the updates await midway, so they're atomic

        self.max_workers = max_workers
        configure_client(max_workers)
        self.worker_tasks = []

        self.technologies = {}
        self.random_agent = random_agent
        self.custom_agent = custom_agent
        self.stealth = stealth
        self.rate_limiter = None

        self.rate_limited_urls = set()
        self.retry_after_values = set()

        self.recent_outcomes = deque(maxlen=RATE_HEURISTIC_WINDOW)
        self.heuristic_triggered_ratio = None

    @staticmethod
    def _normalize_url(url):
        # the URL we actually queue and fetch: only strip query/fragment, keep the
        # real scheme and host so http-only or www-only hosts still resolve
        return urlunparse(urlparse(url)._replace(query='', fragment=''))

    @staticmethod
    def _dedup_key(url):
        # one key per logical page: unify http/https, www/apex, case and empty
        # path, so the same page isn't crawled twice under a different name
        parsed = urlparse(url)
        scheme = 'https' if parsed.scheme == 'http' else parsed.scheme
        return urlunparse(parsed._replace(
            scheme=scheme, netloc=canonical_host(parsed.netloc),
            path=parsed.path or '/', query='', fragment=''))

    @property
    def rate_limit_summary(self):
        summary = {}
        if self.rate_limited_urls:
            summary["429 Responses"] = len(self.rate_limited_urls)
            if self.retry_after_values:
                summary["Retry-After seen"] = ", ".join(sorted(self.retry_after_values))
        if self.heuristic_triggered_ratio is not None:
            summary["Blocking spike detected"] = f"{self.heuristic_triggered_ratio:.0%} of last {RATE_HEURISTIC_WINDOW} requests"
        return summary

    def _engage_backoff(self, seconds):
        seconds = min(seconds, MAX_CRAWL_DELAY)
        if self.rate_limiter is None or seconds > self.rate_limiter.interval:
            self.rate_limiter = _CrawlDelayLimiter(seconds)

    def _add_to_sitemap(self, url, url_data):
        parsed_url = urlparse(url)
        path_segments = [s for s in parsed_url.path.split('/') if s]
        if not path_segments:
            self.sitemap.setdefault('/', {}).update({'_data': url_data})
            return
        current_level = self.sitemap
        for segment in path_segments[:-1]:
            current_level = current_level.setdefault(segment, {})
        current_level.setdefault(path_segments[-1], {}).update({'_data': url_data})

    @staticmethod
    def _get_ancestor_directory_urls(url):
        # /a/b/c/file.html -> [".../a/", ".../a/b/", ".../a/b/c/"], derived straight
        # from the path so we don't need to walk the sitemap tree to find directories
        parsed = urlparse(url)
        # a malformed link (e.g. "hhttps://...") can slip through the crawl; don't
        # let it spawn an equally malformed directory URL to chase
        if parsed.scheme not in ('http', 'https'):
            return []
        base = f"{parsed.scheme}://{parsed.netloc}"
        segments = [s for s in parsed.path.split('/') if s]

        dirs = []
        accumulated = ""
        for segment in segments[:-1]:
            accumulated += f"/{segment}"
            dirs.append(f"{base}{accumulated}/")
        return dirs

    def _enqueue(self, url):
        key = self._dedup_key(url)
        if key not in self.visited_urls:
            self.visited_urls.add(key)
            self.queue.put_nowait(self._normalize_url(url))

    def _build_urls_from_paths(self, paths):
        urls = []
        parsed_start = urlparse(self.start_url)
        base_url = f"{parsed_start.scheme}://{parsed_start.netloc}"
        
        for path in paths:
            path = path.strip()
            if not path:
                continue
            if not path.startswith('/'):
                path = '/' + path
            full_url = base_url + path
            urls.append(full_url)
        
        return urls

    async def worker(self, keywords=None):
        while True:
            url_to_process = None
            try:
                url_to_process = await self.queue.get()

                if self.rate_limiter:
                    await self.rate_limiter.wait()

                if self.stealth:
                    await asyncio.sleep(random.uniform(*STEALTH_JITTER_RANGE))

                request = await http_request(
                    url_to_process,
                    timeout=self.timeout,
                    cookies=self.cookies,
                    random_agent=self.random_agent,
                    custom_agent=self.custom_agent,
                    include_text=bool(keywords)
                )
                code = request['response_code']

                print_status_line(f"Checked: {url_to_process} [{code}]")

                if code == 429:
                    self._on_rate_limited(url_to_process, request['headers'].get('retry-after'))
                self._record_outcome(code)

                canonical_url = self._normalize_url(url_to_process)
                url_data = {
                    'code': code,
                    'content_type': request["content_type"],
                    'url': canonical_url,
                    'keywords': {}
                }

                # the body belongs to wherever the redirects ended up: resolve relative
                # links against that, and don't parse/fingerprint someone else's site
                final_url = request["final_url"]
                if self._normalize_url(final_url) != canonical_url:
                    url_data['final_url'] = final_url
                on_site = same_site(urlparse(final_url).netloc, self.base_domain)

                if request['done'] and on_site:
                    if code == 200 and request["content"]:
                        loop = asyncio.get_running_loop()
                        links, found_keywords, found_tech = await loop.run_in_executor(
                            None, _parse_content, request["content"], request["content_type"],
                            final_url, self.parser_engine, keywords, request['headers']
                        )
                        for link in links:
                            query = urlparse(link).query
                            if query:
                                self.query_params.update(name for name, _ in parse_qsl(query, keep_blank_values=True))
                            self._enqueue(link)
                        if found_keywords:
                            url_data['keywords'] = found_keywords
                    else:
                        found_tech = fingerprint_technologies(request['headers'], request['content'])

                    self.technologies.update(found_tech)
                    if 'html' in request["content_type"]:
                        self.page_headers[canonical_url] = request['headers']

                self.gathered_urls[self._dedup_key(url_to_process)] = url_data
                self._add_to_sitemap(canonical_url, url_data)

                for dir_url in self._get_ancestor_directory_urls(canonical_url):
                    self._enqueue(dir_url)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"\n[!] Error processing {url_to_process}: {type(e).__name__}. Skipping.")
            finally:
                if url_to_process:
                    self.queue.task_done()

    def _on_rate_limited(self, url, retry_after):
        first_hit = not self.rate_limited_urls
        self.rate_limited_urls.add(self._dedup_key(url))
        if retry_after:
            self.retry_after_values.add(retry_after)
        if not first_hit:
            return

        msg = f"\n⚠️  Rate limiting detected (HTTP 429) on {url}"
        if retry_after:
            msg += f", Retry-After: {retry_after}"
        if self.stealth:
            backoff = _parse_retry_after(retry_after) or STEALTH_BACKOFF_SECONDS
            self._engage_backoff(backoff)
            msg += f", backing off to {backoff:.0f}s between requests"
        print(gradient_text(msg))

    def _record_outcome(self, code):
        self.recent_outcomes.append(_is_blocking_signal(code))
        if self.heuristic_triggered_ratio is not None or len(self.recent_outcomes) < self.recent_outcomes.maxlen:
            return

        ratio = sum(self.recent_outcomes) / len(self.recent_outcomes)
        if ratio < RATE_HEURISTIC_THRESHOLD:
            return

        self.heuristic_triggered_ratio = ratio
        msg = (f"\n⚠️  Possible blocking detected: {ratio:.0%} of the last {RATE_HEURISTIC_WINDOW} "
               f"requests were refused (403/429/5xx/network error)")
        if self.stealth:
            self._engage_backoff(STEALTH_BACKOFF_SECONDS)
            msg += f", backing off to {STEALTH_BACKOFF_SECONDS:.0f}s between requests"
        print(gradient_text(msg))

    async def _crawl_loop(self, keywords=None):
        self.worker_tasks = [asyncio.create_task(self.worker(keywords)) for _ in range(self.max_workers)]
        await self.queue.join()

    async def shutdown(self):
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

    async def crawl(self, show_url_in_tree=False, noshow_extensions=None, display_extensions=None, keywords=None, output_file=None, additional_paths=None, check_robots=True, check_sitemap=True):
        start_time = time.time()
        
        robots_paths = []
        sitemap_urls = []
        
        if check_robots:
            robots_result = await check_robots_txt(self.start_url, http_request, custom_agent=self.custom_agent)

            # Allow lines are as interesting as Disallow ones: both name real paths
            robots_paths = robots_result['disallowed_paths'] + robots_result['allowed_paths']
            if robots_paths:
                print(gradient_text(f"🐙 Adding {len(robots_paths)} paths from robots.txt..."))
            
            if robots_result['sitemaps']:
                sitemap_urls.extend(robots_result['sitemaps'])

            if robots_result['crawl_delay']:
                delay = min(robots_result['crawl_delay'], MAX_CRAWL_DELAY)
                self.rate_limiter = _CrawlDelayLimiter(delay)
                capped_note = f" (capped from {robots_result['crawl_delay']}s)" if delay < robots_result['crawl_delay'] else ""
                print(gradient_text(f"🐌 Enforcing crawl-delay: {delay}s between requests{capped_note}"))

        all_sitemap_urls = []
        if check_sitemap:
            if not sitemap_urls:
                sitemap_urls = await discover_sitemaps(self.start_url, http_request, custom_agent=self.custom_agent)

            all_sitemap_urls = await check_sitemaps(sitemap_urls, http_request, self.base_domain, custom_agent=self.custom_agent)
            
            if all_sitemap_urls:
                print(gradient_text(f"🐙 Adding {len(all_sitemap_urls)} URLs from sitemap(s)..."))
        
        self.queue.put_nowait(self.start_url)
        
        if additional_paths:
            additional_urls = self._build_urls_from_paths(additional_paths)
            print(gradient_text(f"🐙 Adding {len(additional_urls)} additional paths to crawl..."))
            for url in additional_urls:
                self._enqueue(url)
        
        for url in robots_paths + all_sitemap_urls:
            self._enqueue(url)
        
        try:
            await self._crawl_loop(keywords)
        except asyncio.CancelledError:
            # swallowed on purpose so the partial results still get printed below,
            # the caller checks self.interrupted to skip whatever comes next
            self.interrupted = True
            print(gradient_text("\n🐙 Crawl interrupted by user, showing partial results."))
        finally:
            await self.shutdown()
        
        end_time = time.time()
        
        print(f"\r{whole_line()}")
        print(gradient_text("🐙 Crawl finished. Generating sitemap tree..."))
        
        tree_maker = TreeMaker(base_url=self.start_url, noshow=noshow_extensions, display_only=display_extensions)
        tree_maker.print_tree(self.sitemap, show_url=show_url_in_tree)

        total_urls = len(self.gathered_urls)
        summary_line = f"\nGathered {total_urls} unique URLs in {round(end_time-start_time, 3)} seconds"
        print(summary_line)

        if output_file:
            print(f"Saving report to {output_file}...")
            try:
                if output_file.lower().endswith('.json'):
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(self.sitemap, f, indent=4)
                else:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        tree_maker.print_tree(self.sitemap, show_url=show_url_in_tree, output_stream=f)
                        f.write(summary_line + "\n")
                print(f"Report saved successfully.")
            except Exception as e:
                print(f"\nError saving report to {output_file}: {e}", file=sys.stderr)