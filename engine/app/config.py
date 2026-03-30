from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI / Script Generation (Claude)
    anthropic_api_key: str = ""

    # Voiceover (ElevenLabs)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_sts_model: str = "eleven_english_sts_v2"

    # Runway Gen-4.5
    runway_api_key: str = ""

    # Stock Footage (Pexels)
    pexels_api_key: str = ""

    # YouTube
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""

    # Branding
    channel_name: str = "FlowStack"
    channel_tagline: str = "B2B SaaS & AI Automation"

    # Audio
    music_volume: float = 0.15

    # Retention Editing
    pattern_interrupt_interval: float = 3.0  # max seconds before a visual change
    jcut_offset: float = 0.5  # audio leads video by this many seconds

    # Footage Mix
    runway_footage_ratio: float = 0.7  # 70% AI, 30% real stock

    # Paths
    output_dir: str = "/app/output"
    assets_dir: str = "/app/assets"

    class Config:
        env_file = ".env"


settings = Settings()
