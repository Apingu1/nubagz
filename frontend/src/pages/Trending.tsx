import { useEffect, useState } from 'react'
import { ArrowRight, Flame, ShieldCheck, Users, WalletCards } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Bag={campaign_id:number;title:string;project_name:string;symbol:string;category:string;reward_asset:string;user_reward:string;estimated_value_gbp:string|null;recent_enrollments:number;recent_completions:number;recent_verified_reviews:number;recent_onchain_verifications:number;repeat_participants:number;project_trust_score:number;project_trust_level:string;trend_score:number;quality_score:number;window_days:number;why_trending:string}
type Payload={window_days:number;bagz:Bag[];method:string}

export default function Trending(){const [d,setD]=useState<Payload|null>(null);const [days,setDays]=useState(7);const load=(windowDays=days)=>api<Payload>(`/trending?days=${windowDays}`).then(setD);useEffect(()=>{load(7)},[])
 const changeWindow=(value:number)=>{setDays(value);load(value)}
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">TRENDING BAGZ</span><h1>Momentum from <em>real participation.</em></h1><p>See which funded Bagz are attracting genuine joins, completions, verified reviews and on-chain participation. Paid or featured placement does not inflate this ranking.</p></div></div>
 <div className="row-actions"><button className={`mini-action ${days===1?'active':''}`} onClick={()=>changeWindow(1)}>24h</button><button className={`mini-action ${days===7?'active':''}`} onClick={()=>changeWindow(7)}>7 days</button><button className={`mini-action ${days===30?'active':''}`} onClick={()=>changeWindow(30)}>30 days</button></div>
 <section className="panel"><div className="panel-head"><div><span><Flame/> LAST {d?.window_days||days} DAYS</span><h2>Trending now</h2></div></div>{d?.bagz.length?d.bagz.map((b,i)=><div className="activity-row" key={b.campaign_id}><div><span>#{i+1} • {b.category} • ${b.symbol}</span><strong>{b.title} — {b.project_name}</strong><small>{b.why_trending}</small><small>Trust {b.project_trust_level} ({b.project_trust_score}/100) • {b.recent_onchain_verifications} on-chain verification{b.recent_onchain_verifications===1?'':'s'} • {b.repeat_participants} repeat participant{b.repeat_participants===1?'':'s'}</small></div><div><b>{b.user_reward} {b.reward_asset}</b><small>{b.estimated_value_gbp?`~£${Number(b.estimated_value_gbp).toFixed(2)} tracked value`:''}</small></div><small><Users/> momentum {b.trend_score} • <WalletCards/> quality {b.quality_score}</small><Link className="mini-action" to={`/app/bagz/${b.campaign_id}`}>Open <ArrowRight/></Link></div>):<div className="empty-state"><Flame/><strong>No eligible trending Bagz right now.</strong><p>Only live, funded opportunities you can actually access appear here.</p></div>}</section>
 {d?.method&&<div className="custody-note"><ShieldCheck/><p>{d.method}</p></div>}</div>
}
