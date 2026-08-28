import { useEffect, useState } from 'react'
import { Activity, ArrowRight, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Event={event_id:string;event_type:string;username:string;headline:string;detail:string;project_name:string;campaign_id:number|null;link_path:string;occurred_at:string}
type Payload={events:Event[];selected_event_type:string|null;available_event_types:string[];privacy:string}

const LABELS:Record<string,string>={BAG_COMPLETED:'Challenge completions',BAGDROP_CLAIMED:'BagDrops'}

export default function ActivityFeed(){const [d,setD]=useState<Payload|null>(null);const [filter,setFilter]=useState('');const load=(type=filter)=>api<Payload>(`/activity?limit=60${type?`&event_type=${type}`:''}`).then(setD);useEffect(()=>{load('')},[])
 const choose=(value:string)=>{setFilter(value);load(value)}
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">COMMUNITY ACTIVITY</span><h1>See what people are <em>actually doing.</em></h1><p>Real verified Challenge completions and funded BagDrop claims—without exposing private wallets or balances.</p></div></div>
 <div className="row-actions"><button className={`mini-action ${filter===''?'active':''}`} onClick={()=>choose('')}>All</button>{(d?.available_event_types||Object.keys(LABELS)).map(type=><button key={type} className={`mini-action ${filter===type?'active':''}`} onClick={()=>choose(type)}>{LABELS[type]||type.replaceAll('_',' ')}</button>)}</div>
 <section className="panel"><div className="panel-head"><div><span>LIVE SIGNALS</span><h2>Recent participation</h2></div></div>{d?.events.length?d.events.map(e=><div className="activity-row" key={e.event_id}><div><span>{LABELS[e.event_type]||e.event_type.replaceAll('_',' ')} • {new Date(e.occurred_at).toLocaleString()}</span><strong>{e.headline}</strong><small>{e.detail}</small></div><b>{e.project_name}</b><Link className="mini-action" to={e.link_path}>Open <ArrowRight/></Link></div>):<div className="empty-state"><Activity/><strong>No community events here yet.</strong><p>Verified funded participation matching this filter will appear here.</p></div>}</section>
 {d?.privacy&&<div className="custody-note"><ShieldCheck/><p>{d.privacy}</p></div>}</div>
}
