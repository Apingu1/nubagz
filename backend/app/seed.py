from datetime import datetime, UTC
from decimal import Decimal
from sqlalchemy.orm import Session
from .models import User, Project, Campaign, Mission
from .economy_models import CampaignFunding
from .security import hash_password
from .utils import unique_referral_code


def seed_demo(db: Session):
    if db.query(User).count() > 0:
        return
    admin = User(email="admin@demo.nubagz.com", username="NuBagzAdmin", password_hash=hash_password("Admin123!"), role="ADMIN", xp=5400, bag_score=930, streak_days=34, referral_code="NUBAGZ0001")
    creator = User(email="creator@demo.nubagz.com", username="FrostByte", password_hash=hash_password("Creator123!"), role="CREATOR", xp=2400, bag_score=720, streak_days=12, referral_code="FROST2048")
    user = User(email="demo@demo.nubagz.com", username="BagHunter", password_hash=hash_password("Demo123!"), role="USER", xp=1280, bag_score=485, streak_days=7, referral_code="BAGH4242")
    db.add_all([admin, creator, user]); db.flush()

    projects = [
        Project(owner_id=creator.id, name="Neon Frog", slug="neon-frog", symbol="NFROG", description="A community-powered meme ecosystem turning on-chain participation into playful social quests.", website="https://example.com", chain="Avalanche", status="APPROVED"),
        Project(owner_id=creator.id, name="Pixel Raiders", slug="pixel-raiders", symbol="RAID", description="A fast arcade crypto game where players collect loot, beat weekly bosses and earn cosmetic rewards.", website="https://example.com", chain="Avalanche", status="APPROVED"),
        Project(owner_id=creator.id, name="OrbitFi", slug="orbitfi", symbol="ORBIT", description="A beginner-friendly DeFi learning project built around small, understandable on-chain actions.", website="https://example.com", chain="Avalanche", status="APPROVED"),
        Project(owner_id=creator.id, name="Mochi Club", slug="mochi-club", symbol="MOCHI", description="A playful creator community rewarding memes, fan art and participation with community tokens.", website="https://example.com", chain="Solana", status="APPROVED"),
    ]
    db.add_all(projects); db.flush()

    specs = [
        (projects[0], "Enter the Neon Swamp", "Meet Neon Frog, learn the lore and earn your first NFROG Bag.", "DISCOVER", "NFROG", 5000000, 2500, 2000, Decimal("1.80"), True),
        (projects[1], "Beat the First Boss", "Play the first Pixel Raiders mission and prove you can survive the neon arena.", "PLAY", "RAID", 2500000, 600, 4000, Decimal("2.40"), True),
        (projects[2], "DeFi Without the Jargon", "Learn three core DeFi concepts and unlock an ORBIT starter allocation.", "LEARN", "ORBIT", 1800000, 300, 6000, Decimal("1.10"), False),
        (projects[3], "Meme Forge", "Create, vote and discover community memes. Earn MOCHI while you contribute.", "CREATE", "MOCHI", 7000000, 1400, 5000, Decimal("0.95"), False),
    ]
    for idx, (project, title, description, category, asset, allocation, gross, max_users, value, featured) in enumerate(specs):
        c = Campaign(project_id=project.id, title=title, description=description, category=category, difficulty="EASY" if idx != 1 else "MEDIUM", reward_asset=asset, funding_type="TOKEN", token_allocation=Decimal(allocation), gross_reward_per_user=Decimal(gross), user_share_pct=Decimal("80"), nubagz_share_pct=Decimal("15"), referral_share_pct=Decimal("5"), max_users=max_users, status="LIVE", featured=featured, estimated_value_gbp=value)
        db.add(c); db.flush()
        required = Decimal(gross) * Decimal(max_users)
        db.add(CampaignFunding(campaign_id=c.id, declared_amount=required, verified_amount=required, tx_hash=f"demo-seed-{c.id}", status="VERIFIED", verified_by_id=admin.id, verified_at=datetime.now(UTC)))
        missions = [
            Mission(campaign_id=c.id, title=f"Meet {project.name}", description="Read the quick project briefing and understand what makes this Bag different.", mission_type="LEARN", verification_type="SELF_ATTEST", xp_reward=60, position=0),
            Mission(campaign_id=c.id, title="Pass the signal check", description="Answer one simple question to show you understood the mission.", mission_type="QUIZ", verification_type="QUIZ", quiz_question=f"Which token powers the {project.name} Bag?", quiz_options=[asset, "BTC", "USDT", "NONE"], quiz_answer=asset, xp_reward=90, position=1),
            Mission(campaign_id=c.id, title="Lock in your Bag", description="Finish the pathway and add this project to your NuBagz history.", mission_type="DISCOVER", verification_type="SELF_ATTEST", xp_reward=120, position=2),
        ]
        db.add_all(missions)
    db.commit()
