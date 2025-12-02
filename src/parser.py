from urllib.parse import urljoin, urlparse
import bs4
import re
import json

def search_text_for_keywords(text, keywords):
    found_keywords = {}
    if not keywords or not text:
        return found_keywords
    
    text_lower = text.lower()
    
    for keyword in keywords:
        count = text_lower.count(keyword.lower())
        if count > 0:
            found_keywords[keyword] = count
    
    return found_keywords


class html_parser:
    URL_IN_TEXT_PATTERN = re.compile(r'url\((["\']?)(.*?)\1\)', re.IGNORECASE)

    def __init__(self, content, base_url, soup=None, parser='html.parser'):
        self.soup = soup if soup is not None else bs4.BeautifulSoup(content, parser)
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        
        self._links_cache = None
        self._text_cache = None

    def find_keywords(self, keywords):
        if self._text_cache is None:
            self._text_cache = self.soup.get_text()
        return search_text_for_keywords(self._text_cache, keywords)

    @property
    def internal_links(self):
        if self._links_cache is not None:
            return self._links_cache
        
        all_links = set()
        
        tags_to_find = {
            'a': 'href', 
            'img': 'src', 
            'link': 'href', 
            'script': 'src',
            'iframe': 'src',
            'source': 'src',
            'video': 'src',
            'audio': 'src'
        }
        
        for tag_name, attribute in tags_to_find.items():
            for tag in self.soup.find_all(tag_name, **{attribute: True}):
                link_path = tag.get(attribute)
                if not link_path:
                    continue
                
                link_lower = link_path.strip().lower()
                if link_lower.startswith(('mailto:', 'tel:', 'javascript:', 'data:', '#')):
                    continue
                
                try:
                    absolute_link = urljoin(self.base_url, link_path)
                    parsed = urlparse(absolute_link)
                    
                    if parsed.netloc == self.base_domain:
                        clean_url = urlparse(absolute_link)._replace(fragment='')
                        all_links.add(clean_url.geturl())
                except Exception:
                    continue

        style_tags = list(self.soup.find_all('style'))
        
        for tag in self.soup.find_all(style=True):
            style_content = tag.get('style', '')
            if style_content:
                for _, url in self.URL_IN_TEXT_PATTERN.findall(style_content):
                    try:
                        absolute_link = urljoin(self.base_url, url.strip())
                        if urlparse(absolute_link).netloc == self.base_domain:
                            clean_url = urlparse(absolute_link)._replace(fragment='')
                            all_links.add(clean_url.geturl())
                    except Exception:
                        continue
        
        for style_tag in style_tags:
            style_content = style_tag.string if style_tag.string else ""
            for _, url in self.URL_IN_TEXT_PATTERN.findall(style_content):
                try:
                    absolute_link = urljoin(self.base_url, url.strip())
                    if urlparse(absolute_link).netloc == self.base_domain:
                        clean_url = urlparse(absolute_link)._replace(fragment='')
                        all_links.add(clean_url.geturl())
                except Exception:
                    continue

        self._links_cache = list(all_links)
        return self._links_cache


class json_parser:
    LINK_KEYS = {'href', 'url', 'src', 'link', 'guid', 'uri', 'path', 'location'}

    def __init__(self, content, base_url):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.raw_content = content
        
        try:
            self.data = json.loads(content)
        except json.JSONDecodeError:
            self.data = {}
        
        self._links_cache = None

    def find_keywords(self, keywords):
        return search_text_for_keywords(self.raw_content, keywords)

    def _find_urls_recursive(self, data_structure, depth=0, max_depth=10):
        if depth > max_depth:
            return set()
        
        found_urls = set()
        
        if isinstance(data_structure, dict):
            for key, value in data_structure.items():
                if key in self.LINK_KEYS and isinstance(value, str):
                    found_urls.add(value)
                elif isinstance(value, (dict, list)):
                    found_urls.update(self._find_urls_recursive(value, depth + 1, max_depth))
        
        elif isinstance(data_structure, list):
            for item in data_structure:
                if isinstance(item, (dict, list)):
                    found_urls.update(self._find_urls_recursive(item, depth + 1, max_depth))
                elif isinstance(item, str):
                    if item.startswith(('http://', 'https://', '/', './')):
                        found_urls.add(item)
        
        return found_urls

    @property
    def internal_links(self):
        if self._links_cache is not None:
            return self._links_cache
        
        if not self.data:
            self._links_cache = []
            return self._links_cache

        discovered_urls = self._find_urls_recursive(self.data)
        internal_links = set()

        for link in discovered_urls:
            clean_link = link.strip('",\'\\() \t\n\r')
            if not clean_link:
                continue

            try:
                absolute_link = urljoin(self.base_url, clean_link)
                parsed = urlparse(absolute_link)
                
                if parsed.netloc == self.base_domain:
                    clean_url = parsed._replace(fragment='')
                    internal_links.add(clean_url.geturl())
            except Exception:
                continue
        
        self._links_cache = list(internal_links)
        return self._links_cache


class dir_listing_parser:
    def __init__(self, content, base_url, soup=None, parser='html.parser'):
        self.soup = soup if soup is not None else bs4.BeautifulSoup(content, parser)
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.raw_content = content
        
        self._links_cache = None

    def find_keywords(self, keywords):
        return search_text_for_keywords(self.raw_content, keywords)

    @property
    def internal_links(self):
        if self._links_cache is not None:
            return self._links_cache
        
        links = set()
        ignored_hrefs = {'/', '../', '?C=N;O=D', '?C=M;O=A', '?C=S;O=A', '?C=D;O=A'}

        for tag in self.soup.find_all('a', href=True):
            href = tag['href']
            
            if not href or href.startswith('?') or href in ignored_hrefs:
                continue
            
            try:
                absolute_link = urljoin(self.base_url, href)
                parsed = urlparse(absolute_link)
                
                if parsed.netloc == self.base_domain:
                    clean_url = parsed._replace(fragment='')
                    links.add(clean_url.geturl())
            except Exception:
                continue
        
        self._links_cache = list(links)
        return self._links_cache


class xml_parser:
    def __init__(self, content, base_url):
        self.content = content
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self._links_cache = None
    
    def find_keywords(self, keywords):
        return search_text_for_keywords(self.content, keywords)
    
    @property
    def internal_links(self):
        if self._links_cache is not None:
            return self._links_cache
        
        url_pattern = re.compile(r'<loc>(.*?)</loc>', re.IGNORECASE)
        links = set()
        
        for match in url_pattern.findall(self.content):
            url = match.strip()
            try:
                if urlparse(url).netloc == self.base_domain:
                    links.add(url)
            except Exception:
                continue
        
        self._links_cache = list(links)
        return self._links_cache