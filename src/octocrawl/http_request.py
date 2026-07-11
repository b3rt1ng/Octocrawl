import httpx
import os
from urllib.parse import urlparse
from octocrawl.user_agents import RandomUserAgent

GET_REQUEST_EXTENSIONS = {'.html', '.htm', '.php', '.js', '.css', '.json', '.xml', '.svg', '.txt'}

_client = None
_client_limits = None


def configure_client(max_workers: int):
    """Size the shared HTTP client's connection pool to match the crawler's
    concurrency, so worker coroutines can actually reuse keep-alive connections
    instead of re-doing a TCP/TLS handshake on every request. Must be called
    before the first request (httpx.Limits defaults to only 20 keepalive
    connections, which starves setups with more concurrent workers)."""
    global _client_limits
    _client_limits = httpx.Limits(
        max_connections=max_workers,
        max_keepalive_connections=max_workers,
    )


def _get_client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=10,
            verify=False,
            limits=_client_limits or httpx.Limits(),
        )
    return _client

def _is_invalid_url(url: str) -> bool:
    """Return True if the URL should be skipped (e.g. contains embedded base64 data)."""
    import re
    # Detect URLs whose path contains a base64 segment (e.g. /image/png;base64,...)
    if re.search(r'[;,]base64,', url):
        return True
    return False


async def http_request(url, timeout=5, cookies=None, random_agent=False, custom_agent=None):
    result = {
        "response_code": "Error",
        "done": False,
        "content": "",
        "content_type": "error",
        "headers": {}
    }

    if _is_invalid_url(url):
        return result

    try:
        request_headers = {}
        
        if custom_agent:
            request_headers["User-Agent"] = custom_agent
        elif random_agent:
            request_headers["User-Agent"] = RandomUserAgent.get()
        else:
            request_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        request_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        request_headers["Accept-Language"] = "en-US,en;q=0.9"
        request_headers["Accept-Encoding"] = "gzip, deflate"
        request_headers["Connection"] = "keep-alive"
        
        path = urlparse(url).path
        _, extension = os.path.splitext(path.lower())
        use_get_request = (extension in GET_REQUEST_EXTENSIONS) or (not extension)

        client = _get_client()

        if use_get_request:
            response = await client.get(
                url,
                timeout=timeout,
                cookies=cookies,
                headers=request_headers
            )
            result["content"] = response.text
        else:
            response = await client.head(
                url,
                timeout=timeout,
                cookies=cookies,
                headers=request_headers
            )
            result["content"] = ""
        
        result["response_code"] = int(response.status_code)
        result["headers"] = dict(response.headers)

        # 4xx/5xx are a routine, expected outcome while crawling (broken links,
        # forbidden paths, ...) rather than an exceptional case, so we branch on
        # the status here instead of raise_for_status() + except HTTPStatusError -
        # exceptions are expensive in Python and this fires on a very hot path.
        if not response.is_error:
            result["content_type"] = response.headers.get('Content-Type', 'unknown')
            result["done"] = True

    except httpx.RequestError:
        pass
    
    return result