import random
from dataclasses import dataclass


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
]


@dataclass(slots=True)
class BrowserProfile:
    user_agent: str
    viewport: dict[str, int]
    locale: str
    timezone_id: str


def random_browser_profile(locale: str = "en-GB", timezone_id: str = "Europe/Madrid") -> BrowserProfile:
    return BrowserProfile(
        user_agent=random.choice(USER_AGENTS),
        viewport=random.choice(VIEWPORTS),
        locale=locale,
        timezone_id=timezone_id,
    )
