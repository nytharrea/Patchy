from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    github_token: SecretStr = SecretStr("")
    github_repository: str = ""

    target_app: str = "all"

    ks_path: Path | None = None
    ks_password: SecretStr | None = None
    ks_alias: str | None = None
    key_password: SecretStr | None = None

    apksigner: Path | None = None
    zipalign: Path | None = None
    android_home: Path | None = None
    android_sdk_root: Path | None = None

    flaresolverr_url: str = "http://localhost:8191/v1"
    flaresolverr_timeout: float = 60.0
    download_timeout: float = 120.0
    patch_timeout: float = 300.0
    tool_timeout: float = 180.0

    skip_signature_verify: bool = False
    known_pins_path: Path = Field(default_factory=paths.known_pins_file)
    pending_pins_path: Path = Field(default_factory=paths.pending_pins_file)

    apps_dir: Path = Field(default_factory=paths.apps_dir)
    bundles_path: Path = Field(default_factory=paths.bundles_file)
    companions_path: Path = Field(default_factory=paths.companions_file)

    discord_webhook_url: SecretStr = SecretStr("")
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    apprise_urls: SecretStr = SecretStr("")

    no_color: str | None = None
    github_actions: bool = False

    release_tag: str | None = None
    release_name: str | None = None
    upload_concurrency: int = 6


settings = Settings()
