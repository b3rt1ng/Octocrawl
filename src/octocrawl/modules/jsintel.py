"""
JS Intel Module
Re-fetches JS files found during the crawl and greps them for API endpoints and leaked secrets
"""

import asyncio
import re
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from octocrawl.http_request import http_request

from .example import BaseModule, CrawlContext, ModuleMetadata

# absolute path under a common API prefix, or a full URL
ENDPOINT_PATTERN = re.compile(
    r'''["'](/(?:api|v[0-9]+|graphql|rest|internal)[a-zA-Z0-9_\-/.]*|https?://[a-zA-Z0-9_\-.]+/[a-zA-Z0-9_\-/.]*)["']''',
    re.IGNORECASE
)

# first string arg of a common JS network call, catches endpoints that don't start with /api, /v1 etc
CALL_CONTEXT_PATTERN = re.compile(
    r'''(?:fetch|axios(?:\.\w+)?|\.ajax|\.open)\s*\(\s*["'`]([^"'`\s]{2,})["'`]''',
    re.IGNORECASE
)

# (label, pattern), kept short on purpose, a few precise patterns beat a long noisy list
SECRET_PATTERNS = [
    ("AWS Access Key ID", re.compile(r'AKIA[0-9A-Z]{16}')),
    ("Google API Key", re.compile(r'AIza[0-9A-Za-z\-_]{35}')),
    ("Firebase Database", re.compile(r'[a-z0-9-]+\.firebaseio\.com')),
    ("Slack Token", re.compile(r'xox[baprs]-[0-9A-Za-z-]{10,48}')),
    ("Stripe Live Key", re.compile(r'sk_live_[0-9a-zA-Z]{16,}')),
    ("JWT", re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')),
    ("Private Key Block", re.compile(r'-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY-----')),
    ("Generic Bearer Token", re.compile(r'[Bb]earer\s+[A-Za-z0-9\-_.=]{20,}')),
    ("Generic Secret Assignment", re.compile(
        r'''(?i)(?:secret|api[_-]?key|access[_-]?token|client[_-]?secret)["']?\s*[:=]\s*["\']([A-Za-z0-9\-_./+=]{12,})["\']'''
    )),
]

MAX_CONCURRENT_FETCHES = 10
MAX_JS_FILES = 200  # safety cap: don't let a huge site trigger hundreds of re-fetches

# xhr.open(method, url): first string arg is the HTTP verb, not an endpoint
HTTP_METHODS = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'}


class JSIntelModule(BaseModule):
    """Re-fetches JS files and scans them for API endpoints and leaked secrets"""

    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="jsintel",
            version="1.0.0",
            description="Extracts API endpoints and leaked secrets from discovered JS files",
            author="@b3rt1ng",
            requires=[],
            category="security"
        )

    def _select_js_urls(self, context: CrawlContext) -> List[str]:
        js_urls = set(context.get_urls_by_content_type('javascript'))

        for url, data in context.gathered_urls.items():
            if data.get('code') == 200 and urlparse(url).path.lower().endswith('.js'):
                js_urls.add(url)

        return sorted(js_urls)

    async def _fetch_js(self, url: str, semaphore: asyncio.Semaphore) -> str:
        async with semaphore:
            response = await http_request(url, timeout=10)
            return response['content'] if response['done'] else ''

    def _extract_endpoints(self, content: str) -> Set[str]:
        found = set()
        for match in ENDPOINT_PATTERN.finditer(content):
            found.add(match.group(1))
        for match in CALL_CONTEXT_PATTERN.finditer(content):
            candidate = match.group(1)
            if candidate.startswith('${') or candidate.upper() in HTTP_METHODS:
                continue
            found.add(candidate)
        return found

    def _extract_secrets(self, content: str, source_url: str, seen: Set[str], secrets: List[Dict[str, str]]) -> None:
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(content):
                value = match.group(0)
                dedup_key = f"{label}:{value}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                secrets.append({'type': label, 'match': value, 'source': source_url})

    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        js_urls = self._select_js_urls(context)

        if not js_urls:
            self.log("No JavaScript files found in crawl results", "INFO")
            return {'js_files_analyzed': 0, 'endpoints': [], 'secrets': []}

        if len(js_urls) > MAX_JS_FILES:
            self.log(f"Found {len(js_urls)} JS files, analyzing the first {MAX_JS_FILES}", "WARNING")
            js_urls = js_urls[:MAX_JS_FILES]

        self.log(f"Fetching and analyzing {len(js_urls)} JS file(s)...", "INFO")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
        contents = await asyncio.gather(*(self._fetch_js(url, semaphore) for url in js_urls))

        endpoints: Set[str] = set()
        secrets: List[Dict[str, str]] = []
        seen_secrets: Set[str] = set()

        for url, content in zip(js_urls, contents):
            if not content:
                continue
            endpoints.update(self._extract_endpoints(content))
            self._extract_secrets(content, url, seen_secrets, secrets)

        self.log(f"Found {len(endpoints)} unique endpoint(s) and {len(secrets)} potential secret(s)", "INFO")

        for secret in secrets:
            self.log(f"  [{secret['type']}] {secret['match'][:60]} found in {secret['source']}", "WARNING")

        report_lines = ["=== Endpoints ===", *sorted(endpoints), "", "=== Potential Secrets ==="]
        report_lines.extend(f"[{s['type']}] {s['match']} found in {s['source']}" for s in secrets)
        self.save_output("jsintel_report.txt", "\n".join(report_lines))

        return {
            'js_files_analyzed': len(js_urls),
            'endpoints': sorted(endpoints),
            'secrets': secrets
        }
