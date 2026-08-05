import time
import logging
import sys
import asyncio
import json
import os
import sqlite3
import requests

from datetime import datetime
from bs4 import BeautifulSoup
from ejobs_scraper import EJobsScraper
from database import JobDatabase
from bestjobs_scraper import BestJobsScraper
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from linkedin_scraper import LinkedInScraper
from dotenv import load_dotenv
from pathlib import Path
from config import (
    DB_NAME, 
    EJOBS_CONCURRENCY, EJOBS_BATCH_SIZE, EJOBS_MAX_RETRIES,
    BESTJOBS_CONCURRENCY, BESTJOBS_BATCH_SIZE, BESTJOBS_MAX_RETRIES,
    LINKEDIN_CONCURRENCY, LINKEDIN_BATCH_SIZE, LINKEDIN_MAX_RETRIES
)

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)

logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(message)s",
    datefmt = "%Y-%m-%d %H-%M-%S",
    handlers = [
        logging.FileHandler('scraper.log', encoding = 'utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

async def db_writer_worker(db, queue):

    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break

        job_list, source_name = item
        try:
            if job_list:
                db.save_jobs_to_db(job_list, source_name = source_name)
        except Exception as e:
            logging.error(f"[DB Worker Error] Failed saving batch for {source_name}: {e}")
        finally:
            queue.task_done()

async def run_ejobs(db_queue, tech_keywords):
    ejobs_scraper = EJobsScraper()
    ejobs_categories = [
        'it-software',
        'internet-e-commerce',
        'it-hardware',
        'telecomunicatii',
        'inginerie',
        'productie'
    ]

    total_saved = 0

    for category in ejobs_categories:
        logging.info(f"\n🚀 Switching to eJobs category: {category.upper()} 🚀")
        base_url = f'https://www.ejobs.ro/locuri-de-munca/{category}'

        raw_category_jobs = []
        session_cookies = None
        session_user_agent = None

        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        ejobs_driver = webdriver.Chrome(options=chrome_options)

        try:
            page_number = 1
            while True:
                url = f'{base_url}/pagina{page_number}/'
                logging.info(f"   [eJobs] Loading page {page_number} for {category}...")

                loop = asyncio.get_running_loop()
                html_data, _ = await loop.run_in_executor(
                    None, ejobs_scraper.fetch_html_content, url, ejobs_driver
                )

                if not html_data:
                    logging.error(f"Could not fetch HTML for {category} page {page_number}. Skipping category")
                    break

                page_jobs, has_cards = ejobs_scraper.parse_job_cards(html_data, None, tech_keywords)
                if not has_cards:
                    logging.info(f"   [eJobs] No jobs found on page {page_number}. Reached end of category {category}.")
                    break
                
                raw_category_jobs.extend(page_jobs)
                page_number += 1
                await asyncio.sleep(2)

        finally:
            if ejobs_driver:
                try:
                    session_cookies = ejobs_driver.get_cookies()
                    session_user_agent = ejobs_driver.execute_script("return navigator.userAgent;")
                    logging.info(f"   [Session - eJobs] Captured {len(session_cookies)} cookies + real UA "
                                f"from the browser session for category '{category}'.")
                except Exception as e:
                    logging.warning(f"   [Session - eJobs] Could not capture cookies/UA from Selenium: {e}")
                ejobs_driver.quit()
            
        if raw_category_jobs:
            logging.info(f"🔥 Starting async processing for {len(raw_category_jobs)} raw eJobs jobs in '{category}'...")
            processed_jobs = await ejobs_scraper.process_descriptions_await(
                raw_category_jobs, tech_keywords,
                batch_size= EJOBS_BATCH_SIZE, 
                concurrency= EJOBS_CONCURRENCY , 
                max_retries= EJOBS_MAX_RETRIES,
                cookies= session_cookies, 
                user_agent=session_user_agent
                )
            
            lost_count = len(raw_category_jobs) - len(processed_jobs)
            logging.info(f"[eJobs Category Summary] '{category}': raw={len(raw_category_jobs)} "
                        f"saved={len(processed_jobs)} lost={lost_count}")
            if processed_jobs:
                await db_queue.put((processed_jobs, 'eJobs'))
                total_saved += len(processed_jobs)
                logging.info(f"   [eJobs Filter] Queued '{category}' for DB save ({len(processed_jobs)} jobs).")
        
        logging.info(f"   [Cooldown - eJobs] Pausing 8s before next eJobs category...")
        await asyncio.sleep(5) 

    return total_saved

async def run_bestjobs(db_queue, tech_keywords):

    bestjobs_scraper = BestJobsScraper()
    bestjobs_categories = [
        'it',
        'telecom',
        'engineering',
        'production',
    ]

    total_saved = 0
    active_driver = None

    for category in bestjobs_categories:
        logging.info(f"\n🚀 Switching to BestJobs category: {category.upper()} 🚀")
        current_url = f"https://www.bestjobs.eu/locuri-de-munca/{category}"

        logging.info(f"   [BestJobs] Fetching HTML content for '{category}'...")

        loop = asyncio.get_running_loop()
        bestjobs_html , live_driver = await loop.run_in_executor(
            None, bestjobs_scraper.fetch_html_content,current_url
        )
        if live_driver:
            active_driver = live_driver

        if bestjobs_html and live_driver:
            raw_bj_jobs = bestjobs_scraper.parse_job_cards(bestjobs_html, None, tech_keywords, live_driver)

            if raw_bj_jobs and isinstance(raw_bj_jobs, list):
                logging.info(f"🔥 Starting async processing for {len(raw_bj_jobs)} raw BestJobs jobs in '{category}'...")
                processed_bj_jobs = await bestjobs_scraper.process_descriptions_await(
                    raw_bj_jobs, tech_keywords, 
                    batch_size= BESTJOBS_BATCH_SIZE, 
                    concurrency= BESTJOBS_CONCURRENCY, 
                    max_retries= BESTJOBS_MAX_RETRIES
                    )

                if processed_bj_jobs:
                    await db_queue.put((processed_bj_jobs, 'BestJobs'))
                    total_saved += len(processed_bj_jobs)
                    logging.info(f"   [BestJobs Filter] Queued '{category}' for DB save ({len(processed_bj_jobs)} jobs).")
        else:
            logging.error(f"[BestJobs Error] Could not initialize Selenium for BestJobs category {category}.")

    if active_driver:
        logging.info("\n[BestJobs] Closing browser session...")
        active_driver.quit()
    return total_saved

async def run_linkedin(db_queue, tech_keywords, location="Romania"):
    scraper = LinkedInScraper()

    linkedin_categories = [
        'Software', 
        'Backend', 
        'Frontend', 
        'Full Stack', 
        'DevOps', 
        'Cloud', 
        'Data', 
        'QA', 
        'Testing', 
        'Automation',
        'IT'
    ]
    total_saved = 0

    for category in linkedin_categories:
        logging.info(f"\n🚀 Switching to LinkedIn category: {category.upper()} 🚀")
        url = f"https://www.linkedin.com/jobs/search?keywords={category}&location={location}"

        logging.info(f"   [LinkedIn] Fetching HTML content for '{category}'...")

        loop = asyncio.get_running_loop()
        html_content, driver = await loop.run_in_executor(
            None, scraper.fetch_html_content, url
        )

        if html_content:
            logging.info(f"   [LinkedIn] Parsing job cards for '{category}'...")
            raw_jobs = scraper.parse_job_cards(html_content, None, tech_keywords, driver)

            if raw_jobs:
                logging.info(f"🔥 Starting async processing for {len(raw_jobs)} raw LinkedIn jobs in '{category}'...")
                processed_jobs = await scraper.process_descriptions_await(
                    raw_jobs, tech_keywords, 
                    batch_size=LINKEDIN_BATCH_SIZE, 
                    concurrency=LINKEDIN_CONCURRENCY,
                    max_retries=LINKEDIN_MAX_RETRIES
                )

                if processed_jobs:
                    await db_queue.put((processed_jobs, 'LinkedIn'))
                    total_saved += len(processed_jobs)
                    logging.info(f"   [LinkedIn Filter] Queued '{category}' for DB save ({len(processed_jobs)} jobs).")
        else:
            logging.error(f"[LinkedIn Error] Failed to retrieve HTML for '{category}'.")

        if driver:
            driver.quit()

        logging.info("   [Cooldown - LinkedIn] Pausing 10s before next LinkedIn category...")
        await asyncio.sleep(10)

    return total_saved

def format_duration(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def send_telegram_run_stats():

    TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT")

    if not TOKEN or not CHAT_ID:
        logging.warning("[Telegram] Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in environment variables. Skipping notification.")
        return

    filename = "run_stats.json"
    if not os.path.exists(filename):
        logging.warning("[Telegram] run_stats.json not found, skipping notification.")
        return

    try:
        with open(filename, 'r', encoding = 'utf-8') as f:
            history = json.load(f)
            if not history:
                return 
            latest = history[-1]
    except Exception as e:
        logging.error(f"[Telegram Error] Could not read run_stats.json: {e}")
        return 

    message = (
        f"🚀 *Romania IT Job Scraper - Run Report*\n\n"
        f"📅 *Date:* {latest.get('date_scraped')}\n"
        f"📥 *Saved/Processed:* {latest.get('total_saved')}\n"
        f"📊 *Total Active:* {latest.get('total_active_jobs')}\n"
        f"❌ *Expired Found:* {latest.get('expired_found')}\n"
        f"⏱️ *Duration:* {latest.get('duration')}"
    )

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json = payload)
        if response.status_code == 200:
            logging.info("[Telegram] Notification sent successfully!")
        else:
            logging.warning(f"[Telegram] Failed to send notification: {response.text}")
    except Exception as e:
        logging.error(f"[Telegram Error] Network exception: {e}")

def save_run_stats(total_saved_run, run_start_time, expired_count, duration_str, db_name = DB_NAME):

    connection = sqlite3.connect(db_name)
    cursor = connection.cursor()

    cursor.execute("SELECT COUNT(*) FROM jobs WHERE status = 'active'")
    total_active_jobs = cursor.fetchone()[0]

    connection.close()
    
    stats = {
        "date_scraped" : run_start_time,
        "total_saved": total_saved_run,
        "total_active_jobs": total_active_jobs,
        "expired_found" : expired_count,
        "duration" : duration_str

    }
    filename = "run_stats.json"

    if os.path.exists(filename):
        with open(filename, 'r', encoding = 'utf-8') as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []
    else:
        history = []

    history.append(stats)

    with open(filename, 'w', encoding = 'utf-8') as f:
        json.dump(history, f, indent = 4, ensure_ascii = False)

async def main():

    start_time_seconds = time.time()
    run_start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    tech_keywords = {
    # Programming Languages
    'python', 'java', 'c++', 'c#', 'c-sharp', 'php', 'ruby', 'go', 'golang', 
    'rust', 'typescript', 'javascript', 'kotlin', 'scala', 'lua', 'solidity',
    
    # Web & Mobile Frameworks
    'react', 'next.js', 'angular', 'vue', 'nuxt.js', ' Svelte', 'node', 'express', 
    'django', 'flask', 'fastapi', 'spring', 'hibernate', 'asp.net', '.net', 'dotnet', 
    'graphql', 'tailwind', 'wordpress', 'flutter', 'react native', 'ionic',
    
    # Databases & Streaming
    'sql', 'mysql', 'postgresql', 'postgres', 'mongodb', 'mongo', 
    'oracle', 'sqlserver', 'redis', 'elasticsearch', 'kafka', 'dynamodb', 'cassandra',
    
    # Cloud, DevOps & Infrastructure
    'aws', 'azure', 'gcp', 'cloud', 'docker', 'podman', 'kubernetes', 
    'openshift', 'terraform', 'ansible', 'helm', 'ci/cd', 'bash', 'serverless', 'lambda',
    
    # Cybersecurity & AppSec
    'oauth', 'jwt', 'penetration testing', 'owasp', 'cybersecurity', 'encryption',
    
    # AI, ML & Data Engineering
    'pytorch', 'tensorflow', 'pandas', 'numpy', 'spark', 'hadoop', 'databricks', 'airflow', 'langchain', 'openai',
    
    # Testing, Version Control & API
    'git', 'github', 'gitlab', 'bitbucket', 'selenium', 'cypress', 
    'playwright', 'jmeter', 'postman', 'prometheus', 'grafana', 'wireshark' 
    }

    db = JobDatabase(DB_NAME)
    db.init_db()

    db_queue = asyncio.Queue()
    
    writer_task = asyncio.create_task(db_writer_worker(db, db_queue))

    logging.info('Starting Fully Parallel Multi-Platform Scraping Process...')

    results = await asyncio.gather(
        run_ejobs(db_queue, tech_keywords),
        run_bestjobs(db_queue, tech_keywords),
        run_linkedin(db_queue, tech_keywords)
    )

    total_saved_run = sum(results)

    logging.info("\n[DB Queue] Waiting for all pending database writes to complete...")
    await db_queue.join()

    await db_queue.put(None)
    await writer_task

    logging.info(f'\nTotal IT jobs saved during this run: {total_saved_run}')

    expired_count = await db.check_expired_jobs_async(run_start_time)

    total_seconds = time.time() - start_time_seconds
    duration_str = format_duration(total_seconds)

    save_run_stats(total_saved_run, run_start_time, expired_count, duration_str)
    send_telegram_run_stats()

    db.generate_market_report()

if __name__ == "__main__":
    
    asyncio.run(main())