# Logging
import logging
# Database
import sqlite3
# Scraping
from playwright.sync_api import sync_playwright
import requests
# Parsing
from bs4 import BeautifulSoup as bs
import json
# Misc
from typing import List
import time

# Configure the logger

logger = logging.getLogger("tyre_scrape_logger") 
logger.setLevel(logging.INFO)
logger.propagate = False # Prevent logs from propagating to the root logger (good practice incase something else sends logs)
handler = logging.FileHandler("tyres.log") # Add the file handler
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Configure the database

conn = sqlite3.connect("tyres.db")
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS tyres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_name TEXT,
    tyre_brand TEXT,
    tyre_pattern TEXT DEFAULT 'unknown',
    tyre_size TEXT,
    seasonality TEXT DEFAULT 'unknown',
    price TEXT
)
""")
conn.commit()
conn.close()

# Base scraper class

class TyreScraper:
    """
    Base class for the scrapers.
    """
    def __init__(self):
        self.website = "Unknown"
        self.last_request_time = None

    def fetch_html(self, url: str) -> bs: 
        """
        Fetch the HTML content of a page and parse it with beautiful soup.
        
        Args: The URL to fetch (url)
            
        Returns: Beautiful soup parsed html (soup)
        """

        response = requests.get(url)
        self.last_request_time = time.monotonic()
        response.raise_for_status() # Checks status 
        html = response.text 
        soup = bs(html, "html.parser")
        return soup
        
    def fetch_html_timed(self, url: str) -> bs:
        """
        Ensures requests are at least a second apart.
        
        Args: The URL to fetch (url)
            
        Returns: Beautiful soup parsed html (soup)
            
        Raises: A failed request error (RequestException)
        """
        try:
            if self.last_request_time:
                time_elapsed = time.monotonic() - self.last_request_time
                if time_elapsed <= 1:
                    time.sleep(1-time_elapsed) 
            soup = self.fetch_html(url)
            return soup
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch page {url}: {str(e)}")

    def add_to_database(self, brand, pattern, size, season, price):
        """
        Adds the tyre to the database (and logs that it has done that).
        
        Args: The brand, pattern, size, season, and price of the tyre (brand, pattern, size, season, price).
        """
        logger.info("Adding tyre to database:\n"
                f"Website name: {self.website}, Brand: {brand}, Pattern: {pattern}, "
                f"Size: {size}, Season: {season}, Cost: {price}") # Adds each tyre found for each garage even if they might be a repeat of the same tyre at a diff garage
        conn = sqlite3.connect("tyres.db") # Better to open this once per session and use a context manager rather than call it for each tyre
        cur = conn.cursor()
        cur.execute("INSERT INTO tyres (website_name, tyre_brand, tyre_pattern, tyre_size, seasonality, price)"
                    "VALUES (?, ?, ?, ?, ?, ?)", 
                    (self.website, brand, pattern, size, season.lower(), price))
        conn.commit()
        conn.close()

# Scrape Dexel

class DexelScraper(TyreScraper):
    """ Class to scrape Dexel's tyre info. """

    def __init__(self):
        super().__init__() # Nothing that isn't overwritten 
        self.website = "Dexel"
    
    def select_dropdown(self, page, dropdown: str, selection: str):
        """ 
        Uses javascript to select the dropdowns.

        Args: Dropdown to select (dropdown), value to select in dropdown (selection).
        """
        page.evaluate("""
            (args) => {
                const select = document.querySelector(args.selector);
                select.value = args.selection;
                select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, {"selector": dropdown, "selection": selection})


    def nav_to_branch_page(self, page, input_tuple: tuple[int, int, int]) -> tuple:
        """
        Creates a new session and navigates to the branch selection page.
        
        Args: Input tuple of width, aspect ratio, and rim size for tyre search (input_tuple)

        Returns: Page
        """
        width, aspect_ratio, rim_size = input_tuple

        page.goto("http://www.dexel.co.uk/")

        # Get to the tyre page
        page.get_by_role("link", name = "Search by Tyre Size.").click()
        page.wait_for_timeout(1000)
        # Trick it with javascript since clicking the divs/select doesn't work
        self.select_dropdown(page, 'select.width_list', f"{width}")
        page.wait_for_timeout(1000) 
        self.select_dropdown(page, 'select.profile_list', f"{aspect_ratio}")
        page.wait_for_timeout(1000) 
        self.select_dropdown(page, 'select.size_list', f"{rim_size}")
        page.wait_for_timeout(1000) 
        page.get_by_role("link", name = "Search ").nth(0).click()
        page.wait_for_timeout(1000) 

        return page

    def scrape_branch(self, page, branch_number_to_select: int, inputs: tuple) -> None:
        """
        Scrapes all pages for the selected branch and closes the browser.
        
        Args: Page playwright instance at branch select (page), browser playwright instance (browser), branch number to select (branch_number_to_select).
        """
        
        page.get_by_role("button", name = "Select This Branch").nth(branch_number_to_select).click() # Selects the branch
        page.wait_for_timeout(15000) # Wait a while for it to load

        pagination_div = page.locator('div.custom-pagination')

        while True:  # Loops through the pages

            html_individual_page = page.content() # Grabs the page content
            self.parse_html(html_individual_page)

            #logger.info("------------------------------------------------------------------------------------\nBreaking pagination, only scraped page 1")
            #break  # For testing purposes only scraping the first page, this break will be removed later

            if pagination_div.locator('a').count() == 0:
                logger.info(f"There is only one page for this tyre search {inputs}, it may be that there are no matching tyres.")
                break

            if 'Last' in pagination_div.locator('a').last.text_content().strip(): # If the 'Last >' button exists
                number_of_links = pagination_div.locator("a").count() # Count how many list items 
                next_page = pagination_div.locator("a").nth(number_of_links-2) # Identify the 2nd to last link (next page)
                next_page.click()
            elif pagination_div.locator("li").last.get_attribute('class') == 'active': # If we're on the last page, break out of the loop
                break
            else: # We're close to the end and the last button has disapeared
                pagination_div.locator("a").last.click() # Click the next page button (last link)

    def parse_html(self, html: str) -> None:
        """
        Parses HTML, submits each tyre to the database, and logs it.

        """
        soup = bs(html, "html.parser")

        individual_tyre_list = soup.select('div.tkf-product') # Select the divs for all the tyres

        for individual_tyre in individual_tyre_list: # Loop through each div (tyre)
            info_div = individual_tyre.select_one("div.detailArea.tf-title-tooltip-box")
            brand = info_div.select_one('input[name="brand"]').get("value").strip().capitalize()
            pattern = info_div.select_one('input[name="pattern"]').get("value").strip().capitalize()
            size = individual_tyre.select_one('p.para-text').get_text().strip().split()
            size = " ".join(size[0:2]) # Join the first 2 (the size)
            season = individual_tyre.select_one('div.tyre-icons i').get("title").strip().capitalize()
            price_json = individual_tyre.select_one('div.box').get("data-prices") # They appear to be doing some kind of sketchy price 'personalisation'
            parsed_price_json = json.loads(price_json)
            minimum_price = parsed_price_json.get("minimum_price").strip() # Pick the minimum price

            self.add_to_database(brand, pattern, size, season, minimum_price)

    def scrape(self, inputs: List[tuple[int, int, int]]) -> None:
        """
        Scrapes the whole site for tyres. Includes a new instance of each tyre even if it is the same price etc in another garage/branch.

        Args: List of size inputs in the format [[width, aspect ratio, rim size],...] (inputs)
        """
        
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless = False,slow_mo = 2000)

            # Temporary context just to count branches
            temp_context = browser.new_context()
            temp_page = temp_context.new_page()
            temp_page = self.nav_to_branch_page(temp_page, inputs[0])
            branch_count = len(temp_page.get_by_role("button", name="Select This Branch").all())
            temp_context.close()

            for branch in range(branch_count):
                logger.info(f"--------------------------------------------------------------------------\nScraping branch number {branch}")
                for input_tuple in inputs:
                    logger.info(f"--------------------------------------------------------------------------\nScraping new input {input_tuple}")
                    context = browser.new_context() # Resets the cookies so it doesn't remember the branch, better to move this into branch loop and change other logic
                    page = context.new_page() 
                    page = self.nav_to_branch_page(page, input_tuple)
                    self.scrape_branch(page, branch, input_tuple)
                    context.close()
            logger.info(f"Scraping complete.")
            browser.close() 

# Scrape bythjul

# Not currently working :(

# Scrape national

class NationalTyreExtractor(TyreScraper):
    """
    Class to extract tyre data from National's HTML.
    """
    def __init__(self):
        super().__init__()
        self.website = "National"
    
    def find_branch_postcodes(self) -> List[str]:
        """
        Finds the postcodes of each branch listed on the website (for use in the tyre search).
        
        Returns: A list of the postcodes (postcodes_list)
        """
        logger.info("Starting National postcode extraction.")

        branches_page_soup = self.fetch_html("https://www.national.co.uk/branches")
        branch_links = branches_page_soup.select('a[id*="hypBranchName"]') # Gets all a tags with 'hypBranchName' (instead of iterating through all 22 locations and all branches within them)
        list_of_branch_sites = [f"https://www.national.co.uk/{link['href']}" for link in branch_links]

        postcodes_list = []
        for branch_site in list_of_branch_sites:
            individual_branch_soup = self.fetch_html(branch_site)
            postcode = individual_branch_soup.find("span", itemprop="postalCode").text.strip()
            postcode = postcode.replace(" ", "") # Remove the space in the middle
            # logger.info(f"Postcode found: {postcode}")
            postcodes_list.append(postcode)

        logger.info(f"{len(postcodes_list)} postcodes extracted.")

        return list(set(postcodes_list)) # Just in case there are duplicate postcodes
    
    def extract_data(self, inputs: List[tuple[int, int, int]], postcodes: List[str]) -> None:
        """
        Extracts the requested data and adds it to the database.
        
        Args: Input tyre size parameters (width, aspect_ratio, rim_size) in list format (inputs)
        """
        
        for postcode in postcodes: 
            logger.info(f"-------------------------------------------------------------------------------------\nScraping postcode: {postcode}")
            for width, aspect_ratio, rim_size in inputs:
                logger.info(f"-------------------------------------------------------------------------------------\nScraping inputs: {width, aspect_ratio, rim_size}")
                url = f"https://www.national.co.uk/tyres-search/{width}-{aspect_ratio}-{rim_size}?pc={postcode}"
                tyre_soup = self.fetch_html(url)
                individual_tyre_list = tyre_soup.select('div[id*="TyreResults_rptTyres_divTyre_"]')

                for individual_tyre in individual_tyre_list:
                    brand = individual_tyre.get("data-brand").strip()
                    pattern = individual_tyre.select_one('a[id*="hypPattern"]')
                    size = pattern.find_parent("p").find_next_sibling("p") # Size always comes after the pattern
                    pattern = pattern.text.strip()
                    size = size.text.strip() # Leaving the V bit in as it is included in the size example (eg. 205/55 R16 91V)
                    season = individual_tyre.get("data-tyre-season").strip()
                    price = individual_tyre.get("data-price").strip()

                    self.add_to_database(brand, pattern, size, season, price) # Could also yield the data and then log it later
    
    def scrape(self, inputs: List) -> None:
        """
        Scrapes the whole site for tyres. Includes a new instance of each tyre even if it is the same price etc in another garage/branch.

        Args: List of size inputs in the format [[width, aspect ratio, rim size],...] (inputs)
        """
        postcodes = self.find_branch_postcodes()
        with open('postcodes.json', "w") as f:
                json.dump(postcodes, f)
        # with open('postcodes.json', "r") as f:
        #     postcodes = json.load(f)
    
        self.extract_data(inputs, postcodes)


inputs = [(205, 55, 16), (225, 50, 16), (185, 16, 14)]

# Run dexel tyre scraping
#dexel_tyre_scraper_instance = DexelScraper()
#dexel_tyre_scraper_instance.scrape(inputs)

# Run bythjul tyre scraping
# :( not yet

# Run national tyre scraping
national_tyre_scraper_instance = NationalTyreExtractor()
national_tyre_scraper_instance.scrape(inputs)

# Convert database to csv format
