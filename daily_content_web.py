import sys
import subprocess

def ensure_dependencies():
    """Ensure all required dependencies are installed and available."""
    required_packages = ["pandas", "requests", "openpyxl", "flask", "flask-cors"]
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

ensure_dependencies()

import os
import time
import json
import random
import threading
import webbrowser
import pandas as pd
from datetime import datetime, timezone, timedelta
import requests
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Initialize Flask app
# Support running either from parent directory or inside the web_static folder
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(script_dir) == "web_static":
    static_dir = "."
    parent_dir = os.path.dirname(script_dir)
else:
    static_dir = "web_static"
    parent_dir = script_dir

app = Flask(__name__, static_folder=static_dir)
CORS(app)

USER_AGENTS = [
    'windows:cinenuggets.viralscraper:v1.0.0 (by /u/cinenuggets)',
    'mac:cinenuggets.viralscraper:v1.0.0 (by /u/cinenuggets)',
    'linux:cinenuggets.viralscraper:v1.0.0 (by /u/cinenuggets)',
    'windows:reddit.viralcontentexplorer:v1.2.0 (by /u/reddit_explorer)',
    'python:dailycontentdownloader:v2.0.1 (by /u/daily_downloader)',
    'windows:dailycontentwebscraper:v1.1.0 (by /u/content_scraper)',
    'mac:reddit.viralcontentexplorer:v1.2.0 (by /u/reddit_explorer)',
    'linux:dailycontentwebscraper:v1.1.0 (by /u/content_scraper)'
]

# Use a global session for better performance
session = requests.Session()

# Global event to manage pausing workers when errors occur
pause_event = threading.Event()
pause_event.set() # Initially allowed to run

# Global lock and timestamp to serialize requests and prevent rate-limit blocks
global_lock = threading.Lock()
last_request_time = 0.0

def wait_for_global_rate_limit(is_scraping=False):
    global last_request_time
    if is_scraping:
        # Space out requests during Phase 2 (comment scraping) by 1.5 to 2.5 seconds (Upay-1)
        min_interval = random.uniform(1.5, 2.5)
    else:
        # Space out requests during discovery (subreddits/search) by 3.0 to 4.5 seconds (Upay-3)
        min_interval = random.uniform(3.0, 4.5)
        
    with global_lock:
        now = time.time()
        elapsed = now - last_request_time
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            time.sleep(sleep_time)
        last_request_time = time.time()

def get_url_target(url):
    """Extract a user-friendly target name from the Reddit API URL."""
    if "/r/" in url:
        parts = url.split("/r/")
        if len(parts) >= 2:
            return f"r/{parts[1].split('/')[0]}"
    if "/search.json" in url:
        return "Global Search"
    if "/comments/" in url:
        parts = url.split("/comments/")
        if len(parts) >= 2:
            sub_parts = parts[1].split("/")
            if len(sub_parts) >= 2:
                return f"Comment Thread ({sub_parts[0]})"
    return url

def safe_request(url, timeout=30, max_retries=8, is_scraping=False):
    """Helper function with UA rotation, Smart Jitter and Global Pause."""
    target = get_url_target(url)
    for attempt in range(max_retries):
        try:
            # Wait if the system is paused due to an error in another worker
            if not pause_event.is_set():
                pause_event.wait()
                # Post-pause jitter to prevent thundering herd
                time.sleep(random.uniform(1.0, 4.0))
            
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Referer': 'https://www.google.com/'
            }
            
            # Ensure safe spacing between requests across all threads
            wait_for_global_rate_limit(is_scraping=is_scraping)
            
            if attempt > 0:
                print(f"    [i] Retrying request for {target}... (Attempt {attempt+1}/{max_retries})")
            
            # Tiny random jitter (0.2 to 0.8 seconds) to make request patterns natural
            time.sleep(random.uniform(0.2, 0.8))
            
            res = session.get(url, headers=headers, timeout=timeout)
            
            if res.status_code == 200:
                # If we were paused and now succeeded, ensure others can resume
                if not pause_event.is_set():
                    pause_event.set()
                return res
            
            elif res.status_code in [403, 429]:
                if pause_event.is_set():
                    pause_event.clear() # STOP other workers
                    wait_time = 180 # 3 minutes pause to allow rate limits to clear completely
                    print(f"    [!] Blocked/Rate limited ({res.status_code}) on {target}. Pausing all workers for {wait_time}s...")
                    try:
                        time.sleep(wait_time)
                    finally:
                        pause_event.set() # RESUME other workers
                else:
                    pause_event.wait()
                
            elif res.status_code in [500, 502, 503, 504]:
                if pause_event.is_set():
                    pause_event.clear() # STOP other workers
                    wait_time = 30
                    print(f"    [!] Server Busy ({res.status_code}) on {target}. Pausing all workers for {wait_time}s...")
                    try:
                        time.sleep(wait_time)
                    finally:
                        pause_event.set() # RESUME
                else:
                    pause_event.wait()
                
            else:
                return res 
                
        except Exception as e:
            # Check if this exception is a timeout or connection issue
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                if pause_event.is_set():
                    pause_event.clear()
                    print(f"    [!] Connection/Timeout Error on {target}: {e}. Pausing all workers for 20s...")
                    try:
                        time.sleep(20)
                    finally:
                        pause_event.set()
                else:
                    pause_event.wait()
            else:
                print(f"    [!] Request Exception on {target}: {e}")
            
            if attempt == max_retries - 1:
                print(f"    [!] Request failed completely for {target}: {e}")
            time.sleep(3)
            
    return None

