from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MTA = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds"
SUBWAY_FEEDS = [
    f"{MTA}/nyct%2F{name}"
    for name in ("gtfs", "gtfs-ace", "gtfs-bdfm", "gtfs-g", "gtfs-jz", "gtfs-nqrw", "gtfs-l", "gtfs-si")
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TP_", extra="ignore")

    database_url: str = "postgresql://transitpulse:transitpulse@localhost:5432/transitpulse"
    redis_url: str = "redis://localhost:6379/0"

    # GTFS-realtime vehicle/trip feeds. file:// URLs work too (used for replaying recorded feeds in tests).
    feed_urls: list[str] = SUBWAY_FEEDS
    alerts_url: str = f"{MTA}/camsys%2Fsubway-alerts"
    static_url: str = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"
    # Only needed for feeds that require a key, such as MTA Bus Time.
    mta_api_key: str | None = None

    poll_seconds: float = 15.0
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
