import { ArrowUpRight, Clock3, Users, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Campaign } from '../types'

const gradients=['g1','g2','g3','g4','g5']
export default function BagCard({campaign,index=0,to}:{campaign:Campaign;index?:number;to?:string}){
 const remaining=Math.max(0,campaign.max_users-campaign.enrolled_count)
 const userReward=Number(campaign.gross_reward_per_user)*Number(campaign.user_share_pct)/100
 return <Link to={to||'/app/work?view=all'} className="bag-card">
   <div className={`bag-visual ${gradients[index%gradients.length]}`}><div className="orb"></div><div className="token-badge">{campaign.project?.symbol?.slice(0,4)||campaign.reward_asset.slice(0,4)}</div>{campaign.featured&&<span className="featured"><Sparkles size={12}/> FEATURED</span>}</div>
   <div className="bag-card-body"><div className="project-line"><span>{campaign.project?.name}</span><b>{campaign.project?.chain}</b></div><h3>{campaign.title}</h3><p>{campaign.description}</p>
   <div className="reward-box"><small>YOU CAN BAG</small><strong>{userReward.toLocaleString(undefined,{maximumFractionDigits:4})} {campaign.reward_asset}</strong>{campaign.estimated_value_gbp&&<em>~£{Number(campaign.estimated_value_gbp)*0.8}</em>}</div>
   <div className="card-meta"><span><Clock3 size={14}/>{Math.max(1,(campaign.challenges?.length||campaign.missions.length))*2+2} min</span><span><Users size={14}/>{remaining.toLocaleString()} spots</span><span className="go">View Bag Work <ArrowUpRight size={15}/></span></div></div>
 </Link>
}