# Individual subreddits for fair representation
DEFAULT_SUB_LIST = [
    "LAinfluencersnark", "tiktokgossip", "SwiftlyNeutral", "KUWTKsnark",
    "BeautyGuruChatter", "ArianaGrandeSnark", "HaileyBaldwinSnark", 
    "youtubedrama", "NYCinfluencersnark", "popculturechat", 
    "Fauxmoi", "CallHerDaddy", "canceledpod", "KUWTK", "kardashians",
    "KylieJenner", "BachelorNation", "vanderpumprules", 
    "h3h3productions", "SnarkingOnCelebrities", "NotEnoughNelsons",
    "NorrisNutsSnark", "FamilyVloggersSnark",
    "kpop_uncensored", "dancemoms", "GypsyRoseBlanchard",
    "MikaylaNogueira", "TheTryGuys", "TaylorSwift"
]

DEFAULT_KEYWORDS = "Zendaya OR Holland OR Selena OR Olivia OR Sabrina OR Sweeney OR Powell OR Elordi OR Miley OR Margot OR Gosling OR Drake OR Kendrick OR Swift OR Kelce OR Kardashian OR Jenner OR Bieber OR Mongeau OR Earle OR MrBeast OR D'Amelio OR Logan Paul OR Jake Paul OR Cardi B OR Nicki Minaj OR Mikayla Nogueira OR JoJo Siwa OR Alix Earle OR Alex Cooper OR Katseye OR Nidal Wonder OR Salish Matter OR Jordan Matter OR Piper Rockelle OR Not Enough Nelsons OR Norris Nuts OR Gypsy Rose OR Bobbi Althoff OR Jenna Ortega OR Benny Blanco OR Cynthia Erivo OR Ethan Slater OR Ned Fulmer OR Alabama Barker OR North West OR Clavicular OR Manon OR Clara Dao OR Chaewon OR Ben Pasternak OR Evelyn Ha OR Brooke Monk OR Natalie Reynolds OR Leah Ashe OR Meganplays OR JustJules OR Paultooreal OR Dylan OR Jooshica OR D4vd OR Celeste OR Katy Perry OR Preslee Faith OR Glow House OR Noah Beck OR Haley OR Cissy OR Ferran OR Lara OR Phibz OR Becca Bloom OR Saidee Nelson OR Rock Squad OR Gia OR Reese OR That Vegan Teacher OR Mattie OR Harper OR Kaido OR Salish OR Jennifer Lopez OR Chappell Roan OR Jude Law OR Haylee Baylee OR Jennette McCurdy OR Malachi Barton OR Malia OR Nayvee Nelson OR LOL Podcast OR Kate OR Jenny Hoyos OR Angelo OR Ryder OR OnlyJayus OR Travis Barker OR JustKass OR Mattie Westbrouck OR Timothee Chalamet OR Daniela OR Rakai OR Danielle OR NewJeans OR Kim Kardashian OR Lewis Hamilton OR Woah Vicky OR Melanie Martinez OR Kourtney Kardashian OR Kalogeras Sisters OR Demetria OR Desmond Scott OR Kristy OR Camilla Araujo OR Bailey OR Allday Project OR Kanye OR Louis Partridge OR Txunamy OR Brooks OR Odessa A'Zion OR Dakota OR Felicity OR MeganPlays OR Sophie Silva OR Samara OR Zuza OR Jack Doherty OR Brianna Olsen OR Ash Trevino OR Nara Smith OR Aaron Taylor Johnson OR Britney Spears OR Ryan Reynolds OR Blake Lively OR Freya Skye OR Ms Shirley OR KJ Apa OR Riverdale OR Bella Hadid OR Benny OR Bhad Bhabie OR Elphaba Orion Doherty OR Princess Amelia OR Sophie Rain OR Lil Tay OR Kendall Jenner OR Sofi Manassyan OR Bella The Wolf OR Wizard Liz OR Landon OR Sockie Norris OR Jazmine Tan OR Lala Sadi OR Nevada OR Asher OR Tate Mcrae OR Kid Laroi OR Labubu OR Ashley Barnes OR Diddy OR Madison Beer OR Chris Hughes OR Austin OR Ashton Kutcher OR Brittany Murphy OR SZA OR Zayn Malik OR Gigi Hadid OR Bradley Cooper OR James Charles OR Jeffree Star OR Sabrina Carpenter OR Rachel Zegler OR Smiley OR Matt Howard OR Abby OR Austin McBroom OR Catherine Paiz OR Mason Disick OR Justin Baldoni OR JonBenét Ramsey OR Penn Badgley OR Anna Kendrick OR Colleen Hoover OR Sienna Mae OR Jack Wright OR Tom Holland"

