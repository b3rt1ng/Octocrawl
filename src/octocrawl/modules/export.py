"""
Export Module
Dumps discovered URLs as a plain list and flat JSON, ready to pipe into httpx/ffuf/nuclei
"""

import json
from typing import Any, Dict

from .example import BaseModule, CrawlContext, ModuleMetadata


class ExportModule(BaseModule):
    """Writes discovered URLs as flat files ready to pipe into other tools"""

    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="export",
            version="1.0.0",
            description="Exports discovered URLs as flat, pipeline-friendly lists (plain text + JSON)",
            author="@b3rt1ng",
            requires=[],
            category="utility"
        )

    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        all_urls = sorted(context.gathered_urls.keys())
        live_urls = sorted(context.get_urls_by_status(200))

        self.log(f"Exporting {len(all_urls)} URL(s) ({len(live_urls)} live)...", "INFO")

        self.save_output("urls_all.txt", "\n".join(all_urls) + "\n" if all_urls else "")
        self.save_output("urls_live.txt", "\n".join(live_urls) + "\n" if live_urls else "")

        flat_records = [
            {
                'url': url,
                'code': data.get('code'),
                'content_type': data.get('content_type'),
                'keywords': data.get('keywords', {})
            }
            for url, data in sorted(context.gathered_urls.items())
        ]
        self.save_output("urls.json", json.dumps(flat_records, indent=2))

        self.log("Exported to urls_all.txt, urls_live.txt and urls.json", "INFO")

        return {
            'total_urls': len(all_urls),
            'live_urls': len(live_urls)
        }
