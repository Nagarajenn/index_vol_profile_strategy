from datetime import date

# NSE/BSE equity market trading holidays for 2026 (source: Zerodha holiday
# calendar, https://zerodha.com/marketintel/holiday-calendar/, weekday
# holidays only -- holidays that already fall on a Sat/Sun are omitted since
# is_trading_day() checks the weekend separately). Diwali Muhurat trading
# (a short special evening session, not a regular day session) is
# intentionally not modeled here.
NSE_BSE_HOLIDAYS_2026 = {
    date(2026, 1, 15),  # Municipal Corporation Elections in Maharashtra
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),  # Holi
    date(2026, 3, 26),  # Shri Ram Navami
    date(2026, 3, 31),  # Shri Mahavir Jayanti
    date(2026, 4, 3),  # Good Friday
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),  # Maharashtra Day
    date(2026, 5, 28),  # Bakri Eid
    date(2026, 6, 26),  # Moharram
    date(2026, 9, 14),  # Ganesh Chaturthi
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali-Balipratipada
    date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if d.year == 2026 and d in NSE_BSE_HOLIDAYS_2026:
        return False
    return True


def trading_days_between(start: date, end: date) -> list[date]:
    days = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return days
