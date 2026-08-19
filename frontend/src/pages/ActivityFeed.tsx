import { useEffect, useState } from 'react'
import { Activity, ArrowRight, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Event={event_type:string;username:string;headline:string;detail:string;project_name:string;campaign_id:number|null;link_path:string;occurred_at:string}
type Payload={events:Event[];privacy:string}

export default function ActivityFeed(){const [d,setD]=useState<Payload|null>(null);useEffect(()=>{api<Payload>('/activity?limit=60').then(setD)},[])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">COMMUNITY ACTIVITY</span><h1>See what people are <em>actually doing.</em></h1><p>Real funded completions, BagDrop claims and verified participant reviews—without exposing private wallets or balances.</p></div></div>
 <section className="panel"><div className="panel-head"><div><span>LIVE SIGNALS</span><h2>Recent participation</h2></div></div>{d?.events.length?d.events.map((e,i)=><div className="activity-row" key={`${e.event_type}-${e.username}-${e.occurred_at}-${i}`}><div><span>{e.event_type.replaceAll('_',' ')} • {new Date(e.occurred_at).toLocaleString()}</span><strong>{e.headline}</strong><small>{e.detail}</small></div><b>{e.project_name}</b><Link className="mini-action" to={e.link_path}>Open <ArrowRight/></Link></div>):<div className="empty-state"><Activity/><strong>No community events yet.</strong><p>Completed funded participation will appear here.</p></div>}</section>
 {d?.privacy&&<div className="custody-note"><ShieldCheck/><p>{d.privacy}</p></div>}</div>
}