SETTINGS_FILE = os.path.join(parent_dir, "daily_content_settings.json")

# --- 2. LOG REDIRECTOR AND STATE MANAGER ---
class ScraperManager:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.progress_percent = 0
        self.status_message = "Idle"
        self.log_lines = []
        self.stats = {"discovered": 0, "scraped": 0, "errors": 0}
        self.thread = None
        self.lock = threading.Lock()
        self.log_buffer = ""

    def add_log(self, text):
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_lines.append(f"[{timestamp}] {text}")

    def write_stdout(self, text):
        # Buffered stdout writer to catch prints correctly
        self.log_buffer += text
        if "\n" in self.log_buffer:
            parts = self.log_buffer.split("\n")
            for part in parts[:-1]:
                if part.strip():
                    self.add_log(part)
            self.log_buffer = parts[-1]

    def get_logs(self, since=0):
        with self.lock:
            if since >= len(self.log_lines):
                return []
            return self.log_lines[since:]

    def reset(self):
        with self.lock:
            self.stop_requested = False
            self.progress_percent = 0
            self.status_message = "Idle"
            self.log_lines = []
            self.stats = {"discovered": 0, "scraped": 0, "errors": 0}
            self.log_buffer = ""

manager = ScraperManager()

class StdinRedirector:
    def __init__(self, manager):
        self.manager = manager
        self.original_stdout = sys.stdout

    def write(self, text):
        try:
            self.original_stdout.write(text)
        except UnicodeEncodeError:
            try:
                enc = self.original_stdout.encoding or 'ascii'
                safe_text = text.encode(enc, errors='replace').decode(enc)
                self.original_stdout.write(safe_text)
            except Exception:
                pass
        self.manager.write_stdout(text)

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass

# Redirect stdout to capture prints
sys.stdout = StdinRedirector(manager)

# --- 3. COMMENT FORMATTER & SCRAPER LOGIC ---
def format_comments_json(children, depth=0):
    formatted = []
    more_ids = []
    
    for child in children:
        kind = child['kind']
        data = child['data']
        
        if kind == 't1': # Normal comment
            body = data.get('body', '').strip()
            if not body or body in ['[removed]', '[deleted]']: continue
                
            prefix = "[MAIN COMMENT]: " if depth == 0 else "  " * depth + "└─ [REPLY]: "
            body_fmt = body.replace("\n", "\n" + "  " * (depth + 1))
            formatted.append(f"\n{prefix}{body_fmt}")
                
            replies = data.get('replies')
            if replies and isinstance(replies, dict):
                inner_comments, inner_more = format_comments_json(replies.get('data', {}).get('children', []), depth + 1)
                formatted.extend(inner_comments)
                more_ids.extend(inner_more)
        
        elif kind == 'more' and depth < 3: # Collect "more" IDs for batch fetching
            more_ids.extend(data.get('children', []))
            
    return formatted, more_ids

