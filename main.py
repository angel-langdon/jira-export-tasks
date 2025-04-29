import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pdfkit
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


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

search_url = f"{JIRA_URL}/rest/api/3/search"
auth = HTTPBasicAuth(EMAIL, API_TOKEN)
jql_query = f'project = "{PROJECT_KEY}" ORDER BY updated ASC'
fields = "project,summary,updated,timespent"
rename_map = {
    "project": "Project name",
    "summary": "Summary",
    "timespent": "Time Spent",
    "updated": "Updated",
    "taskcost": f"Task Cost (hours x{HOURLY_RATE}{CURRENCY}/hour",
}
dt_cols = ["updated"]
params = {"jql": jql_query, "fields": fields, "maxResults": 100}


def get_jira_issues():
    """Fetch issues from JIRA."""
    response = requests.get(search_url, headers=headers, params=params, auth=auth)
    response.raise_for_status()

    issues = response.json()["issues"]
    data = []
    for issue in issues:
        dic = issue["fields"]
        dic["project"] = dic["project"]["name"]
        data.append(dic)

    df = pd.DataFrame(data)
    for c in dt_cols:
        df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d %H:%M:%S")

    df["taskcost"] = [
        (Decimal(v) / Decimal(3600)) * HOURLY_RATE for v in df["timespent"]
    ]
    df["taskcost"] = df["taskcost"].fillna(Decimal(0))
    df["timespent"] = [duration(s) for s in df["timespent"]]
    df = df[rename_map.keys()]
    return df


get_jira_issues()
# %%

if __name__ == "__main__":
    df = get_jira_issues()
    total_cost = df["taskcost"].sum()
    df["taskcost"] = df["taskcost"].apply(lambda x: f"{x:.2f} {CURRENCY}")
    df = df.rename(columns=rename_map)
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

    html = f"""
    {html_styles}

    <h1>Task Report</h1>
    <p>Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

    {df.to_html(index=False)}

    <h3>Total cost {total_cost:.2f}{CURRENCY}</h3>
    """

    pdf_path = Path("report.pdf")
    pdfkit.from_string(
        html,
        pdf_path,
        options={
            "encoding": "UTF-8",
            "page-size": "A4",
            "margin-top": "0.5in",
            "margin-right": "0.5in",
            "margin-bottom": "0.5in",
            "margin-left": "0.5in",
        },
    )
    print(f"PDF report generated at {pdf_path.absolute()}")
    os.startfile(pdf_path)
