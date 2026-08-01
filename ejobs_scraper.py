import time
import logging
import aiohttp
import asyncio
import random

from parser import JobParser
from base_scraper import BaseScraper
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service 
from curl_cffi.requests import AsyncSession


class EJobsScraper(BaseScraper):
        
    def fetch_html_content(self, url, driver = None):

        should_close = False
        if driver is None: 
            chrome_options = Options()
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
            chrome_options.add_argument('--disable-gpu')

            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            driver = webdriver.Chrome(options=chrome_options)
            should_close = True

        try:
            driver.get(url)
            time.sleep(2.5)

            for i in range(7):
                current_pixel = (i + 1) * 1500
                driver.execute_script(f'window.scrollTo(0, {current_pixel});')
                logging.info(f'      [Selenium - eJobs] Incremental scroll to {current_pixel}px ({i+1}/7)...')
                time.sleep(1.2)
            
            full_html = driver.page_source
            return full_html, driver

        except Exception as error:
            logging.exception(f'Selenium Automation Error: {error}')
            return None, driver
        
        finally:
            if should_close and driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        
    def parse_job_cards(self, html_content, db_object, tech_keywords):

        if html_content == None: return [], False
        
        soup = BeautifulSoup(html_content, 'html.parser')
        headings = soup.find_all('h2', class_='job-card-content-middle__title')

        if not headings:
            return [], False
    
        page_jobs = []
        parser = JobParser()

        for heading in headings:

            link_tag = heading.find('a')
            if link_tag:
                title_text = link_tag.get_text(strip = True)

                if parser.is_non_it_job(title_text):
                    continue

                job = self.create_job_blueprint()

                job_url = link_tag.get('href')  
                if job_url and not job_url.startswith('http'):
                    job_url = 'https://www.ejobs.ro' + job_url

                card_parent = heading.parent
                company_tag = card_parent.find('h3', class_ = 'job-card-content-middle__info--darker')
                company_text = company_tag.get_text(strip = True) if company_tag else 'Unknown'

                location_tag = card_parent.find('div', class_= 'job-card-content-middle__info')
                location_text = location_tag.get_text(strip = True) if location_tag else 'Unknown'

                job['title'] = title_text
                job['link'] = job_url
                job['company'] = company_text
                job['location'] = location_text
                
                job['technologies'] = []
                job['experience'] = 'Unknown'
                job['work_mode'] = 'On-site'

                job['id'] = self.generate_job_id(title_text, company_text)

                page_jobs.append(job)

        if page_jobs:
            return page_jobs, True

        return [], True
    
    async def process_descriptions_await(self, job_list, tech_keywords, batch_size = 15, 
                                         concurrency = 7, max_retries = 2, cookies = None, user_agent = None):

        if not job_list:
            return []
        
        parser = JobParser()
        processed_jobs = []
        pending_jobs = list(job_list)

        cookie_dict = {c['name']: c['value'] for c in cookies} if cookies else {}
        headers = {
            'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language' : 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
        }

        if cookie_dict:
            logging.info(f"   [Session Reuse] Using {len(cookie_dict)} cookies from Selenium, "
                         f"over a curl_cffi client impersonating Chrome at the TLS/HTTP2 level.")
        else:
            logging.info(f"   [Session Reuse] No Selenium cookies captured — using curl_cffi's "
                         f"Chrome impersonation without session cookies.")

        for attempt in range(max_retries + 1):
            if not pending_jobs:
                break

            if attempt > 0:
                cooldown = 15 * attempt
                logging.warning(f"   [Retry Round {attempt}] Re-attempting {len(pending_jobs)} "
                                 f"jobs that were blocked/failed on the previous pass. "
                                 f"Cooling down {cooldown}s first...")
                await asyncio.sleep(cooldown)

            next_pending = []
            semaphore = asyncio.Semaphore(concurrency)

            async def worker(session, job):
                async with semaphore:
                    try:
                        html_desc = await self.fetch_description_html_curl(session, job['link'], headers= headers, cookies = cookie_dict)
                        if html_desc and html_desc != 'BLOCKED_429':
                            job['raw_html_desc'] = html_desc
                        else:
                            next_pending.append(job)
                    except Exception as e:
                        logging.warning(f"   [Async Network Warning] Failed fetching for {job['link']}: {e}")
                        next_pending.append(job)

                    await asyncio.sleep(random.uniform(1.2, 2))

            
            for i in range(0, len(pending_jobs), batch_size):  
                batch = pending_jobs[i:i + batch_size]
                pending_before = len(next_pending)

                async with AsyncSession() as session:  
                    tasks = [worker(session,job) for job in batch]
                    await asyncio.gather(*tasks)

                batch_failed = len(next_pending) - pending_before
                if batch_failed >= max(3, len(batch)//2):
                    await asyncio.sleep(10)      
                else:
                    await asyncio.sleep(1.5)

            pending_jobs = next_pending

        if pending_jobs:
            logging.warning(f"   [Giving Up] {len(pending_jobs)}/{len(job_list)} job descriptions "
                             f"could never be downloaded after {max_retries + 1} attempts "
                             f"(persistent 429/network failures). These are skipped, not saved.")

        fetched_count = len(job_list) - len(pending_jobs)
        logging.info(f"   [Parser Engine - eJobs] Starting analytical parsing for {fetched_count} fetched pages...")

        for job in job_list:

            if 'raw_html_desc' in job and job['raw_html_desc']:

                try:
                    html_content = job['raw_html_desc']
                    techs,exp,mode = parser.extract_data_from_description(job['link'], tech_keywords, fetch_func = lambda url : html_content)

                    job['technologies'] = techs
                    job['experience'] = exp
                    job['work_mode'] = mode

                    del job['raw_html_desc']

                    if job['technologies']:
                        processed_jobs.append(job)
                except Exception as e:
                    logging.warning(f"   [Parser Error] Error extracting text details: {e}")
                    
        logging.info(f"   [Fetch Summary] raw={len(job_list)} | saved={len(processed_jobs)} "
                     f"| never_fetched={len(pending_jobs)}")

        return processed_jobs