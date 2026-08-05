import os

# ==========================================
# Database Configuration
# ==========================================
DB_NAME = os.getenv('DB_NAME', 'jobs.db')

# ==========================================
# Global Network Settings
# ==========================================
FETCH_TIMEOUT = 20
IMPERSONATE_BROWSER = 'chrome120'
SELENIUM_WAIT_TIMEOUT = 10

# ==========================================
# Platform-Specific Scraping Settings
# ==========================================
# eJobs (kept lower to strictly avoid 429 rate limit blocks)
EJOBS_CONCURRENCY = 1
EJOBS_BATCH_SIZE = 3
EJOBS_MAX_RETRIES = 1

# BestJobs
BESTJOBS_CONCURRENCY = 5
BESTJOBS_BATCH_SIZE = 15
BESTJOBS_MAX_RETRIES = 1

# LinkedIn (kept lower to strictly avoid 429 rate limit blocks)
LINKEDIN_CONCURRENCY = 2
LINKEDIN_BATCH_SIZE = 5
LINKEDIN_MAX_RETRIES = 1