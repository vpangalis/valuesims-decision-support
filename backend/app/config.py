from pydantic_settings import BaseSettings



class Settings(BaseSettings):
    AZURE_STORAGE_CONNECTION_STRING: str
    AZURE_STORAGE_CONTAINER: str = "cases"

    class Config:
        env_file = ".env"


settings = Settings()
