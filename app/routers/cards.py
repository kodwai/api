from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Response, status

from app.core.database import fetch_one
from app.services.tiers import tier_for

router = APIRouter(tags=["cards"])

_THEMES = {"dark", "light", "gradient"}


@router.get("/developers/{username}/card.svg")
def developer_card(username: str, theme: str = "dark") -> Response:
    """Public embeddable rank card. ?theme=dark|light|gradient (default dark)."""
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
    ctx = {
        "name": name, "uname": uname, "rating": rating, "tier": tier,
        "rank_s": rank_s, "solved": row["challenges_completed"] or 0,
        "streak": row["streak_days"] or 0,
    }
    renderer = {"dark": _render_dark, "light": _render_light, "gradient": _render_gradient}.get(
        theme if theme in _THEMES else "dark", _render_dark
    )
    return Response(content=renderer(**ctx), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})


def _progress_fill(tier: dict, barw: int) -> int:
    return max(8, int(barw * (tier.get("progress") or 0.0)))


# ── Theme: dark (GitHub-native) ──
def _render_dark(name, uname, rating, tier, rank_s, solved, streak) -> str:
    W, H, pad = 500, 200, 28
    tc = tier["color"]
    barw = W - 2 * pad
    fillw = _progress_fill(tier, barw)
    nxt = (f"{rating} / {tier['next_at']} → {tier['next_name']}"
           if tier.get("next_name") else "MAX TIER")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" fill="#0d1117" stroke="#30363d"/>
  <rect x="0" y="0" width="5" height="{H}" rx="2.5" fill="{tc}"/>
  <text x="{pad}" y="46" font-size="20" font-weight="700" fill="#e6edf3">kodwai</text>
  <text x="{pad+72}" y="46" font-size="11" fill="#8b949e" letter-spacing="1">RANK CARD</text>
  <rect x="{W-pad-118}" y="28" width="118" height="26" rx="13" fill="{tc}"/>
  <text x="{W-pad-59}" y="45" text-anchor="middle" font-size="12" font-weight="700" fill="#0d1117" letter-spacing="1.5">{tier['name'].upper()}</text>
  <text x="{pad}" y="108" font-size="52" font-weight="800" fill="{tc}">{rating}</text>
  <text x="{pad}" y="128" font-size="10" fill="#8b949e" letter-spacing="2">DIRECTION RATING</text>
  <text x="{W-pad}" y="92" text-anchor="end" font-size="15" font-weight="600" fill="#e6edf3">{name}</text>
  <text x="{W-pad}" y="110" text-anchor="end" font-size="12" fill="#8b949e">@{uname}</text>
  <text x="{W-pad}" y="132" text-anchor="end" font-size="12" fill="#adbac7">RANK {rank_s} · {solved} solved · {streak}d streak</text>
  <rect x="{pad}" y="158" width="{barw}" height="7" rx="3.5" fill="#21262d"/>
  <rect x="{pad}" y="158" width="{fillw}" height="7" rx="3.5" fill="{tc}"/>
  <text x="{pad}" y="186" font-size="10" fill="#8b949e">{tier['name']}</text>
  <text x="{W-pad}" y="186" text-anchor="end" font-size="10" fill="#8b949e">{nxt}</text>
