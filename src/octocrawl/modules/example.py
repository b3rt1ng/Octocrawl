import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from octocrawl.crawler import STEALTH_JITTER_RANGE
from octocrawl.http_request import http_request

# modules re-fetch URLs after the crawl: in stealth mode keep that trickle small too
STEALTH_MODULE_CONCURRENCY = 2


@dataclass
class CrawlContext:
    """Context shared with all modules after the crawl"""
    
    # Crawl data
    start_url: str
    base_domain: str
    gathered_urls: Dict[str, Dict[str, Any]]
    sitemap: Dict[str, Any]
    technologies: Dict[str, str]
    
    # Metadata
    total_urls: int
    crawl_duration: float
    
    # Configuration used (workers, timeout, keywords, cookies, random_agent,
    # custom_agent, stealth) - see BaseModule.fetch() for the request-related ones
    config: Dict[str, Any] = field(default_factory=dict)

    # response headers of every crawled HTML page, keyed by the crawled URL
    response_headers: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # names of every query parameter seen in a link (crawled URLs have their query stripped)
    query_params: Set[str] = field(default_factory=set)
    
    # Additional data that modules can share
    shared_data: Dict[str, Any] = field(default_factory=dict)
    
    # note: gathered_urls is keyed by a canonical dedup key (https/apex), which
    # may not be fetchable as-is on an http-only host. these helpers return
    # data['url'], the real URL that was actually crawled, so modules can re-fetch.
    def get_urls_by_status(self, status_code: int) -> List[str]:
        """Retrieves all URLs with a specific status code"""
        return [
            data.get('url', url) for url, data in self.gathered_urls.items()
            if data.get('code') == status_code
        ]

    def get_urls_by_content_type(self, content_type: str) -> List[str]:
        """Retrieves all URLs of a specific content type"""
        return [
            data.get('url', url) for url, data in self.gathered_urls.items()
            if content_type.lower() in data.get('content_type', '').lower()
        ]

    def get_urls_with_keywords(self) -> List[str]:
        """Retrieves all URLs containing keywords"""
        return [
            data.get('url', url) for url, data in self.gathered_urls.items()
            if data.get('keywords')
        ]


class ModuleMetadata:
    """Module metadata"""
    
    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        author: str = "Unknown",
        requires: List[str] = None,
        category: str = "general"
    ):
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.requires = requires or []
        self.category = category


class BaseModule(ABC):
    """Base abstract class for all OctoCrawl modules"""
    
    def __init__(self):
        # only turned on by ModuleManager.enable_module() (i.e. -M on the command line)
        self.enabled = False
        self.metadata: Optional[ModuleMetadata] = None
        self._context: Optional[CrawlContext] = None
    
    @abstractmethod
    def get_metadata(self) -> ModuleMetadata:
        """Returns the module metadata"""
        pass
    
    @abstractmethod
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        """
        Executes the module with the provided context
        
        Args:
            context: Crawl context containing all data
            
        Returns:
            Dict containing the module results
        """
        pass
    
    def setup(self, context: CrawlContext) -> bool:
        """
        Optional: Configuration before execution
        
        Returns:
            True if setup succeeded, False otherwise
        """
        self._context = context
        return True
    
    def cleanup(self) -> None:
        """Optional: Cleanup after execution"""
        pass
    
    def validate_requirements(self) -> tuple[bool, List[str]]:
        """
        Verifies that all dependencies are installed
        
        Returns:
            (success, missing_packages)
        """
        if not self.metadata or not self.metadata.requires:
            return True, []
        
        missing = []
        for package in self.metadata.requires:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)
        
        return len(missing) == 0, missing
    
    def concurrency(self, default: int) -> int:
        """Max parallel requests a module should use, lowered in stealth mode"""
        if self._context and self._context.config.get('stealth'):
            return min(default, STEALTH_MODULE_CONCURRENCY)
        return default

    async def fetch(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        http_request() with the crawl's own settings (cookies, user-agent, timeout, stealth
        jitter), so a module sees the same thing the crawler did. kwargs override/extend them.
        """
        config = self._context.config if self._context else {}
        if config.get('stealth'):
            await asyncio.sleep(random.uniform(*STEALTH_JITTER_RANGE))

        request_kwargs = {
            'timeout': config.get('timeout', 10),
            'cookies': config.get('cookies'),
            'random_agent': config.get('random_agent', False),
            'custom_agent': config.get('custom_agent'),
        }
        request_kwargs.update(kwargs)
        return await http_request(url, **request_kwargs)

    def log(self, message: str, level: str = "INFO") -> None:
        """Helper to log messages"""
        prefix = f"[{self.metadata.name if self.metadata else 'Module'}]"
        print(f"{prefix} [{level}] {message}")
    
    def save_output(self, filename: str, content: str, output_dir: Path = None) -> Path:
        """
        Helper to save module results, namespaced by target domain

        Args:
            filename: Output file name
            content: Content to write
            output_dir: Output directory (default: ~/.octocrawl/<target-domain>)

        Returns:
            Path of the created file
        """
        if output_dir is None:
            domain = getattr(self._context, 'base_domain', None) or "unknown-target"
            output_dir = Path.home() / ".octocrawl" / domain

        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a subfolder for this module
        module_dir = output_dir / (self.metadata.name if self.metadata else "unknown")
        module_dir.mkdir(exist_ok=True)
        
        filepath = module_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
