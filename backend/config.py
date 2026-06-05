from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "gisdb"
    db_user: str = "gisuser"
    db_password: str = "123"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = {
        "env_file": str(Path(__file__).parent.parent / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
