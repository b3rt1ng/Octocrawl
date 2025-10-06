from ui import colorize_status, gradient_text, format_keywords, PURPLE, ORANGE, LIGHT_ORANGE, PEACH, LIGHT_PEACH, GREEN, YELLOW
from urllib.parse import urljoin
import sys

class TreeMaker:
    def __init__(self, base_url="", noshow=None):
        self.base_url = base_url
        self.noshow = noshow if noshow is not None else []
    
    def colorize_status(self, status):
        return f"[{status}]" if status else "[---]"

    def gradient_text(self, text):
        return text

    def print_tree(self, data, show_url=False, prefix="", base_path_url=None, output_stream=sys.stdout):
        if base_path_url is None:
            base_path_url = self.base_url

        filtered_data = {
            key: value for key, value in data.items()
            if not (isinstance(key, str) and any(key.lower().endswith(ext) for ext in self.noshow))
        }
        
        items = list(filtered_data.items())
        for index, (key, value) in enumerate(items):
            is_last = index == len(items) - 1
            pointer = gradient_text("└── ") if is_last else gradient_text("├── ")

            is_endpoint = '_data' in value
            children = {k: v for k, v in value.items() if k != '_data'}
            is_directory = bool(children)
            
            display_name = key
            status = "Directory"
            keywords_str = ""
            
            base_for_join = base_path_url if base_path_url.endswith('/') else base_path_url + '/'
            current_url = urljoin(base_for_join, key)

            if is_endpoint:
                url_data = value['_data']
                status = url_data.get('code', '---')
                if show_url:
                    display_name = url_data.get('url', current_url)

                keywords_found = url_data.get('keywords', {})
                if keywords_found:
                    display_name = gradient_text(display_name, start_color=PEACH, end_color=GREEN)
                keywords_str = format_keywords(keywords_found)
            
            elif is_directory and show_url:
                display_name = current_url

            print(prefix + pointer + display_name + " " + colorize_status(status) + keywords_str, file=output_stream)

            if is_directory:
                extension = "    " if is_last else gradient_text("│   ")
                self.print_tree(children, show_url, prefix + extension, base_path_url=current_url, output_stream=output_stream)

    def clean_url_join(self, base, path):
        from urllib.parse import urljoin
        return urljoin(base, path)