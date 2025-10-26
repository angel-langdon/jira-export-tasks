import os
import subprocess
import sys
import webbrowser
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import tqdm
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from requests.auth import HTTPBasicAuth

subprocess.run(["playwright", "install", "chromium"], check=True)

reports_dir = Path(__file__).parent / "reports"
reports_dir.mkdir(exist_ok=True)


def start_file(file: Path):
    if sys.platform != "win32":
        subprocess.call(["xdg-open", file])
    else:
        os.startfile(file)


html_styles = """<style>
        table {
            border-collapse: collapse;
            width: 100%;
            font-family: Arial, sans-serif;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        tr:hover {
            background-color: #e6f7ff;
        }
    </style>"""


def duration(seconds: int) -> str:
    """Convert seconds to a human-readable format."""
    if pd.isna(seconds):
        return "0h 0m"
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:.0f}h {minutes:.0f}m"


load_dotenv(override=True)

JIRA_URL = os.environ["JIRA_URL"]  # "https://your-domain.atlassian.net"
EMAIL = os.environ["EMAIL"]
API_TOKEN = os.environ["API_TOKEN"]
PROJECT_KEY = os.environ["PROJECT_KEY"]
HOURLY_RATE = Decimal(os.environ["HOURLY_RATE"])
CURRENCY = os.environ["CURRENCY"]

headers = {"Accept": "application/json", "Content-Type": "application/json"}

search_url = f"{JIRA_URL}/rest/api/3/search/jql"
auth = HTTPBasicAuth(EMAIL, API_TOKEN)
jql_query = f'project = "{PROJECT_KEY}" and sprint in openSprints ()'
fields = "project,summary,updated,timespent"
rename_map = {
    "project": "Project name",
    "summary": "Summary",
    "timespent": "Time Spent",
    "updated": "Updated",
    "taskcost": f"Task Cost ({HOURLY_RATE}{CURRENCY}/hour)",
}
dt_cols = ["updated"]
initial_params = {"jql": jql_query, "fields": fields, "maxResults": 100}


def extract_text_content(node: dict) -> str:
    if "text" in node and node["type"] == "text":
        return node["text"]
    if "content" in node:
        return "\n".join(extract_text_content(child) for child in node["content"])
    return ""


def get_worklog(issue_id: int):
    """Fetch worklog for a specific issue ID."""
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_id}/worklog"
    response = requests.get(url, headers=headers, auth=auth)
    response.raise_for_status()
    dic = response.json()
    worklogs = dic["worklogs"]
    res = [
        {
            "id": w["id"],
            "issueId": w["issueId"],
            "author": w["author"]["emailAddress"],
            "started": w["started"],
            "timeSpentSeconds": w["timeSpentSeconds"],
            "comment": extract_text_content(w.get("comment", {})),
        }
        for w in worklogs
    ]
    return res


def get_jira_issues(only_finished_tasks: bool = False) -> pd.DataFrame:
    """Fetch issues from JIRA."""
    issues = []
    next_page_token = None
    while True:
        params = {**initial_params}
        if next_page_token is not None:
            params["nextPageToken"] = next_page_token
        if only_finished_tasks:
            print("Filtering issues with status Done")
            params["jql"] += " and status = Done"
        response = requests.get(search_url, headers=headers, params=params, auth=auth)
        response.raise_for_status()
        json = response.json()
        page_issues = json["issues"]
        is_last = json.get("isLast", True)
        next_page_token = json.get("nextPageToken")
        issues.extend(page_issues)
        if is_last:
            break

    data: list[dict[str, Any]] = []
    for issue in issues:
        dic = issue["fields"]
        dic["project"] = dic["project"]["name"]
        dic["id"] = issue["id"]
        data.append(dic)

    df = pd.DataFrame(data)
    df["id"] = df["id"].astype(int)
    if not df.empty:
        df = df.set_index("id")
    df = df[df["timespent"] > 0]
    for c in dt_cols:
        dt_series = pd.to_datetime(df[c], errors="coerce", utc=True)
        localized = dt_series.dt.tz_localize(None)
        df[c] = [
            ts.strftime("%Y-%m-%d %H:%M:%S") if not pd.isna(ts) else ""
            for ts in localized
        ]

    df["taskcost"] = [
        (Decimal(v) / Decimal(3600)) * HOURLY_RATE for v in df["timespent"]
    ]
    df["taskcost"] = df["taskcost"].fillna(Decimal(0))
    total_hours = df["timespent"].sum() / 3600
    df["timespent"] = [duration(s) for s in df["timespent"]]
    df = df[rename_map.keys()]
    return df, total_hours


