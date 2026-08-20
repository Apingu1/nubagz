import { useEffect, useState } from 'react'
import { ArrowRight, CalendarDays, Gift, Sparkles, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Opportunity={type:'CAMPAIGN'|'BAGDROP';id:number;title:string;category:string;reward:string;estimated_value_gbp:string|null;featured:boolean}
type Daily={estimated_available_gbp:string;opportunity_count:number;campaign_count:number;bagdrop_count:number;opportunities:Opportunity[]}

export default function DailyEarn(){const [d,setD]=useState<Daily|null>(null);useEffect(()=>{api<Daily>('/daily/earn').then(setD)},[])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">DAILY EARN</span><h1>What can you Bag <em>today?</em></h1><p>A personalised earning radar that removes opportunities you already completed and prioritises funded value.</p></div></div>
 <div className="stats-grid"><div className="stat-card hot"><span><Zap/>TRACKED VALUE AVAILABLE</span><strong>£{Number(d?.estimated_available_gbp||0).toFixed(2)}</strong><small>Only opportunities with a GBP estimate/feed</small></div><div className="stat-card"><span><CalendarDays/>OPPORTUNITIES</span><strong>{d?.opportunity_count??'—'}</strong><small>Available right now</small></div><div className="stat-card"><span><Sparkles/>FUNDED BAGZ</span><strong>{d?.campaign_count??'—'}</strong><small>Campaign pathways</small></div><div className="stat-card"><span><Gift/>BAGDROPS</span><strong>{d?.bagdrop_count??'—'}</strong><small>Claimable reward drops</small></div></div>
 <section className="panel"><div className="panel-head"><div><span>YOUR EARNING RADAR</span><h2>Best opportunities now</h2></div></div>{d?.opportunities.length?d.opportunities.map(o=><div className="activity-row" key={`${o.type}-${o.id}`}><div><span>{o.type==='BAGDROP'?'BAGDROP':o.category}</span><strong>{o.title}</strong></div><b>{o.reward}</b><small>{o.estimated_value_gbp?`~£${Number(o.estimated_value_gbp).toFixed(2)}`:'Value not tracked'}</small><Link className="mini-action" to={o.type==='BAGDROP'?'/app/drops':`/app/bagz/${o.id}`}>Earn <ArrowRight/></Link></div>):<div className="empty-state"><Sparkles/><strong>You’re caught up.</strong><p>No eligible funded opportunities are available right now. Check back when new Bagz drop.</p></div>}</section></div>
}
