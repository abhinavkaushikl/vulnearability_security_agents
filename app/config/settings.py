"""Configuration loading. YAML + environment, validated into Pydantic models.

Precedence: CLI overrides > environment > config.yaml > built-in defaults.
No module outside this one reads a raw YAML key.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.models.performance import NetworkProfile


class RulesConfig(BaseModel):
    directory: str = "Rules"
    meta_files: list[str] = Field(default_factory=list)


class ViewportConfig(BaseModel):
    width: int = 1440
    height: int = 900


class BrowserConfig(BaseModel):
    type: str = "chromium"
    headless: bool = True
    timeout_ms: int = 30000
    navigation_timeout_ms: int = 45000
    viewport: ViewportConfig = Field(default_factory=ViewportConfig)
    locale: str = "en-US"
    ignore_https_errors: bool = False

    @property
    def supports_throttling(self) -> bool:
        """CDP Network.emulateNetworkConditions is Chromium-only."""
        return self.type == "chromium"


class AssessmentConfig(BaseModel):
    mode: str = "passive"
    authorization_reference: str | None = None
    max_pages: int = 10
    max_navigation_count: int = 20
    max_concurrent_contexts: int = 4
    max_concurrent_evaluations: int = 4
    timeout_seconds: int = 900
    stay_in_scope: bool = True
    probe_well_known: bool = True
    probe_error_page: bool = True
    collect_tls: bool = True
    collect_dns: bool = True
    run_axe: bool = True


class PerformanceConfig(BaseModel):
    enabled: bool = True
    iterations: int = 3
    cooldown_seconds: float = 2.0
    per_profile_budget_seconds: float = 90.0
    profiles: list[str] = Field(default_factory=lambda: ["fast", "4g", "3g", "slow"])


class ScreenshotConfig(BaseModel):
    enabled: bool = True
    full_page: bool = False


class TracingConfig(BaseModel):
    enabled: bool = False


class LLMConfig(BaseModel):
    provider: str = "qwen"
    model: str = "qwen3-coder"
    fallback_models: list[str] = Field(default_factory=list)
    endpoint: str = "http://localhost:11434"
    temperature: float = 0.0
    timeout_seconds: int = 120
    max_retries: int = 2
    cache_dir: str = ".cache/rule_interpretations"
    required: bool = False


class StorageConfig(BaseModel):
    type: str = "excel"
    excel_path: str = "artifacts/{assessment_id}/assessment_results.xlsx"
    postgres_dsn: str | None = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "artifacts/{assessment_id}/logs/assessment.log"


class HstsPolicy(BaseModel):
    min_max_age_seconds: int | None = 15768000
    require_include_subdomains: bool = False
    require_preload: bool = False


class TlsPolicy(BaseModel):
    min_protocol: str = "TLSv1.2"
    forbidden_protocols: list[str] = Field(default_factory=list)
    min_days_until_expiry: int = 14


class PerformanceSlo(BaseModel):
    ttfb_ms_p95: float | None = None
    page_load_ms_p95: float | None = None


class CookiePolicy(BaseModel):
    session_name_patterns: list[str] = Field(default_factory=list)
    require_secure: bool = True
    require_httponly: bool = True
    allowed_samesite: list[str] = Field(default_factory=lambda: ["Strict", "Lax"])


class CspPolicy(BaseModel):
    forbid_unsafe_inline: bool = True
    forbid_unsafe_eval: bool = True
    require_frame_ancestors: bool = True


class Policy(BaseModel):
    """Organizational thresholds the rule pack references but never supplies."""

    hsts: HstsPolicy = Field(default_factory=HstsPolicy)
    tls: TlsPolicy = Field(default_factory=TlsPolicy)
    performance_slo: PerformanceSlo = Field(default_factory=PerformanceSlo)
    cookies: CookiePolicy = Field(default_factory=CookiePolicy)
    csp: CspPolicy = Field(default_factory=CspPolicy)


class Settings(BaseModel):
    rules: RulesConfig = Field(default_factory=RulesConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    assessment: AssessmentConfig = Field(default_factory=AssessmentConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    screenshots: ScreenshotConfig = Field(default_factory=ScreenshotConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    network_profiles: dict[str, NetworkProfile] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)

    # --- resolved at load time ---
    project_root: str = "."

    def profile(self, name: str) -> NetworkProfile | None:
        return self.network_profiles.get(name)

    @property
    def active_profiles(self) -> list[NetworkProfile]:
        """Requested profiles that are actually defined, in requested order."""
        out = []
        for name in self.performance.profiles:
            p = self.network_profiles.get(name)
            if p:
                out.append(p)
        return out

    def artifact_dir(self, assessment_id: str) -> Path:
        return Path(self.project_root) / "artifacts" / assessment_id

    def excel_path(self, assessment_id: str) -> Path:
        return Path(self.project_root) / self.storage.excel_path.format(
            assessment_id=assessment_id)

    def log_path(self, assessment_id: str) -> Path:
        return Path(self.project_root) / self.logging.file.format(
            assessment_id=assessment_id)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(
    config_path: str | Path = "config.yaml",
    policy_path: str | Path = "policy.yaml",
    overrides: dict | None = None,
    project_root: str | Path | None = None,
) -> Settings:
    """Load configuration from YAML, environment and explicit overrides."""
    root = Path(project_root) if project_root else Path.cwd()
    raw: dict = {}

    cfg = Path(config_path)
    if not cfg.is_absolute():
        cfg = root / cfg
    if cfg.exists():
        raw = yaml.safe_load(cfg.read_text()) or {}

    pol = Path(policy_path)
    if not pol.is_absolute():
        pol = root / pol
    if pol.exists():
        raw["policy"] = yaml.safe_load(pol.read_text()) or {}

    # Environment overrides for the few values that belong in .env
    env_llm = {}
    if os.getenv("LLM_ENDPOINT"):
        env_llm["endpoint"] = os.environ["LLM_ENDPOINT"]
    if os.getenv("LLM_MODEL"):
        env_llm["model"] = os.environ["LLM_MODEL"]
    if os.getenv("LLM_PROVIDER"):
        env_llm["provider"] = os.environ["LLM_PROVIDER"]
    if env_llm:
        raw = _deep_merge(raw, {"llm": env_llm})
    if os.getenv("AUTHORIZATION_REFERENCE"):
        raw = _deep_merge(
            raw, {"assessment": {
                "authorization_reference": os.environ["AUTHORIZATION_REFERENCE"]}})

    if overrides:
        raw = _deep_merge(raw, overrides)

    # network_profiles: dict[str, dict] -> dict[str, NetworkProfile]
    profiles = {}
    for name, spec in (raw.get("network_profiles") or {}).items():
        profiles[name] = NetworkProfile(name=name, **spec)
    raw["network_profiles"] = profiles
    raw["project_root"] = str(root)

    return Settings(**raw)