def html_to_pdf(html: str, path: Path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=path,
            format="A4",
            print_background=True,
            margin={
                "top": "0.5in",
                "bottom": "0.5in",
                "left": "0.5in",
                "right": "0.5in",
            },
        )
        browser.close()


def format_cost(cost: Decimal) -> str:
    return f"{cost:.2f} {CURRENCY}"


def to_excel(fpath: str, df: pd.DataFrame):
    """Saves DataFrame as native Excel table autofitting columns"""
    writer = pd.ExcelWriter(fpath, engine="xlsxwriter")
    df.to_excel(writer, sheet_name="Sheet1", startrow=1, header=False, index=False)

    worksheet = writer.sheets["Sheet1"]
    (rows, cols) = df.shape
    column_settings = [{"header": column} for column in df.columns]

    worksheet.add_table(0, 0, rows, cols - 1, {"columns": column_settings})
    worksheet.set_column(0, cols - 1, 1)
    worksheet.autofit()

    writer.close()


def create_worklog_excel(worklogs: list[dict[str, Any]], path: Path):
    """Creates an excel file from worklogs with day and hours spent."""
    daily_seconds: dict[str, int] = {}
    for worklog in worklogs:
        started_str = str(worklog["started"])
        date_str = started_str.split("T")[0]
        seconds = int(worklog["timeSpentSeconds"])
        daily_seconds[date_str] = daily_seconds.get(date_str, 0) + seconds

    if not daily_seconds:
        return

    sorted_days = sorted(daily_seconds.items())
    start_date = date.fromisoformat(sorted_days[0][0])
    end_date = date.fromisoformat(sorted_days[-1][0])

    all_dates = {}
    current_date = start_date
    while current_date <= end_date:
        all_dates[current_date.isoformat()] = daily_seconds.get(
            current_date.isoformat(), ""
        )
        current_date += timedelta(days=1)

    sorted_days = sorted(all_dates.items())

    dates = [item[0] for item in sorted_days]
    hours = [
        f"{Decimal(item[1] / 3600):.2f}".replace(".", ",") if item[1] != "" else ""
        for item in sorted_days
    ]
    dates.append("Total")
    total_seconds = Decimal(0)
    for d in daily_seconds.values():
        total_seconds += Decimal(d)
    hours.append(f"{Decimal(total_seconds / 3600):.2f}".replace(".", ","))

    df = pd.DataFrame([hours], columns=dates)
    to_excel(path, df)


if __name__ == "__main__":
    filter_is_done = sys.argv[1:] == ["done"]
    df, total_decimal_hours = get_jira_issues(only_finished_tasks=filter_is_done)
    current_date = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    worklogs = []
    if not df.empty:
        issue_ids = df.index.tolist()
        for issue_id in tqdm.tqdm(issue_ids, desc="Fetching worklogs"):
            worklogs.extend(get_worklog(issue_id))

    if len(worklogs) > 0:
        worklog_path = reports_dir / f"worklogs-{current_date}.xlsx"
        create_worklog_excel(worklogs, worklog_path)
        print(f"Worklog excel report generated at {worklog_path.absolute()}")
        start_file(worklog_path)

    total_hours, minutes = divmod(total_decimal_hours * 60, 60)
    total_hours = int(total_hours)
    minutes = int(minutes)
    total_cost = df["taskcost"].sum()
    df["taskcost"] = df["taskcost"].apply(format_cost)
    df = df.rename(columns=rename_map)

    html = f"""
    {html_styles}

    <h1>Task Report</h1>
    <p>Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

    {df.to_html(index=False)}

    <h4>Hourly rate: {HOURLY_RATE} {CURRENCY}</h4>
    <h4>Total time: {total_hours} hours {minutes} min ({total_decimal_hours:.2f})</h4>
    <h3>Total cost {total_cost:.2f}{CURRENCY}</h3>
    """
    pdf_path = reports_dir / f"report-{current_date}.pdf"
    html_to_pdf(html, pdf_path)
    print(f"PDF report generated at {pdf_path.absolute()}")
    webbrowser.open(pdf_path.as_posix())