def scrape_single_url(url):
    json_url = url.rstrip("/") + ".json?limit=500&depth=10"
    try:
        response = safe_request(json_url, timeout=60, is_scraping=True)
        if not response or response.status_code != 200: 
            return None
        data = response.json()
        
        post_data = data[0]['data']['children'][0]['data']
        title = post_data['title']
        link_id = post_data['name']
        subreddit = post_data.get('subreddit', 'unknown')
        
        comment_children = data[1]['data']['children']
        formatted_comments, more_ids = format_comments_json(comment_children)

        # Deep scraping for extra comments
        if more_ids and len(formatted_comments) < 800:
            print(f"      [i] Fetching extra comments for: {title[:30]}...")
            for i in range(0, min(len(more_ids), 150), 50):
                if manager.stop_requested:
                    break
                batch_ids = ",".join(more_ids[i:i+50])
                more_url = f"https://www.reddit.com/api/morechildren.json?link_id={link_id}&children={batch_ids}&api_type=json"
                m_res = safe_request(more_url, timeout=30, is_scraping=True)
                if m_res and m_res.status_code == 200:
                    more_data = m_res.json().get('json', {}).get('data', {}).get('things', [])
                    for thing in more_data:
                        if thing['kind'] == 't1':
                            body = thing['data'].get('body', '').strip()
                            author = thing['data'].get('author', '[deleted]')
                            if body and body not in ['[removed]', '[deleted]']:
                                formatted_comments.append(f"\n[ADDITIONAL COMMENT by {author}]: {body}")
                time.sleep(1)

        print(f"    ✅ Scraped {len(formatted_comments)} comments: {title[:40]}...")
        return {
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Subreddit": subreddit,
            "Post_Title": title,
            "Comments_Found": len(formatted_comments),
            "Full_Discussion_For_AI": "".join(formatted_comments),
            "Link": url
        }
    except Exception as e:
        print(f"      [!] Scrape failed for {url}: {e}")
        return None

