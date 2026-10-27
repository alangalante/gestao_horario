from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Iterable


def parse_clock(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M:%S")
    return parsed.hour * 60 + parsed.minute


def worked_minutes(punches: list[str]) -> int:
    total = 0
    for index in range(0, len(punches) - 1, 2):
        start = parse_clock(punches[index])
        end = parse_clock(punches[index + 1])
        if end < start:
            end += 24 * 60
        total += end - start
    return total


def format_minutes(value: int, include_sign: bool = False) -> str:
    sign = ""
    if value < 0:
        sign = "-"
    elif include_sign and value > 0:
        sign = "+"
    absolute = abs(value)
    return f"{sign}{absolute // 60}h{absolute % 60:02d}"


def month_dates(year: int, month: int) -> Iterable[date]:
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        yield date(year, month, day)


def cycle_bounds(reference: date, anchor_month: int) -> tuple[date, date]:
    candidates = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        for offset in (0, 3, 6, 9):
            month_index = anchor_month - 1 + offset
            candidate_year = year + month_index // 12
            candidate_month = month_index % 12 + 1
            candidate = date(candidate_year, candidate_month, 1)
            if candidate <= reference:
                candidates.append(candidate)
    start = max(candidates)
    end_month_index = start.month - 1 + 3
    end_year = start.year + end_month_index // 12
    end_month = end_month_index % 12 + 1
    end = date(end_year, end_month, 1) - timedelta(days=1)
    return start, end

