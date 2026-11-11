from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.services.slots import compute_slots

TZ = ZoneInfo("Asia/Tashkent")
MONDAY = date(2030, 1, 7)
LONG_AGO = datetime(2030, 1, 1, tzinfo=TZ)


def at(h, m=0, day=MONDAY):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)


def test_generates_all_slots():
    slots = compute_slots(MONDAY, [(time(9), time(11))], 30, [], LONG_AGO, TZ)
    assert [s for s, _ in slots] == [at(9), at(9, 30), at(10), at(10, 30)]


def test_busy_slot_is_removed():
    busy = [(at(9, 30), at(10))]
    slots = compute_slots(MONDAY, [(time(9), time(11))], 30, busy, LONG_AGO, TZ)
    assert at(9, 30) not in [s for s, _ in slots]
    assert len(slots) == 3


def test_past_slots_are_hidden():
    now = at(9, 45)
    slots = compute_slots(MONDAY, [(time(9), time(11))], 30, [], now, TZ)
    assert [s for s, _ in slots] == [at(10), at(10, 30)]


def test_lunch_break_has_no_slots():
    windows = [(time(9), time(10)), (time(14), time(15))]
    starts = [s for s, _ in compute_slots(MONDAY, windows, 30, [], LONG_AGO, TZ)]
    assert starts == [at(9), at(9, 30), at(14), at(14, 30)]


def test_incomplete_last_slot_is_dropped():
    slots = compute_slots(MONDAY, [(time(9), time(10, 15))], 30, [], LONG_AGO, TZ)
    assert len(slots) == 2


def test_partial_overlap_blocks_slot():
    busy = [(at(9, 15), at(9, 45))]  # ikkita slotga tegadi
    slots = compute_slots(MONDAY, [(time(9), time(10))], 30, busy, LONG_AGO, TZ)
    assert slots == []