def run_scraper_thread(settings):
    try:
        manager.is_running = True
        manager.status_message = "Initializing scraper..."
        
        comment_threshold = settings.get("comment_threshold", 15)
        lookback_val = settings.get("lookback_val", 16)
        lookback_unit = settings.get("lookback_unit", "Hours")
        save_folder = settings.get("save_folder", "")
        max_scrape_workers = settings.get("max_workers", 15)
        subreddits = settings.get("subreddits", DEFAULT_SUB_LIST)
        keywords = settings.get("keywords", DEFAULT_KEYWORDS)
        
        if not save_folder:
            save_folder = parent_dir
            
        lookback_hours = lookback_val * 24 if lookback_unit == "Days" else lookback_val
        lookback_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        
        if lookback_hours <= 1: search_t = "hour"
        elif lookback_hours <= 24: search_t = "day"
        elif lookback_hours <= 168: search_t = "week"
        elif lookback_hours <= 720: search_t = "month"
        else: search_t = "year"

        print(f">>> Starting High-Speed Scraper")
        print(f">>> Parallel Workers: {max_scrape_workers}")
        print(f">>> Lookback: {lookback_hours}h | Threshold: {comment_threshold} comments\n")
        
        # --- PHASE 1: DISCOVERY ---
        manager.status_message = "Discovering viral posts..."
        all_discovered_links = []
        stats_dict = {sub: 0 for sub in subreddits}
        stats_dict["Global Search"] = 0
        failed_subs = []
        discovery_lock = threading.Lock()

        def check_subreddit(sub):
            nonlocal all_discovered_links
            sub_urls = [
                f"https://www.reddit.com/r/{sub}/top.json?t={search_t}&limit=25",
                f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
            ]
            success_any = False
            for url in sub_urls:
                if manager.stop_requested: 
                    break
                res = safe_request(url, timeout=20, max_retries=3)
                if res and res.status_code == 200:
                    success_any = True
                    children = res.json().get('data', {}).get('children', [])
                    for post in children:
                        p = post['data']
                        created_time = datetime.fromtimestamp(p['created_utc'], tz=timezone.utc)
                        if created_time > lookback_time and p['num_comments'] >= comment_threshold:
                            permalink = p['permalink']
                            full_url = f"https://www.reddit.com{permalink}" if permalink.startswith('/') else permalink
                            with discovery_lock:
                                if full_url not in all_discovered_links:
                                    all_discovered_links.append(full_url)
                                    stats_dict[sub] += 1
                elif res and res.status_code == 404:
                    return True # banned/private
            return success_any

        # Check subreddits in parallel (Max 4 workers to prevent rate limiting blocks)
        max_discovery_workers = min(4, max_scrape_workers)
        print(f"\n>>> Phase 1: Checking {len(subreddits)} subreddits in parallel (Workers: {max_discovery_workers})...")
        
        with ThreadPoolExecutor(max_workers=max_discovery_workers) as executor:
            future_to_sub = {executor.submit(check_subreddit, sub): sub for sub in subreddits}
            
            completed_count = 0
            import concurrent.futures
            for future in concurrent.futures.as_completed(future_to_sub):
                if manager.stop_requested:
                    break
                sub = future_to_sub[future]
                completed_count += 1
                manager.progress_percent = int((completed_count / len(subreddits)) * 25)
                manager.status_message = f"Checking subreddits ({completed_count}/{len(subreddits)})..."
                
                try:
                    success = future.result()
                    if success:
                        print(f"    [{completed_count}/{len(subreddits)}] Completed r/{sub}")
                    else:
                        print(f"    [{completed_count}/{len(subreddits)}] [!] Failed to reach r/{sub}. Queued for final retry.")
                        with discovery_lock:
                            failed_subs.append(sub)
                except Exception as e:
                    print(f"    [{completed_count}/{len(subreddits)}] [!] Error checking r/{sub}: {e}")
                    with discovery_lock:
                        failed_subs.append(sub)

        # Retry failed subs (sequentially to be gentle on final attempt)
        if failed_subs and not manager.stop_requested:
            print(f"\n>>> Final retry for {len(failed_subs)} failed subreddits...")
            for sub in failed_subs:
                if manager.stop_requested: 
                    break
                print(f"    [Final Chance] Retrying r/{sub}...")
                check_subreddit(sub)

        # Global Search (1-by-1 queries, executed in parallel using max_scrape_workers)
        if not manager.stop_requested:
            kw_list = [k.strip() for k in keywords.split(" OR ") if k.strip()]
            sanitized_kws = []
            for kw in kw_list:
                clean_kw = kw.replace("'", "")
                if clean_kw:
                    sanitized_kws.append(clean_kw)
            
            print(f"\n>>> Performing Parallel Global Keyword Search for {len(sanitized_kws)} keywords (Workers: {max_scrape_workers})...")
            
            def search_single_keyword(kw):
                if manager.stop_requested:
                    return 0
                
                print(f"    [+] Searching: '{kw}'")
                import urllib.parse
                # Ensure the keyword is properly quoted for exact matching if it contains spaces
                query_str = f'"{kw}"' if " " in kw else kw
                encoded_query = urllib.parse.quote(query_str)
                search_url = f"https://www.reddit.com/search.json?q={encoded_query}&restrict_sr=0&sort=top&t={search_t}&limit=25"
                
                res = safe_request(search_url, timeout=30, max_retries=8)
                found_count = 0
                
                if res and res.status_code == 200:
                    try:
                        children = res.json().get('data', {}).get('children', [])
                        for post in children:
                            p = post['data']
                            created_time = datetime.fromtimestamp(p['created_utc'], tz=timezone.utc)
                            if created_time > lookback_time and p['num_comments'] >= comment_threshold:
                                permalink = p['permalink']
                                full_url = f"https://www.reddit.com{permalink}" if permalink.startswith('/') else permalink
                                with discovery_lock:
                                    if full_url not in all_discovered_links:
                                        all_discovered_links.append(full_url)
                                        found_count += 1
                                        sub_name = p.get('subreddit', 'Unknown')
                                        if sub_name in stats_dict:
                                            stats_dict[sub_name] += 1
                                        else:
                                            stats_dict["Global Search"] = stats_dict.get("Global Search", 0) + 1
                    except Exception as parse_err:
                        print(f"      [!] Error parsing results for keyword '{kw}': {parse_err}")
                return found_count

            # Run keyword searches in parallel using the user-defined max_scrape_workers limit
            with ThreadPoolExecutor(max_workers=max_scrape_workers) as kw_executor:
                future_to_kw = {kw_executor.submit(search_single_keyword, kw): kw for kw in sanitized_kws}
                
                completed_kws = 0
                import concurrent.futures
                for future in concurrent.futures.as_completed(future_to_kw):
                    if manager.stop_requested:
                        break
                    kw = future_to_kw[future]
                    completed_kws += 1
                    
                    # Allocate 25% of total progress for subreddits, 5% for transition, 
                    # and map 25% to 50% progress bar to parallel keyword searches
                    kw_progress = 25 + int((completed_kws / len(sanitized_kws)) * 25)
                    manager.progress_percent = kw_progress
                    manager.status_message = f"Global Search ({completed_kws}/{len(sanitized_kws)} keywords)..."
                    
                    try:
                        count = future.result()
                        print(f"    [{completed_kws}/{len(sanitized_kws)}] Keyword '{kw}' -> Found {count} viral posts.")
                    except Exception as kw_err:
                        print(f"    [{completed_kws}/{len(sanitized_kws)}] [!] Keyword '{kw}' failed with error: {kw_err}")

        manager.stats["discovered"] = len(all_discovered_links)
        print(f"    [+] Discovery complete. Found {len(all_discovered_links)} unique viral posts.")

        # --- PHASE 2: PERSISTENT PARALLEL SCRAPING ---
        all_final_results = []
        if all_discovered_links and not manager.stop_requested:
            pending_links = list(set(all_discovered_links))
            total_links = len(pending_links)
            scraped_count = 0
            error_count = 0
            
            manager.status_message = f"Scraping discussions (0/{total_links})..."
            print(f"\n>>> Scraping {total_links} viral discussions using {max_scrape_workers} workers...")
            
            import concurrent.futures
            with ThreadPoolExecutor(max_workers=max_scrape_workers) as executor:
                future_to_url = {executor.submit(scrape_single_url, url): url for url in pending_links}
                
                for future in concurrent.futures.as_completed(future_to_url):
                    if manager.stop_requested: 
                        break
                    url = future_to_url[future]
                    try:
                        result = future.result()
                        if result:
                            all_final_results.append(result)
                            scraped_count += 1
                            manager.stats["scraped"] = scraped_count
                        else:
                            error_count += 1
                            manager.stats["errors"] = error_count
                    except Exception as e:
                        print(f"      [!] Error processing {url}: {e}")
                        error_count += 1
                        manager.stats["errors"] = error_count
                    
                    processed = scraped_count + error_count
                    manager.status_message = f"Scraping discussions ({processed}/{total_links})..."
                    manager.progress_percent = 30 + int((processed / total_links) * 65)
        else:
            if not all_discovered_links:
                print("\n❌ No viral posts found in this run.")

        # --- PHASE 3: EXPORT ---
        if all_final_results and not manager.stop_requested:
            manager.status_message = "Saving scraped results..."
            manager.progress_percent = 95
            
            df = pd.DataFrame(all_final_results)
            save_path_root = os.path.join(save_folder, "Scrapped list")
            os.makedirs(save_path_root, exist_ok=True)
            
            for i, row in df.iterrows():
                clean_title = "".join([c for c in row['Post_Title'][:50] if c.isalnum() or c in (' ', '_')]).strip().replace(' ', '_')
                txt_filename = f"{i+1}_r_{row['Subreddit']}_{clean_title}.txt"
                
                with open(os.path.join(save_path_root, txt_filename), "w", encoding="utf-8") as f:
                    f.write(
                        f"SUBREDDIT: r/{row['Subreddit']}\n"
                        f"TITLE: {row['Post_Title']}\n"
                        f"DATE: {row['Date']}\n"
                        f"LINK: {row['Link']}\n"
                        f"COMMENTS:\n{row['Full_Discussion_For_AI']}\n"
                    )

            print(f"\n🎉 ALL DONE! Saved {len(all_final_results)} discussions to: {save_path_root}")
            manager.status_message = f"Completed successfully! Saved {len(all_final_results)} files."
            manager.progress_percent = 100
        elif manager.stop_requested:
            print("\n🛑 Scraper execution stopped by user request.")
            manager.status_message = "Scraper stopped."
        else:
            manager.status_message = "Finished. No results to save."
            manager.progress_percent = 100

    except Exception as e:
        print(f"\n❌ Critical Error: {str(e)}")
        manager.status_message = f"Error occurred: {str(e)}"
    finally:
        manager.is_running = False

