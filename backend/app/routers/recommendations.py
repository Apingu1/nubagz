from collections import Counter
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Campaign, Project, Enrollment
from ..economy_models import CampaignAccessRule
from ..risk_models import UserTrustProfile
from .daily import campaign_is_eligible
from .trust import project_trust

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])
PUBLIC_PROJECT_STATUSES={"LIVE","APPROVED"}
METHOD="Explainable rules-based ranking using verified funding, hard eligibility/access gates, reward value, participation history, difficulty fit, continuation state and Project Trust signals. Wallet wealth and token balances are not ranking inputs."

def difficulty_fit(user:User,difficulty:str)->tuple[int,str|None]:
    diff=(difficulty or "EASY").upper()
    if user.bag_score<200 and diff=="EASY":return 10,"Beginner-friendly for your current BagScore"
    if 200<=user.bag_score<600 and diff in {"EASY","MEDIUM"}:return 8,"Difficulty fits your current BagScore"
    if user.bag_score>=600 and diff in {"MEDIUM","HARD"}:return 8,"Higher-trust challenge fits your BagScore"
    return 0,None

@router.get("/me")
def my_recommendations(db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    trust_profile=db.query(UserTrustProfile).filter(UserTrustProfile.user_id==user.id).first()
    if trust_profile and trust_profile.trust_level=="RESTRICTED":return {"bag_score":user.bag_score,"history_categories":[],"recommendations":[],"restricted":True,"method":METHOD}
    enrollment_rows=db.query(Enrollment,Campaign).join(Campaign,Campaign.id==Enrollment.campaign_id).filter(Enrollment.user_id==user.id).all();completed_rows=[(e,c) for e,c in enrollment_rows if e.status=="COMPLETED"];completed_ids={e.campaign_id for e,_ in completed_rows};active_enrollment_ids={e.campaign_id for e,_ in enrollment_rows if e.status!="COMPLETED"};category_counts=Counter(c.category for _,c in completed_rows)
    campaigns=db.query(Campaign).filter(Campaign.status=="LIVE").order_by(Campaign.featured.desc(),Campaign.created_at.desc()).all();recommendations=[]
    for campaign in campaigns:
        if campaign.id in completed_ids or not campaign_is_eligible(db,user,campaign):continue
        enrolled_count=db.query(func.count(Enrollment.id)).filter(Enrollment.campaign_id==campaign.id).scalar() or 0;already_enrolled=campaign.id in active_enrollment_ids
        if enrolled_count>=campaign.max_users and not already_enrolled:continue
        available_slots=max(0,campaign.max_users-enrolled_count);project=db.get(Project,campaign.project_id)
        if not project or project.status not in PUBLIC_PROJECT_STATUSES:continue
        score=10;reasons=["Verified reward inventory is available"]
        if already_enrolled:score+=30;reasons.append("Continue a Bag you already started")
        if campaign.featured:score+=25;reasons.append("Featured funded opportunity")
        estimated_user_gbp=None
        if campaign.estimated_value_gbp is not None:
            estimated_user_gbp=Decimal(campaign.estimated_value_gbp)*Decimal(campaign.user_share_pct)/Decimal("100");score+=min(25,max(1,int(estimated_user_gbp*Decimal("10"))));reasons.append(f"Tracked user reward value ~£{estimated_user_gbp.quantize(Decimal('0.01'))}")
        if category_counts[campaign.category]>0:score+=min(20,10+category_counts[campaign.category]*3);reasons.append(f"Matches your {campaign.category.title()} participation history")
        elif category_counts:score+=5;reasons.append("Adds a new category to your Bag history")
        fit_points,fit_reason=difficulty_fit(user,campaign.difficulty);score+=fit_points
        if fit_reason:reasons.append(fit_reason)
        access=db.query(CampaignAccessRule).filter(CampaignAccessRule.campaign_id==campaign.id).first();min_bag_score=access.min_bag_score if access else 0
        if min_bag_score>0:score+=5;reasons.append(f"You meet the BagScore {min_bag_score}+ gate")
        else:score+=3;reasons.append("Open BagScore access")
        trust=project_trust(project,db);score+=min(15,trust["score"]//7);reasons.append(f"Project Trust signal: {trust['level']} ({trust['score']}/100)")
        recommendations.append({"campaign_id":campaign.id,"title":campaign.title,"project_name":project.name,"project_symbol":project.symbol,"category":campaign.category,"difficulty":campaign.difficulty,"reward_asset":campaign.reward_asset,"user_reward":str(Decimal(campaign.gross_reward_per_user)*Decimal(campaign.user_share_pct)/Decimal("100")),"estimated_value_gbp":str(estimated_user_gbp) if estimated_user_gbp is not None else None,"recommendation_score":score,"project_trust_score":trust["score"],"access_min_bag_score":min_bag_score,"already_enrolled":already_enrolled,"available_slots":available_slots,"reasons":reasons[:7]})
    recommendations.sort(key=lambda item:(-item["recommendation_score"],-(Decimal(item["estimated_value_gbp"]) if item["estimated_value_gbp"] else Decimal("0")),item["campaign_id"]))
    return {"bag_score":user.bag_score,"history_categories":[{"category":category,"completed":count} for category,count in category_counts.most_common()],"recommendations":recommendations[:12],"restricted":False,"method":METHOD}
