import sqlite3
import time
import logging
import asyncio
import random

from parser import JobParser
from datetime import datetime
from curl_cffi.requests import AsyncSession
from config import DB_NAME
class JobDatabase:
    
    def __init__(self, db_name = DB_NAME):
        self.db_name = db_name

    
    def init_db(self):
        with sqlite3.connect(self.db_name) as connection:
            cursor = connection.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT,
                    location TEXT,
                    experience TEXT,
                    city TEXT,
                    work_mode TEXT,
                    link TEXT,
                    technologies TEXT,
                    date_scraped TEXT,
                    source TEXT,
                    status TEXT DEFAULT 'active'
                )
            ''')

            connection.commit()
    
        logging.info(f'[SQL Database] Initialized successfully. Table "jobs" is ready.')

        
    def save_jobs_to_db(self, job_list, source_name = 'eJobs'):

        if not job_list :
            logging.info('[SQL] No jobs to save.')
            return

        saved_count = 0
        parser = JobParser()

        with sqlite3.connect(self.db_name) as connection:
            cursor = connection.cursor()

            for job in job_list:

                tech_string = ', '.join(job['technologies'])
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                extracted_city , fallback_work_mode = parser.parse_location(job['location'])

                final_work_mode = job.get('work_mode', 'On-site')

                if final_work_mode == 'On-site' and fallback_work_mode in ['Remote', 'Hybrid']:
                    final_work_mode = fallback_work_mode

                query = '''
                    INSERT INTO jobs (id, title, company, location, experience, city, work_mode, link, technologies, date_scraped, source, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET status = 'active' , date_scraped = ?, source = ?
                
                '''

                cursor.execute(query, (
                    job['id'],
                    job['title'],
                    job['company'],
                    job['location'],
                    job['experience'],
                    extracted_city,
                    final_work_mode,
                    job['link'],
                    tech_string,
                    current_time,
                    source_name,
                    'active',
                    current_time,
                    source_name
                ))

                saved_count += 1

            connection.commit()

        logging.info(f'[SQL Database] Done! Out of {len(job_list)} filtered jobs, {saved_count} were NEW and successfully saved.')


    async def check_expired_jobs_async(self, run_start_time):

        logging.info('\n[Checker] Starting verification of active jobs for expiration...')

        with sqlite3.connect(self.db_name) as connection:
            cursor = connection.cursor()

            cursor.execute(
                "SELECT id, link, title FROM jobs WHERE status = 'active' and date_scraped < datetime(?, '-7 days')",
                (run_start_time,)
                )   
            active_jobs = cursor.fetchall()

        if not active_jobs:
            logging.info('[Checker] No active jobs found in the database to verify.')
            return 0
        
        logging.info(f'[Checker] Found {len(active_jobs)} active jobs to check. Firing up async workers...')

        expired_ids = []
        semaphore = asyncio.Semaphore(3)

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1'
         }

        expired_keywords = [
            'anuntul nu mai este activ', 
            'aceasta pagina a expirat', 
            'page not found', 
            'anunt indisponibil',
            'acest anunt a expirat',
            'nu mai este disponibil',
            'no longer accepting applications',
            'this job is no longer available',
            'job is closed',
            'job nu mai este valabil',
            'postul nu mai este disponibil'
        ]

        async def check_job(session, job_id, job_url, job_title):
            max_retries = 3

            async with semaphore:
                for attempt in range(1,max_retries + 1):
                    try:
                        response = await session.get(job_url, headers=headers, impersonate='chrome120', timeout=20, allow_redirects=True)

                        if response.status_code == 429:
                            wait_time = 15 * attempt
                            logging.warning(f'[Checker] 429 Too Many Requests on: {job_url}')
                            await asyncio.sleep(wait_time)
                            continue

                        if response.status_code in [404, 410]:
                            expired_ids.append((job_id,))
                            logging.info(f'       [Expired - HTTP 404] "{job_title}" marked as expired.')
                            break

                        html_lower = response.text.lower()

                        is_expired = any(keyword in html_lower for keyword in expired_keywords)

                        if is_expired or (('linkedin.com/jobs/view' in job_url) and ('linkedin.com/jobs/search' in response.url)):
                            expired_ids.append((job_id,))
                            logging.info(f'       [Expired - Keyword/Redirect] "{job_title}" marked as expired.')

                        break
                            
                    except Exception as e:
                        if attempt < max_retries:
                            await asyncio.sleep(5)
                        else:
                            logging.warning(f'       [Checker Network Fail] Could not load {job_url} after {max_retries} attempts.')

                await asyncio.sleep(random.uniform(3.0, 5.0))

        batch_size = 15
        async with AsyncSession() as session:
            for i in range(0, len(active_jobs), batch_size):
                batch = active_jobs[i:i + batch_size]
                tasks = [check_job(session, job_id, job_url, job_title) for job_id, job_url, job_title in batch]
                await asyncio.gather(*tasks)    

                logging.info(f'       [Checker Cooldown] Batch {i//batch_size + 1} / {(len(active_jobs)//batch_size) + 1} completed. Pausing for 10 seconds...')
                await asyncio.sleep(10)

        if expired_ids:
            with sqlite3.connect(self.db_name) as connection:
                cursor = connection.cursor()
                cursor.executemany("UPDATE jobs SET status = 'expired' WHERE id = ?", expired_ids)
                connection.commit()
            logging.info(f'[Checker] Successfully updated {len(expired_ids)} expired jobs in the database.')
        else:
            logging.info('[Checker] No expired jobs found during this run.')

        return len(expired_ids)

    def generate_market_report(self):

        with sqlite3.connect(self.db_name) as connection:
            cursor = connection.cursor()

            cursor.execute("SELECT technologies FROM jobs WHERE status = 'active'")
            active_jobs_tech = cursor.fetchall()

            tech_counts = {}

            for row in active_jobs_tech:
                tech_string = row[0]
                if tech_string:
                    technologies = tech_string.split(', ')

                    for tech in technologies:
                        if tech in tech_counts:
                            tech_counts[tech] += 1
                        else:
                            tech_counts[tech] = 1
        
            sorted_tech = sorted(tech_counts.items() , key = lambda item : item[1], reverse = True)
            logging.info('\n' + "=" * 40)
            logging.info('   📊 ACTIVE JOB MARKET REPORT 📊   ')
            logging.info('=' * 40)

            for technology, count in sorted_tech:
                logging.info(f' {technology.upper()} : {count} jobs')

            logging.info('=' * 40 + '\n')


            cursor.execute("SELECT work_mode, COUNT(*) FROM jobs WHERE status = 'active' GROUP BY work_mode")
            mode_counts = cursor.fetchall()

            mode_emojis = {
                'Remote' : '🏠 REMOTE',
                'Hybrid' : '🤝 HYBRID',
                'On-site' : '🏢 ON-SITE'
            }

            logging.info('=' * 40)
            logging.info("   🏢 WORK MODE DISTRIBUTION 🏢   ")
            logging.info("=" * 40)
            for mode, count in mode_counts:
                display_name = mode_emojis.get(mode, mode.upper())
                logging.info(f' {display_name} : {count} jobs' )

            cursor.execute("SELECT experience , COUNT(*) FROM jobs WHERE status = 'active' GROUP BY experience")
            experience_counts = cursor.fetchall()

            logging.info('\n' + "=" * 40)
            logging.info("   📊 EXPERIENCE LEVEL DISTRIBUTION 📊   ") 
            logging.info("=" * 40)
            for exp_level, count in experience_counts:
                display_level = exp_level if exp_level else 'UNKNOWN'
                logging.info(f' 📊{display_level} : {count} jobs')

            logging.info("=" * 40)

    
