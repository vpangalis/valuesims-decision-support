from pathlib import Path
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings


_BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

load_dotenv(_BACKEND_ENV_PATH)
load_dotenv(_ROOT_ENV_PATH)


def _load_windows_env_from_registry() -> None:
    if os.name != "nt":
        return
    try:
        import winreg
    except Exception:
        return

    targets = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_ADMIN_KEY",
    ]

    def _try_key(root, subkey):
        try:
            with winreg.OpenKey(root, subkey) as reg_key:
                for name in targets:
                    if os.environ.get(name):
                        continue
                    try:
                        value, _ = winreg.QueryValueEx(reg_key, name)
                        if value:
                            os.environ[name] = value
                    except FileNotFoundError:
                        continue
        except FileNotFoundError:
            return

    _try_key(winreg.HKEY_CURRENT_USER, r"Environment")
    _try_key(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")


_load_windows_env_from_registry()


class Settings(BaseSettings):
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_API_VERSION: str | None = None
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str | None = None

    # Azure AI Search
    AZURE_SEARCH_ENDPOINT: str | None = None
    AZURE_SEARCH_ADMIN_KEY: str | None = None
    AZURE_SEARCH_VECTOR_DIMENSIONS: int = 3072

    class Config:
        env_file = _BACKEND_ENV_PATH
        case_sensitive = True
        extra = "allow"   # 👈 THIS is the key line


settings = Settings()
