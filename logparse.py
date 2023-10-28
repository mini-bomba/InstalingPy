import csv
import datetime
import pathlib
import re

TIMESTAMP_REGEX = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}]")
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_log(log: pathlib.Path) -> tuple[datetime.datetime, datetime.datetime, bool]:
    with log.open("r") as f:
        lines = list(f)
    start_time = datetime.datetime.strptime(TIMESTAMP_REGEX.match(lines[0]).groups()[0], DATETIME_FORMAT)
    end_time = start_time
    success = False
    for line in reversed(lines):
        timestamp_match = TIMESTAMP_REGEX.match(line)
        if timestamp_match is not None:
            end_time = datetime.datetime.strptime(timestamp_match.groups()[0], DATETIME_FORMAT)
            success = line.find("crashed!") == -1
            break

    return start_time, end_time, success


if __name__ == "__main__":
    LOGS_DIR = pathlib.Path("/tmp/logs")
    USER_MAPPINGS = {"KSz281623": 1856488, "28kk58253": 1380166}
    times = []
    for username, user_id in USER_MAPPINGS.items():
        for logfile in LOGS_DIR.glob(f"*-{username}.log"):
            start_time, end_time, success = parse_log(logfile)
            times.append({
                "timestamp": end_time,
                "user_id": user_id,
                "start_time": start_time,
                "end_time": end_time,
                "success": success,
            })

    with open("SessionHistory.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, ["timestamp", "user_id", "start_time", "end_time", "success"])

        writer.writeheader()
        writer.writerows(times)
