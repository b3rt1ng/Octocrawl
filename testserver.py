#!/usr/bin/env python3
"""
This is a test HTTP server i use to test functionallities of octocrawl.
I thought it could be useful for other people to test the crawler as well to unerstand how it behaves.
I also like to use this as a local webserver for CTFs and sometimes pentests, so here it goes :)

Quick disclaimer: This file is fully vibe coded and might not follow best practices / nice code structure.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import socket
import sys
import os
from pathlib import Path

try:
    script_dir = Path(__file__).parent
    src_dir = script_dir / "src"
    if src_dir.exists():
        sys.path.insert(0, str(src_dir))
    from ui import gradient_text, colored_text, PURPLE, ORANGE, GREEN, YELLOW, LIGHT_ORANGE, PEACH
    HAS_UI = True
except ImportError:
    HAS_UI = False
    def gradient_text(text, start_color=None, end_color=None):
        return text
    def colored_text(text, color, bg=None):
        return str(text)
    PURPLE = GREEN = YELLOW = LIGHT_ORANGE = PEACH = ORANGE = None

class TestRequestHandler(SimpleHTTPRequestHandler):
    
    request_counter = 0
    
    def log_request_details(self):
        TestRequestHandler.request_counter += 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        print("\n" + gradient_text("=" * 80, PURPLE, ORANGE))
        print(gradient_text(f"📥 REQUEST #{TestRequestHandler.request_counter} - {timestamp}", PURPLE, ORANGE))
        print(gradient_text("=" * 80, PURPLE, ORANGE))
        
        print(f"Method:    {colored_text(self.command, GREEN)}")
        parsed_path = urlparse(self.path)
        print(f"Path:      {colored_text(parsed_path.path, GREEN)}")
        if parsed_path.query:
            print(f"Query:     {colored_text(parsed_path.query, PEACH)}")
            query_params = parse_qs(parsed_path.query)
            for key, values in query_params.items():
                print(f"           {key} = {values}")
        
        print(gradient_text("\n📋 HEADERS:", PURPLE, ORANGE))
        print("-" * 80)
        
        if 'User-Agent' in self.headers:
            print(f"{colored_text('User-Agent:', YELLOW):30} {colored_text(self.headers['User-Agent'], YELLOW)}")
        
        important_headers = ['Host', 'Accept', 'Accept-Encoding', 'Accept-Language', 
                           'Connection', 'Cookie', 'Referer', 'Content-Type', 'Content-Length']
        
        for header in important_headers:
            if header in self.headers and header != 'User-Agent':
                print(f"{header:18} {self.headers[header]}")
        
        other_headers = [h for h in self.headers.keys() 
                        if h not in important_headers + ['User-Agent']]
        if other_headers:
            print(gradient_text("\nOther headers:", PEACH, ORANGE))
            for header in other_headers:
                print(f"{header:18} {self.headers[header]}")
        
        print(gradient_text("\n🌐 CLIENT INFO:", PURPLE, ORANGE))
        print("-" * 80)
        print(f"IP Address:        {colored_text(self.client_address[0], GREEN)}")
        print(f"Port:              {colored_text(self.client_address[1], GREEN)}")
        
        if self.command in ['POST', 'PUT', 'PATCH']:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                print(gradient_text("\n📦 REQUEST BODY:", PURPLE, ORANGE))
                print("-" * 80)
                try:
                    json_body = json.loads(body.decode('utf-8'))
                    print(json.dumps(json_body, indent=2))
                except:
                    print(body.decode('utf-8', errors='replace'))
        
        print(gradient_text("=" * 80, PURPLE, ORANGE) + "\n")
    
    def do_GET(self):
        self.log_request_details()
        return SimpleHTTPRequestHandler.do_GET(self)
    
    def do_HEAD(self):
        self.log_request_details()
        return SimpleHTTPRequestHandler.do_HEAD(self)
    
    def do_POST(self):
        self.log_request_details()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {"status": "success", "message": "POST received"}
        self.wfile.write(json.dumps(response).encode())
    
    def end_headers(self):
        self.send_header('X-Test-Server', 'OctoCrawl-Test')
        self.send_header('X-Request-Count', str(TestRequestHandler.request_counter))
        self.send_header('X-Timestamp', datetime.now().isoformat())
        SimpleHTTPRequestHandler.end_headers(self)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "127.0.0.1"

def get_vpn_ip():
    import netifaces
    
    vpn_interfaces = []
    try:
        for iface in netifaces.interfaces():
            if iface.startswith(('tun', 'tap', 'wg')):
                try:
                    addrs = netifaces.ifaddresses(iface)
                    if netifaces.AF_INET in addrs:
                        ip = addrs[netifaces.AF_INET][0]['addr']
                        vpn_interfaces.append((iface, ip))
                except:
                    continue
        return vpn_interfaces
    except ImportError:
        try:
            import subprocess
            result = subprocess.run(['ip', 'addr', 'show', 'tun0'], 
                                  capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'inet ' in line:
                        ip = line.strip().split()[1].split('/')[0]
                        return [('tun0', ip)]
        except:
            pass
        return []

def display_server_banner():
    banner = r"""                       
