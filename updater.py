import json
import requests
import sys
import re
import html
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from email.utils import parsedate_to_datetime

CHANGELOG_RSS_URL = "https://static.everythingmoe.com/feeds/changelog.xml"

JSON_FILE = "marketplace.json"
BACKUP_FILE = "marketplace.json.bak"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

REMOVE_RE = re.compile(
    r"\b(?:removed|remove)\s*(?:>|:|-|–|—|→|›)?\s*(?P<name>[^,\n\r#<]+)",
    re.IGNORECASE,
)

RE_ADD_RE = re.compile(
    r"\b(?:re-add|readd|restored|re-added)\s*(?:>|:|-|–|—|→|›)?\s*(?P<name>[^,\n\r#<]+)",
    re.IGNORECASE,
)

ADD_RE = re.compile(
    r"\b(?:added|add)\s*(?:>|:|-|–|—|→|›)?\s*(?P<name>[^,\n\r#<]+)",
    re.IGNORECASE,
)

TRAILING_TAGS_RE = re.compile(
    r"\s+\b("
    r"MULT|DDL|LOGIN|HUB|KOTO|MANGA|MANHWA|MANHUA|NOVEL|LN|VN|H|APP|APPS|"
    r"FORUM|ROM|TOKUSATSU|VOCALOID|CHAR|DOUJIN|UNIVERSAL"
    r")\b.*$",
    re.IGNORECASE,
)


