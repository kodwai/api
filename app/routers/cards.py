from __future__ import annotations
import html
from fastapi import APIRouter, HTTPException, Response, status
from app.core.database import fetch_one
from app.services.tiers import tier_for

router = APIRouter(tags=["cards"])


@router.get("/developers/{username}/card.svg")
def developer_card(username: str) -> Response:
    row = fetch_one(
        """SELECT u.name, u.username, dp.direction_rating, dp.rank,
                  dp.challenges_completed, dp.streak_days
           FROM users u JOIN developer_profiles dp ON dp.user_id = u.id
           WHERE u.username = ?""",
        (username,),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")
    rating = row["direction_rating"] or 1000
    tier = tier_for(rating)
    name = html.escape(row["name"] or row["username"] or "developer")
    uname = html.escape(row["username"] or "")
    rank = row["rank"]
    rank_s = f"#{rank}" if rank else "—"
    svg = _render_card(name, uname, rating, tier, rank_s,
                       row["challenges_completed"] or 0, row["streak_days"] or 0)
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


def _render_card(name, uname, rating, tier, rank_s, challenges, streak) -> str:
    W, H = 480, 150
    tc = tier["color"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img">
  <rect width="{W}" height="{H}" rx="10" fill="#faf8f4" stroke="#e7e2d9"/>
  <rect x="0" y="0" width="6" height="{H}" rx="3" fill="{tc}"/>
  <text x="24" y="38" font-family="Georgia,'Times New Roman',serif" font-size="22" fill="#1a1a1a">{name}</text>
  <text x="24" y="58" font-family="ui-monospace,Menlo,monospace" font-size="12" fill="#8a8a8a">@{uname}</text>
  <text x="24" y="100" font-family="Georgia,serif" font-size="40" fill="{tc}">{rating}</text>
  <text x="24" y="120" font-family="ui-monospace,monospace" font-size="11" fill="#8a8a8a" letter-spacing="1">DIRECTION RATING</text>
  <rect x="270" y="22" width="186" height="28" rx="14" fill="{tc}"/>
  <text x="363" y="41" text-anchor="middle" font-family="ui-monospace,monospace" font-size="13" fill="#ffffff" letter-spacing="1">{tier['name'].upper()}</text>
  <text x="270" y="92" font-family="ui-monospace,monospace" font-size="12" fill="#1a1a1a">RANK {rank_s}</text>
  <text x="270" y="112" font-family="ui-monospace,monospace" font-size="12" fill="#1a1a1a">{challenges} solved · {streak}d streak</text>
  <text x="270" y="134" font-family="ui-monospace,monospace" font-size="10" fill="#c2410c" letter-spacing="1">kodwai.com</text>
</svg>"""
