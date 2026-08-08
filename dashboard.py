import sqlite3

from fastapi import FastAPI, Request, Form
from fastapi.responses import JSONResponse 
from fastapi.templating import Jinja2Templates
from config import DB_NAME
from typing import Optional

app = FastAPI()

templates = Jinja2Templates(directory="templates")

def fetch_jobs_from_db(
    status_filter: str,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None
):

    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row  
    cursor = connection.cursor()

    base_query = f"""
    SELECT id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status
    FROM jobs
    WHERE status = '{status_filter}'
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
    return jobs

@app.get('/')
def read_jobs(
    request: Request,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None
):
    jobs = fetch_jobs_from_db('active', search, work_mode, experience, source)
    
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "request": request, 
            "jobs": jobs,
            "current_tab": "active",
            "current_search" : search or "",
            "current_work_mode" : work_mode or "",
            "current_experience" : experience or "",
            "current_source" : source or ""
            }
    )

@app.get('/applied')
def read_applied_jobs(
    request: Request,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None
):
    jobs = fetch_jobs_from_db('applied', search, work_mode, experience, source)
    
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "request": request, 
            "jobs": jobs,
            "current_tab": "applied",
            "current_search": search or "",
            "current_work_mode": work_mode or "",
            "current_experience": experience or "",
            "current_source": source or ""
        }
    )

@app.post('/toggle_status/{job_id}')
def toggle_job_status(job_id: str, new_status: str = Form(...)):
    connection = sqlite3.connect(DB_NAME)
    cursor = connection.cursor()

    cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    connection.commit()
    connection.close()

    return JSONResponse(content={"success": True, "job_id": job_id, "new_status": new_status})