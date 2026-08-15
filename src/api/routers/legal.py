"""Public legal-page routes."""

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import HTMLResponse

from src.api.presentation.legal import render_page, resolve_language

router = APIRouter(tags=["legal"], include_in_schema=False)


def page_response(kind: str, language: str) -> HTMLResponse:
    return HTMLResponse(
        content=render_page(kind, language),
        status_code=status.HTTP_200_OK,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Language": language,
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'"
            ),
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Vary": "Accept-Language",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(
    request: Request,
    lang: str | None = Query(default=None, max_length=10),
) -> HTMLResponse:
    language = resolve_language(lang, request.headers.get("accept-language", ""))
    return page_response("privacy", language)


@router.get("/terms", response_class=HTMLResponse)
async def terms_of_service(
    request: Request,
    lang: str | None = Query(default=None, max_length=10),
) -> HTMLResponse:
    language = resolve_language(lang, request.headers.get("accept-language", ""))
    return page_response("terms", language)


__all__ = ["router"]
