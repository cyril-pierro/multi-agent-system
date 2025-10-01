from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    CONTEXT_TTL_SECONDS: int = 3600
    APP_ID: str = "default-app-id"
    GEMINI_API_KEY: str

    class Config:
        env_file = ".env"


settings = AppSettings()
