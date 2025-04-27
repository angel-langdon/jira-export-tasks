import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pdfkit

if __name__ == "__main__":
    path = Path(sys.argv[1])
    df = pd.read_csv(path)
    dt_cols = ["Created", "Updated", "Resolved"]
    time_cols = ["Time Spent", "Σ Time Spent"]
    keep_cols = ["Summary", "Project name", "Time Spent", "Σ Time Spent", *dt_cols]
    for col in time_cols:
        df[col] = [
            str(timedelta(seconds=int(v))) if pd.notna(v) else v for v in df[col]
        ]
    df = df[keep_cols]

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
