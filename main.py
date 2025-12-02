#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path
import asyncio

real_script_path = Path(os.path.realpath(__file__))
project_root = real_script_path.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from crawler import crawler
from ui import display_art, gradient_text, print_report_box
from updater import update_command

def get_current_version():
    version_file = project_root / "version.txt"
    try:
        if version_file.exists():
            return version_file.read_text().strip()
        return "unknown"
    except Exception as e:
        print(f"Warning: Could not read version file: {e}", file=sys.stderr)
        return "unknown"

async def main():
    parser = argparse.ArgumentParser(
        description="OctoCrawl: A simple, asyncio-based website crawler.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("url", nargs='?', default=None, help="The starting URL for the crawl.")
    parser.add_argument("-w", "--workers", type=int, default=80, metavar="NUM", help="Number of concurrent workers (default: 80).")
    parser.add_argument("-i", "--ignore", type=str, default="", metavar="EXT", help="File extensions to ignore in the final report, comma-separated (e.g., .jpg,.png).")
    parser.add_argument("-d", "--display", type=str, default="", metavar="EXT", help="File extensions to display exclusively in the final report, comma-separated (e.g., js,html,css).")
    parser.add_argument("--fullpath", action="store_true", help="Displays full URLs in the final tree report.")
    parser.add_argument("-o", "--output", metavar="FILE", help="Saves the report to a file. Format is determined by extension (.json or .txt).")
    parser.add_argument("--timeout", type=float, default=10, metavar="SEC", help="Timeout in seconds for each HTTP request (default: 10).")
    parser.add_argument("--cookies", type=str, default="", metavar='"key1=val1;key2=val2"', help="Cookies to send with requests.")
    parser.add_argument("-ra", "--random-agent", action="store_true", help="will randomize user agents for each requests")
    parser.add_argument("-k", "--keywords", type=str, default="", metavar='"word1,word2"', help="Keywords to search for in pages, comma-separated.")
    parser.add_argument("--parser", type=str, default="html.parser", help="HTML parser to use: 'lxml' (fast) or 'html.parser' (built-in).")
    parser.add_argument("--version", action="store_true", help="Display the current version of OctoCrawl.")
    parser.add_argument("--update", action="store_true", help="Check for updates and apply them.")

    args = parser.parse_args()
    current_version = get_current_version()

    if args.version:
        print(f"🐙 OctoCrawl version: {gradient_text(current_version)}")
        sys.exit(0)

    if args.update:
        update_command(project_root)
        sys.exit(0)

    if not args.url:
        parser.error("l'argument 'url' est requis pour lancer un crawl. (Utilisez --help pour plus d'infos)")
        sys.exit(1)

    if args.ignore and args.display:
        print("Error: Cannot use both --ignore and --display options simultaneously.", file=sys.stderr)
        sys.exit(1)

    display_art()

    keywords_list = [kw.strip().lower() for kw in args.keywords.split(',') if kw]
    
    config_data = {
        "Target URL": args.url,
        "Version": current_version,
        "Workers": args.workers,
        "Timeout": f"{args.timeout}s",
        "Parser": args.parser,
        "Cookies": "Yes" if args.cookies else "No",
        "Random User-Agent": "Yes" if args.random_agent else "No"
    }

    if keywords_list:
        config_data["Keywords"] = ', '.join(keywords_list)

    if args.output:
        config_data["Output File"] = args.output
    
    if args.ignore:
        config_data["Ignored Extensions"] = args.ignore
    if args.display:
        config_data["Display Only"] = args.display
        
    print_report_box("OctoCrawl Configuration", config_data)

    print(gradient_text("🐙 Starting crawl..."))

    ignored_extensions = [ext.strip() if ext.strip().startswith('.') else f'.{ext.strip()}' 
                         for ext in args.ignore.split(',') if ext] if args.ignore else []
    
    display_extensions = [ext.strip() if ext.strip().startswith('.') else f'.{ext.strip()}' 
                         for ext in args.display.split(',') if ext] if args.display else []
    
    cookies_dict = {}
    if args.cookies:
        try:
            cookies_dict = {
                key.strip(): value.strip()
                for key, value in (item.split('=', 1) for item in args.cookies.split(';') if item)
            }
        except ValueError:
            print("Error: Invalid cookie format. Use 'key1=value1;key2=value2'.", file=sys.stderr)
            sys.exit(1)

    my_crawler = crawler(
        start_url=args.url, 
        max_workers=args.workers,
        timeout=args.timeout,
        cookies=cookies_dict,
        random_agent=args.random_agent,
        parser=args.parser
    )
    
    await my_crawler.crawl(
        show_url_in_tree=args.fullpath,
        noshow_extensions=ignored_extensions,
        display_extensions=display_extensions,
        keywords=keywords_list,
        output_file=args.output
    )

    print_report_box("Detected Technologies", my_crawler.technologies)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(gradient_text("\n🐙 Crawl cancelled by user. Exiting."))