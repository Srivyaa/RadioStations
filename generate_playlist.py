import requests
import os
import json
from time import sleep

# --- Configuration ---
# Your GitHub Repository Details
REPO_OWNER = "Srivyaa"
REPO_NAME = "RadioStations"
REPO_BRANCH = "main"
DATA_PATH = "data"
OUTPUT_FILENAME = "working_stations.m3u"
# Timeout (in seconds) for link validation.
LINK_CHECK_TIMEOUT = 10 
# Prefixes to ignore (case-sensitive)
EXCLUDED_PREFIXES = ("mp3", "samadada") 
# ---

def get_file_list(token=None):
    """
    Fetches the list of JSON files in the data directory and applies filters:
    1. Must be a .json file.
    2. Base name length must be > 3 characters.
    3. Base name must NOT start with any of the EXCLUDED_PREFIXES.
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{DATA_PATH}?ref={REPO_BRANCH}"
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    
    print(f"Fetching file list from: {url}")
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    all_files = response.json()
    
    json_files = []
    for file_info in all_files:
        if file_info.get('type') == 'file' and file_info.get('name', '').endswith('.json'):
            filename = file_info['name']
            
            # Extract the base name (filename without .json extension)
            basename = os.path.splitext(filename)[0] 
            
            # --- NEW & UPDATED FILTERING LOGIC ---
            
            # Filter 1: File name must have more than 3 characters (excluding .json)
            if len(basename) <= 3:
                # print(f"  -> Skipping {filename}: Name too short.")
                continue 
            
            # Filter 2: File name must NOT start with any excluded prefix
            if basename.startswith(EXCLUDED_PREFIXES):
                print(f"  -> Skipping {filename}: Starts with excluded prefix {basename[:len(EXCLUDED_PREFIXES[0])]}...")
                continue
            
            # --- END FILTERING LOGIC ---
            
            json_files.append(filename)
    
    return json_files

def fetch_json_content(filename):
    """Fetches the raw content of a single JSON file from the repository."""
    raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/{DATA_PATH}/{filename}"
    print(f"  -> Fetching content for {filename}")
    response = requests.get(raw_url)
    response.raise_for_status()
    return response.json()

def validate_stream_link(url):
    """Checks if a streaming URL is reachable using a small GET request."""
    try:
        r = requests.get(url, timeout=LINK_CHECK_TIMEOUT, stream=True, allow_redirects=True)
        r.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
        r.close()
        return True
            
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False

def generate_m3u_entry(station, filename):
    """Creates an M3U extended format entry (#EXTINF) from station data."""
    name = station.get('name', 'Unknown Name')
    url = station.get('url')
    # Use 'tags' or 'country' for group-title, falling back to the filename's basename
    group = station.get('tags', station.get('country', os.path.splitext(filename)[0])) 
    
    if not url:
        return None, None

    # Clean up group name for M3U format
    group_clean = group[0] if isinstance(group, list) else group
    group_clean = str(group_clean).replace(',', ';').replace('"', '').strip()

    # M3U Extended Format: #EXTINF:-1 group-title="Group Name",Station Name\nStation URL
    m3u_line = f'#EXTINF:-1 group-title="{group_clean}",{name}\n{url}'
    
    return m3u_line, url

def main():
    """Main function to generate the M3U playlist."""
    working_links_m3u = ['#EXTM3U']
    total_links_processed = 0
    working_links_count = 0
    
    try:
        # 1. Get filtered list of JSON files
        json_files = get_file_list()
        print(f"\nFound {len(json_files)} JSON files matching all criteria.")
        
        if not json_files:
            print("No files to process. Exiting.")
            return

        # 2. Process each file
        for filename in json_files:
            print(f"\nProcessing file: {filename}")
            try:
                stations = fetch_json_content(filename)
            except Exception as e:
                print(f"  !! Error fetching or parsing JSON for {filename}: {e}")
                continue

            if not isinstance(stations, list):
                print(f"  !! Expected a list of stations in {filename}. Skipping.")
                continue

            # 3. Validate links and generate M3U entries
            for station in stations:
                total_links_processed += 1
                m3u_entry, url = generate_m3u_entry(station, filename)
                
                if url:
                    if validate_stream_link(url):
                        working_links_m3u.append(m3u_entry)
                        working_links_count += 1
                        # print(f"    - SUCCESS: {station.get('name', 'Unknown')} ({url})")
                    # Delay to avoid hitting rate limits too quickly on streaming servers
                    sleep(0.1) 
                
        # 4. Write the final M3U playlist
        with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
            f.write('\n'.join(working_links_m3u))
            
        print(f"\n--- Validation Complete ---")
        print(f"Total links processed: {total_links_processed}")
        print(f"Working links found: {working_links_count}")
        print(f"Playlist created: **{OUTPUT_FILENAME}**")

    except requests.exceptions.RequestException as e:
        print(f"\n!! Fatal Error: Failed to communicate with GitHub API or an external resource: {e}")
    except Exception as e:
        print(f"\n!! An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
