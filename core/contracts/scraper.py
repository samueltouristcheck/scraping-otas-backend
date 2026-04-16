from abc import ABC, abstractmethod

from models.dto import HorizonRequest, ScrapeResult


class OtaScraper(ABC):
    ota_name: str

    @abstractmethod
    async def scrape(self, source_url: str, horizons: list[HorizonRequest]) -> ScrapeResult:
        raise NotImplementedError
