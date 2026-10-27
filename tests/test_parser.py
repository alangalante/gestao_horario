from pathlib import Path

from app.calculations import format_minutes, worked_minutes
from app.parser import parse_timesheet


PDF = Path("/Users/acg/Downloads/sistemas.macae.rj.gov.br_94_apps_portalservidor_soapauth.asp_tipo=marcacoes&matrselponto=396398&mes=10&ano=2026.pdf")


def test_parser_real_pdf():
    if not PDF.exists():
        return
    result = parse_timesheet(PDF)
    assert (result.year, result.month) == (2026, 10)
    assert len(result.days) == 31
    assert result.days[4].punches == ["08:49:00", "12:09:00"]
    assert result.days[26].punches == ["14:50:00"]


def test_worked_minutes_ignores_unpaired_punch():
    assert worked_minutes(["08:49:00", "12:09:00", "14:50:00"]) == 200
    assert format_minutes(200) == "3h20"

