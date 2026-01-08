import httpx
import os
from urllib.parse import urlparse
from user_agents import RandomUserAgent

GET_REQUEST_EXTENSIONS = {'.html', '.htm', '.php', '.js', '.css', '.json', '.xml', '.svg'}

async_client = httpx.AsyncClient(
    http2=True, 
    follow_redirects=True, 
    timeout=10,
    headers={
        "User-Agent": RandomUserAgent.get()
    }
)

async def http_request(url, timeout=5, cookies=None, random_agent=False, custom_agent=None):
    result = {
        "response_code": "Error",
        "done": False,
        "content": "",
        "content_type": "error",
        "headers": {}
    }

    try:
        if custom_agent:
            async_client.headers["User-Agent"] = custom_agent
        elif random_agent:
            async_client.headers["User-Agent"] = RandomUserAgent.get()
        
        path = urlparse(url).path
        _, extension = os.path.splitext(path.lower())
        use_get_request = (extension in GET_REQUEST_EXTENSIONS) or (not extension)

        if use_get_request:
            response = await async_client.get(url, timeout=timeout, cookies=cookies)
            result["content"] = response.text
        else:
            response = await async_client.head(url, timeout=timeout, cookies=cookies)
            result["content"] = ""
        
        response.raise_for_status()
        
        result["response_code"] = int(response.status_code)
        result["content_type"] = response.headers.get('Content-Type', 'unknown')
        result["headers"] = dict(response.headers)
        result["done"] = True

    except httpx.HTTPStatusError as e:
        result["response_code"] = e.response.status_code
        result["headers"] = dict(e.response.headers)
    except httpx.RequestError:
        pass
    
    return result