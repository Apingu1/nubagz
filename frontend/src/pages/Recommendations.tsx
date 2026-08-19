import { useEffect, useState } from 'react'
import { ArrowRight, BrainCircuit, ShieldCheck, Sparkles, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Recommendation={campaign_id:number;title:string;project_name:string;project_symbol:string;category:string;difficulty:string;reward_asset:string;user_reward:string;estimated_value_gbp:string|null;recommendation_score:number;project_trust_score:number;reasons:string[]}
type Payload={bag_score:number;history_categories:{category:string;completed:number}[];recommendations:Recommendation[];restricted:boolean;method:string}

export default function Recommendations(){const [d,setD]=useState<Payload|null>(null);useEffect(()=>{api<Payload>('/recommendations/me').then(setD)},[])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">FOR YOU</span><h1>Better Bagz, <em>explained.</em></h1><p>NuBagz ranks opportunities you can actually access and tells you why each one surfaced. Funding and eligibility come before recommendation score.</p></div></div>
 <div className="stats-grid"><div className="stat-card hot"><span><Target/>BAGSCORE</span><strong>{d?.bag_score??'—'}</strong><small>Used for access and difficulty fit</small></div><div className="stat-card"><span><Sparkles/>RECOMMENDATIONS</span><strong>{d?.recommendations.length??'—'}</strong><small>Eligible funded Bagz only</small></div><div className="stat-card"><span><BrainCircuit/>HISTORY SIGNALS</span><strong>{d?.history_categories.length??'—'}</strong><small>Completed categories, not personal data sales</small></div></div>
 {d?.restricted&&<div className="form-error">Recommendations are paused while this account is Restricted for trust review.</div>}
 <section className="panel"><div className="panel-head"><div><span>EXPLAINABLE RANKING</span><h2>Your best next Bagz</h2></div></div>{d?.recommendations.length?d.recommendations.map((r,i)=><div className="activity-row" key={r.campaign_id}><div><span>#{i+1} • {r.category} • {r.difficulty}</span><strong>{r.title} — {r.project_name}</strong><small>{r.reasons.join(' • ')}</small></div><b>{r.user_reward} {r.reward_asset}</b><small>{r.estimated_value_gbp?`~£${Number(r.estimated_value_gbp).toFixed(2)} • score ${r.recommendation_score}`:`score ${r.recommendation_score}`}</small><Link className="mini-action" to={`/app/bagz/${r.campaign_id}`}>Open <ArrowRight/></Link></div>):<div className="empty-state"><Sparkles/><strong>No eligible recommendations right now.</strong><p>NuBagz will not recommend an unfunded, completed or inaccessible Bag just to fill this screen.</p></div>}</section>
 {d?.method&&<div className="custody-note"><ShieldCheck/><p><strong>How ranking works:</strong> {d.method}</p></div>}</div>
}