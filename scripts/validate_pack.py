"""Validate a game folder before uploading it to the server."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.packs import load_pack

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('folder')
    args = parser.parse_args()
    try:
        pack = load_pack(args.folder)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
    rounds = pack['questions']
    print(f"OK: {pack['title']}; questions={sum(q['type']=='question' for q in rounds)}, events={sum(q['type']=='event' for q in rounds)}")
