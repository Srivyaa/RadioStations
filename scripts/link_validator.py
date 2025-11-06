#!/usr/bin/env python3
"""
Radio Station Link Validator Script
Reads JSON files from data folder, validates stream URLs, and moves broken entries to separate files.
"""

import json
import os
import requests
import logging
from urllib.parse import urlparse
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# Configuration
CONFIG = {
    'data_folder': 'data',
    'broken_links_folder': 'broken_links',
    'timeout': 15,  # Increased for audio streams
    'max_workers': 3,  # Reduced to avoid overwhelming servers
    'retry_attempts': 2,
    'retry_delay': 2,
    'user_agent': 'Mozilla/5.0 (compatible; RadioStreamValidator/1.0)',
    'stream_check_method': 'head'  # 'head' or 'get' - head is faster but may not work for all streams
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('link_validation.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class RadioStationValidator:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': config['user_agent']})
        self.broken_entries = []
        self.valid_entries = []
        self.validated_count = 0
        
        # Create folders if they don't exist
        os.makedirs(config['data_folder'], exist_ok=True)
        os.makedirs(config['broken_links_folder'], exist_ok=True)
    
    def is_valid_url(self, url):
        """Check if URL has valid format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def check_stream_url(self, url, entry, source_file):
        """Check if a stream URL is accessible with retries"""
        if not self.is_valid_url(url):
            return {
                'entry': entry,
                'source_file': source_file,
                'status': 'INVALID_URL',
                'error': 'Invalid URL format'
            }
        
        for attempt in range(self.config['retry_attempts']):
            try:
                # For audio streams, we try HEAD first, then GET if needed
                if self.config['stream_check_method'] == 'head':
                    response = self.session.head(
                        url, 
                        timeout=self.config['timeout'],
                        allow_redirects=True
                    )
                else:
                    # Some streams don't support HEAD, so we try GET with range
                    headers = {'Range': 'bytes=0-1'}  # Just get first few bytes
                    response = self.session.get(
                        url,
                        headers=headers,
                        timeout=self.config['timeout'],
                        allow_redirects=True,
                        stream=True
                    )
                
                # Check if it's a successful response
                if response.status_code < 400:
                    # Additional check for audio streams - look for audio content type
                    content_type = response.headers.get('content-type', '').lower()
                    if any(audio_type in content_type for audio_type in ['audio', 'stream', 'mpeg']):
                        return {
                            'entry': entry,
                            'source_file': source_file,
                            'status': 'VALID',
                            'status_code': response.status_code,
                            'content_type': content_type
                        }
                    else:
                        # Still valid but might not be audio
                        return {
                            'entry': entry,
                            'source_file': source_file,
                            'status': 'VALID',
                            'status_code': response.status_code,
                            'content_type': content_type,
                            'warning': 'Non-audio content type'
                        }
                else:
                    return {
                        'entry': entry,
                        'source_file': source_file,
                        'status': 'BROKEN',
                        'status_code': response.status_code,
                        'error': f'HTTP {response.status_code}'
                    }
                    
            except requests.exceptions.RequestException as e:
                if attempt < self.config['retry_attempts'] - 1:
                    time.sleep(self.config['retry_delay'])
                else:
                    return {
                        'entry': entry,
                        'source_file': source_file,
                        'status': 'BROKEN',
                        'error': str(e)
                    }
    
    def read_json_files(self):
        """Read all JSON files from data folder"""
        json_files = []
        
        for filename in os.listdir(self.config['data_folder']):
            if filename.endswith('.json'):
                file_path = os.path.join(self.config['data_folder'], filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    # Handle both array of objects and single object
                    if isinstance(data, list):
                        entries = data
                    elif isinstance(data, dict):
                        entries = [data]
                    else:
                        logging.warning(f"Unexpected JSON format in {filename}")
                        continue
                        
                    json_files.append({
                        'filename': filename,
                        'path': file_path,
                        'entries': entries
                    })
                    logging.info(f"Loaded {len(entries)} entries from {filename}")
                    
                except Exception as e:
                    logging.error(f"Error reading {filename}: {e}")
        
        return json_files
    
    def validate_all_entries(self):
        """Validate all stream URLs from all JSON files"""
        json_files = self.read_json_files()
        all_entries_to_check = []
        
        # Extract all entries with their URLs
        for json_file in json_files:
            for entry in json_file['entries']:
                # Check both url and url_resolved fields
                stream_url = entry.get('url_resolved') or entry.get('url')
                if stream_url and self.is_valid_url(stream_url):
                    all_entries_to_check.append({
                        'entry': entry,
                        'stream_url': stream_url,
                        'source_file': json_file['filename']
                    })
                else:
                    logging.warning(f"No valid stream URL found in entry: {entry.get('name', 'Unknown')}")
        
        # Validate entries concurrently
        logging.info(f"Validating {len(all_entries_to_check)} stream URLs with {self.config['max_workers']} workers...")
        
        with ThreadPoolExecutor(max_workers=self.config['max_workers']) as executor:
            future_to_entry = {
                executor.submit(
                    self.check_stream_url, 
                    item['stream_url'], 
                    item['entry'], 
                    item['source_file']
                ): item 
                for item in all_entries_to_check
            }
            
            for future in as_completed(future_to_entry):
                result = future.result()
                self.validated_count += 1
                
                if result['status'] == 'BROKEN':
                    self.broken_entries.append(result)
                    logging.warning(f"BROKEN: {result['entry'].get('name', 'Unknown')} - {result['stream_url']} - {result.get('error', 'Unknown error')}")
                else:
                    self.valid_entries.append(result)
                    logging.info(f"VALID: {result['entry'].get('name', 'Unknown')} - {result['stream_url']}")
        
        logging.info(f"Validation complete. {len(self.broken_entries)} broken streams found out of {self.validated_count} checked.")
    
    def update_data_files(self):
        """Update original JSON files by removing broken entries"""
        json_files = self.read_json_files()
        
        for json_file in json_files:
            filename = json_file['filename']
            original_entries = json_file['entries']
            
            # Get valid entries for this file
            valid_entries_for_file = [
                result['entry'] for result in self.valid_entries 
                if result['source_file'] == filename
            ]
            
            # Remove duplicates by stationuuid
            seen_uuids = set()
            unique_valid_entries = []
            for entry in valid_entries_for_file:
                uuid = entry.get('stationuuid')
                if uuid and uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    unique_valid_entries.append(entry)
                elif not uuid:
                    unique_valid_entries.append(entry)
            
            # Write back only valid entries
            file_path = os.path.join(self.config['data_folder'], filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                if len(unique_valid_entries) == 1:
                    json.dump(unique_valid_entries[0], f, indent=4, ensure_ascii=False)
                else:
                    json.dump(unique_valid_entries, f, indent=4, ensure_ascii=False)
            
            removed_count = len(original_entries) - len(unique_valid_entries)
            logging.info(f"Updated {filename}: {len(unique_valid_entries)} valid entries, {removed_count} removed")
    
    def save_broken_entries(self):
        """Save broken entries to timestamped JSON files grouped by source file"""
        if not self.broken_entries:
            logging.info("No broken entries to save.")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Group broken entries by source file
        broken_by_file = {}
        for broken in self.broken_entries:
            source_file = broken['source_file']
            if source_file not in broken_by_file:
                broken_by_file[source_file] = []
            broken_by_file[source_file].append(broken)
        
        # Save separate files for each source
        for source_file, broken_list in broken_by_file.items():
            # Create filename without extension for the broken entries file
            base_name = os.path.splitext(source_file)[0]
            broken_filename = f"{base_name}_broken_{timestamp}.json"
            broken_file_path = os.path.join(self.config['broken_links_folder'], broken_filename)
            
            # Extract just the entry objects
            broken_entries_only = [broken['entry'] for broken in broken_list]
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'source_file': source_file,
                'broken_entries_count': len(broken_entries_only),
                'broken_entries': broken_entries_only
            }
            
            with open(broken_file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=4, ensure_ascii=False)
            
            logging.info(f"Broken entries from {source_file} saved to: {broken_filename}")
        
        # Also create a consolidated report
        consolidated_filename = f"all_broken_entries_{timestamp}.json"
        consolidated_path = os.path.join(self.config['broken_links_folder'], consolidated_filename)
        
        all_broken_entries = [broken['entry'] for broken in self.broken_entries]
        consolidated_report = {
            'timestamp': datetime.now().isoformat(),
            'total_broken_entries': len(all_broken_entries),
            'broken_entries_by_file': broken_by_file,
            'all_broken_entries': all_broken_entries
        }
        
        with open(consolidated_path, 'w', encoding='utf-8') as f:
            json.dump(consolidated_report, f, indent=4, ensure_ascii=False)
        
        # Update latest file
        latest_file = os.path.join(self.config['broken_links_folder'], "broken_entries_latest.json")
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(consolidated_report, f, indent=4, ensure_ascii=False)
        
        logging.info(f"Consolidated broken entries saved to: {consolidated_filename}")
    
    def run(self):
        """Main execution method"""
        logging.info("Starting radio station stream validation...")
        start_time = time.time()
        
        try:
            self.validate_all_entries()
            self.update_data_files()
            self.save_broken_entries()
            
            elapsed_time = time.time() - start_time
            logging.info(f"Validation completed in {elapsed_time:.2f} seconds")
            logging.info(f"Summary: {self.validated_count} streams checked, {len(self.broken_entries)} broken, {len(self.valid_entries)} valid")
            
        except Exception as e:
            logging.error(f"Error during validation: {e}")
            raise

def main():
    """Main function"""
    validator = RadioStationValidator(CONFIG)
    validator.run()

if __name__ == "__main__":
    main()
