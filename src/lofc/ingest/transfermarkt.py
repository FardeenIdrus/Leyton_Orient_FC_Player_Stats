"""Download the Transfermarkt market-value data (players + valuations).

Market value is our valuation target, and StatsBomb has none, so we bring it in here.
Public, auth-free source: the maintained dcaribou dataset's hosting bucket. If that URL
ever breaks, the same files are on Kaggle (davidcariboo/player-scores) and data.world.

Files arrive gzipped and land decompressed in data/reference/transfermarkt/ (gitignored,
since they are large external data, re-downloadable any time).

Run with:  python -m lofc.ingest.transfermarkt
"""

from __future__ import annotations

import gzip
import urllib.request
from pathlib import Path

from lofc.config import settings

BASE_URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
# appearances lets us scope matching to players who actually played in our leagues
# that season, which avoids matching short names to same-named lesser players.
FILES = ["players.csv", "player_valuations.csv", "appearances.csv"]


def target_dir() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt"


def download(force: bool = False) -> None:
    out = target_dir()
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = out / name
        if dest.exists() and not force:
            print(f"  {name} already present, skipping")
            continue
        print(f"  downloading {name} ...")
        # The bucket rejects the default Python user-agent, so send a normal one.
        request = urllib.request.Request(
            f"{BASE_URL}/{name}.gz", headers={"User-Agent": "Mozilla/5.0 (lofc-recruitment)"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            data = gzip.decompress(response.read())
        dest.write_bytes(data)
        print(f"  wrote {dest} ({len(data) // 1024} KB)")


def main() -> None:
    print(f"Transfermarkt data -> {target_dir()}")
    download()


if __name__ == "__main__":
    main()