⠀⠀⠀⠀⣀⣤⡶⠾⠛⠛⠋⠉⠙⠛⠿⠶⣦⣄⠀⠀⠀⠀
⠀⠀⣠⡾⠛⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠿⣦⡀⠀
⠀⣼⠟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⡄
⢸⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣷    ___     _        _            _                                  
⢸⡇⠀⠀⠀⠀⠀⢀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿   /___\___| |_ ___ | |_ ___  ___| |_   ___  ___ _ ____   _____ _ __ 
⠘⣿⡀⠀⠀⣰⠟⣭⣿⣽⢷⣴⢟⣽⣯⡙⢷⡀⠀⠀⣸⡇  //  // __| __/ _ \| __/ _ \/ __| __| / __|/ _ \ '__\ \ / / _ \ '__|
⠀⠘⢷⣄⠀⣿⠀⠻⠿⠟⢸⣏⠘⠿⠿⠃⢸⡇⢀⣴⠏⠀ / \_// (__| || (_) | ||  __/\__ \ |_  \__ \  __/ |   \ V /  __/ |   
⠀⣴⣦⡙⣷⣿⣷⣄⣀⣤⣾⢿⣦⣀⣀⣤⡾⣷⢿⣥⣦⡀ \___/ \___|\__\___/ \__\___||___/\__| |___/\___|_|    \_/ \___|_|   
⢸⡯⠀⠹⠿⢇⠌⠉⠋⠉⠁⡀⢉⠙⠛⠉⠸⢿⠟⠁⢸⡇
⠈⢿⣄⡨⠠⠀⣁⡅⠀⠉⠆⡐⠀⠀⢮⣆⠈⠊⠀⢰⣼⠇
⠀⠀⠉⠛⠛⠛⣿⣿⣀⣠⡼⢷⣄⣄⣀⣿⠛⠛⠛⠋⠁⠀  
"""
    print(gradient_text(banner, PURPLE, ORANGE))

def run_server(port=8000, directory="."):
    os.chdir(directory)
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, TestRequestHandler)
    
    local_ip = get_local_ip()
    vpn_ips = get_vpn_ip()
    current_dir = os.getcwd()
    
    print("\n" + gradient_text("=" * 80, PURPLE, ORANGE))
    display_server_banner()
    print(gradient_text("=" * 80, PURPLE, ORANGE))
    print(f"\n{colored_text('✅ Server started successfully!', GREEN)}")
    print(f"\n{gradient_text('📁 Serving directory:', PURPLE, ORANGE)} {colored_text(current_dir, PEACH)}")
    print(f"\n{gradient_text('📡 Listening on:', PURPLE, ORANGE)}")
    print(f"   • Local:   {colored_text(f'http://127.0.0.1:{port}', GREEN)}")
    print(f"   • Network: {colored_text(f'http://{local_ip}:{port}', GREEN)}")
    
    if vpn_ips:
        for iface, ip in vpn_ips:
            print(f"   • {iface.upper():8} {colored_text(f'http://{ip}:{port}', YELLOW)}")
    
    print(f"\n{gradient_text('💡 Test your crawler with:', YELLOW, ORANGE)}")
    print(f"   {colored_text(f'octocrawl http://127.0.0.1:{port}', PEACH)}")
    print(f"   {colored_text(f'octocrawl http://127.0.0.1:{port} --agent \"MyCustomAgent/1.0\"', PEACH)}")
    print(f"\n{gradient_text('⌨️  Press Ctrl+C to stop the server', PURPLE, ORANGE)}")
    print(gradient_text("=" * 80, PURPLE, ORANGE) + "\n")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n" + gradient_text("🛑 Server stopped by user", YELLOW, ORANGE))
        print(gradient_text(f"📊 Total requests processed: {TestRequestHandler.request_counter}", PURPLE, ORANGE))
        httpd.shutdown()

if __name__ == "__main__":
    port = 8000
    directory = "."
    
    args = sys.argv[1:]
    
    if len(args) > 0:
        try:
            port = int(args[0])
            if len(args) > 1:
                directory = args[1]
        except ValueError:
            directory = args[0]
            if len(args) > 1:
                try:
                    port = int(args[1])
                except ValueError:
                    print(gradient_text(f"❌ Invalid port number: {args[1]}", ORANGE, ORANGE))
                    print(gradient_text("Usage: python test_server.py [port] [directory]", PEACH, ORANGE))
                    print(gradient_text("   or: python test_server.py [directory] [port]", PEACH, ORANGE))
                    sys.exit(1)
    
    if not HAS_UI:
        print("⚠️  Warning: Could not import OctoCrawl UI module. Using plain text output.")
        print("   Make sure test_server.py is in the OctoCrawl project root.\n")
    
    try:
        run_server(port, directory)
    except OSError as e:
        if e.errno == 98 or e.errno == 48:  # Address already in use
            print(gradient_text(f"\n❌ Error: Port {port} is already in use", ORANGE, ORANGE))
            print(gradient_text(f"💡 Try another port: python test_server.py {port + 1}", PEACH, ORANGE))
        else:
            print(gradient_text(f"\n❌ Error starting server: {e}", ORANGE, ORANGE))
        sys.exit(1)
    except FileNotFoundError:
        print(gradient_text(f"\n❌ Error: Directory '{directory}' not found", ORANGE, ORANGE))
        sys.exit(1)