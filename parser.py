import re
import logging

from bs4 import BeautifulSoup
from config import NEGATIVE_KEYWORDS
class JobParser:

    def __init__(self):
        self.compiled_patterns = {}

    def get_compiled_pattern(self, kw):
        if kw in self.compiled_patterns:
            return self.compiled_patterns[kw]

        kw_lower = kw.lower()
        special_patterns = {
            '.net': r'(\bdotnet\b|\.net)',
            'c#': r'(?:c\s*#|c-sharp)',
            'c++': r'c\s*\+\+',
            'ci/cd': r'(?:ci/cd|ci-cd)',
            'asp.net': r'asp\.net'
        }

        if kw_lower in special_patterns:
            pattern = special_patterns[kw_lower]
        elif re.match(r'^[a-zA-Z0-9]+$', kw_lower):
            pattern = r'\b' + re.escape(kw_lower) + r'\b'
        else:
            pattern = r'(?<![a-zA-Z0-9])' + re.escape(kw_lower) + r'(?![a-zA-Z0-9])'

        compiled = re.compile(pattern)
        self.compiled_patterns[kw] = compiled 

        return compiled

    def parse_location(self, location_text):

        if not location_text:
            return 'N/A', 'On-site'
        
        loc_lower = location_text.lower()

        experience_keywords = ['junior', 'middle', 'senior', 'entry', 'executive', 'ani', 'experien']
        if any(exp_kw in loc_lower for exp_kw in experience_keywords):
            return 'Unknown', 'On-site'

        if 'remote' in loc_lower:
            work_mode = 'Remote'
        elif 'hybrid' in loc_lower or 'hibrid' in loc_lower:
            work_mode = 'Hybrid'
        else:
            work_mode = 'On-site'

        clean_city = location_text
        words_to_remove = ['remote', 'Remote', 'hybrid', 'Hybrid', 'hibrid', 'Hibrid', '(', ')', ',']

        for word in words_to_remove:
            clean_city = clean_city.replace(word, '')

        clean_city = clean_city.strip().strip(',').strip()

        if not clean_city or 'acas' in clean_city.lower():
            clean_city = 'All' if work_mode == 'Remote' else 'N/A'

        return clean_city, work_mode

    def is_non_it_job(self, title_text):

        if not title_text:
            return True

        title_lower = title_text.lower()

        for neg in NEGATIVE_KEYWORDS:
            pattern = r'\b' + re.escape(neg) + r'\b'
            if re.search(pattern, title_lower):
                return True

        return False

    def find_tech_in_text(self, text, tech_keywords):

        found = []
        text_lower = text.lower()

        for kw in tech_keywords:
            pattern = self.get_compiled_pattern(kw)
            if pattern.search(text_lower):
                found.append(kw)

        return found

    def extract_data_from_description(self, job_url, tech_keywords, fetch_func):

        job_html = fetch_func(job_url)

        if job_html == None: return [], 'Unknown', 'Unknown'

        soup = BeautifulSoup(job_html, 'html.parser')

        description_container = soup.find('div' , class_ = 'jobs-show-main-description__section')
        
        if description_container:
            full_text = description_container.get_text(separator=' ',strip = True).lower()
        else:
            description_container = soup.find('main') or soup.find('body')
            full_text = description_container.get_text(separator=' ',strip = True).lower() if description_container else ""

        experience_tags = soup.find_all('a' , class_ = 'jobs-show-main-summaries__summary-link')

        experience_text = 'Unknown'
        work_mode_text = 'On-site'

        if experience_tags:
            for tag in experience_tags:
                text_clean = tag.get_text(strip = True).strip(', ')
                text_lower = text_clean.lower()

                if 'level' in text_lower or 'ani' in text_lower or 'experien' in text_lower:
                    experience_text = text_clean
                    continue

                if 'remote' in text_lower:
                    work_mode_text = 'Remote'
                elif 'hibrid' in text_lower or 'hybrid' in text_lower:
                    work_mode_text = 'Hybrid'

        valid_experience_levels = {
            'Entry-Level (< 2 ani)',
            'Mid-Level (2-5 ani)',
            'Senior-Level (> 5 ani)'
        }
        if experience_text == 'Fără experiență':
            experience_text = 'Entry-Level (< 2 ani)'
        elif experience_text not in valid_experience_levels:
            experience_text = 'Unknown'

        found_tech = self.find_tech_in_text(full_text, tech_keywords)
            
        return found_tech , experience_text, work_mode_text
    
    def extract_data_from_bestjobs_description(self, job_url, tech_keywords, fetch_func):

        job_html = fetch_func(job_url)

        if job_html is None:
            return [], 'Unknown', 'Unknown', 'Unknown'
        
        soup = BeautifulSoup(job_html, 'html.parser')
        description_container = soup.find('div' , class_ = 'job-description')
        
        if description_container:
            full_text = description_container.get_text(separator=' ',strip = True).lower()
        else:
            body_container = soup.find('body')
            full_text = body_container.get_text(strip = True).lower() if body_container else ""

        work_mode_text = 'On-site'
        location_text = 'Unknown'
        experience_text = 'Unknown'

        detail_blocks = soup.find_all('div', class_ = 'flex-1 text-left')
        for block in detail_blocks:
            block_text = block.get_text(strip = True).lower()

            remote_span = block.find('span', class_ = 'font-bold')
            if remote_span and 'remote' in remote_span.get_text(strip = True).lower():
                work_mode_text = 'Remote'
                location_text = 'Remote'
                continue
            
            if 'hibrid' in block_text or 'hybrid' in block_text:
                work_mode_text = "Hybrid"

            location_link = block.find('a', class_ = 'hover:text-ink')
            if location_link:
                location_text = location_link.get_text(strip = True)

        experience_containers = soup.find_all('div', class_ = 'ml-2')
        for container in experience_containers:
            parent = container.find_parent('div', class_ = 'flex')
            if parent:
                experience_link = container.find('a', class_ = 'hover:text-ink')
                if experience_link:
                    raw_exp = experience_link.get_text(strip = True).lower()
                    if 'entry' in raw_exp or '0-2' in raw_exp or 'fără' in raw_exp:
                        experience_text = 'Entry-Level (< 2 ani)'
                        break
                    elif 'mid' in raw_exp or '2-5' in raw_exp or 'middle' in raw_exp:
                        experience_text = 'Mid-Level (2-5 ani)'
                        break
                    elif 'senior' in raw_exp or '5-10' in raw_exp:
                        experience_text = 'Senior-Level (> 5 ani)'
                        break
        
        if experience_text == 'Unknown':
            if 'senior' in full_text or 'lead' in full_text or 'principal' in full_text:
                experience_text = 'Senior-Level (> 5 ani)'
            elif 'mid' in full_text:
                experience_text = 'Mid-Level (2-5 ani)'
            elif 'junior' in full_text or 'entry' in full_text or 'fără experiență' in full_text:
                experience_text = 'Entry-Level (< 2 ani)'

        found_tech = self.find_tech_in_text(full_text, tech_keywords)
        
        return found_tech, experience_text, work_mode_text, location_text

    def extract_data_from_linkedin_description(self, html_content, title, tech_keywords):

        if not html_content:
            return [], 'Unknown', 'Unknown'

        soup = BeautifulSoup(html_content, 'html.parser')
        desc_container = soup.find('div', class_= 'description__text') or soup.find('section', class_='show-more-less-html')
        full_text = desc_container.get_text(separator=' ', strip=True).lower() if desc_container else soup.get_text().lower()

        found_tech = self.find_tech_in_text(full_text, tech_keywords)
        
        work_mode = 'Remote' if 'remote' in full_text else ('Hybrid' if 'hibrid' in full_text or 'hybrid' in full_text else 'On-site')

        experience = 'Unknown'
        title_lower = title.lower()
        
        if any(word in title_lower for word in ['senior', 'lead', 'principal', 'head', 'architect', 'manager', 'director']):
            experience = 'Senior-Level (> 5 ani)'
        elif any(word in title_lower for word in ['junior', 'trainee', 'intern', 'entry', 'graduate', 'începător']):
            experience = 'Entry-Level (< 2 ani)'
        elif any(word in title_lower for word in ['mid', 'middle']):
            experience = 'Mid-Level (2-5 ani)'
        else:
            criteria_list = soup.find_all('ul', class_= 'description__job-criteria-list')
            if criteria_list:
                first_criteria = criteria_list[0].find('li', class_='description__job-criteria-item')
                if first_criteria: 
                    exp_span = first_criteria.find('span', class_='description__job-criteria-text--criteria')
                    if exp_span:
                        exp_text = exp_span.get_text(strip=True).lower()

                        if 'începător' in exp_text or 'entry' in exp_text or 'intern' in exp_text or 'stagiar' in exp_text:
                            experience = 'Entry-Level (< 2 ani)'
                        elif 'superior' in exp_text or 'director' in exp_text or 'executive' in exp_text:
                            experience = 'Senior-Level (> 5 ani)'
                        elif 'mediu' in exp_text or 'mid' in exp_text or 'associate' in exp_text:
                            experience = 'Mid-Level (2-5 ani)'

        return found_tech, experience, work_mode
