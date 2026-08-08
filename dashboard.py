import sqlite3

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from config import DB_NAME
from typing import Optional

app = FastAPI()

templates = Jinja2Templates(directory="templates")

@app.get('/')

def read_jobs(
    request: Request,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None
):
    
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row  
    cursor = connection.cursor()

    base_query = """
    SELECT id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status
    FROM jobs
    WHERE status = 'active'
    """

    params = []

    if search:
        base_query += " AND (title LIKE ? OR company LIKE ? OR technologies LIKE ? or city LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term, search_term])

    if work_mode:
        base_query += " AND work_mode = ?"
        params.append(work_mode)

    if experience:
        base_query += " AND experience = ?"
        params.append(experience)

    if source:
        base_query += " AND source = ?"
        params.append(source)

    base_query += " ORDER BY date_scraped DESC"

    cursor.execute(base_query, params)
    jobs = cursor.fetchall()
    connection.close()

    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "request": request, 
            "jobs": jobs,
            "current_search" : search or "",
            "current_work_mode" : work_mode or "",
            "current_experience" : experience or "",
            "current_source" : source or ""
            }
    )
    