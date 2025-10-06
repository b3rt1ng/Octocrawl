# OctoCrawl 🐙

[![Python Version](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight asynchronous web crawler, written in Python for web recon. Why octocrawl ? the multithreading pattern looks like an octopus trying to find it's path... that's more than enough !

---
### Demo

<img src="https://i.imgur.com/sSNzTge.gif">

---
## ✨ Features

* **Multi-threaded Scanning**: Utilizes multiple threads to crawl sites quickly.
* **Status Checks**: Verifies the status code for every discovered resource.
* **Keyword Searching**: Scans the content of text-based files for a list of specified keywords.
* **Cookie Handling**: Allows passing cookies to crawl pages that require authentication.
* **Tree like restitution**: Displays an intuitive and visual representation of the site's architecture directly in the terminal.

---
## 🚀 Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/b3rt1ng/Octocrawl
    cd OctoCrawl
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Install system wide: (optional)**
    ```bash
    python3 install.py
    ```

---
## 💻 Usage

### Basic Command
To run a simple crawl with default options:
```bash
python3 main.py https://example.org/
```

### Advanced Example
Run a crawl using 15 threads, displaying full URLs, searching for the keywords "api" and "user", and saving the report to a file:
```bash
python3 main.py https://example.org --workers 15 --fullpath --keywords "api,user" -o report.txt
```

### More Advanced Example
After running the install script, the octocrawl command becomes available system-wide from any directory:
```bash
# Basic crawl
octocrawl https://example.org
# Advanced crawl
octocrawl https://example.org --workers 15 --keywords "api,user"
```

You can also update the tool from your terminal:
```bash
octocrawl --update
```
### Optimizing your crawls

by default the crawler is [html.parser](https://docs.python.org/3/library/html.parser.html), but you can fine tune your engine for larger crawl. For exemple, if you enable directory listing, there's a high chance that the amount of data to analyse will get **BIG**! In that case, you can install lxml, wich uses a C based engine and is therefore faster :
```
pip install lxml
```

and use the `--parser lxml` option. it is slightly less accurate but gains way much more time as the amount of endpoints grows.
### All Options

```
usage: octocrawl [-h] [-w NUM] [-i EXT] [--fullpath] [-o FILE] [--timeout SEC] [--cookies "key1=val1;key2=val2"] [-k "word1,word2"] [--listing [MODE]] [--parser PARSER] [--version] [--update] [url]

OctoCrawl: A simple, asyncio-based website crawler.

positional arguments:
  url                   The starting URL for the crawl.

options:
  -h, --help            show this help message and exit
  -w, --workers NUM     Number of concurrent workers (default: 80).
  -i, --ignore EXT      File extensions to ignore in the final report, comma-separated (e.g., .jpg,.png).
  --fullpath            Displays full URLs in the final tree report.
  -o, --output FILE     Saves the report to a file. Format is determined by extension (.json or .txt).
  --timeout SEC         Timeout in seconds for each HTTP request (default: 10).
  --cookies "key1=val1;key2=val2"
                        Cookies to send with requests.
  -k, --keywords "word1,word2"
                        Keywords to search for in pages, comma-separated.
  --listing [MODE]      Enables Phase 2 to actively check for directory listings. Use 'only' to show only listing discoveries.
  --parser PARSER       HTML parser to use: 'lxml' (fast) or 'html.parser' (built-in).
  --version             Display the current version of OctoCrawl.
  --update              Check for updates and apply them.
```
