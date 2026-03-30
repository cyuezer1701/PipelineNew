from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI / Script Generation (Claude)
    anthropic_api_key: str = ""

    # Voiceover
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Stock Footage
    pexels_api_key: str = ""

    # YouTube
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""

    # Branding
    channel_name: str = "FlowStack"
    channel_tagline: str = "B2B SaaS & AI Automation"

    # Audio
    music_volume: float = 0.15  # Background music volume (0.0-1.0)

    # Paths
    output_dir: str = "/app/output"
    assets_dir: str = "/app/assets"

    class Config:
        env_file = ".env"


settings = Settings()
