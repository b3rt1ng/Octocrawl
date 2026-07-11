"""
Broken Links Module
Groups every non-200 URL found during the crawl by category: client errors, server errors,
unresolved redirects and connection failures
"""

from collections import defaultdict
from typing import Any, Dict, List

from .example import BaseModule, CrawlContext, ModuleMetadata

CATEGORY_ORDER = [
    "Client Errors (4xx)",
    "Server Errors (5xx)",
    "Unresolved Redirects",
    "Connection Failures",
    "Other",
]


class BrokenLinksModule(BaseModule):
    """Groups every non-2xx or failed URL found during the crawl by category"""

    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="brokenlinks",
            version="1.0.0",
            description="Reports dead links, client/server errors and connection failures found during the crawl",
            author="@b3rt1ng",
            requires=[],
            category="analysis"
        )

    def _categorize(self, code: Any) -> str:
        if not isinstance(code, int):
            return "Connection Failures"
        if 300 <= code < 400:
            return "Unresolved Redirects"
        if 400 <= code < 500:
            return "Client Errors (4xx)"
        if 500 <= code < 600:
            return "Server Errors (5xx)"
        return "Other"

    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        categories: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for url, data in context.gathered_urls.items():
            code = data.get('code')
            if code == 200:
                continue
            categories[self._categorize(code)].append({'url': url, 'code': code})

        total_broken = sum(len(entries) for entries in categories.values())

        if total_broken == 0:
            self.log("No broken links found - every discovered URL returned 200", "INFO")
            return {'total_broken': 0, 'categories': {}}

        self.log(f"Found {total_broken} non-200 URL(s)", "INFO")

        report_lines = [f"# Broken Links Report ({total_broken} total)\n"]
        counts_by_category: Dict[str, Dict[Any, int]] = {}

        for category in CATEGORY_ORDER:
            entries = categories.get(category)
            if not entries:
                continue

            self.log(f"  {category}: {len(entries)}", "WARNING")
            report_lines.append(f"## {category} ({len(entries)})\n")

            by_code: Dict[Any, List[str]] = defaultdict(list)
            for entry in sorted(entries, key=lambda e: e['url']):
                by_code[entry['code']].append(entry['url'])

            for code, urls in sorted(by_code.items(), key=lambda kv: str(kv[0])):
                report_lines.append(f"### {code} ({len(urls)})")
                report_lines.extend(f"- {u}" for u in urls)
                report_lines.append("")

            counts_by_category[category] = {code: len(urls) for code, urls in by_code.items()}

        self.save_output("brokenlinks_report.md", "\n".join(report_lines))

        return {
            'total_broken': total_broken,
            'categories': {cat: len(entries) for cat, entries in categories.items()},
            'counts_by_code': counts_by_category
        }
