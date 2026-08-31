"""
FOMC statement dates 2015-2026, from federalreserve.gov FOMC calendars + historical pages.

The statement lands at 14:00 ET on the LAST day of the meeting; the press conference is 14:30 ET.
In this project's NQ convention (m = minutes since midnight CENTRAL): 14:00 ET = m 780, 14:30 ET = m 810.

Only SCHEDULED meetings are marked tradeable. The 2020 emergency actions (Mar 3, Mar 15) are
recorded but flagged unscheduled: nobody could position for them ex-ante, and Paper 2's Template 2
is explicitly a *scheduled*-release model. Including them would import hindsight into the sample.

Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm and fomchistorical<YYYY>.htm
"""
import pandas as pd

# (year, month, last-day-of-meeting) -- the statement day
SCHEDULED = [
    (2015, 1, 28), (2015, 3, 18), (2015, 4, 29), (2015, 6, 17),
    (2015, 7, 29), (2015, 9, 17), (2015, 10, 28), (2015, 12, 16),
    (2016, 1, 27), (2016, 3, 16), (2016, 4, 27), (2016, 6, 15),
    (2016, 7, 27), (2016, 9, 21), (2016, 11, 2), (2016, 12, 14),
    (2017, 2, 1), (2017, 3, 15), (2017, 5, 3), (2017, 6, 14),
    (2017, 7, 26), (2017, 9, 20), (2017, 11, 1), (2017, 12, 13),
    (2018, 1, 31), (2018, 3, 21), (2018, 5, 2), (2018, 6, 13),
    (2018, 8, 1), (2018, 9, 26), (2018, 11, 8), (2018, 12, 19),
    (2019, 1, 30), (2019, 3, 20), (2019, 5, 1), (2019, 6, 19),
    (2019, 7, 31), (2019, 9, 18), (2019, 10, 30), (2019, 12, 11),
    (2020, 1, 29), (2020, 4, 29), (2020, 6, 10), (2020, 7, 29),
    (2020, 9, 16), (2020, 11, 5), (2020, 12, 16),
    (2021, 1, 27), (2021, 3, 17), (2021, 4, 28), (2021, 6, 16),
    (2021, 7, 28), (2021, 9, 22), (2021, 11, 3), (2021, 12, 15),
    (2022, 1, 26), (2022, 3, 16), (2022, 5, 4), (2022, 6, 15),
    (2022, 7, 27), (2022, 9, 21), (2022, 11, 2), (2022, 12, 14),
    (2023, 2, 1), (2023, 3, 22), (2023, 5, 3), (2023, 6, 14),
    (2023, 7, 26), (2023, 9, 20), (2023, 11, 1), (2023, 12, 13),
    (2024, 1, 31), (2024, 3, 20), (2024, 5, 1), (2024, 6, 12),
    (2024, 7, 31), (2024, 9, 18), (2024, 11, 7), (2024, 12, 18),
    (2025, 1, 29), (2025, 3, 19), (2025, 5, 7), (2025, 6, 18),
    (2025, 7, 30), (2025, 9, 17), (2025, 10, 29), (2025, 12, 10),
    (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17),
    (2026, 7, 29), (2026, 9, 16), (2026, 10, 28), (2026, 12, 9),
]

UNSCHEDULED_2020 = [(2020, 3, 3), (2020, 3, 15)]   # emergency cuts -- NOT tradeable ex-ante

STATEMENT_M = 780      # 14:00 ET in minutes-since-midnight CENTRAL
PRESSER_M   = 810      # 14:30 ET


def build(path="data/pkl/fomc_calendar.pkl"):
    rows = [(f"{y:04d}-{m:02d}-{d:02d}", True) for y, m, d in SCHEDULED]
    rows += [(f"{y:04d}-{m:02d}-{d:02d}", False) for y, m, d in UNSCHEDULED_2020]
    df = pd.DataFrame(rows, columns=["d", "scheduled"]).sort_values("d").set_index("d")
    df["statement_m"] = STATEMENT_M
    df["presser_m"] = PRESSER_M
    df.to_pickle(path)
    print(f"{len(df)} FOMC dates -> {path}  "
          f"({df.scheduled.sum()} scheduled, {(~df.scheduled).sum()} emergency)")
    print(f"range {df.index.min()} -> {df.index.max()}")
    return df


if __name__ == "__main__":
    build()
