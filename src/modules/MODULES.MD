# OctoCrawl Module System

The OctoCrawl module system allows you to extend the crawler's functionality by creating post-crawl analysis modules.

## 🚀 Quick Start

### Using Existing Modules

```bash
# List available modules
octocrawl --list-modules

# Get info about a module
octocrawl --module-info summary

# Run a crawl with modules
octocrawl https://example.com -M autopawn,export

# Run with all available modules
octocrawl https://example.com -M all
```

### Creating a New Module

1. **Create your module file** in `src/modules/` (e.g., `mymodule.py`)

2. **Basic template:**

```python
"""
My Custom Module for OctoCrawl
Brief description of what your module does
"""

from .example import BaseModule, ModuleMetadata, CrawlContext
from typing import Dict, Any


class MyCustomModule(BaseModule):
    """
    Detailed description of your module
    """
    
    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="mymodule",
            version="1.0.0",
            description="Brief description",
            author="Your Name",
            requires=[],  # List of required packages, e.g., ["requests", "beautifulsoup4"]
            category="analysis"  # Categories: analysis, security, utility, export
        )
    
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        """
        Main execution method
        
        Args:
            context: Contains all crawl data
            
        Returns:
            Dictionary with your results
        """
        self.log("Starting my module...", "INFO")
        
        # Access crawl data
        total_urls = context.total_urls
        technologies = context.technologies
        
        # Do your analysis
        result = self._analyze(context)
        
        # Save output
        output_file = self.save_output(
            "my_report.txt",
            "Your content here"
        )
        
        self.log(f"Report saved to {output_file}", "INFO")
        
        return {
            'result': result,
            'output_file': str(output_file)
        }
    
    def _analyze(self, context: CrawlContext):
        """Your analysis logic"""
        # Your code here
        return "analysis result"
```

3. **Test your module:**

```bash
octocrawl https://example.com -M mymodule
```

## 📚 CrawlContext API

The `CrawlContext` object provides access to all crawl data:

### Properties

```python
context.start_url          # Starting URL of the crawl
context.base_domain        # Base domain being crawled
context.gathered_urls      # Dict[url, {code, content_type, keywords}]
context.sitemap            # Hierarchical sitemap structure
context.technologies       # Detected technologies {name: version}
context.total_urls         # Total number of URLs found
context.crawl_duration     # Duration in seconds
context.config             # Crawl configuration used
context.shared_data        # Data shared between modules
```

### Helper Methods

```python
# Get all URLs with status code 200
urls_200 = context.get_urls_by_status(200)

# Get all HTML pages
html_urls = context.get_urls_by_content_type('text/html')

# Get URLs containing keywords
keyword_urls = context.get_urls_with_keywords()
```

## 🛠️ BaseModule Methods

Your module inherits these useful methods:

```python
# Log messages
self.log("Message", "INFO")   # Levels: INFO, WARNING, ERROR

# Save output files
filepath = self.save_output(
    filename="report.txt",
    content="Your content",
    output_dir=None  # Default: ./octocrawl_output/module_name/
)

# Optional: Setup before execution
def setup(self, context: CrawlContext) -> bool:
    super().setup(context)
    # Your setup code
    return True  # Return False to abort

# Optional: Cleanup after execution
def cleanup(self) -> None:
    # Your cleanup code
    pass
```

## 📦 Module Categories

Choose the appropriate category for your module:

- **`analysis`**: Modules that analyze crawl data (e.g., summary, statistics)
- **`security`**: Security-focused modules (e.g., autopawn, vulnerability scanners)
- **`utility`**: General purpose tools (e.g., export, conversion)
- **`custom`**: Miscellaneous or specialized modules

## 💡 Examples

### Example 1: Simple Statistics Module

