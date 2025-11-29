#!/bin/bash
# Setup script for News Scraper Daemon on Ubuntu
# Run this script on your Ubuntu machine to set up the scraper

set -e

echo "========================================"
echo "News Scraper Daemon - Ubuntu Setup"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo -e "${YELLOW}Repository root: $REPO_ROOT${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}Please do not run this script as root${NC}"
    exit 1
fi

# Step 1: Install system dependencies
echo ""
echo -e "${GREEN}Step 1: Installing system dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git

# Step 2: Create virtual environment
echo ""
echo -e "${GREEN}Step 2: Setting up Python virtual environment...${NC}"
cd "$REPO_ROOT"
python3 -m venv venv
source venv/bin/activate

# Step 3: Install Python dependencies
echo ""
echo -e "${GREEN}Step 3: Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r scripts/scraper/requirements.txt

# Step 4: Install Playwright browsers
echo ""
echo -e "${GREEN}Step 4: Installing Playwright browsers...${NC}"
playwright install chromium
playwright install-deps chromium

# Step 5: Set up logs directory
echo ""
echo -e "${GREEN}Step 5: Setting up logs directory...${NC}"
mkdir -p logs
touch logs/.gitkeep

# Step 6: Configure git
echo ""
echo -e "${GREEN}Step 6: Configuring git...${NC}"
git config user.name "News Scraper Bot"
git config user.email "scraper@local"

# Step 7: Prompt for GitHub token
echo ""
echo -e "${YELLOW}Step 7: GitHub Token Setup${NC}"
echo "You need a GitHub Personal Access Token (PAT) with these permissions:"
echo "  - Contents: Read and Write"
echo "  - Pull requests: Read and Write"
echo ""
echo "Generate one at: https://github.com/settings/tokens?type=beta"
echo ""

read -p "Enter your GitHub token (or press Enter to skip): " GITHUB_TOKEN

if [ -n "$GITHUB_TOKEN" ]; then
    # Create environment file
    ENV_FILE="$HOME/.scraper_env"
    echo "GITHUB_TOKEN=$GITHUB_TOKEN" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo -e "${GREEN}Token saved to $ENV_FILE${NC}"
    
    # Export for current session
    export GITHUB_TOKEN
fi

# Step 8: Test the daemon
echo ""
echo -e "${GREEN}Step 8: Testing the daemon...${NC}"
echo "Running a single sync cycle..."

if [ -n "$GITHUB_TOKEN" ]; then
    cd "$REPO_ROOT"
    source venv/bin/activate
    python scripts/scraper/daemon.py --once
    echo -e "${GREEN}Test completed!${NC}"
else
    echo -e "${YELLOW}Skipping test - no token provided${NC}"
fi

# Step 9: Set up systemd service
echo ""
echo -e "${YELLOW}Step 9: systemd Service Setup${NC}"
echo ""
read -p "Do you want to install the systemd service? (y/n): " INSTALL_SERVICE

if [ "$INSTALL_SERVICE" = "y" ]; then
    # Create service file from template
    SERVICE_FILE="/tmp/news-scraper.service"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Hong Kong Fire Documentary News Scraper Daemon
After=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$REPO_ROOT
EnvironmentFile=$HOME/.scraper_env
ExecStart=$REPO_ROOT/venv/bin/python $REPO_ROOT/scripts/scraper/daemon.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Install service
    sudo cp "$SERVICE_FILE" /etc/systemd/system/news-scraper.service
    sudo systemctl daemon-reload
    sudo systemctl enable news-scraper
    
    echo ""
    read -p "Start the service now? (y/n): " START_NOW
    if [ "$START_NOW" = "y" ]; then
        sudo systemctl start news-scraper
        echo -e "${GREEN}Service started!${NC}"
        echo ""
        echo "View logs with: journalctl -u news-scraper -f"
        echo "Check status with: sudo systemctl status news-scraper"
    fi
    
    echo -e "${GREEN}Service installed!${NC}"
fi

echo ""
echo "========================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "========================================"
echo ""
echo "To run the daemon manually:"
echo "  cd $REPO_ROOT"
echo "  source venv/bin/activate"
echo "  export GITHUB_TOKEN='your_token'"
echo "  python scripts/scraper/daemon.py"
echo ""
echo "To check service status:"
echo "  sudo systemctl status news-scraper"
echo ""
echo "To view logs:"
echo "  journalctl -u news-scraper -f"
echo "  # or"
echo "  tail -f $REPO_ROOT/logs/scraper.log"
echo ""

