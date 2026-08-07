import sqlite3

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from config import DB_NAME

app = FastAPI()

templates = Jinja2Templates(directory="templates")

@app.get('/')

def read_jobs(request: Request):

    connection = sqlite3.connect(DB_NAME)
    
    connection.row_factory = sqlite3.Row  
    cursor = connection.cursor()

    cursor.execute("""
    SELECT id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status
    FROM jobs
    WHERE status = 'active'
    ORDER BY date_scraped DESC
    """)

    jobs = cursor.fetchall()
    connection.close()

    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"request": request, "jobs": jobs}
    )
    