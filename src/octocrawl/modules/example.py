from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from pathlib import Path


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
    
    # Configuration used
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Additional data that modules can share
    shared_data: Dict[str, Any] = field(default_factory=dict)
    
    def get_urls_by_status(self, status_code: int) -> List[str]:
        """Retrieves all URLs with a specific status code"""
        return [
            url for url, data in self.gathered_urls.items()
            if data.get('code') == status_code
        ]
    
    def get_urls_by_content_type(self, content_type: str) -> List[str]:
        """Retrieves all URLs of a specific content type"""
        return [
            url for url, data in self.gathered_urls.items()
            if content_type.lower() in data.get('content_type', '').lower()
        ]
    
    def get_urls_with_keywords(self) -> List[str]:
        """Retrieves all URLs containing keywords"""
        return [
            url for url, data in self.gathered_urls.items()
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
        self.enabled = True
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
    
    def log(self, message: str, level: str = "INFO") -> None:
        """Helper to log messages"""
        prefix = f"[{self.metadata.name if self.metadata else 'Module'}]"
        print(f"{prefix} [{level}] {message}")
    
    def save_output(self, filename: str, content: str, output_dir: Path = None) -> Path:
        """
        Helper to save module results
        
        Args:
            filename: Output file name
            content: Content to write
            output_dir: Output directory (default: ./octocrawl_output)
            
        Returns:
            Path of the created file
        """
        if output_dir is None:
            output_dir = Path("./octocrawl_output")
        
        output_dir.mkdir(exist_ok=True)
        
        # Create a subfolder for this module
        module_dir = output_dir / (self.metadata.name if self.metadata else "unknown")
        module_dir.mkdir(exist_ok=True)
        
        filepath = module_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
