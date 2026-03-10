"""
Wordlist Module
Extracts paths, parameters, and filenames for fuzzing/pentesting

This is my first shot at making a somewhat functional module for OctoCrawl.
"""

from typing import Dict, Any, Set
from urllib.parse import urlparse, parse_qs

from .example import BaseModule, ModuleMetadata, CrawlContext


class WordlistModule(BaseModule):
    """
    Generates wordlists for fuzzing and pentesting
    """
    
    def get_metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="wordlist",
            version="1.0.0",
            description="Generates wordlists from discovered paths and parameters",
            author="@b3rt1ng",
            requires=[],
            category="security"
        )
    
    async def run(self, context: CrawlContext) -> Dict[str, Any]:
        """Extracts wordlists from URLs"""
        
        self.log("Extracting wordlists...", "INFO")
        
        paths: Set[str] = set()
        parameters: Set[str] = set()
        filenames: Set[str] = set()
        extensions: Set[str] = set()
        directories: Set[str] = set()
        
        for url in context.gathered_urls.keys():
            parsed = urlparse(url)
            
            path_parts = [p for p in parsed.path.split('/') if p]
            for part in path_parts:
                if '.' in part:
                    filenames.add(part)
                    ext = part.split('.')[-1]
                    extensions.add(ext)
                else:
                    directories.add(part)
                
                paths.add(part)
            
            if parsed.query:
                params = parse_qs(parsed.query)
                for param_name in params.keys():
                    parameters.add(param_name)
        
        wordlists = {
            'paths': sorted(paths),
            'parameters': sorted(parameters),
            'filenames': sorted(filenames),
            'extensions': sorted(extensions),
            'directories': sorted(directories)
        }
        
        output_files = {}
        
        for name, words in wordlists.items():
            if words:
                content = '\n'.join(words)
                file = self.save_output(
                    f"wordlist_{name}_{context.base_domain}.txt",
                    content
                )
                output_files[name] = str(file)
        
        all_words = set()
        for words in wordlists.values():
            all_words.update(words)
        
        combined_file = self.save_output(
            f"wordlist_combined_{context.base_domain}.txt",
            '\n'.join(sorted(all_words))
        )
        output_files['combined'] = str(combined_file)
        
        report = self._generate_report(context, wordlists)
        report_file = self.save_output(
            f"wordlist_report_{context.base_domain}.md",
            report
        )
        
        self.log(f"Generated {len(output_files)} wordlist files", "INFO")
        self.log(f"Total unique words: {len(all_words)}", "INFO")
        
        return {
            'total_words': len(all_words),
            'breakdown': {k: len(v) for k, v in wordlists.items()},
            'output_files': output_files,
            'report_file': str(report_file)
        }
    
    def _generate_report(self, context: CrawlContext, wordlists: Dict[str, list]) -> str:
        """Generates a markdown report"""
        
        report = f"""# Wordlist Generation Report

**Target:** {context.start_url}  
**Domain:** {context.base_domain}

---

## Statistics

"""
        
        for name, words in wordlists.items():
            report += f"- **{name.capitalize()}**: {len(words)} unique entries\n"
        
        report += """

---

## Sample Entries

"""
        
        for name, words in wordlists.items():
            if words:
                report += f"\n### {name.capitalize()}\n\n"
                sample = sorted(words)[:20]
                for word in sample:
                    report += f"- `{word}`\n"
                
                if len(words) > 20:
                    report += f"\n*...and {len(words) - 20} more (see {name} wordlist file)*\n"
        
        report += """

---

## Usage Examples

### With ffuf
```bash
ffuf -u https://target.com/FUZZ -w wordlist_paths_*.txt
ffuf -u https://target.com/?FUZZ=value -w wordlist_parameters_*.txt
```

### With gobuster
```bash
gobuster dir -u https://target.com -w wordlist_directories_*.txt
```

### With wfuzz
```bash
wfuzz -u https://target.com/FUZZ -w wordlist_combined_*.txt
```

"""
        
        return report