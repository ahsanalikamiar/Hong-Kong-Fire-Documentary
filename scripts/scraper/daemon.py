#!/usr/bin/env python3
"""
News Scraper Daemon for Hong Kong Fire Documentary
Runs 24/7 on a machine, syncs with upstream, scrapes URLs, creates PRs.

Requirements:
    - gh CLI installed and authenticated (run: gh auth login)
    - Git configured with push access to your fork

Environment Variables Required:
    FORK_REPO    - Your fork's repo path (e.g., 'username/repo-name')

Optional Environment Variables:
    UPSTREAM_REPO - Upstream repo (default: Hong-Kong-Emergency-Coordination-Hub/...)
    PR_BRANCH     - Branch for PRs (default: scraper-updates)
    MAIN_BRANCH   - Main branch name (default: main)
    
Usage:
    python daemon.py              # Run daemon (runs forever)
    python daemon.py --once       # Run one cycle and exit (for testing)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Project paths
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "scraper.log"

# GitHub configuration - set via environment variables or defaults
UPSTREAM_REPO = os.environ.get(
    "UPSTREAM_REPO",
    "Hong-Kong-Emergency-Coordination-Hub/Hong-Kong-Fire-Documentary"
)
FORK_REPO = os.environ.get("FORK_REPO", "")  # Required - no default
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPO}.git"
PR_BRANCH = os.environ.get("PR_BRANCH", "scraper-updates")
MAIN_BRANCH = os.environ.get("MAIN_BRANCH", "main")

# Timing configuration
SYNC_INTERVAL_MINUTES = 10
PR_INTERVAL_MINUTES = 60


def setup_logging():
    """Set up logging to both file and console"""
    LOGS_DIR.mkdir(exist_ok=True)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler (append mode)
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def run_cmd(cmd: list[str], cwd: Path = None, check: bool = True, env: dict = None) -> subprocess.CompletedProcess:
    """Run a shell command and return the result"""
    # Merge environment, unsetting GITHUB_TOKEN to let gh use its own auth
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    # Unset GITHUB_TOKEN so gh CLI uses its own authentication
    run_env.pop("GITHUB_TOKEN", None)
    
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=check,
            env=run_env
        )
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(cmd)}")
        logging.error(f"stderr: {e.stderr}")
        raise


def get_fork_repo() -> str:
    """Get fork repo from environment variable"""
    if not FORK_REPO:
        logging.error("FORK_REPO environment variable not set!")
        logging.error("Please set it: export FORK_REPO='username/repo-name'")
        sys.exit(1)
    return FORK_REPO


def get_fork_owner() -> str:
    """Get the owner/username from FORK_REPO"""
    return get_fork_repo().split("/")[0]


def check_gh_auth() -> bool:
    """Check if gh CLI is authenticated"""
    try:
        result = run_cmd(["gh", "auth", "status"], check=False)
        if result.returncode != 0:
            logging.error("gh CLI is not authenticated!")
            logging.error("Please run: gh auth login")
            return False
        logging.info("gh CLI authenticated")
        return True
    except FileNotFoundError:
        logging.error("gh CLI not found! Please install it: https://cli.github.com/")
        return False


def setup_git_remotes():
    """Ensure git remotes are configured correctly"""
    logging.info("Setting up git remotes...")
    
    # Check current remotes
    result = run_cmd(["git", "remote", "-v"], check=False)
    
    # Add upstream if not exists
    if "upstream" not in result.stdout:
        run_cmd(["git", "remote", "add", "upstream", UPSTREAM_URL])
        logging.info(f"Added upstream remote: {UPSTREAM_URL}")
    
    # Ensure origin points to fork (use gh for auth)
    fork_repo = get_fork_repo()
    fork_url = f"https://github.com/{fork_repo}.git"
    run_cmd(["git", "remote", "set-url", "origin", fork_url])
    logging.info("Configured origin remote")


def sync_with_upstream() -> bool:
    """
    Sync local repo with upstream.
    Returns True if there were changes, False otherwise.
    """
    logging.info("Syncing with upstream...")
    
    try:
        # Fetch upstream
        run_cmd(["git", "fetch", "upstream", MAIN_BRANCH])
        
        # Check if we're behind upstream
        result = run_cmd([
            "git", "rev-list", "--count",
            f"HEAD..upstream/{MAIN_BRANCH}"
        ])
        commits_behind = int(result.stdout.strip())
        
        if commits_behind > 0:
            logging.info(f"Behind upstream by {commits_behind} commits, merging...")
            
            # Stash any local changes
            run_cmd(["git", "stash"], check=False)
            
            # Checkout main and merge upstream
            run_cmd(["git", "checkout", MAIN_BRANCH])
            run_cmd(["git", "merge", f"upstream/{MAIN_BRANCH}", "--no-edit"])
            
            # Pop stash if exists
            run_cmd(["git", "stash", "pop"], check=False)
            
            logging.info("Synced with upstream successfully")
            return True
        else:
            logging.info("Already up to date with upstream")
            return False
            
    except Exception as e:
        logging.error(f"Failed to sync with upstream: {e}")
        return False


def run_scraper() -> tuple[int, int]:
    """
    Run the scraper to detect and scrape new URLs.
    Returns (success_count, fail_count)
    """
    logging.info("Running scraper...")
    
    try:
        # Import and run scraper
        sys.path.insert(0, str(SCRIPT_DIR))
        from scraper import run_scraper as scrape, load_registry, get_all_urls, filter_new_urls
        
        # Check for new URLs first
        registry = load_registry()
        all_urls = get_all_urls()
        new_urls = filter_new_urls(all_urls, registry)
        
        if not new_urls:
            logging.info("No new URLs to scrape")
            return 0, 0
        
        logging.info(f"Found {len(new_urls)} new URLs to scrape")
        
        # Run the scraper (it handles everything internally)
        scrape(dry_run=False, verbose=False)
        
        # Count results by checking registry again
        new_registry = load_registry()
        scraped_count = len(new_registry.get("scraped_urls", {})) - len(registry.get("scraped_urls", {}))
        
        return scraped_count, len(new_urls) - scraped_count
        
    except Exception as e:
        logging.error(f"Scraper error: {e}")
        return 0, 0


def has_local_changes() -> bool:
    """Check if there are uncommitted changes"""
    result = run_cmd(["git", "status", "--porcelain"])
    return bool(result.stdout.strip())


def commit_changes() -> bool:
    """Commit any local changes"""
    if not has_local_changes():
        return False
    
    logging.info("Committing changes...")
    
    try:
        # Stage all changes
        run_cmd(["git", "add", "-A"])
        
        # Create commit message with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg = f"chore(scraper): auto-scrape {timestamp}"
        
        run_cmd(["git", "commit", "-m", msg])
        logging.info(f"Committed: {msg}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to commit: {e}")
        return False


def get_open_pr() -> dict | None:
    """Check if there's an existing open PR from the scraper branch using gh CLI"""
    fork_owner = get_fork_owner()
    
    try:
        result = run_cmd([
            "gh", "pr", "list",
            "--repo", UPSTREAM_REPO,
            "--head", f"{fork_owner}:{PR_BRANCH}",
            "--state", "open",
            "--json", "number,url",
            "--limit", "1"
        ], check=False)
        
        if result.returncode == 0 and result.stdout.strip():
            prs = json.loads(result.stdout)
            if prs:
                return prs[0]
        return None
        
    except Exception as e:
        logging.error(f"Failed to check for open PRs: {e}")
        return None


