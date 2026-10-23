"""Local development server.

Reads host/port from the same Settings object the app uses, so changing
HELIX_API_HOST or HELIX_API_PORT in .env actually takes effect.

Run with: python -m apps.api.dev
"""

import uvicorn

from helix.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
