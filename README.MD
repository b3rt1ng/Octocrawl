# OctoCrawl 🐙

[![Python Version](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight asynchronous web crawler, written in Python for web recon. Why octocrawl? The multithreading pattern looks like an octopus trying to find its path... that's more than enough!

---
### Demo

<img src="https://i.imgur.com/sSNzTge.gif">

---
## ✨ Features

* **Async Crawling**: Uses `asyncio` and concurrent workers to crawl sites quickly.
* **Status Checks**: Verifies the status code for every discovered resource.
* **Keyword Searching**: Scans the content of text-based files for a list of specified keywords.
* **Cookie Handling**: Allows passing cookies to crawl pages that require authentication.
* **Tree-like restitution**: Displays an intuitive visual representation of the site's architecture directly in the terminal.
* **Module API**: Use OctoCrawl's results to run your own post-crawl scripts!

---
## 🚀 Installation

### Recommended — via pipx

`octocrawl` now works with [pipx](https://pipx.pypa.io/) !

```bash
# Simple install
pipx install octocrawl

# Install OctoCrawl directly from GitHub (latest version)
pipx install git+https://github.com/b3rt1ng/Octocrawl
```

To upgrade later:
```bash
pipx upgrade octocrawl
```

### From source

```bash
git clone https://github.com/b3rt1ng/Octocrawl
cd Octocrawl
pipx install .
```

---
## 💻 Usage

### Basic crawl
```bash
octocrawl https://example.org/
```

### Advanced example
Run a crawl with 15 workers, displaying full URLs, searching for keywords, and saving the report:
```bash
octocrawl https://example.org --workers 15 --fullpath --keywords "api,user" -o report.txt
```

### All options
```
positional arguments:
  url                   The starting URL for the crawl.

options:
  -w, --workers NUM     Number of concurrent workers (default: 80).
  -i, --ignore EXT      File extensions to ignore in the report, comma-separated.
  -d, --display EXT     File extensions to display exclusively in the report.
  --fullpath            Display full URLs in the tree report.
  -o, --output FILE     Save the report to a file (.txt or .json).
  --timeout SEC         Timeout per HTTP request in seconds (default: 10).
  -c, --cookies "k=v"   Cookies to send with requests.
  -ra, --random-agent   Randomize user agent for each request.
  --agent "UA string"   Custom User-Agent string.
  -k, --keywords "w1,w2" Keywords to search for in pages.
  -a, --add "p1,p2"     Additional paths to crawl.
  --no-robots, -nr      Skip checking robots.txt.
  --no-sitemap, -ns     Skip checking sitemap.xml.
  --parser              HTML parser: 'lxml' (fast) or 'html.parser' (default).
  --version             Display the current version.
  -M, --modules         Modules to run after crawl (comma-separated).
  --list-modules        List all available modules.
  --module-info NAME    Show info about a specific module.
```

### Optimizing your crawls

By default the crawler uses [html.parser](https://docs.python.org/3/library/html.parser.html), but you can switch to `lxml` for large sites. It uses a C-based engine and is significantly faster when the number of endpoints grows:

```bash
pipx inject octocrawl lxml
octocrawl https://example.org --parser lxml
```

---
## 🔧 Modules

OctoCrawl has a module system for post-crawl scripts that operate on the gathered data.

```bash
# List available modules
octocrawl --list-modules

# Run a specific module after crawl
octocrawl https://example.org -M headers

# Run all modules
octocrawl https://example.org -M all
```

Check the [MODULES.MD](https://github.com/b3rt1ng/Octocrawl/blob/main/src/octocrawl/modules/MODULES.MD) file for documentation on how to write your own module, and use the [example module](https://github.com/b3rt1ng/Octocrawl/blob/main/src/octocrawl/modules/example.py) as a base.
