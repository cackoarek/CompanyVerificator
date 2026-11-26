"""Router zakładki informacyjnej i metodologicznej 'Jak to działa' (dostępny publicznie)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.web.dependencies import base_context, templates

router = APIRouter(prefix="/jak-to-dziala", tags=["Jak to działa"])


@router.get("", response_class=HTMLResponse)
async def how_it_works_page(request: Request):
    """
    Publicznie dostępna strona kompendium:
    - Jak aplikacja działa,
    - Jakie rejestry i bazy bada (Biała Lista MF, KRS, CEIDG, CRBR, VIES, MSWiA, UE),
    - Jak wylicza ryzyko AML/VAT i wycenia punkty (scoring),
    - Co dzieje się w sytuacjach granicznych (brak VAT, brak wpisu, zwolnienia, nowa firma, rachunek poza wykazem itp.).
    """
    ctx = base_context(request, active_tab="how_it_works")
    return templates.TemplateResponse(request=request, name="pages/how_it_works.html", context=ctx)
