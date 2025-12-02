import asyncio
import json
import sys
import time
import bs4

from urllib.parse import urlparse, urlunparse, urljoin
from http_request import http_request
from parser import html_parser, json_parser, dir_listing_parser
from tree_maker import TreeMaker
from ui import print_status_line, gradient_text, whole_line
from fingerprint import fingerprint_technologies

class crawler:
    def __init__(self, start_url, max_workers=50, timeout=5, cookies=None, parser="lxml", random_agent=False):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.timeout = timeout
        self.cookies = cookies if cookies is not None else {}
        self.parser_engine = parser
        
        self.queue = asyncio.Queue()
        self.visited_urls = {self._normalize_url(start_url)}
        self.gathered_urls = {}
        self.sitemap = {}
        self.checked_for_listing = set()

        self.max_workers = max_workers
        self.print_lock = asyncio.Lock()
        self.sitemap_lock = asyncio.Lock()
        self.queue_lock = asyncio.Lock()
        self.worker_tasks = []

        self.technologies = {}
        self.tech_lock = asyncio.Lock()
        self.random_agent = random_agent

    @staticmethod
    def _normalize_url(url):
        return urlunparse(urlparse(url)._replace(query='', fragment=''))

    def _add_to_sitemap(self, url, url_data):
        parsed_url = urlparse(url)
        path_segments = parsed_url.path.strip('/').split('/') if parsed_url.path.strip('/') else []
        current_level = self.sitemap
        if not path_segments or (len(path_segments) == 1 and path_segments[0] == ''):
            self.sitemap.setdefault('/', {}).update({'_data': url_data})
            return
        for segment in path_segments[:-1]:
            if not segment: continue
            current_level = current_level.setdefault(segment, {})
        last_segment = path_segments[-1]
        if last_segment:
             current_level.setdefault(last_segment, {}).update({'_data': url_data})

    async def worker(self, keywords=None):
        while True:
            url_to_process = None
            try:
                url_to_process = await self.queue.get()

                request = await http_request(url_to_process, timeout=self.timeout, cookies=self.cookies, random_agent=self.random_agent)
                
                async with self.print_lock:
                    print_status_line(f"Checked: {url_to_process} [{request['response_code']}]")

                if request['done']:
                    found_tech = fingerprint_technologies(request['headers'], request['content'])
                    if found_tech:
                        async with self.tech_lock:
                            self.technologies.update(found_tech)

                canonical_url = self._normalize_url(url_to_process)
                
                async with self.sitemap_lock:
                    if canonical_url in self.gathered_urls:
                        self.queue.task_done()
                        continue

                url_data = { 
                    'code': request["response_code"], 
                    'content_type': request["content_type"], 
                    'url': canonical_url, 
                    'keywords': {}
                }

                if request["done"] and request["response_code"] == 200 and request["content"]:
                    parser = None
                    content, ctype = request["content"], request["content_type"]

                    if 'html' in ctype:
                        soup = bs4.BeautifulSoup(content, self.parser_engine)
                        is_listing = soup.title and "Index of /" in soup.title.string
                        parser = dir_listing_parser(content, canonical_url, soup=soup, parser=self.parser_engine) if is_listing else html_parser(content, canonical_url, soup=soup, parser=self.parser_engine)
                    elif 'json' in ctype:
                        parser = json_parser(content, canonical_url)
                    
                    if parser:
                        for link in parser.internal_links:
                            normalized_link = self._normalize_url(link)
                            async with self.queue_lock:
                                if normalized_link not in self.visited_urls:
                                    self.visited_urls.add(normalized_link)
                                    await self.queue.put(normalized_link)
                        if keywords:
                            url_data['keywords'] = parser.find_keywords(keywords)
                
                async with self.sitemap_lock:
                    self.gathered_urls[canonical_url] = url_data
                    self._add_to_sitemap(canonical_url, url_data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                async with self.print_lock:
                    print(f"\n[!] Error processing {url_to_process}: {type(e).__name__}. Skipping.")
            finally:
                if url_to_process:
                    self.queue.task_done()

    async def _crawl_loop(self, keywords=None):
        self.worker_tasks = [asyncio.create_task(self.worker(keywords)) for _ in range(self.max_workers)]
        await self.queue.join()

    def _get_all_directory_urls(self, sitemap_node=None, current_path_url=None):
        if sitemap_node is None: sitemap_node = self.sitemap
        if current_path_url is None: current_path_url = self.start_url
        dir_urls = set()
        for key, value in sitemap_node.items():
            children = {k: v for k, v in value.items() if k != '_data'}
            if children:
                base_for_join = current_path_url if current_path_url.endswith('/') else current_path_url + '/'
                dir_url = urljoin(base_for_join, key + '/')
                dir_urls.add(dir_url)
                dir_urls.update(self._get_all_directory_urls(children, dir_url))
        return dir_urls
    
    async def shutdown(self):
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

    async def crawl(self, show_url_in_tree=False, noshow_extensions=None, display_extensions=None, keywords=None, output_file=None):
        start_time = time.time()
        self.queue.put_nowait(self.start_url)
        
        try:
            await self._crawl_loop(keywords)
            print(f"\r{whole_line()}")
            
            while True:
                all_dirs = self._get_all_directory_urls()
                new_dirs_to_check = all_dirs - self.checked_for_listing
                if not new_dirs_to_check: 
                    break
                
                async with self.queue_lock:
                    for d in new_dirs_to_check:
                        normalized_dir = self._normalize_url(d)
                        if normalized_dir not in self.visited_urls:
                            self.visited_urls.add(normalized_dir)
                            await self.queue.put(d)
                
                self.checked_for_listing.update(new_dirs_to_check)
                await self._crawl_loop(keywords)
                    
        except asyncio.CancelledError:
            async with self.print_lock: 
                print(gradient_text("\n🐙 Crawl cancelled by user. Exiting."))
        finally:
            await self.shutdown()
        
        end_time = time.time()
        
        async with self.print_lock: 
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