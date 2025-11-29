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
sudo apt-get install -y python3 python3-pip python3-venv git curl

# Step 2: Install gh CLI if not present
echo ""
echo -e "${GREEN}Step 2: Installing GitHub CLI (gh)...${NC}"
if ! command -v gh &> /dev/null; then
    # Install gh CLI
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y gh
    echo -e "${GREEN}gh CLI installed!${NC}"
else
    echo -e "${GREEN}gh CLI already installed: $(gh --version | head -1)${NC}"
fi

# Step 3: Authenticate gh CLI
echo ""
echo -e "${GREEN}Step 3: GitHub CLI Authentication${NC}"
if ! gh auth status &> /dev/null; then
    echo -e "${YELLOW}Please authenticate with GitHub:${NC}"
    gh auth login
else
    echo -e "${GREEN}Already authenticated with GitHub${NC}"
fi

# Step 4: Create virtual environment
echo ""
echo -e "${GREEN}Step 4: Setting up Python virtual environment...${NC}"
cd "$REPO_ROOT"
python3 -m venv venv
source venv/bin/activate

# Step 5: Install Python dependencies
echo ""
echo -e "${GREEN}Step 5: Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r scripts/scraper/requirements.txt

# Step 6: Install Playwright browsers
echo ""
echo -e "${GREEN}Step 6: Installing Playwright browsers...${NC}"
playwright install chromium
playwright install-deps chromium

# Step 7: Set up logs directory
echo ""
echo -e "${GREEN}Step 7: Setting up logs directory...${NC}"
mkdir -p logs
touch logs/.gitkeep

# Step 8: Configure git
echo ""
echo -e "${GREEN}Step 8: Configuring git...${NC}"
git config user.name "News Scraper Bot"
git config user.email "scraper@local"

# Step 9: Configuration Setup
echo ""
echo -e "${YELLOW}Step 9: Configuration Setup${NC}"
echo ""

# Get Fork Repo
echo "Enter your GitHub fork repository (e.g., 'username/Hong-Kong-Fire-Documentary')"
read -p "Fork repo: " FORK_REPO

if [ -z "$FORK_REPO" ]; then
    echo -e "${RED}Fork repo is required!${NC}"
    exit 1
fi

# Create environment file
ENV_FILE="$HOME/.scraper_env"
cat > "$ENV_FILE" << EOF
FORK_REPO=$FORK_REPO
EOF
chmod 600 "$ENV_FILE"
echo -e "${GREEN}Configuration saved to $ENV_FILE${NC}"

# Export for current session
export FORK_REPO

# Step 10: Configure DNS (recommended)
echo ""
echo -e "${YELLOW}Step 10: DNS Configuration${NC}"
echo ""
echo "For reliable operation, we recommend using Google DNS (8.8.8.8)."
echo "Some networks have slow DNS which causes timeouts."
echo ""
read -p "Configure Google DNS for your network interface? (y/n): " CONFIGURE_DNS

if [ "$CONFIGURE_DNS" = "y" ]; then
    # Get the default network interface
    DEFAULT_IF=$(ip route | grep default | awk '{print $5}' | head -1)
    echo "Detected network interface: $DEFAULT_IF"
    read -p "Use this interface? (y/n): " USE_DEFAULT_IF
    
    if [ "$USE_DEFAULT_IF" = "y" ]; then
        sudo resolvectl dns "$DEFAULT_IF" 8.8.8.8 8.8.4.4
        echo -e "${GREEN}DNS configured to use Google DNS (8.8.8.8)${NC}"
        echo -e "${YELLOW}Note: This is temporary and will reset on reboot.${NC}"
        echo "To make permanent, see README.md DNS Setup section."
    fi
fi

# Step 11: Test the daemon
echo ""
echo -e "${GREEN}Step 11: Testing the daemon...${NC}"
echo "Running a single sync cycle..."

cd "$REPO_ROOT"
source venv/bin/activate
source "$ENV_FILE"
python scripts/scraper/daemon.py --once
echo -e "${GREEN}Test completed!${NC}"

# Step 12: Set up systemd service
echo ""
echo -e "${YELLOW}Step 12: systemd Service Setup${NC}"
echo ""
read -p "Do you want to install the systemd service? (y/n): " INSTALL_SERVICE

if [ "$INSTALL_SERVICE" = "y" ]; then
    # Create service file from template
    SERVICE_FILE="/tmp/news-scraper.service"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Hong Kong Fire Documentary News Scraper Daemon
After=network-online.target
Wants=network-online.target

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
echo "  source ~/.scraper_env"
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
