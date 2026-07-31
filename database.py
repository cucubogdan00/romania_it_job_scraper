import sqlite3
import time
import logging

from parser import JobParser
from datetime import datetime

class JobDatabase:
    
    def __init__(self, db_name = 'jobs.db'):
        self.db_name = db_name

    
    def init_db(self):

        connection = sqlite3.connect(self.db_name)
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
        connection.close()
        logging.info(f'[SQL Database] Initialized successfully. Table "jobs" is ready.')

        
    def save_jobs_to_db(self, job_list, source_name = 'eJobs'):

        if not job_list :
            logging.info('[SQL] No jobs to save.')
            return
        
        connection = sqlite3.connect(self.db_name)
        cursor = connection.cursor()

        saved_count = 0
        
        parser = JobParser()

        for job in job_list:

            tech_string = ', '.join(job['technologies'])
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            extracted_city , extracted_work_mode = parser.parse_location(job['location'])

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
                extracted_work_mode,
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
        connection.close()

        logging.info(f'[SQL Database] Done! Out of {len(job_list)} filtered jobs, {saved_count} were NEW and successfully saved.')


    def check_expired_jobs(self, fetch_func, run_start_time):

        logging.info('\n[Checker] Starting verification of active jobs for expiration...')

        connection = sqlite3.connect(self.db_name)
        cursor = connection.cursor()

        cursor.execute(
            "SELECT id, link, title FROM jobs WHERE status = 'active' and date_scraped < datetime(?, '-1 day')",
            (run_start_time,)
            )   
        active_jobs = cursor.fetchall()

        if not active_jobs:
            logging.info('[Checker] No active jobs found in the database to verify.')
            connection.close()
            return
        
        logging.info(f'[Checker] Found {len(active_jobs)} active jobs to check on the website.')

        expired_count = 0

        for job_id, job_url, job_title in active_jobs:
            logging.info(f'       [Checking] "{job_title}"...')

            job_html = fetch_func(job_url)

            time.sleep(1.5)

            if job_html == 'BLOCKED_429':
                logging.warning('[Warning] 429 Too Many Requests detected. Stopping verification loop to protect database integrity.')
                break

            is_expired = False
            if job_html is None:
                is_expired = True
            else:
                html_lower = job_html.lower()
                if ('anuntul nu mai este activ' in html_lower or
                    'aceasta pagina a expirat' in html_lower or
                    'page not found' in html_lower or
                    'anunt indisponibil' in html_lower):
                    is_expired = True

            if is_expired:
                expired_count += 1
                query_update = "UPDATE jobs SET status = 'expired' WHERE id = ?"
                cursor.execute(query_update, (job_id, ))
                logging.info(f'       [Expired] "{job_title}" has been marked as expired in the database.')

        connection.commit()
        connection.close()

        return expired_count

    def generate_market_report(self):

        connection = sqlite3.connect(self.db_name)
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

        connection.close()
