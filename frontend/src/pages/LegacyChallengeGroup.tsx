import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, Layers3, ShieldCheck } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { formatTokenAmount } from '../lib/formatToken'
import type { Campaign, ChallengeFeed } from '../types'

type Bundle={joined:boolean;enrollment_status:string|null;earned_amount:string;completed_count:number;total_count:number;challenges:ChallengeFeed[]}

export default function LegacyChallengeGroup(){
 const {id}=useParams();const [params]=useSearchParams();const rawReturn=params.get('return')||'';const returnPath=rawReturn.startsWith('/app/')?rawReturn:'/app/work?view=all'
 const [campaign,setCampaign]=useState<Campaign|null>(null);const [bundle,setBundle]=useState<Bundle|null>(null);const [message,setMessage]=useState('')
 useEffect(()=>{Promise.all([api<Campaign>(`/campaigns/${id}`),api<Bundle>(`/challenges/campaigns/${id}`)]).then(([c,b])=>{setCampaign(c);setBundle(b)}).catch((e:any)=>setMessage(e.message||'Could not load this compatibility record.'))},[id])
 if(!campaign||!bundle)return <div className="page"><Link to={returnPath} className="back-link"><ArrowLeft/> Back</Link>{message?<div className="form-note">{message}</div>:<div className="skeleton detail"/>}</div>
 const userReward=Number(campaign.gross_reward_per_user)*Number(campaign.user_share_pct)/100
 return <div className="page"><Link to={returnPath} className="back-link"><ArrowLeft/> Back to Bag Work</Link><div className="page-head"><div><span className="eyebrow small">PRE-V2 COMPATIBILITY</span><h1>Grouped Challenge <em>record.</em></h1><p>This historical reward definition contains multiple linked Challenge requirements. New V2 work is always Project → one independent Challenge.</p></div></div>
 <div className="custody-note"><ShieldCheck/><p><strong>Why this page exists:</strong> historical completions and reward obligations are preserved rather than rewritten. The grouped container remains internal compatibility plumbing until the Phase 3 Challenge schema migration.</p></div>
 <div className="stats-grid"><div className="stat-card"><span><Layers3/>LINKED REQUIREMENTS</span><strong>{bundle.total_count}</strong><small>{bundle.completed_count} verified for your account</small></div><div className="stat-card hot"><span>PROJECT REWARD</span><strong>{formatTokenAmount(String(userReward))}</strong><small>{campaign.reward_asset} after all linked requirements are verified</small></div><div className="stat-card"><span>STATUS</span><strong>{bundle.enrollment_status||'NOT JOINED'}</strong><small>Open any requirement below to join or continue</small></div></div>
 <section className="panel"><div className="panel-head"><div><span>LINKED CHALLENGES</span><h2>Continue each requirement individually</h2></div></div>{bundle.challenges.map((row,index)=>{const done=row.completion_status==='VERIFIED'||row.completion_status==='APPROVED';return <div className="activity-row" key={row.id}><div><span>Requirement {index+1} • {row.category.replaceAll('_',' ')} • {row.verification_type.replaceAll('_',' ')}</span><strong>{row.title}</strong><small>{row.description}</small></div><b>{done?<><CheckCircle2/> VERIFIED</>:(row.completion_status||'OPEN')}</b><Link className="mini-action" to={`/app/challenges/${row.id}?return=${encodeURIComponent(`/app/bagz/${id}`)}`}>Open Challenge <ArrowRight/></Link></div>})}</section></div>
}