# --- 4. FLASK SERVER ROUTES ---

@app.after_request
def add_header(response):
    # Prevent browser caching of API endpoints
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

def get_current_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Defaults if file doesn't exist
    return {
        "comment_threshold": 15,
        "lookback_val": 16,
        "lookback_unit": "Hours",
        "max_workers": 15,
        "save_folder": parent_dir,
        "subreddits": DEFAULT_SUB_LIST,
        "keywords": DEFAULT_KEYWORDS
    }

def save_current_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False

# Serve Frontend SPA
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

# API: Settings
@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        return jsonify(get_current_settings())
    else:
        new_settings = request.json
        if save_current_settings(new_settings):
            return jsonify({"status": "success", "message": "Settings saved successfully."})
        else:
            return jsonify({"status": "error", "message": "Failed to save settings."}), 500

# API: Start
@app.route('/api/start', methods=['POST'])
def api_start():
    if manager.is_running:
        return jsonify({"status": "error", "message": "Scraper is already running."}), 400
    
    manager.reset()
    settings = get_current_settings()
    manager.thread = threading.Thread(target=run_scraper_thread, args=(settings,), daemon=True)
    manager.thread.start()
    return jsonify({"status": "success", "message": "Scraper started."})

# API: Stop
@app.route('/api/stop', methods=['POST'])
def api_stop():
    if not manager.is_running:
        return jsonify({"status": "error", "message": "Scraper is not running."}), 400
    
    manager.stop_requested = True
    print("\n[!] User requested scraper stop. Stopping threads gracefully...")
    return jsonify({"status": "success", "message": "Stop requested. Thread cleaning up..."})

