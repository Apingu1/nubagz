import { useEffect, useState } from 'react'
import { ArrowRight, Flame, ShieldCheck, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Bag={campaign_id:number;title:string;project_name:string;symbol:string;category:string;reward_asset:string;user_reward:string;recent_enrollments:number;recent_completions:number;recent_verified_reviews:number;trend_score:number;window_days:number;why_trending:string}
type Payload={window_days:number;bagz:Bag[];method:string}

export default function Trending(){const [d,setD]=useState<Payload|null>(null);useEffect(()=>{api<Payload>('/trending?days=7').then(setD)},[])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">TRENDING BAGZ</span><h1>Momentum from <em>real participation.</em></h1><p>See which funded Bagz are attracting genuine recent joins, completions and verified participant reviews. Featured placement does not inflate this ranking.</p></div></div>
 <section className="panel"><div className="panel-head"><div><span><Flame/> LAST {d?.window_days||7} DAYS</span><h2>Trending now</h2></div></div>{d?.bagz.length?d.bagz.map((b,i)=><div className="activity-row" key={b.campaign_id}><div><span>#{i+1} • {b.category} • ${b.symbol}</span><strong>{b.title} — {b.project_name}</strong><small>{b.why_trending}</small></div><b>{b.user_reward} {b.reward_asset}</b><small><Users/> score {b.trend_score}</small><Link className="mini-action" to={`/app/bagz/${b.campaign_id}`}>Open <ArrowRight/></Link></div>):<div className="empty-state"><Flame/><strong>No eligible trending Bagz right now.</strong><p>Only live, funded opportunities you can actually access appear here.</p></div>}</section>
 {d?.method&&<div className="custody-note"><ShieldCheck/><p>{d.method}</p></div>}</div>
}