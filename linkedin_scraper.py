import time
import logging
import asyncio
import random

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from base_scraper import BaseScraper
from parser import JobParser
from curl_cffi.requests import AsyncSession

class LinkedInScraper(BaseScraper):

    def fetch_html_content(self, url):
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')

        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(url)
            time.sleep(3.0)

            scroll_attempts = 50
            logging.info("   [Selenium LinkedIn] Starting scroll down loop to load jobs...")

            last_height = driver.execute_script("return document.body.scrollHeight")
            
            for i in range(scroll_attempts):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2.0)
                
                try:
                    load_more_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'infinite-scroller__show-more-button')]")
                    if load_more_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", load_more_btn)
                        time.sleep(2.0)
                        logging.info("   [Selenium LinkedIn] Clicked 'Load More' button.")
                except Exception:
                    pass 

                new_height = driver.execute_script("return document.body.scrollHeight")

                if new_height == last_height:
                    logging.info(f"   [Selenium LinkedIn] End of jobs reached after {i+1} scrolls. Stopping.")
                    break

                last_height = new_height

            full_html = driver.page_source
            return full_html, driver

        except Exception as error:
            logging.exception(f'Selenium Automation Error on LinkedIn: {error}')
            if driver:
                driver.quit()
            return None, None

    def parse_job_cards(self, html_content, db_object, tech_keywords, driver=None):
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
    
        job_cards = soup.find_all('div', class_='base-card')
        if not job_cards:
            job_cards = soup.find_all('li', class_='result-card')

        logging.info(f"[Soup LinkedIn] Found {len(job_cards)} raw job cards.")
        page_jobs = []
        parser = JobParser()

        for card in job_cards:
            try:

                link_tag = card.find('a', class_='base-card__full-link') or card.find('a', href=True)

                if not link_tag:
                    continue

                title_tag = card.find('h3', class_='base-search-card__title')
                if not title_tag:
                    title_tag = link_tag.find('span', class_='sr-only')

                company_tag = card.find('h4', class_='base-search-card__subtitle')
                location_tag = card.find('span', class_='job-search-card__location')

                if not title_tag:
                    continue

                title_text = title_tag.get_text(strip=True)
                if parser.is_non_it_job(title_text):
                    continue

                company_text = company_tag.get_text(strip=True) if company_tag else 'Unknown'
                location_text = location_tag.get_text(strip=True) if location_tag else 'Romania'
                job_url = link_tag.get('href').split('?')[0] 

                job = self.create_job_blueprint()
                job['title'] = title_text
                job['company'] = company_text
                job['link'] = job_url
                job['location'] = location_text
                job['id'] = self.generate_job_id(title_text, company_text)

                page_jobs.append(job)

            except Exception as e:
                logging.warning(f"   [Parser Warning LinkedIn] Error parsing individual card: {e}")

        return page_jobs

    async def process_descriptions_await(self, job_list, tech_keywords, batch_size=10, concurrency=5):
        if not job_list:
            return []

        parser = JobParser()
        processed_jobs = []
        pending_jobs = list(job_list)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }

        semaphore = asyncio.Semaphore(concurrency)

        async def worker(session, job):
            async with semaphore:
                try:
                    html_desc = await self.fetch_description_html_curl(session, job['link'], headers=headers)
                    if html_desc and html_desc != 'BLOCKED_429':
                        job['raw_html_desc'] = html_desc
                except Exception as e:
                    logging.warning(f"   [Async LinkedIn Warning] Failed fetching {job['link']}: {e}")
                await asyncio.sleep(random.uniform(2.0, 4.0))

        for i in range(0, len(pending_jobs), batch_size):
            batch = pending_jobs[i:i + batch_size]
            async with AsyncSession() as session:
                tasks = [worker(session, job) for job in batch]
                await asyncio.gather(*tasks)
            await asyncio.sleep(1.0)

        await asyncio.sleep(random.uniform(3.0, 6.0))
        
        logging.info(f"   [Parser Engine LinkedIn] Analyzing descriptions for fetched pages...")
        for job in job_list:
            if 'raw_html_desc' in job and job['raw_html_desc']:
                try:
                    html_content = job['raw_html_desc']
                    
                    soup = BeautifulSoup(html_content, 'html.parser')
                    desc_container = soup.find('div', class_='description__text') or soup.find('section', class_='show-more-less-html')
                    full_text = desc_container.get_text(separator=' ', strip=True).lower() if desc_container else soup.get_text().lower()

                    job['technologies'] = parser.find_tech_in_text(full_text, tech_keywords)
                    
                    job['work_mode'] = 'Remote' if 'remote' in full_text else ('Hybrid' if 'hibrid' in full_text or 'hybrid' in full_text else 'On-site')

                    job['experience'] = 'Unknown'
                    title_lower = job['title'].lower()
                    
                    if any(word in title_lower for word in ['senior', 'lead', 'principal', 'head', 'architect', 'manager', 'director']):
                        job['experience'] = 'Senior-Level (> 5 ani)'
                    elif any(word in title_lower for word in ['junior', 'trainee', 'intern', 'entry', 'graduate', 'începător']):
                        job['experience'] = 'Entry-Level (< 2 ani)'
                    elif any(word in title_lower for word in ['mid', 'middle']):
                        job['experience'] = 'Mid-Level (2-5 ani)'
                    else:
                        criteria_list = soup.find_all('ul', class_= 'description__job-criteria-list')
                        if criteria_list:
                            first_criteria = criteria_list[0].find('li', class_='description__job-criteria-item')
                            if first_criteria: 
                                exp_span = first_criteria.find('span', class_='description__job-criteria-text--criteria')
                                if exp_span:
                                    exp_text = exp_span.get_text(strip=True).lower()

                                    if 'începător' in exp_text or 'entry' in exp_text or 'intern' in exp_text or 'stagiar' in exp_text:
                                        job['experience'] = 'Entry-Level (< 2 ani)'
                                    elif 'superior' in exp_text or 'director' in exp_text or 'executive' in exp_text:
                                        job['experience'] = 'Senior-Level (> 5 ani)'
                                    elif 'mediu' in exp_text or 'mid' in exp_text or 'associate' in exp_text:
                                        job['experience'] = 'Mid-Level (2-5 ani)'

                    del job['raw_html_desc']

                    if job['technologies']:
                        processed_jobs.append(job)

                except Exception as e:
                    logging.warning(f"   [Parser Error LinkedIn] Failed parsing text: {e}")

        return processed_jobs