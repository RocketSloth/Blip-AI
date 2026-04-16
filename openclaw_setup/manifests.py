"""
Declarative setup manifests for providers, channels, and profiles.

Each manifest declares what it needs (binaries, env vars, config fields),
how to detect readiness, and how to install missing pieces.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InstallMethod:
    tool: str           # brew, npm, apt, uv, go, download, script
    command: str        # full install command
    url: Optional[str] = None


@dataclass
class BinaryRequirement:
    name: str
    check_cmd: str
    version_flag: str = "--version"
    install_methods: list = field(default_factory=list)  # list[InstallMethod], ordered by preference

    def __post_init__(self):
        if not self.install_methods:
            self.install_methods = []


@dataclass
class ProviderManifest:
    id: str
    label: str
    required_env: list       # list[str] — env var names
    required_bins: list      # list[BinaryRequirement]
    config_fields: dict      # fields to emit in openclaw config
    setup_notes: list        # list[str] — human-readable guidance

    def __post_init__(self):
        if not self.required_bins:
            self.required_bins = []
        if not self.setup_notes:
            self.setup_notes = []


@dataclass
class ChannelManifest:
    id: str
    label: str
    required_env: list       # list[str]
    required_bins: list      # list[BinaryRequirement]
    optional_bins: list      # list[BinaryRequirement]
    config_fields: dict
    setup_steps: list        # list[str] — ordered human-readable steps
    smoke_test_cmd: Optional[str] = None

    def __post_init__(self):
        if not self.required_bins:
            self.required_bins = []
        if not self.optional_bins:
            self.optional_bins = []
        if not self.setup_steps:
            self.setup_steps = []


@dataclass
class ProfileManifest:
    id: str
    label: str
    description: str
    provider_choices: list   # list[str] — provider ids
    channel_id: Optional[str]
    install_service_default: bool
    required_features: list  # list[str]


# ---------------------------------------------------------------------------
# Binary registry
# ---------------------------------------------------------------------------

NODE_BIN = BinaryRequirement(
    name="node",
    check_cmd="node --version",
    install_methods=[
        InstallMethod("brew", "brew install node"),
        InstallMethod("download", "https://nodejs.org/en/download/", "https://nodejs.org"),
    ],
)

NPM_BIN = BinaryRequirement(
    name="npm",
    check_cmd="npm --version",
    install_methods=[
        InstallMethod("brew", "brew install node"),
    ],
)

OPENCLAW_BIN = BinaryRequirement(
    name="openclaw",
    check_cmd="openclaw --version",
    install_methods=[
        InstallMethod("script", "curl -fsSL https://openclaw.io/install.sh | sh"),
        InstallMethod("npm", "npm install -g openclaw"),
    ],
)

UV_BIN = BinaryRequirement(
    name="uv",
    check_cmd="uv --version",
    install_methods=[
        InstallMethod("brew", "brew install uv"),
        InstallMethod("script", "curl -LsSf https://astral.sh/uv/install.sh | sh"),
    ],
)

GO_BIN = BinaryRequirement(
    name="go",
    check_cmd="go version",
    install_methods=[
        InstallMethod("brew", "brew install go"),
        InstallMethod("download", "https://go.dev/dl/", "https://go.dev/dl/"),
    ],
)


# ---------------------------------------------------------------------------
# Provider manifests
# ---------------------------------------------------------------------------

PROVIDERS: dict = {
    "openai": ProviderManifest(
        id="openai",
        label="OpenAI",
        required_env=["OPENAI_API_KEY"],
        required_bins=[],
        config_fields={
            "provider": "openai",
            "model": "gpt-4o",
        },
        setup_notes=[
            "Get your API key at https://platform.openai.com/api-keys",
            "Set: export OPENAI_API_KEY=sk-...",
        ],
    ),
    "anthropic": ProviderManifest(
        id="anthropic",
        label="Anthropic",
        required_env=["ANTHROPIC_API_KEY"],
        required_bins=[],
        config_fields={
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
        },
        setup_notes=[
            "Get your API key at https://console.anthropic.com/",
            "Set: export ANTHROPIC_API_KEY=sk-ant-...",
        ],
    ),
    "openrouter": ProviderManifest(
        id="openrouter",
        label="OpenRouter",
        required_env=["OPENROUTER_API_KEY"],
        required_bins=[],
        config_fields={
            "provider": "openrouter",
            "model": "openai/gpt-4o",
        },
        setup_notes=[
            "Get your API key at https://openrouter.ai/keys",
            "Set: export OPENROUTER_API_KEY=sk-or-...",
        ],
    ),
    "local": ProviderManifest(
        id="local",
        label="Local / self-hosted (Ollama)",
        required_env=[],
        required_bins=[
            BinaryRequirement(
                name="ollama",
                check_cmd="ollama --version",
                install_methods=[
                    InstallMethod("brew", "brew install ollama"),
                    InstallMethod("download", "https://ollama.com/download", "https://ollama.com/download"),
                ],
            )
        ],
        config_fields={
            "provider": "ollama",
            "model": "llama3",
            "base_url": "http://localhost:11434",
        },
        setup_notes=[
            "Install Ollama and pull a model: ollama pull llama3",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Channel manifests
# ---------------------------------------------------------------------------

CHANNELS: dict = {
    "local": ChannelManifest(
        id="local",
        label="Local terminal / web UI",
        required_env=[],
        required_bins=[NODE_BIN],
        optional_bins=[],
        config_fields={
            "channel": "local",
            "gateway.mode": "local",
        },
        setup_steps=[
            "Gateway will start in local mode",
            "Open http://localhost:3000 to chat",
        ],
        smoke_test_cmd="openclaw gateway status",
    ),
    "telegram": ChannelManifest(
        id="telegram",
        label="Telegram bot",
        required_env=["TELEGRAM_BOT_TOKEN"],
        required_bins=[NODE_BIN],
        optional_bins=[],
        config_fields={
            "channel": "telegram",
            "gateway.mode": "remote",
        },
        setup_steps=[
            "Create a bot via @BotFather on Telegram and copy the token",
            "Set: export TELEGRAM_BOT_TOKEN=<your-token>",
            "Optionally set TELEGRAM_ALLOWED_USERS=user1,user2 to restrict access",
        ],
        smoke_test_cmd="openclaw channel telegram status",
    ),
    "whatsapp": ChannelManifest(
        id="whatsapp",
        label="WhatsApp bot",
        required_env=[],
        required_bins=[NODE_BIN],
        optional_bins=[],
        config_fields={
            "channel": "whatsapp",
            "gateway.mode": "remote",
        },
        setup_steps=[
            "Run the WhatsApp pairing flow after setup completes",
            "Scan the QR code with your WhatsApp app",
            "Optionally configure allowlist and mention settings in config",
        ],
        smoke_test_cmd="openclaw channel whatsapp status",
    ),
}


# ---------------------------------------------------------------------------
# Profile manifests (MVP happy paths)
# ---------------------------------------------------------------------------

PROFILES: dict = {
    "personal_bot": ProfileManifest(
        id="personal_bot",
        label="Personal bot on this machine",
        description="Local chat bot — runs on your laptop or desktop",
        provider_choices=["openai", "anthropic", "openrouter", "local"],
        channel_id="local",
        install_service_default=True,
        required_features=["openclaw", "gateway"],
    ),
    "telegram_bot": ProfileManifest(
        id="telegram_bot",
        label="Telegram bot",
        description="Bot accessible via your Telegram account",
        provider_choices=["openai", "anthropic", "openrouter"],
        channel_id="telegram",
        install_service_default=True,
        required_features=["openclaw", "gateway", "telegram"],
    ),
    "whatsapp_bot": ProfileManifest(
        id="whatsapp_bot",
        label="WhatsApp bot",
        description="Bot accessible via WhatsApp",
        provider_choices=["openai", "anthropic", "openrouter"],
        channel_id="whatsapp",
        install_service_default=True,
        required_features=["openclaw", "gateway", "whatsapp"],
    ),
    "remote_gateway": ProfileManifest(
        id="remote_gateway",
        label="Remote gateway (VPS / server)",
        description="Headless gateway for a remote host",
        provider_choices=["openai", "anthropic", "openrouter"],
        channel_id=None,
        install_service_default=True,
        required_features=["openclaw", "gateway", "service"],
    ),
    "dev_setup": ProfileManifest(
        id="dev_setup",
        label="Developer setup",
        description="Full dev environment with verbose logging and no service",
        provider_choices=["openai", "anthropic", "openrouter", "local"],
        channel_id="local",
        install_service_default=False,
        required_features=["openclaw", "gateway"],
    ),
}