def close_pr(pr_number: int) -> bool:
    """Close an existing PR using gh CLI"""
    try:
        run_cmd([
            "gh", "pr", "close",
            str(pr_number),
            "--repo", UPSTREAM_REPO
        ])
        logging.info(f"Closed PR #{pr_number}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to close PR #{pr_number}: {e}")
        return False


def push_to_pr_branch() -> bool:
    """Push changes to the PR branch (force push to keep clean history)"""
    logging.info(f"Pushing to branch '{PR_BRANCH}'...")
    
    try:
        # Create or checkout the PR branch
        result = run_cmd(["git", "branch", "--list", PR_BRANCH], check=False)
        
        if PR_BRANCH in result.stdout:
            # Branch exists, checkout and reset to main
            run_cmd(["git", "checkout", PR_BRANCH])
            run_cmd(["git", "reset", "--hard", MAIN_BRANCH])
        else:
            # Create new branch from main
            run_cmd(["git", "checkout", "-b", PR_BRANCH, MAIN_BRANCH])
        
        # Force push to origin using gh for authentication
        run_cmd(["gh", "repo", "sync", "--source", f".:{PR_BRANCH}", "--force"], check=False)
        # Fallback to git push
        run_cmd(["git", "push", "origin", PR_BRANCH, "--force"])
        
        # Go back to main
        run_cmd(["git", "checkout", MAIN_BRANCH])
        
        logging.info(f"Pushed to {PR_BRANCH}")
        return True
        
    except Exception as e:
        logging.error(f"Failed to push: {e}")
        # Try to get back to main
        run_cmd(["git", "checkout", MAIN_BRANCH], check=False)
        return False


