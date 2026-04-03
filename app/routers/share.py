from __future__ import annotations

import io
import json
import math
import secrets

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.core.database import execute, fetch_one
from app.core.deps import CurrentUser

router = APIRouter(tags=["share"])


# ── Generate share token ──


@router.post("/submissions/{submission_id}/share")
def create_share_link(submission_id: str, current_user: CurrentUser) -> dict:
    """Generate a public share link for a scored submission."""
    sub = fetch_one(
        "SELECT id, user_id, status, share_token FROM submissions WHERE id = ?",
        (submission_id,),
    )
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    if sub["user_id"] != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your submission")
    if sub["status"] != "scored":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Submission must be scored before sharing")

    # Reuse existing token if already shared
    if sub["share_token"]:
        return {"share_token": sub["share_token"], "share_url": f"https://app.kodwai.com/s/{sub['share_token']}"}

    token = secrets.token_urlsafe(8)
    execute("UPDATE submissions SET share_token = ? WHERE id = ?", (token, submission_id))
    return {"share_token": token, "share_url": f"https://app.kodwai.com/s/{token}"}


# ── Public share data ──


@router.get("/share/{share_token}")
def get_share_data(share_token: str) -> dict:
    """Get public submission data for a shared score card. No auth required."""
    row = fetch_one(
        """SELECT s.id, s.score, s.score_breakdown, s.agent_used, s.time_taken_ms,
                  s.started_at, s.submitted_at,
                  c.title as challenge_title, c.slug as challenge_slug,
                  c.difficulty as challenge_difficulty, c.category as challenge_category,
                  c.time_limit_minutes as challenge_time_limit_minutes,
                  u.username, u.name as user_name,
                  dp.total_score, dp.challenges_completed, dp.rank
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           JOIN users u ON s.user_id = u.id
           LEFT JOIN developer_profiles dp ON s.user_id = dp.user_id
           WHERE s.share_token = ? AND s.status = 'scored'""",
        (share_token,),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared submission not found")

    data = dict(row)
    breakdown = json.loads(data["score_breakdown"]) if data.get("score_breakdown") else None
    time_min = round(data["time_taken_ms"] / 60000) if data.get("time_taken_ms") else None

    return {
        "challenge_title": data["challenge_title"],
        "challenge_slug": data["challenge_slug"],
        "challenge_difficulty": data["challenge_difficulty"],
        "challenge_category": data["challenge_category"],
        "score": data["score"],
        "objective_score": breakdown.get("objective", {}).get("total") if breakdown else None,
        "analytical_score": breakdown.get("analytical", {}).get("total") if breakdown else None,
        "strengths": breakdown.get("analytical", {}).get("strengths", []) if breakdown else [],
        "agent_used": data["agent_used"],
        "time_minutes": time_min,
        "time_limit_minutes": data["challenge_time_limit_minutes"],
        "username": data["username"],
        "user_name": data["user_name"],
        "rank": data["rank"],
    }


# ── OG Image Generation ──


def _draw_score_card_image(data: dict) -> bytes:
    """Render a 1200x630 OG image for the score card using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), color=(250, 248, 244))  # cream
    draw = ImageDraw.Draw(img)

    # Colors
    ink = (26, 26, 26)
    muted = (154, 148, 138)
    rust = (194, 54, 22)
    border = (228, 224, 216)
    green = (34, 197, 94)
    amber = (245, 158, 11)

    score = data.get("score", 0) or 0
    score_color = green if score >= 70 else amber if score >= 50 else rust

    # Try to load fonts, fall back to default
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", 64)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 18)
        font_tiny = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_tiny = ImageFont.load_default()

    # Border
    draw.rectangle([0, 0, W - 1, H - 1], outline=border, width=2)

    # Top bar
    draw.text((48, 36), "kodwai", fill=ink, font=font_medium)

    difficulty = data.get("challenge_difficulty", "").upper()
    diff_color = {"EASY": green, "MEDIUM": amber, "HARD": rust}.get(difficulty, muted)
    draw.text((W - 48 - len(difficulty) * 12, 40), difficulty, fill=diff_color, font=font_small)

    # Divider
    draw.line([(48, 80), (W - 48, 80)], fill=border, width=1)

    # Challenge title
    title = data.get("challenge_title", "Challenge")
    if len(title) > 40:
        title = title[:37] + "..."
    draw.text((48, 100), title, fill=ink, font=font_medium)

    # Score circle area (left side)
    cx, cy = 180, 320
    r = 90
    # Background circle
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=border, width=6)
    # Score arc
    angle = (score / 100) * 360
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=-90, end=-90 + angle, fill=score_color, width=8)
    # Score text
    score_text = str(round(score))
    bbox = draw.textbbox((0, 0), score_text, font=font_large)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 10), score_text, fill=score_color, font=font_large)
    draw.text((cx - 12, cy + 40), "/100", fill=muted, font=font_tiny)

    # Stats (right side)
    stats_x = 340
    stats_y = 180

    # Objective score bar
    obj_score = data.get("objective_score")
    if obj_score is not None:
        draw.text((stats_x, stats_y), "OBJECTIVE", fill=muted, font=font_tiny)
        draw.text((stats_x + 400, stats_y), f"{obj_score:.0f}/85", fill=ink, font=font_tiny)
        bar_y = stats_y + 24
        draw.rectangle([stats_x, bar_y, stats_x + 500, bar_y + 8], fill=border)
        bar_w = min((obj_score / 85) * 500, 500)
        draw.rectangle([stats_x, bar_y, stats_x + bar_w, bar_y + 8], fill=ink)
        stats_y += 56

    # Analytical score bar
    ana_score = data.get("analytical_score")
    if ana_score is not None:
        draw.text((stats_x, stats_y), "AI ANALYSIS", fill=muted, font=font_tiny)
        draw.text((stats_x + 400, stats_y), f"{ana_score:.0f}/100", fill=ink, font=font_tiny)
        bar_y = stats_y + 24
        draw.rectangle([stats_x, bar_y, stats_x + 500, bar_y + 8], fill=border)
        bar_w = min((ana_score / 100) * 500, 500)
        draw.rectangle([stats_x, bar_y, stats_x + bar_w, bar_y + 8], fill=ink)
        stats_y += 56

    # Agent and time
    agent = data.get("agent_used", "Unknown")
    time_min = data.get("time_minutes")

    draw.text((stats_x, stats_y + 10), "AGENT", fill=muted, font=font_tiny)
    draw.text((stats_x + 100, stats_y + 10), agent, fill=ink, font=font_small)

    if time_min is not None:
        draw.text((stats_x + 350, stats_y + 10), "TIME", fill=muted, font=font_tiny)
        draw.text((stats_x + 420, stats_y + 10), f"{time_min} min", fill=ink, font=font_small)

    # Top strength
    strengths = data.get("strengths", [])
    if strengths:
        draw.text((stats_x, stats_y + 60), "TOP STRENGTH", fill=muted, font=font_tiny)
        strength_text = strengths[0]
        if len(strength_text) > 60:
            strength_text = strength_text[:57] + "..."
        draw.text((stats_x, stats_y + 82), f"+ {strength_text}", fill=(22, 163, 74), font=font_tiny)

    # Bottom bar
    draw.line([(48, H - 60), (W - 48, H - 60)], fill=border, width=1)

    username = data.get("username")
    if username:
        draw.text((48, H - 44), f"@{username}", fill=muted, font=font_tiny)

    draw.text((W - 48 - 80, H - 44), "kodwai.com", fill=muted, font=font_tiny)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


@router.get("/share/{share_token}/og")
def get_og_image(share_token: str) -> Response:
    """Generate OG image for a shared score card. Returns 1200x630 PNG."""
    row = fetch_one(
        """SELECT s.score, s.score_breakdown, s.agent_used, s.time_taken_ms,
                  c.title as challenge_title, c.difficulty as challenge_difficulty,
                  c.time_limit_minutes,
                  u.username
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           JOIN users u ON s.user_id = u.id
           WHERE s.share_token = ? AND s.status = 'scored'""",
        (share_token,),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    data = dict(row)
    breakdown = json.loads(data["score_breakdown"]) if data.get("score_breakdown") else None
    time_min = round(data["time_taken_ms"] / 60000) if data.get("time_taken_ms") else None

    card_data = {
        "challenge_title": data["challenge_title"],
        "challenge_difficulty": data["challenge_difficulty"],
        "score": data["score"],
        "objective_score": breakdown.get("objective", {}).get("total") if breakdown else None,
        "analytical_score": breakdown.get("analytical", {}).get("total") if breakdown else None,
        "strengths": breakdown.get("analytical", {}).get("strengths", []) if breakdown else [],
        "agent_used": data["agent_used"],
        "time_minutes": time_min,
        "username": data["username"],
    }

    image_bytes = _draw_score_card_image(card_data)
    return Response(content=image_bytes, media_type="image/png", headers={
        "Cache-Control": "public, max-age=86400",
    })
