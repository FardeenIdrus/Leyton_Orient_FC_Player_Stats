"""Render the PLAYER PROFILE headlessly -- the path AppTest missed before."""
import datetime, sys
import sqlalchemy as sa
from streamlit.testing.v1 import AppTest
from lofc.config import settings

e = sa.create_engine(settings.database_url)
# Lyall Cameron: assessed, signed off, with prose written.
row = e.connect().execute(sa.text(
    "select a.player_id, a.competition_id, a.season_id, m.player_name, m.position_group "
    "from scout_assessments a join player_metrics_neutral m "
    "  on m.player_id=a.player_id and m.competition_id=a.competition_id "
    " and m.season_id=a.season_id where a.id=65")).one()
pid, cid, sid, name, pos = row
print(f"opening profile: {name} ({pos}, league {cid}, season {sid})")

at = AppTest.from_file("/app/src/lofc/dashboard/app.py", default_timeout=300)
for k, v in {"user_id": 1, "full_name": "Check", "role": "admin",
             "logged_in_at": datetime.datetime.now(),
             "sidebar_season": sid, "sidebar_position": pos,
             "_open_player": (pid, cid, sid)}.items():
    at.session_state[k] = v
at.run()
if at.exception:
    for x in at.exception:
        print("EXCEPTION:", x.value)
    sys.exit(1)
print("metrics rendered:", len(at.metric))
for m in at.metric:
    print(f"   {m.label:12} {m.value:>6}   delta={m.delta}")
print("expanders:", [x.label for x in at.expander][:6])
print("PROFILE RENDERED CLEAN")