def create_pr() -> bool:
    """Create a new PR to upstream using gh CLI"""
    fork_owner = get_fork_owner()
    
    # Get count of archives for PR description
    archives_dir = PROJECT_ROOT / "content" / "news"
    archive_count = 0
    for source_dir in archives_dir.iterdir():
        if source_dir.is_dir():
            archive_dir = source_dir / "archive"
            if archive_dir.exists():
                archive_count += len(list(archive_dir.iterdir()))
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    title = f"[Auto-Scraper] News archives update - {timestamp}"
    body = f"""## Automated News Archive Update

This PR was automatically generated by the news scraper daemon.

### Summary
- **Timestamp**: {timestamp}
- **Total archived articles**: {archive_count}

### What's included
- Scraped HTML archives of news articles
- Updated URL registry to prevent duplicates
- Scraper activity logs

---
*This PR will be automatically replaced if not merged before the next hourly update.*
"""
    
    try:
        result = run_cmd([
            "gh", "pr", "create",
            "--repo", UPSTREAM_REPO,
            "--head", f"{fork_owner}:{PR_BRANCH}",
            "--base", MAIN_BRANCH,
            "--title", title,
            "--body", body
        ], check=False)
        
        if result.returncode == 0:
            pr_url = result.stdout.strip()
            logging.info(f"Created PR: {pr_url}")
            return True
        elif "already exists" in result.stderr.lower():
            logging.info("PR already exists")
            return True
        else:
            logging.error(f"Failed to create PR: {result.stderr}")
            return False
        
    except Exception as e:
        logging.error(f"Failed to create PR: {e}")
        return False


def manage_pr():
    """Close old PR if exists, push changes, and create new PR"""
    logging.info("Managing PR...")
    
    # Check for existing open PR
    existing_pr = get_open_pr()
    if existing_pr:
        pr_number = existing_pr["number"]
        logging.info(f"Found existing open PR #{pr_number}, closing...")
        close_pr(pr_number)
    
    # Push to PR branch
    if not push_to_pr_branch():
        logging.error("Failed to push to PR branch")
        return
    
    # Create new PR
    create_pr()


def commit_logs():
    """Commit log file changes"""
    if not LOG_FILE.exists():
        return
    
    try:
        run_cmd(["git", "add", str(LOG_FILE)])
        
        # Check if there are staged changes for the log file
        result = run_cmd(["git", "diff", "--cached", "--name-only"])
        if "logs/scraper.log" in result.stdout:
            run_cmd(["git", "commit", "-m", "chore(logs): update scraper logs"])
            logging.info("Committed log updates")
            
    except Exception as e:
        logging.debug(f"No log changes to commit: {e}")


def run_daemon(run_once: bool = False):
    """Main daemon loop"""
    logger = setup_logging()
    
    logging.info("=" * 60)
    logging.info("News Scraper Daemon Starting")
    logging.info(f"Fork: {get_fork_repo()}")
    logging.info(f"Upstream: {UPSTREAM_REPO}")
    logging.info(f"Sync interval: {SYNC_INTERVAL_MINUTES} minutes")
    logging.info(f"PR interval: {PR_INTERVAL_MINUTES} minutes")
    logging.info("=" * 60)
    
    # Verify gh CLI auth and fork repo
    if not check_gh_auth():
        sys.exit(1)
    get_fork_repo()
    
    # Setup git remotes
    setup_git_remotes()
    
    last_sync = datetime.min
    last_pr = datetime.min
    
    try:
        while True:
            now = datetime.now()
            
            # Check if it's time to sync (every 10 minutes)
            if now - last_sync >= timedelta(minutes=SYNC_INTERVAL_MINUTES):
                logging.info("-" * 40)
                logging.info("Starting sync cycle...")
                
                # Sync with upstream
                sync_with_upstream()
                
                # Run scraper
                success, failed = run_scraper()
                if success > 0 or failed > 0:
                    logging.info(f"Scraper results: {success} success, {failed} failed")
                
                # Commit any changes
                commit_changes()
                
                # Commit logs
                commit_logs()
                
                last_sync = now
                logging.info("Sync cycle complete")
            
            # Check if it's time to create/update PR (every hour)
            if now - last_pr >= timedelta(minutes=PR_INTERVAL_MINUTES):
                logging.info("-" * 40)
                logging.info("Starting PR cycle...")
                
                # Push to fork first
                try:
                    run_cmd(["git", "push", "origin", MAIN_BRANCH])
                except:
                    pass
                
                manage_pr()
                
                last_pr = now
                logging.info("PR cycle complete")
            
            if run_once:
                logging.info("Run once mode, exiting...")
                break
            
            # Sleep for 1 minute between checks
            time.sleep(60)
            
    except KeyboardInterrupt:
        logging.info("Daemon stopped by user")
    except Exception as e:
        logging.error(f"Daemon error: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="News Scraper Daemon - runs 24/7, syncs and scrapes"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sync+scrape+PR cycle and exit"
    )
    
    args = parser.parse_args()
    run_daemon(run_once=args.once)


if __name__ == "__main__":
    main()
