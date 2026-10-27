from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com"
    openai_model: str = "deepseek-flash"

    max_react_steps: int = 8
    tool_timeout_seconds: float = 10.0
    llm_timeout_seconds: float = 60.0

    context_max_chars: int = 12000
    history_keep_messages: int = 8

    db_path: str = "data/agent.db"
