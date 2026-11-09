#!/bin/bash
# Double-click this file to update TickerChatter and open the website.
cd "$(dirname "$0")"
source venv/bin/activate
echo "Installing what the pipeline needs..."
pip install -q -r requirements.txt
if [ -f data/headlines.json ]; then
  python -m pipeline.run
else
  python -m pipeline.run --backfill
fi
echo ""
echo "Opening the site at http://localhost:8000 (close this window to stop it)."
(sleep 1; open "http://localhost:8000") &
python -m http.server 8000 --directory site
