import time 
import logging
import asyncio
import random

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service 
from selenium.webdriver.common.by import By
from base_scraper import BaseScraper
from parser import JobParser
from database import JobDatabase
from curl_cffi.requests import AsyncSession

class BestJobsScraper(BaseScraper):

    def fetch_html_content(self, url):

        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        chrome_options.add_argument('--disable-gpu')

        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(url)
            time.sleep(2.0)

            click_count = 0
            max_clicks = 50

            logging.info("   [Selenium - BestJobs] Starting progressive manual scroll and click loop...")

            while click_count < max_clicks:

                last_height = driver.execute_script('return document.body.scrollHeight')

                for i in range(1, 10):
                    target_pixel = int((i / 9) * last_height)
                    driver.execute_script(f'window.scrollTo(0, {target_pixel});')
                    time.sleep(0.2)

                time.sleep(0.8)
               
                try:
                    button = driver.find_element(By.CSS_SELECTOR, "button.bg-secondary")
                    if button.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(0.4)
                        button.click()
                        click_count += 1
                        logging.info(f"   [Selenium - BestJobs] Clicked 'Load more' ({click_count}/{max_clicks}). Loading next batch...")
                        time.sleep(1.2)
                    else:
                        logging.info("   [Pagination - BestJobs] 'Load more' button is hidden. Reached the end.")
                        break
                    
                except Exception:
                    logging.info("   [Pagination - BestJobs] Reached the end of the category (Button not found anymore).")
                    break
                        
            full_html = driver.page_source
            soup = BeautifulSoup(full_html, 'html.parser')
            job_links = soup.find_all('a', class_ = 'absolute inset-0 z-1')
            logging.info(f"\n[Soup - BestJobs] Total jobs loaded after deep scroll: {len(job_links)} !")

            return full_html, driver

        except Exception as error:
            logging.exception(f'Selenium Automation Error during fetch: {error}')        
            return None, None
    
    def fetch_description_html_selenium(self, url, driver):
        try:
            driver.get(url)
            time.sleep(0.6) 
            return driver.page_source
        except Exception as error:
            logging.exception(f"[Selenium Error] Error loading description via Selenium: {error}")
            return None 
            
    def parse_job_cards(self, html_content, db_object, tech_keywords, driver):

        if html_content == None: return []
        
        soup = BeautifulSoup(html_content, 'html.parser')
        headings = soup.find_all('a', class_='absolute inset-0 z-1')
    
        page_jobs = []
        parser = JobParser()

        for link_tag in headings:

            if link_tag:
                job = self.create_job_blueprint()

                job_url = link_tag.get('href')  

                if job_url and not job_url.startswith('http'):
                    job_url = 'https://www.bestjobs.eu' + job_url

                card_parent = link_tag.find_parent('div')
                if not card_parent:
                    continue

                title_tag = card_parent.find('h2', class_ = 'line-clamp-2')
                title_text = title_tag.get_text(strip = True) if title_tag else 'Unknown'

                if parser.is_non_it_job(title_text):
                    continue
               
                company_tag = card_parent.find('div', class_ = 'text-ink-medium')
                company_text = company_tag.get_text(strip = True) if company_tag else 'Unknown'

                location_tag = card_parent.find('div', class_= 'relative z-2')
                location_text = location_tag.get_text(strip = True) if location_tag else 'Unknown'

                job['title'] = title_text
                job['link'] = job_url
                job['company'] = company_text
                job['location'] = 'Unknown'

                job['technologies'] = []
                job['experience'] = 'Unknown'
                job['work_mode'] = 'On-site'

                job['id'] = self.generate_job_id(title_text, company_text)

                page_jobs.append(job)

        if page_jobs:
            return page_jobs

        return []
    
    async def process_descriptions_await(self, job_list, tech_keywords, batch_size = 15, concurrency = 7):

        if not job_list:
            return []
        
        parser = JobParser()
        processed_jobs = []

        headers = {
            'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language' : 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
            'Upgrade-Insecure-Requests': '1'
        }

        await self.fetch_all_descriptions_generic(
            job_list, headers=headers, cookies=None, impersonate='chrome120', 
            concurrency=concurrency, batch_size=batch_size
            )
                

        logging.info(f"   [Parser Engine - BestJobs] Starting analytical parsing for {len(job_list)} fetched pages...")
        for job in job_list:
            if 'raw_html_desc' in job and job['raw_html_desc']:
                  
                try:
                    html_content = job['raw_html_desc']
                    techs, exp, mode, real_location = parser.extract_data_from_bestjobs_description(job['link'], tech_keywords, fetch_func = lambda url : html_content)

                    job['technologies'] = techs
                    job['experience'] = exp
                    job['work_mode'] = mode

                    if real_location and real_location != 'Unknown':
                        job['location'] = real_location

                    del job['raw_html_desc']

                    if job['technologies']:
                        processed_jobs.append(job)
                except Exception as e:
                    logging.warning(f"   [Parser Error BestJobs] Error extracting text details: {e}")
                    
        return processed_jobs
