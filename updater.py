import json
import requests
from bs4 import BeautifulSoup
import sys

URL = "https://everything.moe/"
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

    removed_sites = set()

    for entry in changelog.find_all(['div', 'li', 'p']):
        text = entry.get_text().lower()
        if 'removed' in text or 'dead' in text:
            site_tag = entry.find('a')
            if site_tag:
                removed_sites.add(site_tag.get_text().strip().lower())

    if not removed_sites:
        print("No removed sites found in the changelog.")
        sys.exit(0)

    print(f"Found removed sites: {removed_sites}")

    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            marketplace_data = json.load(f)
    except FileNotFoundError:
        print(f"{JSON_FILE} not found.")
        sys.exit(1)

    original_count = len(marketplace_data)
    updated_data = [
        item for item in marketplace_data
        if item.get('name', '').lower() not in removed_sites
    ]

    if len(updated_data) != original_count:
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(updated_data, f, indent=4)
        print(f"Success! Removed {original_count - len(updated_data)} items from marketplace.json.")
    else:
        print("No matches found. marketplace.json is already up to date.")

if __name__ == "__main__":
    main()