def strip_html(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_name(value):
    value = strip_html(value)
    value = value.casefold()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = TRAILING_TAGS_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[^a-z0-9]+", "", value)


def clean_event_name(value):
    value = strip_html(value)

    value = re.split(
        r"\s+\b("
        r"anime|manga|manhwa|manhua|novel|light novel|streaming|reading|site|website|app|"
        r"tool|database|download|music|drama|game|games"
        r")\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    value = value.strip(" -–—>|:,.#\t\r\n")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def get_child_text(parent, names):
    wanted = {name.casefold() for name in names}

    for child in list(parent):
        tag = child.tag.split("}", 1)[-1].casefold()
        if tag in wanted:
            return child.text or ""

    return ""


def fetch_text(url):
    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Failed to reach {url} - Status: {response.status_code}")

    return response.text


def parse_feed_items(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        preview = xml_text[:500].replace("\n", " ")
        raise RuntimeError(f"RSS response was not valid XML. Preview: {preview}") from exc

    items = []

    for node in root.iter():
        tag = node.tag.split("}", 1)[-1].casefold()

        if tag not in {"item", "entry"}:
            continue

        title = strip_html(get_child_text(node, ["title"]))
        description = strip_html(get_child_text(node, ["description", "summary", "content"]))
        link = strip_html(get_child_text(node, ["link"]))
        pub_date_raw = strip_html(get_child_text(node, ["pubDate", "published", "updated"]))

        pub_date = None
        if pub_date_raw:
            try:
                pub_date = parsedate_to_datetime(pub_date_raw)
            except Exception:
                pub_date = None

        text = f"{title} {description}".strip()

        if text:
            items.append(
                {
                    "title": title,
                    "description": description,
                    "link": link,
                    "pub_date": pub_date,
                    "text": text,
                }
            )

    return items


def extract_event_action(entry_text):
    match = RE_ADD_RE.search(entry_text)
    if match:
        return "active", clean_event_name(match.group("name"))

    match = REMOVE_RE.search(entry_text)
    if match:
        return "removed", clean_event_name(match.group("name"))

    match = ADD_RE.search(entry_text)
    if match:
        return "active", clean_event_name(match.group("name"))

    return None, None


def build_latest_status_map(feed_items):
    events = []

    for index, item in enumerate(feed_items):
        action, name = extract_event_action(item["text"])

        if not action or not name:
            continue

        normalized = normalize_name(name)

        if not normalized:
            continue

        events.append(
            {
                "index": index,
                "action": action,
                "name": name,
                "normalized": normalized,
                "pub_date": item["pub_date"],
                "title": item["title"],
                "link": item["link"],
            }
        )

    def sort_key(event):
        if event["pub_date"]:
            return (1, event["pub_date"].timestamp() * -1)
        return (0, event["index"])

    events.sort(key=sort_key)

    latest = {}

    for event in events:
        if event["normalized"] not in latest:
            latest[event["normalized"]] = event

    return latest, events


def marketplace_aliases(item):
    aliases = set()

    for key in ("name", "title", "id", "site"):
        value = item.get(key)

        if isinstance(value, str) and value.strip():
            aliases.add(value.strip())

    name = item.get("name", "")

    if isinstance(name, str):
        cleaned = TRAILING_TAGS_RE.sub("", name).strip()
        cleaned = re.sub(r"\([^)]*\)", "", cleaned).strip()
        if cleaned:
            aliases.add(cleaned)

    return {normalize_name(alias) for alias in aliases if normalize_name(alias)}


def main():
    json_path = Path(JSON_FILE)

    print(f"Requesting changelog RSS from {CHANGELOG_RSS_URL}...")

    try:
        rss_text = fetch_text(CHANGELOG_RSS_URL)
    except Exception as exc:
        print(f"Failed to fetch EverythingMoe changelog RSS: {exc}")
        sys.exit(1)

    try:
        feed_items = parse_feed_items(rss_text)
    except Exception as exc:
        print(f"Failed to parse EverythingMoe changelog RSS: {exc}")
        sys.exit(1)

    if not feed_items:
        print("No changelog items were found in the RSS feed.")
        sys.exit(1)

    latest_status, all_events = build_latest_status_map(feed_items)

    if not all_events:
        print("RSS loaded, but no add/remove/re-add changelog events were found.")
        sys.exit(1)

    print(f"Loaded {len(feed_items)} RSS entries.")
    print(f"Detected {len(all_events)} add/remove/re-add events.")

    try:
        with json_path.open("r", encoding="utf-8") as f:
            marketplace_data = json.load(f)
    except FileNotFoundError:
        print(f"{JSON_FILE} not found.")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"{JSON_FILE} is not valid JSON: {exc}")
        sys.exit(1)

    if not isinstance(marketplace_data, list):
        print(f"{JSON_FILE} must contain a JSON array/list.")
        sys.exit(1)

    original_count = len(marketplace_data)
    updated_data = []
    removed_sites_found = []

    print("Analyzing marketplace entries against latest EverythingMoe status...")

    for item in marketplace_data:
        if not isinstance(item, dict):
            updated_data.append(item)
            continue

        aliases = marketplace_aliases(item)

        if not aliases:
            updated_data.append(item)
            continue

        matched_event = None

        for alias in aliases:
            event = latest_status.get(alias)

            if event:
                matched_event = event
                break

        if matched_event and matched_event["action"] == "removed":
            removed_sites_found.append(
                {
                    "marketplace_name": item.get("name", "Unknown"),
                    "event_name": matched_event["name"],
                    "event_title": matched_event["title"],
                    "event_link": matched_event["link"],
                }
            )
        else:
            updated_data.append(item)

    if removed_sites_found:
        shutil.copyfile(json_path, BACKUP_FILE)

        with json_path.open("w", encoding="utf-8") as f:
            json.dump(updated_data, f, indent=4, ensure_ascii=False)

        print("")
        print("Found and removed dead sites:")

        for site in removed_sites_found:
            print(f"- {site['marketplace_name']} -> {site['event_title']}")

        print("")
        print(f"Backup saved as {BACKUP_FILE}")
        print(f"Success! Purged {original_count - len(updated_data)} blocks from {JSON_FILE}.")
    else:
        print("Sync clean. No latest removal indicators match items inside your marketplace data.")


if __name__ == "__main__":
    main()
