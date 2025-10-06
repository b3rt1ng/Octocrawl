from urllib.parse import urljoin, urlparse
import bs4
import re
import json

def search_text_for_keywords(text, keywords):
    found_keywords = {}
    if not keywords or not text:
        return found_keywords

    for keyword in keywords:
        matches = re.findall(keyword, text, re.IGNORECASE)
        if matches:
            found_keywords[keyword] = len(matches)
    
    return found_keywords


class html_parser:
    URL_IN_TEXT_PATTERN = re.compile(r'url\((["\']?)(.*?)\1\)', re.IGNORECASE)

    def __init__(self, content, base_url, soup=None, parser='html.parser'):
        self.soup = soup if soup is not None else bs4.BeautifulSoup(content, parser)
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc

    def find_keywords(self, keywords):
        page_text = self.soup.get_text()
        return search_text_for_keywords(page_text, keywords)

    @property
    def internal_links(self):
        all_links = set()
        tags_to_find = {
            'a': 'href', 'img': 'src', 'link': 'href', 'script': 'src'
        }
        for tag_name, attribute in tags_to_find.items():
            for tag in self.soup.find_all(tag_name, **{attribute: True}):
                link_path = tag.get(attribute)
                if not link_path:
                    continue
                if link_path.strip().startswith(('mailto:', 'tel:', 'javascript:', '#')):
                    continue
                absolute_link = urljoin(self.base_url, link_path)
                if urlparse(absolute_link).netloc == self.base_domain:
                    link_without_fragment = absolute_link.split('#')[0]
                    all_links.add(link_without_fragment)

        style_tags = self.soup.find_all('style')
        for tag in self.soup.find_all(style=True):
            style_tags.append(tag)

        for style_tag in style_tags:
            style_content = style_tag.string if style_tag.string else ""
            if style_tag.has_attr('style'):
                style_content += " " + style_tag['style']
                
            for _, url in self.URL_IN_TEXT_PATTERN.findall(style_content):
                absolute_link = urljoin(self.base_url, url.strip())
                if urlparse(absolute_link).netloc == self.base_domain:
                    all_links.add(absolute_link.split('#')[0])

        return list(all_links)

class json_parser:
    LINK_KEYS = {'href', 'url', 'src', 'link', 'guid'}

    def __init__(self, content, base_url):
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.raw_content = content
        try:
            self.data = json.loads(content)
        except json.JSONDecodeError:
            self.data = {}

    def find_keywords(self, keywords):
        return search_text_for_keywords(self.raw_content, keywords)

    def _find_urls_recursive(self, data_structure):
        found_urls = set()
        if isinstance(data_structure, dict):
            for key, value in data_structure.items():
                if key in self.LINK_KEYS and isinstance(value, str):
                    found_urls.add(value)
                elif isinstance(value, (dict, list)):
                    found_urls.update(self._find_urls_recursive(value))
        
        elif isinstance(data_structure, list):
            for item in data_structure:
                found_urls.update(self._find_urls_recursive(item))
        
        return found_urls

    @property
    def internal_links(self):
        if not self.data:
            return []

        discovered_urls = self._find_urls_recursive(self.data)
        internal_links = set()

        for link in discovered_urls:
            clean_link = link.strip('",\'\\()')
            if not clean_link:
                continue

            absolute_link = urljoin(self.base_url, clean_link)
            
            if urlparse(absolute_link).netloc == self.base_domain:
                link_without_fragment = absolute_link.split('#')[0]
                internal_links.add(link_without_fragment)
        
        return list(internal_links)
    
class dir_listing_parser:
    def __init__(self, content, base_url, soup=None, parser='html.parser'):
        self.soup = soup if soup is not None else bs4.BeautifulSoup(content, parser)
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.raw_content = content

    def find_keywords(self, keywords):
        return search_text_for_keywords(self.raw_content, keywords)

    @property
    def internal_links(self):
        links = set()
        ignored_hrefs = {'/', '../'}

        for tag in self.soup.find_all('a', href=True):
            href = tag['href']
            if href and not href.startswith('?') and href not in ignored_hrefs:
                absolute_link = urljoin(self.base_url, href)
                if urlparse(absolute_link).netloc == self.base_domain:
                    links.add(absolute_link.split('#')[0])
        
        return list(links)