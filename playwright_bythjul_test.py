# Trying to access bythjul's tyres, doesn't work

from patchright.sync_api import sync_playwright
import os 
from dotenv import load_dotenv
import json

load_dotenv() # Load the .env file with environmental variables
USERNAME = os.environ.get("USERNAME_API") 
PASSWORD = os.environ.get("PASSWORD_API") 

proxies = {
    "server": "brd.superproxy.io:33335",
    "username": f"{USERNAME}",
    "password": f"{PASSWORD}",
}

with sync_playwright() as pw:

    browser = pw.chromium.launch(
        headless = False,
        slow_mo = 5000, # Doesn't work when I remove this
        proxy = proxies,
    )

    context = browser.new_context(ignore_https_errors=True, 
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                  viewport={"width": 1920, "height": 1080},
                                  device_scale_factor=1,
                                  is_mobile=False,
                                  has_touch=False,
                                  locale="en-US",
                                  timezone_id="America/New_York",
                                  geolocation={"latitude": 40.7128, "longitude": -74.0060},
                                  permissions=["geolocation"],

                                  ) # To remove the https error block

    page = context.new_page()
    #page.goto("https://www.bythjul.com/sok/storlek/dack/2,2/DV/205-55-16") # replace this directly with the other sizes to search, also by season
    page.goto("https://www.bythjul.com/sok/storlek/dack/2,2/DV/205-55-16#!price=568.125,1539") # replace this directly with the other sizes to search, also by season
    page.wait_for_timeout(10000)

    print("Navigated to the first page")

    while page.get_by_text('Flera').is_visible(): # No pagination, we just need to make sure we have clicked the show more button
        print("See more button visible: clicking!")
        page.get_by_text('Flera').click() # Could also do locator'a.more-button'
        page.wait_for_timeout(5000)

    print("Can't see any more see more button, moving onto the tyre data")

    tyres_on_page = page.locator('div.product-item-tyre').all()

    for tyre in tyres_on_page: # Loop through each tyre, opening its page to get the schema (for more robust variables to scrape)
        title_div = tyre.locator('div.title') # There are multiple links so we need to isolate one, could do this with one line
        product_link = title_div.locator('a') # Just with this line and nth(0), but I think this is prob more robust to changes
        href = product_link.get_attribute('href')
        p = browser.new_page(base_url = "https://www.bythjul.com/")
        if href is not None:
            p.goto(href)
        else:
            p.close()
        
        # Get product details (mostly from json schema on each page)
        product_details_section = p.locator('div[data-component="ProductDetails"]')
        tyre_info = product_details_section.locator("script[type='application/ld+json']").text_content() 
        json_data = json.loads(tyre_info)
        brand = json_data['brand']
        pattern = json_data['model'] # I assume this is the same thing as the pattern
        season = json_data['inProductGroupWithID'] # It is in ?Swedish? though
        if season == 'Vinterdäck': # Convert to English
            season = 'Winter'
        elif season == 'Sommardäck':
            season = 'Summer'
        price_in_sek = json_data['price']
        price_in_gbp = price_in_sek * 0.081
        # Size isn't in the schema we'll so get this from the table
        table = product_details_section.locator("table")
        table_label = table.locator("th", has_text = 'Storlek')
        table_value = table.locator("tr").filter(has = table_label)
        size = table_value.locator('td').text_content()

        print("Printing:\n"
                f"Webite name: bythjul, Brand: {brand}, Pattern: {pattern}, "
                f"Size: {size}, Season: {season}, Cost: {price_in_gbp}") 
                #self.add_to_database(brand, pattern, size, season, minimum_price)
        print("First tyre added! Breaking out of loop.")

        p.close()

        break


    print(page.title())
    #age.screenshot(path="example.png")

    browser.close()