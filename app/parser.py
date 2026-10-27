from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pdfplumber


MONTHS = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARCO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}
WEEKDAYS = {
    "SEGUNDA": 0,
    "TERCA": 1,
    "QUARTA": 2,
    "QUINTA": 3,
    "SEXTA": 4,
    "SABADO": 5,
    "DOMINGO": 6,
}


class PDFParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDay:
    work_date: date
    weekday_label: str
    punches: list[str]


@dataclass(frozen=True)
class ParsedTimesheet:
    name: str
    cpf: str
    year: int
    month: int
    days: list[ParsedDay]


def normalize(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value.upper())
        if unicodedata.category(char) != "Mn"
    )


def extract_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages)
    if len(text.strip()) < 50:
        raise PDFParseError("O PDF não contém texto suficiente. OCR ainda não está habilitado neste MVP.")
    return text


def parse_timesheet(path: Path) -> ParsedTimesheet:
    text = extract_text(path)
    normalized = normalize(text)

    reference = re.search(
        r"FREQUENCIA\s+REFERENTE\s+A\s+([A-Z]+)\s+DE\s+(\d{4})",
        normalized,
    )
    if not reference or reference.group(1) not in MONTHS:
        raise PDFParseError("Não foi possível identificar o mês e o ano de referência.")
    month = MONTHS[reference.group(1)]
    year = int(reference.group(2))

    cpf_match = re.search(r"\b(\d{11})\b", normalized)
    if not cpf_match:
        raise PDFParseError("Não foi possível identificar o CPF do servidor.")
    cpf = cpf_match.group(1)

    name = "Servidor"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if normalize(line) == "NOME" and index + 2 < len(lines):
            candidate = lines[index + 2].split(cpf)[0].strip()
            if candidate:
                name = candidate
                break
    if name == "Servidor":
        cpf_line_index = next((i for i, line in enumerate(lines) if cpf in line), None)
        if cpf_line_index is not None:
            candidate = lines[cpf_line_index].replace(cpf, "").strip()
            if candidate:
                name = candidate

    day_pattern = re.compile(
        r"^\s*(\d{1,2})\s+(SEGUNDA|TER[CÇ]A|QUARTA|QUINTA|SEXTA|S[ÁA]BADO|DOMINGO)\b(.*)$",
        re.IGNORECASE,
    )
    time_pattern = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b")
    parsed_by_day: dict[int, ParsedDay] = {}
    for raw_line in text.splitlines():
        match = day_pattern.match(raw_line)
        if not match:
            continue
        day_number = int(match.group(1))
        weekday_label = normalize(match.group(2))
        punches = []
        for time_match in time_pattern.finditer(match.group(3)):
            value = time_match.group(0)
            punches.append(value if len(value) == 8 else f"{value}:00")
        try:
            work_date = date(year, month, day_number)
        except ValueError:
            continue
        parsed_by_day[day_number] = ParsedDay(work_date, weekday_label, punches)

    expected_days = calendar.monthrange(year, month)[1]
    if len(parsed_by_day) < expected_days:
        missing = sorted(set(range(1, expected_days + 1)) - set(parsed_by_day))
        raise PDFParseError(f"A tabela está incompleta; dias não encontrados: {missing}.")

    return ParsedTimesheet(
        name=name,
        cpf=cpf,
        year=year,
        month=month,
        days=[parsed_by_day[number] for number in sorted(parsed_by_day)],
    )