</svg>"""


# ── Theme: light (kodwai brand) ──
def _render_light(name, uname, rating, tier, rank_s, solved, streak) -> str:
    W, H, pad = 500, 200, 30
    tc = tier["color"]
    barw = W - 2 * pad
    fillw = _progress_fill(tier, barw)
    nxt = f"{tier['name']} → {tier['next_name']}" if tier.get("next_name") else f"{tier['name']} (max tier)"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img">
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="12" fill="#faf8f4" stroke="#e7e2d9"/>
  <text x="{pad}" y="44" font-family="Georgia,'Times New Roman',serif" font-size="21" fill="#1a1a1a">{name}</text>
  <text x="{pad}" y="62" font-family="ui-monospace,Menlo,monospace" font-size="11" fill="#9a9388">@{uname}</text>
  <rect x="{W-pad-120}" y="26" width="120" height="28" rx="6" fill="{tc}"/>
  <text x="{W-pad-60}" y="45" text-anchor="middle" font-family="ui-monospace,monospace" font-size="12" font-weight="700" fill="#ffffff" letter-spacing="2">{tier['name'].upper()}</text>
  <line x1="{pad}" y1="78" x2="{W-pad}" y2="78" stroke="#e7e2d9"/>
  <text x="{pad}" y="128" font-family="Georgia,serif" font-size="50" fill="{tc}">{rating}</text>
  <text x="{pad}" y="146" font-family="ui-monospace,monospace" font-size="10" fill="#9a9388" letter-spacing="2">DIRECTION RATING</text>
  <text x="{W-pad}" y="108" text-anchor="end" font-family="ui-monospace,monospace" font-size="13" fill="#1a1a1a">RANK {rank_s}</text>
  <text x="{W-pad}" y="128" text-anchor="end" font-family="ui-monospace,monospace" font-size="12" fill="#6b6b6b">{solved} solved · {streak}d streak</text>
  <rect x="{pad}" y="160" width="{barw}" height="6" rx="3" fill="#ece7dd"/>
  <rect x="{pad}" y="160" width="{fillw}" height="6" rx="3" fill="{tc}"/>
  <text x="{pad}" y="186" font-family="ui-monospace,monospace" font-size="9" fill="#9a9388">{nxt}</text>
  <text x="{W-pad}" y="186" text-anchor="end" font-family="ui-monospace,monospace" font-size="9" fill="#c2410c" letter-spacing="1">kodwai.com</text>
</svg>"""


# ── Theme: gradient (header band) ──
def _render_gradient(name, uname, rating, tier, rank_s, solved, streak) -> str:
    W, H, pad = 500, 200, 28
    tc = tier["color"]
    barw = W - 2 * pad
    fillw = _progress_fill(tier, barw)
    nxt = f"NEXT: {tier['next_name']} ({tier['next_at']})" if tier.get("next_name") else "MAX TIER"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{tc}"/>
      <stop offset="1" stop-color="#1a1a1a"/>
    </linearGradient>
    <clipPath id="r"><rect x="0" y="0" width="{W}" height="{H}" rx="14"/></clipPath>
  </defs>
  <g clip-path="url(#r)">
    <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>
    <rect x="0" y="0" width="{W}" height="72" fill="url(#g)"/>
    <text x="{pad}" y="34" font-size="18" font-weight="700" fill="#ffffff">{name}</text>
    <text x="{pad}" y="54" font-family="ui-monospace,monospace" font-size="11" fill="#ffffffcc">@{uname}</text>
    <text x="{W-pad}" y="44" text-anchor="end" font-size="14" font-weight="800" fill="#ffffff" letter-spacing="2">{tier['name'].upper()}</text>
    <text x="{pad}" y="128" font-family="Georgia,serif" font-size="46" font-weight="800" fill="{tc}">{rating}</text>
    <text x="{pad}" y="146" font-family="ui-monospace,monospace" font-size="10" fill="#8a8a8a" letter-spacing="2">DIRECTION RATING</text>
    <g font-family="ui-monospace,monospace" text-anchor="end">
      <text x="{W-pad}" y="104" font-size="20" font-weight="700" fill="#1a1a1a">{rank_s}</text>
      <text x="{W-pad}" y="118" font-size="9" fill="#8a8a8a" letter-spacing="1">RANK</text>
      <text x="{W-pad-90}" y="104" font-size="20" font-weight="700" fill="#1a1a1a">{solved}</text>
      <text x="{W-pad-90}" y="118" font-size="9" fill="#8a8a8a" letter-spacing="1">SOLVED</text>
      <text x="{W-pad-170}" y="104" font-size="20" font-weight="700" fill="#1a1a1a">{streak}d</text>
      <text x="{W-pad-170}" y="118" font-size="9" fill="#8a8a8a" letter-spacing="1">STREAK</text>
    </g>
    <rect x="{pad}" y="170" width="{barw}" height="6" rx="3" fill="#eeeeee"/>
    <rect x="{pad}" y="170" width="{fillw}" height="6" rx="3" fill="{tc}"/>
    <text x="{pad}" y="166" font-family="ui-monospace,monospace" font-size="9" fill="#8a8a8a">{nxt}</text>
    <text x="{W-pad}" y="166" text-anchor="end" font-family="ui-monospace,monospace" font-size="9" fill="{tc}">kodwai.com</text>
  </g>
</svg>"""
