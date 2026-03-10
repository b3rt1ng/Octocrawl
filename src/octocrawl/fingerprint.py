import re

INTERESTING_HEADERS = {
    'server': 'Server',
    'x-powered-by': 'X-Powered-By',
    'x-aspnet-version': 'ASP.NET Version',
    'via': 'Via (Proxies)',
    'x-runtime': 'X-Runtime (Ruby/Rails)',
    
    'x-cache': 'X-Cache',
    'x-cache-status': 'X-Cache-Status',
    'age': 'Age (seconds in cache)',
    'cf-cache-status': 'Cloudflare Cache',
    
    'strict-transport-security': 'HSTS Policy',
    'content-security-policy': 'Content-Security-Policy',
    'x-frame-options': 'X-Frame-Options',
    'x-content-type-options': 'X-Content-Type-Options',
    
    'x-generator': 'X-Generator',
    'link': 'Link Header',
    'x-drupal-cache': 'X-Drupal-Cache',
}

CONTENT_SIGNATURES = {
    'Generator (Meta)': re.compile(r'<meta\s+name=["\']generator["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE),
}

def fingerprint_technologies(headers, content):
    found_tech = {}
    
    for header_key, display_name in INTERESTING_HEADERS.items():
        header_value = headers.get(header_key.lower())
        if header_value:
            found_tech[display_name] = header_value.strip()

    if content:
        for display_name, pattern in CONTENT_SIGNATURES.items():
            match = pattern.search(content)
            if match:
                found_tech[display_name] = match.group(1).strip()

    cookie_header = headers.get('set-cookie', '')
    if 'phpsessid' in cookie_header.lower():
        if 'Session' not in found_tech: found_tech['Session'] = 'PHP (PHPSESSID cookie)'
    elif 'jsessionid' in cookie_header.lower():
        if 'Session' not in found_tech: found_tech['Session'] = 'Java (JSESSIONID cookie)'

    return found_tech