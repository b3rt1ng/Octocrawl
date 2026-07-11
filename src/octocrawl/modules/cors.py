"""
CORS Module
Sends a spoofed Origin header to each live endpoint and flags reflected-origin
or overly permissive Access-Control-Allow-Origin/Credentials responses
"""

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from octocrawl.http_request import http_request

from .example import BaseModule, CrawlContext, ModuleMetadata

MAX_CONCURRENT_REQUESTS = 10
MAX_ENDPOINTS_TO_TEST = 50  # safety cap: don't hammer a big site with 2x extra requests

# a domain we obviously don't own, reflecting it back proves the allow-list is broken
PROBE_ORIGIN = "https://octocrawl-cors-probe.invalid"


class CORSModule(BaseModule):
    """Sends a spoofed Origin header to each live endpoint and flags misconfigured CORS responses"""

    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="cors",
            version="1.0.0",
            description="Detects reflected-origin / overly permissive CORS misconfigurations",
            author="@b3rt1ng",
            requires=[],
            category="security"
        )

    def _select_urls(self, context: CrawlContext) -> List[str]:
        live_urls = context.get_urls_by_status(200)

        def api_like(url: str) -> int:
            content_type = context.gathered_urls.get(url, {}).get('content_type', '')
            if 'json' in content_type or '/api' in urlparse(url).path.lower():
                return 0
            return 1

        # test JSON/API-looking endpoints first in case we have to cap
        ordered = sorted(live_urls, key=lambda u: (api_like(u), u))
        return ordered[:MAX_ENDPOINTS_TO_TEST]

    async def _probe(self, url: str, semaphore: asyncio.Semaphore) -> Dict[str, Any]:
        async with semaphore:
            reflected = await http_request(url, timeout=10, extra_headers={"Origin": PROBE_ORIGIN})
            null_origin = await http_request(url, timeout=10, extra_headers={"Origin": "null"})

        return {
            'url': url,
            'reflected_headers': reflected.get('headers', {}),
            'null_headers': null_origin.get('headers', {}),
        }

    def _analyze(self, url: str, headers: Dict[str, str], sent_origin: str) -> Optional[Dict[str, Any]]:
        acao = headers.get('access-control-allow-origin')
        if not acao:
            return None

        acac = headers.get('access-control-allow-credentials', '').lower() == 'true'
        reflects_arbitrary = acao == sent_origin
        is_wildcard = acao == '*'

        if not (reflects_arbitrary or (is_wildcard and acac)):
            # a bare wildcard with no credentials is normal for public APIs, not a finding
            return None

        if reflects_arbitrary and acac:
            severity = "CRITICAL"
            note = "Reflects any Origin and allows credentials, any site can read authenticated responses"
        elif reflects_arbitrary:
            severity = "HIGH"
            note = "Reflects any Origin, readable cross-origin even without credentials"
        else:
            severity = "MEDIUM"
            note = "Wildcard '*' Allow-Origin combined with Allow-Credentials (invalid per spec, but seen in the wild)"

        return {
            'url': url,
            'severity': severity,
            'sent_origin': sent_origin,
            'allow_origin': acao,
            'allow_credentials': acac,
            'note': note,
        }

    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        urls = self._select_urls(context)

        if not urls:
            self.log("No live (200) endpoints to test", "INFO")
            return {'tested': 0, 'findings': []}

        if len(context.get_urls_by_status(200)) > MAX_ENDPOINTS_TO_TEST:
            self.log(f"Testing the first {MAX_ENDPOINTS_TO_TEST} live endpoints (safety cap)", "WARNING")

        self.log(f"Probing {len(urls)} endpoint(s) with a spoofed Origin...", "INFO")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        probes = await asyncio.gather(*(self._probe(url, semaphore) for url in urls))

        findings: List[Dict[str, Any]] = []
        for probe in probes:
            for headers, sent_origin in (
                (probe['reflected_headers'], PROBE_ORIGIN),
                (probe['null_headers'], 'null'),
            ):
                finding = self._analyze(probe['url'], headers, sent_origin)
                if finding:
                    findings.append(finding)

        self.log(f"Found {len(findings)} CORS misconfiguration(s)", "INFO")
        for finding in findings:
            self.log(f"  [{finding['severity']}] {finding['url']}: {finding['note']}", "WARNING")

        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        report_lines = [f"# CORS Misconfiguration Report ({len(findings)} finding(s))\n"]
        for finding in sorted(findings, key=lambda f: severity_order.get(f['severity'], 9)):
            report_lines.append(f"## [{finding['severity']}] {finding['url']}")
            report_lines.append(f"- Sent Origin: `{finding['sent_origin']}`")
            report_lines.append(f"- Access-Control-Allow-Origin: `{finding['allow_origin']}`")
            report_lines.append(f"- Access-Control-Allow-Credentials: `{finding['allow_credentials']}`")
            report_lines.append(f"- {finding['note']}\n")

        self.save_output("cors_report.md", "\n".join(report_lines))

        return {'tested': len(urls), 'findings': findings}
