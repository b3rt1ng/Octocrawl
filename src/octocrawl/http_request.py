import httpx
import os
import re
from urllib.parse import urlparse
from octocrawl.user_agents import RandomUserAgent

GET_REQUEST_EXTENSIONS = {'.html', '.htm', '.php', '.js', '.css', '.json', '.xml', '.svg', '.txt'}

# matches embedded base64 data used as a fake URL path, e.g. /image/png;base64,...
_BASE64_URL_PATTERN = re.compile(r'[;,]base64,')

_client = None
_client_limits = None


def configure_client(max_workers: int):
    # call before the first request: httpx defaults to 20 keepalive connections,
    # not enough once max_workers goes higher than that
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
    return bool(_BASE64_URL_PATTERN.search(url))


async def http_request(url, timeout=5, cookies=None, random_agent=False, custom_agent=None, extra_headers=None):
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

        if extra_headers:
            request_headers.update(extra_headers)

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

        # 4xx/5xx happen on almost every crawl, so check the status directly
        # instead of raise_for_status()/except - exceptions aren't free and this
        # runs on every single request
        if not response.is_error:
            result["content_type"] = response.headers.get('Content-Type', 'unknown')
            result["done"] = True

    except httpx.RequestError:
        pass
    
    return result