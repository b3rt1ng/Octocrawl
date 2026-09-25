#!/usr/bin/env python3
import argparse
import sys
import importlib.resources
import asyncio
import time

from octocrawl.crawler import crawler
from octocrawl.ui import display_art, gradient_text, print_report_box
from octocrawl.modules.example import CrawlContext
from octocrawl.modules.module_manager import ModuleManager


def get_current_version():
    try:
        ref = importlib.resources.files("octocrawl").joinpath("version.txt")
        with importlib.resources.as_file(ref) as path:
            return path.read_text().strip()
    except Exception:
        return "unknown"


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

        cookies_dict = {}
        if args.cookies:
            try:
                cookies_dict = {
                    key.strip(): value.strip()
                    for key, value in (item.split('=', 1) for item in args.cookies.split(';') if item.strip())
                }
            except ValueError:
                print("Error: Invalid cookie format. Use 'key1=value1;key2=value2'.", file=sys.stderr)
                sys.exit(1)

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


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(gradient_text("\n🐙 Crawl cancelled by user. Exiting."))


if __name__ == "__main__":
    run()