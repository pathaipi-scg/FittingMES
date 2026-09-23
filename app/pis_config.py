"""Environment-only PIS configuration; no network access."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')


@dataclass(frozen=True)
class PISConfig:
    base_url: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)

    @classmethod
    def from_environment(cls):
        return cls(os.getenv('PIS_BASE_URL', '').strip().rstrip('/'),
                   os.getenv('PIS_USERNAME', ''), os.getenv('PIS_PASSWORD', ''))

    @property
    def endpoint_configured(self):
        try:
            url = urlsplit(self.base_url)
            return bool(url.scheme == 'https' and url.hostname and url.port != 0
                        and not url.username and not url.password
                        and not url.path and not url.query and not url.fragment
                        and not any(char.isspace() for char in self.base_url))
        except ValueError:
            return False

    @property
    def authentication_configured(self):
        return bool(self.username.strip() and self.password.strip() and ':' not in self.username)

    def diagnostics(self):
        # Only these booleans may enter template context; never the config object.
        return dict(endpoint_configured=self.endpoint_configured,
                    authentication_configured=self.authentication_configured)
