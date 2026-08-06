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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class LinkedInScraper(BaseScraper):

    def fetch_html_content(self, url):
        
        driver = None
        try:
            chrome_options = self.get_chrome_options()
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(url)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(0.5)

            scroll_attempts = 50
            logging.info("   [Selenium - LinkedIn] Starting scroll down loop to load jobs...")

            last_height = driver.execute_script("return document.body.scrollHeight")
            
            for i in range(scroll_attempts):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2.0)
                
                try:
                    load_more_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'infinite-scroller__show-more-button')]")
                    if load_more_btn.is_displayed():
                        driver.execute_script("arguments[0].click();", load_more_btn)
                        time.sleep(2.0)
                        logging.info("   [Selenium - LinkedIn] Clicked 'Load More' button.")
                except Exception:
                    pass 

                new_height = driver.execute_script("return document.body.scrollHeight")

                if new_height == last_height:
                    logging.info(f"   [Selenium - LinkedIn] End of jobs reached after {i+1} scrolls. Stopping.")
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

        logging.info(f"[Soup - LinkedIn] Found {len(job_cards)} raw job cards.")
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

    async def process_descriptions_await(self, job_list, tech_keywords, batch_size=10, concurrency=5, max_retries=0):
        if not job_list:
            return []

        parser = JobParser()
        processed_jobs = []

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1'
        }

        await self.fetch_all_descriptions_generic(
            job_list, headers=headers, cookies=None, impersonate='chrome120', 
            concurrency=concurrency, batch_size=batch_size, max_retries=max_retries
            )
        
        logging.info(f"   [Parser Engine - LinkedIn] Analyzing descriptions for fetched pages...")
        for job in job_list:
            if 'raw_html_desc' in job and job['raw_html_desc']:
                try:
                    html_content = job['raw_html_desc']

                    techs, exp, mode = parser.extract_data_from_linkedin_description(html_content, job['title'], tech_keywords)

                    job['technologies'] = techs
                    job['experience'] = exp
                    job['work_mode'] = mode
                    
                    del job['raw_html_desc']

                    if job['technologies']:
                        processed_jobs.append(job)

                except Exception as e:
                    logging.warning(f"   [Parser Error LinkedIn] Failed parsing text: {e}")

        return processed_jobs