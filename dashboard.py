import sqlite3

from fastapi import FastAPI, Response
from config import DB_NAME

app = FastAPI()

@app.get('/')

def read_jobs():

    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute("""
    SELECT id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status
    FROM jobs
    WHERE status = 'active'
    ORDER BY date_scraped DESC
    """)

    jobs = cursor.fetchall()
    connection.close()

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Active IT Jobs Dashboard</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; color: #333; }
            h1 { color: #2c3e50; text-align: center; }
            .counter { text-align: center; margin-bottom: 20px; font-size: 1.1em; color: #555; }
            .table-container { overflow-x: auto; background: #fff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9em; }
            th, td { padding: 12px 15px; border-bottom: 1px solid #e1e8ed; }
            th { background-color: #2c3e50; color: #ffffff; text-transform: uppercase; font-size: 0.85em; letter-spacing: 0.05em; }
            tr:hover { background-color: #f8fafc; }
            a { color: #3498db; text-decoration: none; font-weight: bold; }
            a:hover { text-decoration: underline; }
            .badge { padding: 4px 8px; border-radius: 4px; font-size: 0.85em; font-weight: bold; }
            .remote { background-color: #e8f8f5; color: #1abc9c; }
            .hybrid { background-color: #fef9e7; color: #f1c40f; }
            .onsite { background-color: #f2f3f4; color: #7f8c8d; }
        </style>
    </head>
    <body>
        <h1>📊 Active IT Jobs Dashboard</h1>
    """
    
    html_content += f"<div class='counter'>Total active jobs: <b>{len(jobs)}</b></div>"
    html_content += "<div class='table-container'><table>"

    html_content += """
        <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Company</th>
            <th>Location</th>
            <th>Experience</th>
            <th>City</th>
            <th>Work Mode</th>
            <th>Technologies</th>
            <th>Date Scraped</th>
            <th>Source</th>
            <th>Status</th>
            <th>Link</th>
        </tr>
    """

    for job in jobs:
        job_id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status = job   

        mode_class = "onsite"
        if work_mode == 'Remote' : mode_class = "remote"
        elif work_mode == 'Hybrid' : mode_class = "hybrid"

        html_content += f"""
        <tr>
            <td style="font-family: monospace; font-size: 0.8em; color: #888;" title="{job_id}">{job_id[:8]}...</td>
            <td><b>{title}</b></td>
            <td>{company}</td>
            <td>{location}</td>
            <td>{experience}</td>
            <td>{city}</td>
            <td><span class="badge {mode_class}">{work_mode}</span></td>
            <td>{technologies}</td>
            <td>{date_scraped}</td>
            <td><b>{source}</b></td>
            <td>{status}</td>
            <td><a href="{link}" target="_blank">🔗 Apply</a></td>
        </tr>
        """

    html_content += "</table></div></body></html>"
    return Response(content=html_content, media_type="text/html")

    