"""Japanese national holiday calculation (2020-2099)."""

import datetime


def national_holidays(year):
    if not 2020 <= year <= 2099:
        return {}

    def nth(month, weekday, n):
        first = datetime.date(year, month, 1)
        return datetime.date(
            year, month, 1 + (weekday - first.weekday()) % 7 + 7 * (n - 1)
        )

    def equinox(spring):
        day = int(
            (20.8431 if spring else 23.2488)
            + 0.242194 * (year - 1980)
            - int((year - 1980) / 4)
        )
        return datetime.date(year, 3 if spring else 9, day)

    h = {}

    def add(month, day, name):
        h[datetime.date(year, month, day)] = name

    add(1, 1, "元日")
    h[nth(1, 0, 2)] = "成人の日"
    add(2, 11, "建国記念の日")
    add(2, 23, "天皇誕生日")
    h[equinox(True)] = "春分の日"
    add(4, 29, "昭和の日")
    add(5, 3, "憲法記念日")
    add(5, 4, "みどりの日")
    add(5, 5, "こどもの日")
    h[nth(7, 0, 3)] = "海の日"
    add(8, 11, "山の日")
    h[nth(9, 0, 3)] = "敬老の日"
    h[equinox(False)] = "秋分の日"
    h[nth(10, 0, 2)] = "スポーツの日"
    add(11, 3, "文化の日")
    add(11, 23, "勤労感謝の日")
    for d in list(h):
        mid = d + datetime.timedelta(days=1)
        if (
            mid not in h
            and mid.weekday() != 6
            and (mid + datetime.timedelta(days=1) in h)
        ):
            h[mid] = "国民の休日"
    for d in sorted(list(h)):
        if d.weekday() == 6:
            sub = d + datetime.timedelta(days=1)
            while sub in h:
                sub += datetime.timedelta(days=1)
            h[sub] = "振替休日"
    return h
