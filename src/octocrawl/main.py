#!/usr/bin/env python3
import argparse
import os
import sys
import importlib.metadata
import importlib.resources
import asyncio
import time

from octocrawl.crawler import crawler
from octocrawl.ui import clear_status_line, display_art, gradient_text, print_report_box
from octocrawl.fuzz_rules import DEFAULT_CALIBRATION_PROBES
from octocrawl.fuzzer import (DEFAULT_MAX_REQUESTS, DEFAULT_WORKERS, FUZZ_KEYWORD,
                              STEALTH_DEFAULT_WORKERS, Fuzzer, build_rules)
from octocrawl.modules.example import CrawlContext
from octocrawl.modules.module_manager import ModuleManager


def get_current_version():
    # pyproject.toml is the single source of truth; read it back from the
    # installed package metadata rather than keeping a second copy in the tree
    try:
        return importlib.metadata.version("octocrawl")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _lxml_available():
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


def split_csv(value):
    # strip *before* filtering: " , " must not turn into an empty entry
    return [item.strip() for item in value.split(',') if item.strip()]


def normalize_extensions(value):
    return [ext if ext.startswith('.') else f'.{ext}' for ext in split_csv(value)]


def parse_cookies(raw):
    if not raw:
        return {}
    try:
        return {
            key.strip(): value.strip()
            for key, value in (item.split('=', 1) for item in raw.split(';') if item.strip())
        }
    except ValueError:
        print("Error: Invalid cookie format. Use 'key1=value1;key2=value2'.", file=sys.stderr)
        sys.exit(1)


def parse_headers(raw_headers):
    headers = {}
    for item in raw_headers or []:
        if ':' not in item:
            print(f"Error: Invalid header '{item}'. Use 'Name: value'.", file=sys.stderr)
            sys.exit(1)
        name, _, value = item.partition(':')
        headers[name.strip()] = value.strip()
    return headers


# where content-discovery wordlists usually live, so a run with no -w can pick one up
# by itself. Ordered best-first on purpose: a zero-argument run should land on a small,
# high-signal list, not a 220k-line monster that turns a 10s run into a 7-minute one.
COMMON_WORDLIST_PATHS = (
    "/usr/share/seclists/Discovery/Web-Content/common.txt",
    "/usr/share/wordlists/dirb/common.txt",
    "/usr/share/dirb/wordlists/common.txt",
    "/usr/share/seclists/Discovery/Web-Content/raft-small-words.txt",
    "/usr/share/dirbuster/wordlists/directory-list-2.3-small.txt",
    "/usr/share/seclists/Discovery/Web-Content/directory-list-2.3-medium.txt",
)


def available_wordlists(limit=None):
    found = [path for path in COMMON_WORDLIST_PATHS if os.path.isfile(path)]
    return found[:limit] if limit else found


def resolve_parser(requested):
    # lxml is C-based: it releases the GIL while parsing, so offloading it to the
    # worker threads actually runs in parallel (html.parser, being pure Python,
    # can't). Prefer it when present; only warn if the user asked for it explicitly.
    if requested is None:
        return "lxml" if _lxml_available() else "html.parser"
    if requested == "lxml" and not _lxml_available():
        print("Warning: lxml not installed, falling back to html.parser. "
              "Install it with: pipx inject octocrawl lxml", file=sys.stderr)
        return "html.parser"
    return requested


