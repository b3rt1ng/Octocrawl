# OctoCrawl 🐙

[![Python Version](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight asynchronous web crawler, written in Python for web recon. Why octocrawl? The multithreading pattern looks like an octopus trying to find its path... that's more than enough!

---
### Demo

<img src="https://i.imgur.com/mjSpJNs.gif">

---
## ✨ Features

* **Async Crawling**: Uses `asyncio` and concurrent workers to crawl sites quickly.
* **Status Checks**: Verifies the status code for every discovered resource.
* **Keyword Searching**: Scans the content of text-based files for a list of specified keywords.
* **Cookie Handling**: Allows passing cookies to crawl pages that require authentication.
* **Tree-like restitution**: Displays an intuitive visual representation of the site's architecture directly in the terminal.
* **Module API**: Use OctoCrawl's results to run your own post-crawl scripts!
* **Fuzzing**: `octocrawl fuzz` does content discovery with per-directory baseline calibration, so a soft-404 site doesn't report every word in your list as a hit.

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
  --stealth             Fewer workers, randomized delay between requests, random
                        user-agent, and automatic backoff if blocking is detected.
  --parser              HTML parser: 'lxml' (fast) or 'html.parser'. Default: lxml if installed, else html.parser.
  --version             Display the current version.
  -M, --modules         Modules to run after crawl (comma-separated).
  --list-modules        List all available modules.
  --module-info NAME    Show info about a specific module.
```

### Optimizing your crawls

The crawler uses [lxml](https://lxml.de/) automatically when it's installed, and falls back to Python's built-in [html.parser](https://docs.python.org/3/library/html.parser.html) otherwise. `lxml` uses a C-based engine (and releases the GIL, so parsing runs in parallel across workers), which is significantly faster as the number of endpoints grows. To make it available:

```bash
pipx inject octocrawl lxml
```

You can still force a specific parser with `--parser lxml` or `--parser html.parser`.

---
## 🎯 Fuzzing

`octocrawl fuzz` is a content-discovery fuzzer built on the same async engine as the crawler.

```bash
# simplest form: target is positional, FUZZ is appended, wordlist is picked for you
octocrawl fuzz https://example.org

# explicit placeholder, anywhere in the URL
octocrawl fuzz https://example.org/FUZZ.php -w wordlist.txt

# -u also works, for ffuf-style invocations
octocrawl fuzz -u https://example.org/FUZZ -w wordlist.txt
```

### Wordlist

`-w` is optional. Without it, OctoCrawl picks the first wordlist it finds in the usual
places and tells you which one:

```
📖 No wordlist given, picked /usr/share/seclists/Discovery/Web-Content/common.txt
```

The search order prefers small, high-signal lists (`common.txt` and friends) over the
large `directory-list-*` ones, so a bare run stays short. Locations probed, in order:

```
/usr/share/seclists/Discovery/Web-Content/common.txt
/usr/share/wordlists/dirb/common.txt
/usr/share/dirb/wordlists/common.txt
/usr/share/seclists/Discovery/Web-Content/raft-small-words.txt
/usr/share/dirbuster/wordlists/directory-list-2.3-small.txt
/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt
```

If none exist, OctoCrawl says so rather than guessing. Pass `-w -` to read from stdin.

### Baseline calibration

Before fuzzing a directory, OctoCrawl requests a few random paths and records what the
target answers for something that does not exist. Every response matching that baseline
is dropped.

This is what makes the output usable on a site that serves `200 OK` for every path: it
reports the real pages instead of your whole wordlist. The probes all use terms of the
same length on purpose, so a 404 page that echoes the requested path still produces a
stable baseline.

```
baseline [bare terms]: status 404, size 108, stable (4 probes)
admin        [Status: 301, Size: 0, Words: 0, Lines: 0] -> /admin/
secret.php   [Status: 200, Size: 46, Words: 3, Lines: 0]
```

Each extension gets its own baseline, since `/x` and `/x.php` can answer very differently.
Turn it off with `--no-calibrate` (a default status matcher is then applied instead).

### Matchers and filters

Filters are applied first and win over matchers. Within one rule the values are OR'd,
across rules they are AND'd. Specs take single values, comma lists and ranges:
`-mc 200,301,400-499`, or `-mc all`.

```bash
# only 200s
octocrawl fuzz https://example.org/FUZZ -w words.txt -mc 200

# everything except a known-noisy response size
octocrawl fuzz https://example.org/FUZZ -w words.txt -mc all -fs 1234

# only responses whose body matches a regex
octocrawl fuzz https://example.org/FUZZ -w words.txt -mr 'DB_PASSWORD'
```

### Recursion and extensions

```bash
# append extensions to every term, and fuzz inside discovered directories
octocrawl fuzz https://example.org/FUZZ -w words.txt -e .php,.bak -r --recursion-depth 2
```

Recursion follows directories found via a redirect to a trailing slash, which is why
redirects are **not** followed by default. Each new directory is calibrated on its own.

### Other injection points

FUZZ works in headers and in the request body too:

```bash
# virtual host discovery
octocrawl fuzz https://example.org/ -w hosts.txt -H "Host: FUZZ.example.org"

# POST body (--data implies POST)
octocrawl fuzz https://example.org/lookup -w ids.txt -d "id=FUZZ"
```

### All fuzz options
```
  url                    Target URL; FUZZ marks the injection point.
                         Without FUZZ, it is appended to the path.
  -u, --url URL          Same as the positional target (ffuf-style).
  -w, --wordlist FILE    Wordlist file, or '-' for stdin.
                         Optional: auto-selected when omitted.
  -e, --extensions EXT   Extensions to append to each term, comma-separated.
  -t, --workers NUM      Concurrent workers (default: 40, or 5 with --stealth).
  --timeout SEC          Timeout per request (default: 10).
  -X, --method VERB      HTTP method (default: GET, or POST with --data).
  -d, --data BODY        Request body; FUZZ is substituted here too.
  -H, --header "K: V"    Extra header, repeatable; FUZZ works in the value.
  -c, --cookies "k=v"    Cookies to send with requests.
  -ra, --random-agent    Randomize user agent for each request.
  --agent "UA string"    Custom User-Agent string.
  --follow-redirects     Follow redirects (off by default).
  -mc/-ms/-mw/-ml SPEC   Match status code / size / words / lines.
  -mr RE                 Match responses whose body matches this regex.
  -fc/-fs/-fw/-fl SPEC   Filter out status code / size / words / lines.
  -fr RE                 Filter out responses whose body matches this regex.
  --no-calibrate         Skip baseline calibration.
  --calibrate-probes N   Random probes per directory (default: 4).
  -r, --recursion        Fuzz inside discovered directories.
  --recursion-depth N    Maximum recursion depth (default: 1).
  --max-requests N       Stop after this many queued requests (default: 100000).
  --stealth              Fewer workers, randomized delay, random user-agent.
  -o, --output FILE      Save results (.json for structured output).
```

The wordlist is streamed from disk rather than loaded, and only matches are kept in
memory, so a 500k-term list costs the same as a 5k one. `--max-requests` is a deliberate
ceiling: a fuzz run is far louder than a crawl, so raise it on purpose.

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
