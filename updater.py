import json
import requests
from bs4 import BeautifulSoup
import sys
import re

URL = "https://everythingmoe.com/activity.html"
JSON_FILE = "marketplace.json"

def main():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(URL, headers=headers)

    if response.status_code != 200:
        print(f"Failed to fetch {URL} - Status: {response.status_code}")
        sys.exit(1)

    soup = BeautifulSoup(response.text, 'html.parser')
    changelog = soup.find('div', id='changelog-cont')

    if not changelog:
        print("Could not find <div id='changelog-cont'> on the page.")
        sys.exit(1)

    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            marketplace_data = json.load(f)
    except FileNotFoundError:
        print(f"{JSON_FILE} not found.")
        sys.exit(1)

    changelog_text = changelog.get_text(separator=' ').lower()

    original_count = len(marketplace_data)
    updated_data = []
    removed_sites_found = []

    for item in marketplace_data:
        site_name = item.get('src', item.get('name', '')).strip().lower()

        if not site_name:
            updated_data.append(item)
            continue

        pattern = rf"removed\s*>\s*{re.escape(site_name)}"

        if re.search(pattern, changelog_text):
            removed_sites_found.append(site_name)
        else:
            updated_data.append(item)

    if removed_sites_found:
        print(f"Found and removed dead sites: {', '.join(removed_sites_found)}")
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=4)
        print(f"Success! Removed {original_count - len(updated_data)} items from marketplace.json.")
    else:
        print("No removed sites found in the changelog that match marketplace.json.")

if __name__ == "__main__":
    main()