async def main():
    parser = argparse.ArgumentParser(
        description="OctoCrawl: A simple, asyncio-based website crawler.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument("url", nargs='?', default=None, help="The starting URL for the crawl.")
    parser.add_argument("-w", "--workers", type=int, default=None, metavar="NUM",
                        help="Number of concurrent workers (default: 80, or 10 with --stealth).")
    parser.add_argument("-i", "--ignore", type=str, default="", metavar="EXT",
                        help="File extensions to ignore in the final report, comma-separated.")
    parser.add_argument("-d", "--display", type=str, default="", metavar="EXT",
                        help="File extensions to display exclusively in the final report.")
    parser.add_argument("--fullpath", action="store_true",
                        help="Displays full URLs in the final tree report.")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Saves the report to a file. Format determined by extension.")
    parser.add_argument("--timeout", type=float, default=10, metavar="SEC",
                        help="Timeout in seconds for each HTTP request (default: 10).")
    parser.add_argument("-c", "--cookies", type=str, default="",
                        metavar='"key1=val1;key2=val2"', help="Cookies to send with requests.")
    parser.add_argument("-ra", "--random-agent", action="store_true",
                        help="Randomize user agents for each request")
    parser.add_argument("--agent", type=str, default="", metavar='"Custom User-Agent"',
                        help="Custom User-Agent string")
    parser.add_argument("-k", "--keywords", type=str, default="",
                        metavar='"word1,word2"', help="Keywords to search for in pages.")
    parser.add_argument("-a", "--add", type=str, default="", metavar='"path1,path2"',
                        help="Additional paths to crawl.")
    parser.add_argument("--no-robots", "-nr", action="store_true",
                        help="Skip checking robots.txt")
    parser.add_argument("--no-sitemap", "-ns", action="store_true",
                        help="Skip checking sitemap.xml")
    parser.add_argument("--parser", type=str, default=None,
                        help="HTML parser to use: 'lxml' (fast) or 'html.parser' (built-in). "
                             "Default: lxml if installed, otherwise html.parser.")
    parser.add_argument("--version", action="store_true",
                        help="Display the current version of OctoCrawl.")
    parser.add_argument("-M", "--modules", type=str, default="", metavar="mod1,mod2",
                        help="Modules to run after crawl (comma-separated). Use '--list-modules' to see available.")
    parser.add_argument("--list-modules", action="store_true",
                        help="List all available modules and exit")
    parser.add_argument("--module-info", type=str, metavar="MODULE_NAME",
                        help="Show detailed information about a specific module")
    parser.add_argument("--stealth", action="store_true",
                        help="Stealth mode: fewer workers, randomized delay between requests, "
                             "random user-agent, and automatic backoff if blocking is detected.")

    args = parser.parse_args()
    current_version = get_current_version()

    if args.version:
        print(f"🐙 OctoCrawl version: {gradient_text(current_version)}")
        sys.exit(0)

    modules_ref = importlib.resources.files("octocrawl").joinpath("modules")
    with importlib.resources.as_file(modules_ref) as modules_path:
        module_manager = ModuleManager(modules_path)
        module_manager.load_all_modules()

        if args.list_modules:
            print(gradient_text("\n🔧 Available Modules:\n"))
            modules = module_manager.list_modules()

            if not modules:
                print("No modules found.")
            else:
                categories = {}
                for mod in modules:
                    cat = mod['category']
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(mod)

                for category, mods in categories.items():
                    print(gradient_text(f"\n📦 {category.upper()}:"))
                    for mod in mods:
                        status = "✅" if mod['enabled'] else "⭕"
                        print(f"  {status} {mod['name']} (v{mod['version']}) - {mod['description']}")
                        if mod['requires']:
                            print(f"      Requirements: {', '.join(mod['requires'])}")

            sys.exit(0)

        if args.module_info:
            modules = module_manager.list_modules()
            mod_info = next((m for m in modules if m['name'] == args.module_info), None)

            if not mod_info:
                print(f"❌ Module '{args.module_info}' not found")
                sys.exit(1)

            print(gradient_text(f"\n🔍 Module Information: {mod_info['name']}\n"))
            print(f"Version:     {mod_info['version']}")
            print(f"Author:      {mod_info['author']}")
            print(f"Category:    {mod_info['category']}")
            print(f"Description: {mod_info['description']}")
            print(f"Status:      {'Enabled ✅' if mod_info['enabled'] else 'Disabled ⭕'}")

            if mod_info['requires']:
                print(f"\nRequirements:")
                for req in mod_info['requires']:
                    print(f"  - {req}")

            sys.exit(0)

        if not args.url:
            parser.error("the 'url' argument is required to start a crawl. (Use --help for more info)")

        if args.ignore and args.display:
            print("Error: Cannot use both --ignore and --display options simultaneously.", file=sys.stderr)
            sys.exit(1)

        if args.random_agent and args.agent:
            print("Error: Cannot use both --random-agent and --agent options simultaneously.", file=sys.stderr)
            sys.exit(1)

        if '://' not in args.url:
            # "example.com" would otherwise parse with an empty host and crawl nothing
            args.url = f"https://{args.url}"

        if args.workers is None:
            args.workers = 10 if args.stealth else 80

        if args.stealth and not args.agent:
            args.random_agent = True

        args.parser = resolve_parser(args.parser)

        display_art()

        keywords_list = [kw.lower() for kw in split_csv(args.keywords)]
        additional_paths = split_csv(args.add)

        requested_modules = []
        if args.modules:
            if args.modules.lower() == 'all':
                requested_modules = list(module_manager.available_modules.keys())
            else:
                requested_modules = split_csv(args.modules)

        for mod_name in requested_modules:
            if not module_manager.enable_module(mod_name):
                print(f"⚠️  Warning: Module '{mod_name}' not found", file=sys.stderr)

        config_data = {
            "Target URL": args.url,
            "Version": current_version,
            "Workers": args.workers,
            "Timeout": f"{args.timeout}s",
            "Parser": args.parser,
            "Cookies": "Yes" if args.cookies else "No",
            "Stealth Mode": "Yes" if args.stealth else "No",
        }

        if args.agent:
            config_data["User-Agent"] = f"Custom ({args.agent[:50]}{'...' if len(args.agent) > 50 else ''})"
        elif args.random_agent:
            config_data["User-Agent"] = "Random"
        else:
            config_data["User-Agent"] = "Default"

        if keywords_list:
            config_data["Keywords"] = ', '.join(keywords_list)
        if additional_paths:
            config_data["Additional Paths"] = ', '.join(additional_paths)
        if args.output:
            config_data["Output File"] = args.output
        if args.ignore:
            config_data["Ignored Extensions"] = args.ignore
        if args.display:
            config_data["Display Only"] = args.display
        if requested_modules:
            config_data["Active Modules"] = ', '.join(requested_modules)

        print_report_box("OctoCrawl Configuration", config_data)
        print(gradient_text("🐙 Starting crawl..."))

        ignored_extensions = normalize_extensions(args.ignore)
        display_extensions = normalize_extensions(args.display)

        cookies_dict = parse_cookies(args.cookies)

        start_time = time.time()

        my_crawler = crawler(
            start_url=args.url,
            max_workers=args.workers,
            timeout=args.timeout,
            cookies=cookies_dict,
            random_agent=args.random_agent,
            custom_agent=args.agent if args.agent else None,
            parser=args.parser,
            stealth=args.stealth
        )

        await my_crawler.crawl(
            show_url_in_tree=args.fullpath,
            noshow_extensions=ignored_extensions,
            display_extensions=display_extensions,
            keywords=keywords_list,
            output_file=args.output,
            additional_paths=additional_paths,
            check_robots=not args.no_robots,
            check_sitemap=not args.no_sitemap
        )

        end_time = time.time()
        crawl_duration = end_time - start_time

        print_report_box("Detected Technologies", my_crawler.technologies)
        print_report_box("Rate Limiting", my_crawler.rate_limit_summary)

        if requested_modules and my_crawler.interrupted:
            print(gradient_text("\n🔧 Crawl was interrupted, skipping modules."))
        elif requested_modules:
            print(gradient_text("\n🔧 Running post-crawl modules...\n"))

            context = CrawlContext(
                start_url=args.url,
                base_domain=my_crawler.base_domain,
                gathered_urls=my_crawler.gathered_urls,
                sitemap=my_crawler.sitemap,
                technologies=my_crawler.technologies,
                total_urls=len(my_crawler.gathered_urls),
                crawl_duration=crawl_duration,
                config={
                    'workers': args.workers,
                    'timeout': args.timeout,
                    'keywords': keywords_list,
                    'cookies': cookies_dict,
                    'random_agent': args.random_agent,
                    'custom_agent': args.agent or None,
                    'stealth': args.stealth,
                },
                response_headers=my_crawler.page_headers,
                query_params=my_crawler.query_params
            )

            module_results = await module_manager.run_modules(context)

            print(gradient_text("\n📊 Module Execution Summary:\n"))
            for mod_name, result in module_results.items():
                if result['success']:
                    print(f"  ✅ {mod_name}: Success")
                else:
                    print(f"  ❌ {mod_name}: Failed - {result.get('error', 'Unknown error')}")


def build_fuzz_parser():
    parser = argparse.ArgumentParser(
        prog="octocrawl fuzz",
        description="OctoCrawl fuzz: content discovery with per-directory baseline calibration.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""examples:
  octocrawl fuzz -u https://target.com/FUZZ -w words.txt
  octocrawl fuzz -u https://target.com/FUZZ -w words.txt -e .php,.bak -r
  octocrawl fuzz -u https://target.com/FUZZ -w words.txt -mc all -fs 1234
  octocrawl fuzz -u https://target.com/ -w hosts.txt -H "Host: FUZZ.target.com"
"""
    )

    parser.add_argument("url", nargs='?', default=None,
                        help="Target URL. Put FUZZ where terms should be injected;\n"
                             "without it, FUZZ is appended to the path.")
    parser.add_argument("-u", "--url", dest="url_flag", default=None, metavar="URL",
                        help="Same as the positional target, for ffuf-style invocations.")
    parser.add_argument("-w", "--wordlist", default=None, metavar="FILE",
                        help="Wordlist file, or '-' to read from stdin.")
    parser.add_argument("-e", "--extensions", type=str, default="", metavar="EXT",
                        help="Extensions to append to each term, comma-separated (e.g. .php,.bak).")
    parser.add_argument("-t", "--workers", type=int, default=None, metavar="NUM",
                        help="Concurrent workers (default: 40, or 5 with --stealth).")
    parser.add_argument("--timeout", type=float, default=10, metavar="SEC",
                        help="Timeout in seconds for each request (default: 10).")
    parser.add_argument("-X", "--method", type=str, default=None, metavar="VERB",
                        help="HTTP method (default: GET, or POST when --data is given).")
    parser.add_argument("-d", "--data", type=str, default=None, metavar="BODY",
                        help="Request body; FUZZ is substituted here too.")
    parser.add_argument("-H", "--header", action="append", default=[], metavar='"Name: value"',
                        help="Extra header, repeatable; FUZZ is substituted in the value.")
    parser.add_argument("-c", "--cookies", type=str, default="", metavar='"k=v;k2=v2"',
                        help="Cookies to send with requests.")
    parser.add_argument("-ra", "--random-agent", action="store_true",
                        help="Randomize user agents for each request")
    parser.add_argument("--agent", type=str, default="", metavar='"Custom User-Agent"',
                        help="Custom User-Agent string")
    parser.add_argument("--follow-redirects", action="store_true",
                        help="Follow redirects. Off by default: a 301 to /admin/ is the finding,\n"
                             "and recursion relies on seeing it.")

    matchers = parser.add_argument_group("matchers (keep only what these allow)")
    matchers.add_argument("-mc", "--match-code", type=str, default=None, metavar="SPEC",
                          help="Status codes, e.g. '200,301,400-499' or 'all'.")
    matchers.add_argument("-ms", "--match-size", type=str, default=None, metavar="SPEC",
                          help="Response sizes in bytes.")
    matchers.add_argument("-mw", "--match-words", type=str, default=None, metavar="SPEC",
                          help="Word counts.")
    matchers.add_argument("-ml", "--match-lines", type=str, default=None, metavar="SPEC",
                          help="Line counts.")
    matchers.add_argument("-mr", "--match-regex", type=str, default=None, metavar="RE",
                          help="Keep only responses whose body matches this regex.")

    filters = parser.add_argument_group("filters (drop what these catch, applied first)")
    filters.add_argument("-fc", "--filter-code", type=str, default=None, metavar="SPEC")
    filters.add_argument("-fs", "--filter-size", type=str, default=None, metavar="SPEC")
    filters.add_argument("-fw", "--filter-words", type=str, default=None, metavar="SPEC")
    filters.add_argument("-fl", "--filter-lines", type=str, default=None, metavar="SPEC")
    filters.add_argument("-fr", "--filter-regex", type=str, default=None, metavar="RE")

    parser.add_argument("--no-calibrate", action="store_true",
                        help="Skip baseline calibration. Without it a soft-404 site reports\n"
                             "every term as a hit, so a default status matcher is applied instead.")
    parser.add_argument("--calibrate-probes", type=int, default=DEFAULT_CALIBRATION_PROBES,
                        metavar="N", help=f"Random probes per directory (default: {DEFAULT_CALIBRATION_PROBES}).")
    parser.add_argument("-r", "--recursion", action="store_true",
                        help="Fuzz inside discovered directories.")
    parser.add_argument("--recursion-depth", type=int, default=1, metavar="N",
                        help="Maximum recursion depth (default: 1).")
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, metavar="N",
                        help=f"Stop after this many queued requests (default: {DEFAULT_MAX_REQUESTS}).")
    parser.add_argument("--stealth", action="store_true",
                        help="Fewer workers, randomized delay between requests, random user-agent.")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Save results to a file (.json for structured output).")

    return parser


async def fuzz_main(argv):
    parser = build_fuzz_parser()
    args = parser.parse_args(argv)

    if args.url and args.url_flag and args.url != args.url_flag:
        parser.error(f"two different targets given: '{args.url}' and '{args.url_flag}'")
    args.url = args.url or args.url_flag

    if not args.url:
        parser.error("a target URL is required. (Use --help for more info)")

    auto_wordlist = False
    if not args.wordlist:
        found = available_wordlists()
        if not found:
            parser.error("no wordlist given, and none found in the usual places.\n"
                         "Pass -w <file>, or install one (e.g. 'apt install seclists').")
        args.wordlist = found[0]
        auto_wordlist = True

    if args.random_agent and args.agent:
        print("Error: Cannot use both --random-agent and --agent options simultaneously.", file=sys.stderr)
        sys.exit(1)

    if '://' not in args.url:
        args.url = f"https://{args.url}"

    if args.wordlist != '-' and not os.path.isfile(args.wordlist):
        print(f"Error: wordlist '{args.wordlist}' not found.", file=sys.stderr)
        sys.exit(1)

    headers = parse_headers(args.header)

    if FUZZ_KEYWORD not in args.url and \
            not any(FUZZ_KEYWORD in v for v in headers.values()) and \
            not (args.data and FUZZ_KEYWORD in args.data):
        # plain 'octocrawl fuzz -u https://target.com -w words.txt' should just work
        args.url = args.url.rstrip('/') + '/' + FUZZ_KEYWORD

    if args.workers is None:
        args.workers = STEALTH_DEFAULT_WORKERS if args.stealth else DEFAULT_WORKERS
    if args.stealth and not args.agent:
        args.random_agent = True

    extensions = normalize_extensions(args.extensions)
    rules = build_rules(args)

    display_art()

    if auto_wordlist:
        print(gradient_text(f"📖 No wordlist given, picked {args.wordlist}"))

    fuzzer = Fuzzer(
        args.url,
        args.wordlist,
        extensions=extensions,
        max_workers=args.workers,
        timeout=args.timeout,
        cookies=parse_cookies(args.cookies),
        extra_headers=headers,
        method=args.method,
        body=args.data,
        rules=rules,
        calibration_probes=args.calibrate_probes,
        calibrate_enabled=not args.no_calibrate,
        recursion=args.recursion,
        recursion_depth=args.recursion_depth,
        max_requests=args.max_requests,
        stealth=args.stealth,
        random_agent=args.random_agent,
        custom_agent=args.agent or None,
        follow_redirects=args.follow_redirects,
    )

    term_count = fuzzer.count_terms()
    if args.wordlist != '-' and term_count == 0:
        print(f"Error: wordlist '{args.wordlist}' has no usable terms.", file=sys.stderr)
        sys.exit(1)

    config_data = {
        "Target": args.url,
        "Version": get_current_version(),
        "Wordlist": (f"{args.wordlist} ({term_count} terms)"
                     f"{' [auto]' if auto_wordlist else ''}" if term_count else args.wordlist),
        "Workers": args.workers,
        "Timeout": f"{args.timeout}s",
        "Method": fuzzer.method or "GET",
        "Calibration": f"{args.calibrate_probes} probes/directory" if not args.no_calibrate else "Off",
        "Rules": rules.describe(),
        "Recursion": f"Yes (depth {args.recursion_depth})" if args.recursion else "No",
        "Follow redirects": "Yes" if args.follow_redirects else "No",
        "Request cap": args.max_requests,
        "Cookies": "Yes" if args.cookies else "No",
        "Stealth Mode": "Yes" if args.stealth else "No",
    }
    if extensions:
        config_data["Extensions"] = ', '.join(extensions)
    if headers:
        config_data["Extra headers"] = ', '.join(headers)
    if args.agent:
        config_data["User-Agent"] = f"Custom ({args.agent[:50]}{'...' if len(args.agent) > 50 else ''})"
    elif args.random_agent:
        config_data["User-Agent"] = "Random"
    else:
        config_data["User-Agent"] = "Default"
    if args.output:
        config_data["Output File"] = args.output

    print_report_box("OctoCrawl Fuzz Configuration", config_data)
    print(gradient_text("🐙 Starting fuzz..."))

    results = await fuzzer.run()

    clear_status_line()
    print(gradient_text(f"\n🐙 Fuzz finished. {len(results)} hit(s)."))
    print_report_box("Fuzz Summary", fuzzer.summary)

    if args.output:
        fuzzer.save(args.output)


def run():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "fuzz":
            asyncio.run(fuzz_main(sys.argv[2:]))
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print(gradient_text("\n🐙 Cancelled by user. Exiting."))


if __name__ == "__main__":
    run()