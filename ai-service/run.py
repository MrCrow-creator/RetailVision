from pathlib import Path

import uvicorn

from app.core.settings import get_settings


def main() -> None:
    settings = get_settings()
    app_directory = Path(__file__).resolve().parent / "app"

    uvicorn.run(
        "app.main:app",
        host=settings.ai_service_host,
        port=settings.ai_service_port,
        reload=settings.ai_reload,
        reload_dirs=[str(app_directory)] if settings.ai_reload else None,
    )


if __name__ == "__main__":
    main()
