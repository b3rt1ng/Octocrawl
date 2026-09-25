from urllib.parse import urljoin, urlparse
from octocrawl.ui import gradient_text
from octocrawl.parser import same_site
import asyncio
import re
import xml.etree.ElementTree as ET

# a sitemap index can point to other indexes, and robots.txt/sitemaps are
# attacker-controlled: bound how deep and how many we follow
MAX_SITEMAP_DEPTH = 3
MAX_SITEMAPS = 100

SITEMAP_NAMESPACES = {
    'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
    'image': 'http://www.google.com/schemas/sitemap-image/1.1',
    'video': 'http://www.google.com/schemas/sitemap-video/1.1'
}

LOC_PATTERN = re.compile(r'<loc>(.*?)</loc>', re.IGNORECASE)


async def check_robots_txt(base_url, http_request_func, custom_agent=None):
    result = {
        'disallowed_paths': [],
        'allowed_paths': [],
        'sitemaps': [],
        'crawl_delay': None
    }

    robots_url = urljoin(base_url, '/robots.txt')

    try:
        response = await http_request_func(robots_url, timeout=10, custom_agent=custom_agent, force_get=True)

        if not response['done'] or response['response_code'] != 200:
            print(gradient_text(f"🪽  No robots.txt found at {robots_url}"))
            return result

        content = response['content']
        print(gradient_text(f"🪽  Found robots.txt, let's parse !"))

        for line in content.split('\n'):
            line = line.strip()

            if not line or line.startswith('#'):
                continue

            if ':' in line:
                directive, value = line.split(':', 1)
                directive = directive.strip().lower()
                value = value.strip()

                if directive == 'disallow' and value:
                    if value.startswith('/'):
                        full_url = urljoin(base_url, value.rstrip('*'))
                        result['disallowed_paths'].append(full_url)

                elif directive == 'allow' and value:
                    if value.startswith('/'):
                        full_url = urljoin(base_url, value.rstrip('*'))
                        result['allowed_paths'].append(full_url)

                elif directive == 'sitemap':
                    result['sitemaps'].append(value)

                elif directive == 'crawl-delay':
                    try:
                        result['crawl_delay'] = float(value)
                    except ValueError:
                        pass

        if result['disallowed_paths']:
            print(gradient_text(f"    🌊 Found {len(result['disallowed_paths'])} disallowed paths"))
        if result['allowed_paths']:
            print(gradient_text(f"    🌊 Found {len(result['allowed_paths'])} allowed paths"))
        if result['sitemaps']:
            print(gradient_text(f"    🌊 Found {len(result['sitemaps'])} sitemap(s)"))
        if result['crawl_delay']:
            print(gradient_text(f"    🌊 Crawl-delay: {result['crawl_delay']}s"))

        return result

    except Exception as e:
        print(gradient_text(f"🏴‍☠️ Error parsing robots.txt: {e}"))
        return result


def _filter_same_site(urls, base_domain):
    return [url for url in urls if same_site(urlparse(url).netloc, base_domain)]


async def check_sitemaps(sitemap_urls, http_request_func, base_domain, custom_agent=None):
    # entry point: fetches every sitemap (and the sub-sitemaps of indexes) concurrently,
    # sharing one `visited` set so an index pointing back to itself can't loop
    visited = set()
    results = await asyncio.gather(*(
        check_sitemap_xml(url, http_request_func, base_domain, custom_agent, visited=visited)
        for url in sitemap_urls
    ))
    return [url for urls in results for url in urls]


async def check_sitemap_xml(sitemap_url, http_request_func, base_domain, custom_agent=None, visited=None, depth=0):
    urls = []
    visited = visited if visited is not None else set()

    # the sitemap location itself comes from robots.txt / a sitemap index, i.e. from
    # the target: never let it send us to another host (out of scope)
    if not same_site(urlparse(sitemap_url).netloc, base_domain):
        print(gradient_text(f"🧭 Skipping off-site sitemap {sitemap_url}"))
        return urls
    if sitemap_url in visited or depth > MAX_SITEMAP_DEPTH or len(visited) >= MAX_SITEMAPS:
        return urls
    visited.add(sitemap_url)

    try:
        response = await http_request_func(sitemap_url, timeout=10, custom_agent=custom_agent, force_get=True)

        if not response['done'] or response['response_code'] != 200:
            print(gradient_text(f"🧭 No sitemap found at {sitemap_url}"))
            return urls

        content = response['content']
        print(gradient_text(f"🧭 Found sitemap at {sitemap_url}, parsing..."))

        try:
            root = ET.fromstring(content)

            sitemap_tags = root.findall('.//sm:sitemap', SITEMAP_NAMESPACES)
            if sitemap_tags:
                print(gradient_text(f"    🌊 Sitemap index detected, found {len(sitemap_tags)} sub-sitemaps"))

                sub_sitemaps = [loc.text.strip() for loc in
                                (tag.find('sm:loc', SITEMAP_NAMESPACES) for tag in sitemap_tags)
                                if loc is not None and loc.text]
                results = await asyncio.gather(*(
                    check_sitemap_xml(sub_url, http_request_func, base_domain, custom_agent,
                                      visited=visited, depth=depth + 1)
                    for sub_url in sub_sitemaps
                ))
                for sub_urls in results:
                    urls.extend(sub_urls)

            else:
                locs = [loc.text.strip() for loc in
                        (tag.find('sm:loc', SITEMAP_NAMESPACES) for tag in root.findall('.//sm:url', SITEMAP_NAMESPACES))
                        if loc is not None and loc.text]
                urls = _filter_same_site(locs, base_domain)
                print(gradient_text(f"    🌊 Extracted {len(urls)} URLs from sitemap"))

        except ET.ParseError:
            print(gradient_text(f"🏴‍☠️ XML parsing failed, trying regex extraction..."))

            urls = _filter_same_site((m.strip() for m in LOC_PATTERN.findall(content)), base_domain)
            if urls:
                print(gradient_text(f"    🌊 Extracted {len(urls)} URLs using regex"))
        return urls

    except Exception as e:
        print(f"[!] Error parsing sitemap: {e}")
        return urls


async def discover_sitemaps(base_url, http_request_func, custom_agent=None):
    common_sitemap_paths = [
        '/sitemap.xml',
        '/sitemap_index.xml',
        '/sitemap1.xml',
        '/sitemaps.xml',
        '/sitemap/sitemap.xml',
        '/sitemap/index.xml',
        '/sitemaps/sitemap.xml'
    ]

    print(gradient_text(f"🗺️  Checking for common sitemap locations..."))

    async def probe(path):
        sitemap_url = urljoin(base_url, path)
        try:
            response = await http_request_func(sitemap_url, timeout=5, custom_agent=custom_agent, force_get=True)
        except Exception:
            return None
        if response['done'] and response['response_code'] == 200:
            if 'xml' in response.get('content_type', '').lower() or \
               response['content'].strip().startswith('<?xml'):
                print(gradient_text(f"    🌊 Found: {path}"))
                return sitemap_url
        return None

    results = await asyncio.gather(*(probe(path) for path in common_sitemap_paths))
    return [url for url in results if url]
