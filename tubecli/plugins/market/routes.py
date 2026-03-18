"""
Marketplace API routes.
"""
from fastapi import APIRouter
from typing import Optional

router = APIRouter(prefix="/api/v1/market", tags=["market"])

COMMUNITY_SKILLS = [
    {"id": "youtube-uploader", "name": "🎬 YouTube Uploader", "author": "community", "desc": "Auto upload videos with SEO", "type": "community"},
    {"id": "tiktok-poster", "name": "📱 TikTok Poster", "author": "community", "desc": "Post content to TikTok", "type": "community"},
    {"id": "email-sender", "name": "📧 Email Sender", "author": "community", "desc": "Batch email sending with templates", "type": "community"},
    {"id": "web-scraper", "name": "🕷️ Web Scraper", "author": "official", "desc": "Extract data from websites", "type": "official"},
    {"id": "social-poster", "name": "📤 Social Poster", "author": "community", "desc": "Post to multiple social platforms", "type": "community"},
    {"id": "seo-analyzer", "name": "🔍 SEO Analyzer", "author": "official", "desc": "Analyze website SEO metrics", "type": "official"},
]


@router.get("/skills")
async def list_market_skills(q: Optional[str] = None):
    skills = COMMUNITY_SKILLS
    if q:
        ql = q.lower()
        skills = [s for s in skills if ql in s["name"].lower() or ql in s["desc"].lower()]
    return {"skills": skills, "count": len(skills)}


@router.post("/install/{skill_id}")
async def install_market_skill(skill_id: str):
    skill = next((s for s in COMMUNITY_SKILLS if s["id"] == skill_id), None)
    if not skill:
        from fastapi import HTTPException
        raise HTTPException(404, f"Skill '{skill_id}' not found")
    return {"status": "installed", "skill": skill}
