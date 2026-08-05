import hashlib
import requests
import logging
import aiohttp
import asyncio
import random 

from curl_cffi.requests import AsyncSession
class BaseScraper:

    def create_job_blueprint(self):
    
        job_structure = {
            'id': None,              # Will hold the SHA-256 unique hash
            'title': "",             # Will hold the job title string
            'company': "",           # Will hold the company name string
            'location': "",          # Will hold the city / remote status
            'experience' : "",       # Will hold the experience level (Entry-level, Mid-level, Senior-level)
            'work_mode' : "",        # Will hold the work_mode (Remote, Hybrid, On-site)
            'link': "",              # Will hold the URL to the job application
            'technologies': []       # Will hold a list of required skills/tech
        }
        
        return job_structure


    def generate_job_id(self, title, company):
        
        combined_text = title + company
        hash_object = hashlib.sha256(combined_text.encode('utf-8'))
        return hash_object.hexdigest()

        
    def fetch_description_html_fast(self, url):

        headers = {
            'User-Agent' : 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language' : 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
            }

        try: 
            response = requests.get(url, headers = headers,  timeout = 20)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 429:
                logging.warning(f'[Rate Limit 429 - sync] Blocked on: {url}')
                return 'BLOCKED_429'
            else:
                logging.error(f'[HTTP Error] Status: {http_err}')
                return None
        except Exception as error:
            logging.error(f'[Request Error] Read timed out or network error: {error}')
            return None
        
    async def fetch_description_html_async(self, session, url, headers = None):
        
        if headers is None:
            headers = {
                'User-Agent' : 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language' : 'ro-RO,ro;q=0.9,en-US;q=0.8 ,en;q=0.7',
                }

        try:
            async with session.get(url, headers = headers ,timeout = 20) as response:
                if response.status == 429:
                    logging.warning(f'[Rate Limit 429 - async] Blocked on: {url}')
                    return 'BLOCKED_429'
                
                response.raise_for_status()

                return await response.text(encoding = 'utf-8')
        except aiohttp.ClientResponseError as http_error:
            logging.error(f'[HTTP Async Error] Status : {http_error.status} for URL: {url}')
            return None
        except Exception as error:
            logging.error(f'[Request Async Error] Network failure or timeout: {error}')
            return None
        
    async def fetch_description_html_curl(self, session, url, headers = None, cookies = None, impersonate = 'chrome'):
        try:
            response = await session.get(
                url, headers = headers, cookies = cookies,
                impersonate = impersonate, timeout = 20
            )

            if response.status_code == 429:
                logging.warning(f'[Rate Limit 429 - curl_cffi] Blocked on: {url}')
                return 'BLOCKED_429'

            response.raise_for_status()
            return response.text

        except Exception as error:
            logging.error(f'[curl_cffi Error] {error} for URL: {url}')
            return None

    async def fetch_all_descriptions_generic(self, job_list, headers=None, cookies=None, impersonate='chrome120', concurrency=5, batch_size=10, max_retries=0):
        if not job_list:
            return []
            
        pending_jobs = list(job_list)
        
        for attempt in range(max_retries + 1):
            if not pending_jobs:
                break
                
            if attempt > 0:
                cooldown = 15 * attempt
                logging.warning(f"   [Retry Round {attempt}] Re-attempting {len(pending_jobs)} jobs. Cooling down {cooldown}s...")
                await asyncio.sleep(cooldown)
                
            next_pending = []
            semaphore = asyncio.Semaphore(concurrency)
            
            async def worker(session, job):
                async with semaphore:
                    try:
                        html_desc = await self.fetch_description_html_curl(
                            session, job['link'], headers=headers, cookies=cookies, impersonate=impersonate
                        )
                        if html_desc and html_desc != 'BLOCKED_429':
                            job['raw_html_desc'] = html_desc
                        else:
                            next_pending.append(job)
                    except Exception as e:
                        logging.warning(f"   [Async Network Warning] Failed fetching for {job['link']}: {e}")
                        next_pending.append(job)
                    await asyncio.sleep(random.uniform(1.2, 2.5))
            
            for i in range(0, len(pending_jobs), batch_size):
                batch = pending_jobs[i:i + batch_size]
                pending_before = len(next_pending)
                
                async with AsyncSession() as session:
                    tasks = [worker(session, job) for job in batch]
                    await asyncio.gather(*tasks)
                
                batch_failed = len(next_pending) - pending_before
                if batch_failed >= max(3, len(batch)//2):
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(1.5)
            
            pending_jobs = next_pending
            
        if pending_jobs:
            logging.warning(f"   [Giving Up] {len(pending_jobs)}/{len(job_list)} job descriptions could never be downloaded after {max_retries + 1} attempts.")
            
        return job_list
     