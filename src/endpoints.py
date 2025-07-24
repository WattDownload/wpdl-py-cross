from io import BytesIO
from typing import Optional
import backoff
from aiohttp import ClientResponseError, ClientSession
from exceptions import PartNotFoundError, StoryNotFoundError
from models import Story

headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36"
}


async def fetch_cookies(username: str, password: str) -> dict:
    # source: https://github.com/TheOnlyWayUp/WP-DM-Export/blob/dd4c7c51cb43f2108e0f63fc10a66cd24a740e4e/src/API/src/main.py#L25-L58
    """Retrieves authorization cookies from Wattpad by logging in with user creds.

    Args:
        username (str): Username.
        password (str): Password.

    Raises:
        ValueError: Bad status code.
        ValueError: No cookies returned.

    Returns:
        dict: Authorization cookies.
    """
    async with ClientSession(headers=headers) as session:
        async with session.post(
            "https://www.wattpad.com/auth/login?nextUrl=%2F&_data=routes%2Fauth.login",
            data={
                "username": username.lower(),
                "password": password,
            },  # the username.lower() is for caching
        ) as response:
            if response.status != 204:
                raise ValueError("Not a 204.")

            cookies = {
                k: v.value
                for k, v in response.cookies.items()  # Thanks https://stackoverflow.com/a/32281245
            }

            if not cookies:
                raise ValueError("No cookies.")

            return cookies


@backoff.on_exception(backoff.expo, ClientResponseError, max_time=15)
async def fetch_story_content_zip(story_id: int, cookies: dict) -> BytesIO:
    """BytesIO Stream of an Archive of Part Contents for a Story."""
    async with ClientSession(headers=headers, cookies=cookies) as session:
        async with session.get(
            f"https://www.wattpad.com/apiv2/?m=storytext&group_id={story_id}&output=zip"
        ) as response:
            response.raise_for_status()

            bytes_stream = BytesIO(await response.read())

    return bytes_stream


@backoff.on_exception(backoff.expo, ClientResponseError, max_time=15)
async def fetch_story_from_partId(
    part_id: int, cookies: Optional[dict] = None
) -> tuple[int, Story]:
    """Fetch Story metadata from a Part ID."""
    async with ClientSession(headers=headers) as session:
        async with session.get(
            f"https://www.wattpad.com/api/v3/story_parts/{part_id}?fields=group(tags,id,title,createDate,modifyDate,language(name),description,completed,mature,url,isPaywalled,user(username,avatar,description),parts(id,title),cover,copyright)"
        ) as response:
            body = await response.json()

            if response.status == 400:
                match body.get("error_code"):
                    case 1020:  # "Story part not found"
                        raise PartNotFoundError()

            response.raise_for_status()

    return body.get("group", body)


@backoff.on_exception(backoff.expo, ClientResponseError, max_time=15)
async def fetch_story(story_id: int, cookies: Optional[dict] = None) -> Story:
    """Fetch Story metadata from a Story ID."""
    async with ClientSession(headers=headers, cookies=cookies) as session:
        async with session.get(
            f"https://www.wattpad.com/api/v3/stories/{story_id}?fields=tags,id,title,createDate,modifyDate,language(name),description,completed,mature,url,isPaywalled,user(username,avatar,description),parts(id,title),cover,copyright"
        ) as response:
            body = await response.json()

            if response.status == 400:
                match body.get("error_code"):
                    case 1017:  # "Story not found"
                        raise StoryNotFoundError()

            response.raise_for_status()

    return body
