# Export Jira tasks and generate PDF report

## Usage

Fill `.env` with your values:

```
JIRA_URL=https://yoursite.atlassian.net/
EMAIL=youremail@email.com
API_TOKEN="<your api token https://id.atlassian.com/manage-profile/security/api-tokens>"
PROJECT_KEY=AB # TWO LETTER PROJECT KEY NORMALLY
HOURLY_RATE=250 # YOUR HOURLY RATE IN YOUR CURRENCY
CURRENCY=$ # YOUR CURRENCY SYMBOL
```

Export CSV tasks from Jira and run the following program

```
uv run main.py
```

## Result

**report.pdf**

![Example report](img/report-example.png)
