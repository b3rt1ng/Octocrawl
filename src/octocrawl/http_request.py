import httpx
import os
import re
from urllib.parse import urlparse
from octocrawl.user_agents import RandomUserAgent

# extensions whose body the crawler actually parses for links (HTML + JSON).
# no-extension URLs are treated the same way since they're usually pages.
# (when JS parsing lands, '.js' moves here so its body is always fetched.)
PARSED_EXTENSIONS = {'.html', '.htm', '.php', '.json'}

# text assets we don't parse for links but may want to keyword-search; only
# worth a full GET when the user actually passed --keywords.
TEXT_EXTENSIONS = {'.js', '.css', '.xml', '.svg', '.txt'}

# matches embedded base64 data used as a fake URL path, e.g. /image/png;base64,...
_BASE64_URL_PATTERN = re.compile(r'[;,]base64,')


def _wants_body(url, include_text):
    # decide GET vs HEAD from the extension: we only download a body when we'll
    # actually use it (parse it, or keyword-search a text asset). everything else
    # (images, fonts, archives, ...) just needs a HEAD to confirm it exists.
    extension = os.path.splitext(urlparse(url).path.lower())[1]
    if not extension or extension in PARSED_EXTENSIONS:
        return True
    if include_text and extension in TEXT_EXTENSIONS:
        return True
    return False

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


# bodies we never need to read, even on a GET: skip the download entirely
_BINARY_CONTENT_PREFIXES = ('image/', 'video/', 'audio/', 'font/', 'application/pdf',
                            'application/zip', 'application/gzip', 'application/x-',
                            'application/octet-stream')

# hard cap on a single body: a no-extension URL can just as well be a 500MB download
MAX_BODY_BYTES = 10 * 1024 * 1024

# HEAD answers some servers/CDNs get wrong; retry with GET to get the real status
_HEAD_FALLBACK_CODES = (400, 403, 405, 501)


async def _read_capped_body(response):
    content_type = response.headers.get('Content-Type', '').lower()
    if content_type.startswith(_BINARY_CONTENT_PREFIXES):
        return ""

    # oversized text is truncated, not dropped: the first 10MB of a page still hold links
    chunks = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BODY_BYTES:
            break
    return b"".join(chunks)[:MAX_BODY_BYTES].decode(response.encoding or 'utf-8', errors='replace')


async def http_request(url, timeout=5, cookies=None, random_agent=False, custom_agent=None,
                       extra_headers=None, force_get=False, include_text=False,
                       follow_redirects=None, method=None, content=None):
    result = {
        "response_code": "Error",
        "done": False,
        "content": "",
        "content_type": "error",
        "headers": {},
        "final_url": url
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
        # no "Connection: keep-alive" here: httpx handles it, and it's a forbidden
        # header in HTTP/2 (Go servers - Caddy, Traefik... - reset the stream on it)

        if extra_headers:
            request_headers.update(extra_headers)

        client = _get_client()
        request_kwargs = {"timeout": timeout, "cookies": cookies, "headers": request_headers}

        # the client follows redirects by default (what the crawler wants), but a
        # fuzzer needs to see the 301 itself: a redirect to /admin/ is the finding
        if follow_redirects is not None:
            request_kwargs["follow_redirects"] = follow_redirects

        verb = method.upper() if method else ("GET" if (force_get or _wants_body(url, include_text)) else "HEAD")

        if verb == "HEAD":
            # a HEAD carries no body, so `content` is deliberately dropped here
            response = await client.head(url, **request_kwargs)
            if response.status_code in _HEAD_FALLBACK_CODES:
                # only the status matters here, don't download the body
                async with client.stream("GET", url, **request_kwargs) as response:
                    pass
        else:
            if content is not None:
                request_kwargs["content"] = content
            # streamed so we can look at the headers before deciding to download the body
            async with client.stream(verb, url, **request_kwargs) as response:
                result["content"] = await _read_capped_body(response)

        result["response_code"] = int(response.status_code)
        result["headers"] = dict(response.headers)
        result["final_url"] = str(response.url)

        # 4xx/5xx happen on almost every crawl, so check the status directly
        # instead of raise_for_status()/except - exceptions aren't free and this
        # runs on every single request
        if not response.is_error:
            result["content_type"] = response.headers.get('Content-Type', 'unknown')
            result["done"] = True

    except httpx.RequestError:
        pass
    
    return result
