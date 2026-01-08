from urllib.parse import urljoin, urlparse
from ui import gradient_text
import re
import xml.etree.ElementTree as ET

async def check_robots_txt(base_url, http_request_func, print_lock=None, custom_agent=None):
    result = {
        'disallowed_paths': [],
        'allowed_paths': [],
        'sitemaps': [],
        'crawl_delay': None
    }
    
    robots_url = urljoin(base_url, '/robots.txt')
    
    try:
        response = await http_request_func(robots_url, timeout=10, custom_agent=custom_agent)
        
        if not response['done'] or response['response_code'] != 200:
            if print_lock:
                async with print_lock:
                    print(gradient_text(f"🪽  No robots.txt found at {robots_url}"))
            return result
        
        content = response['content']
        
        if print_lock:
            async with print_lock:
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
        
        if print_lock:
            async with print_lock:
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
        if print_lock:
            async with print_lock:
                print(gradient_text(f"🏴‍☠️ Error parsing robots.txt: {e}"))
        return result


async def check_sitemap_xml(sitemap_url, http_request_func, print_lock=None, base_domain=None, custom_agent=None):
    urls = []
    
    try:
        response = await http_request_func(sitemap_url, timeout=10, custom_agent=custom_agent)
        
        if not response['done'] or response['response_code'] != 200:
            if print_lock:
                async with print_lock:
                    print(gradient_text(f"🧭 No sitemap found at {sitemap_url}"))
            return urls
        
        content = response['content']
        
        if print_lock:
            async with print_lock:
                print(gradient_text(f"🧭 Found sitemap at {sitemap_url}, parsing..."))
        
        try:
            root = ET.fromstring(content)
            
            namespaces = {
                'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                'image': 'http://www.google.com/schemas/sitemap-image/1.1',
                'video': 'http://www.google.com/schemas/sitemap-video/1.1'
            }
            
            sitemap_tags = root.findall('.//sm:sitemap', namespaces)
            if sitemap_tags:
                if print_lock:
                    async with print_lock:
                        print(gradient_text(f"    🌊 Sitemap index detected, found {len(sitemap_tags)} sub-sitemaps"))
                
                for sitemap_tag in sitemap_tags:
                    loc = sitemap_tag.find('sm:loc', namespaces)
                    if loc is not None and loc.text:
                        sub_urls = await check_sitemap_xml(
                            loc.text, 
                            http_request_func, 
                            print_lock, 
                            base_domain,
                            custom_agent
                        )
                        urls.extend(sub_urls)
            
            else:
                url_tags = root.findall('.//sm:url', namespaces)
                
                for url_tag in url_tags:
                    loc = url_tag.find('sm:loc', namespaces)
                    if loc is not None and loc.text:
                        url = loc.text.strip()
                        if base_domain:
                            parsed = urlparse(url)
                            if parsed.netloc == base_domain:
                                urls.append(url)
                        else:
                            urls.append(url)
                
                if print_lock:
                    async with print_lock:
                        print(gradient_text(f"    🌊 Extracted {len(urls)} URLs from sitemap"))
        
        except ET.ParseError as e:
            if print_lock:
                async with print_lock:
                    print(gradient_text(f"🏴‍☠️ XML parsing failed, trying regex extraction..."))
            
            url_pattern = re.compile(r'<loc>(.*?)</loc>', re.IGNORECASE)
            matches = url_pattern.findall(content)
            
            for url in matches:
                url = url.strip()
                if base_domain:
                    parsed = urlparse(url)
                    if parsed.netloc == base_domain:
                        urls.append(url)
                else:
                    urls.append(url)
            
            if print_lock and urls:
                async with print_lock:
                    print(gradient_text(f"    🌊 Extracted {len(urls)} URLs using regex"))
        return urls
        
    except Exception as e:
        if print_lock:
            async with print_lock:
                print(f"[!] Error parsing sitemap: {e}")
        return urls

async def discover_sitemaps(base_url, http_request_func, print_lock=None, custom_agent=None):
    common_sitemap_paths = [
        '/sitemap.xml',
        '/sitemap_index.xml',
        '/sitemap1.xml',
        '/sitemaps.xml',
        '/sitemap/sitemap.xml',
        '/sitemap/index.xml',
        '/sitemaps/sitemap.xml'
    ]    
    found_sitemaps = []
    
    if print_lock:
        async with print_lock:
            print(gradient_text(f"🗺️  Checking for common sitemap locations..."))

    for path in common_sitemap_paths:
        sitemap_url = urljoin(base_url, path)
        try:
            response = await http_request_func(sitemap_url, timeout=5, custom_agent=custom_agent)
            if response['done'] and response['response_code'] == 200:
                if 'xml' in response.get('content_type', '').lower() or \
                   response['content'].strip().startswith('<?xml'):
                    found_sitemaps.append(sitemap_url)
                    if print_lock:
                        async with print_lock:
                            print(gradient_text(f"    🌊 Found: {path}"))
        except Exception:
            continue
    
    return found_sitemaps