```python
from .example import BaseModule, ModuleMetadata, CrawlContext
from typing import Dict, Any


class StatsModule(BaseModule):
    
    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="stats",
            version="1.0.0",
            description="Generates crawl statistics",
            author="@yourname",
            category="analysis"
        )
    
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        stats = {
            'total_urls': context.total_urls,
            'duration': context.crawl_duration,
            'avg_time_per_url': context.crawl_duration / max(context.total_urls, 1)
        }
        
        # Count status codes
        status_counts = {}
        for url, data in context.gathered_urls.items():
            code = data.get('code', 'unknown')
            status_counts[code] = status_counts.get(code, 0) + 1
        
        stats['status_codes'] = status_counts
        
        # Save report
        report = f"""# Crawl Statistics

- Total URLs: {stats['total_urls']}
- Duration: {stats['duration']:.2f}s
- Average time per URL: {stats['avg_time_per_url']:.3f}s

## Status Codes
"""
        for code, count in sorted(status_counts.items()):
            report += f"\n- {code}: {count} URLs"
        
        self.save_output("statistics.md", report)
        
        return stats
```

### Example 2: Module with External Dependencies

```python
from .example import BaseModule, ModuleMetadata, CrawlContext
from typing import Dict, Any


class ApiModule(BaseModule):
    
    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="api",
            version="1.0.0",
            description="Sends data to external API",
            author="@yourname",
            requires=["requests"],  # Will check if installed
            category="utility"
        )
    
    def setup(self, context: CrawlContext) -> bool:
        super().setup(context)
        
        # Check for required config
        if not os.getenv('API_KEY'):
            self.log("API_KEY environment variable not set", "ERROR")
            return False
        
        self.api_key = os.getenv('API_KEY')
        return True
    
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        import requests
        
        # Prepare data
        data = {
            'domain': context.base_domain,
            'url_count': context.total_urls
        }
        
        # Send to API
        try:
            response = requests.post(
                'https://api.example.com/submit',
                json=data,
                headers={'Authorization': f'Bearer {self.api_key}'}
            )
            response.raise_for_status()
            
            return {
                'success': True,
                'response': response.json()
            }
        except Exception as e:
            self.log(f"API error: {e}", "ERROR")
            return {'success': False, 'error': str(e)}
```

## 🔍 Accessing URLs and Data

```python
async def run(self, context: CrawlContext) -> Dict[str, Any]:
    # Iterate over all URLs
    for url, data in context.gathered_urls.items():
        status_code = data.get('code')
        content_type = data.get('content_type')
        keywords = data.get('keywords', {})
        
        # Your processing
        if status_code == 404:
            self.log(f"404 found: {url}", "WARNING")
    
    # Get specific subsets
    success_urls = context.get_urls_by_status(200)
    js_files = context.get_urls_by_content_type('javascript')
    
    return {'processed': len(context.gathered_urls)}
```

## 🎯 Best Practices

1. **Always provide metadata**: Name, version, description, author
2. **Handle errors gracefully**: Use try/except and log errors
3. **Validate requirements**: Check for API keys, env vars in `setup()`
4. **Save meaningful output**: Use `save_output()` for reports
5. **Log important events**: Use `self.log()` for user feedback
6. **Keep it async**: Use `async def run()` and `await` where needed
7. **Document your code**: Add docstrings and comments

## 🚨 Common Issues

### Module not found

```bash
# Make sure your file is in src/modules/
ls src/modules/mymodule.py

# Check it's not ignored
octocrawl --list-modules
```

### Missing dependencies

```python
# Declare them in metadata
requires=["requests", "beautifulsoup4"]

# Install them
pip install requests beautifulsoup4
```

### Import errors

```python
# Always import from .example (relative import)
from .example import BaseModule, ModuleMetadata, CrawlContext

# NOT from modules.example or absolute paths
```

## 🤝 Contributing

To contribute a module to OctoCrawl:

1. Create your module following this guide
2. Test it thoroughly
3. Submit a pull request with:
   - Your module file
   - Documentation of what it does
   - Any new dependencies in requirements.txt

Happy coding! 🐙
