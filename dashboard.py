import sqlite3

from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import JSONResponse 
from fastapi.templating import Jinja2Templates
from core.config import DB_NAME
from typing import Optional

app = FastAPI()

templates = Jinja2Templates(directory="templates")

def get_db():
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
    finally:
        connection.close()


def fetch_jobs_from_db(
    cursor,
    status_filter: str,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None
):

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
    return cursor.fetchall()
    
@app.get('/')
def read_jobs(
    request: Request,
    search: Optional[str] = None,
    work_mode: Optional[str] = None,
    experience: Optional[str] = None,
    source: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    jobs = fetch_jobs_from_db(cursor, 'active', search, work_mode, experience, source)
    
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
    source: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    jobs = fetch_jobs_from_db(cursor, 'applied', search, work_mode, experience, source)
    
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
def toggle_job_status(
    job_id: str, 
    new_status: str = Form(...),
    db: sqlite3.Connection = Depends(get_db)
    ):
    cursor = db.cursor()
    cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    db.commit()
    
    return JSONResponse(content={"success": True, "job_id": job_id, "new_status": new_status})