# API: Status
@app.route('/api/status', methods=['GET'])
def api_status():
    since = request.args.get('since', 0, type=int)
    new_logs = manager.get_logs(since=since)
    
    return jsonify({
        "is_running": manager.is_running,
        "stop_requested": manager.stop_requested,
        "status_message": manager.status_message,
        "progress_percent": manager.progress_percent,
        "stats": manager.stats,
        "logs": new_logs,
        "total_log_count": len(manager.log_lines)
    })

# API: Results List
@app.route('/api/results', methods=['GET'])
def api_results():
    settings = get_current_settings()
    save_folder = settings.get("save_folder") or os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(save_folder, "Scrapped list")
    
    if not os.path.exists(target_dir):
        return jsonify([])
        
    try:
        files = []
        for f in os.listdir(target_dir):
            if f.endswith('.txt'):
                full_path = os.path.join(target_dir, f)
                stat = os.stat(full_path)
                # Parse title and subreddit from filename if matching our format
                # e.g., "1_r_popculturechat_Title.txt"
                subreddit = "unknown"
                parts = f.split('_r_')
                if len(parts) >= 2:
                    sub_part = parts[1].split('_')
                    if len(sub_part) > 0:
                        subreddit = sub_part[0]
                
                files.append({
                    "name": f,
                    "subreddit": subreddit,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "mtime": stat.st_mtime
                })
        
        # Sort by modified time descending (newest first)
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify(files)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# API: Result Content
@app.route('/api/results/content', methods=['GET'])
def api_result_content():
    filename = request.args.get('file', '')
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400
        
    settings = get_current_settings()
    save_folder = settings.get("save_folder") or os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(save_folder, "Scrapped list")
    file_path = os.path.join(target_dir, filename)
    
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "File not found"}), 404
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"filename": filename, "content": content})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# API: Open Folder
@app.route('/api/open-folder', methods=['POST'])
def api_open_folder():
    settings = get_current_settings()
    save_folder = settings.get("save_folder") or os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(save_folder, "Scrapped list")
    
    os.makedirs(target_dir, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(target_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_dir])
        else:
            subprocess.Popen(["xdg-open", target_dir])
        return jsonify({"status": "success", "message": "Folder opened."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 5. MAIN EXECUTION ---
if __name__ == "__main__":
    ensure_dependencies()
    
    # Create static assets folder if not exists
    if static_dir == "web_static":
        os.makedirs('web_static', exist_ok=True)
    
    # Start server in a background-friendly way and open browser
    def open_browser():
        time.sleep(1.5)
        print("\n[*] Server is ready! Launching web application browser...")
        webbrowser.open("http://127.0.0.1:5000")
        
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("\n[*] Starting CineNuggets Web Scraper Server...")
    print("[*] Access UI at: http://127.0.0.1:5000")
    print("[*] Press Ctrl+C in this terminal to stop the server.")
    
    app.run(host='127.0.0.1', port=5000, debug=False)
