import { useEffect, useState } from 'react'
import { Bell, CheckCheck, Circle, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Notice={id:number;type:string;title:string;message:string;link_path:string|null;read:boolean;created_at:string;read_at:string|null}
type Payload={unread_count:number;notifications:Notice[]}

export default function Notifications(){const [d,setD]=useState<Payload|null>(null);const [msg,setMsg]=useState('');const load=()=>api<Payload>('/notifications').then(setD);useEffect(()=>{load()},[])
 const read=async(id:number)=>{try{await api(`/notifications/${id}/read`,{method:'POST'});load()}catch(e:any){setMsg(e.message||'Could not mark notification read')}}
 const readAll=async()=>{try{const out=await api<{marked_read:number}>('/notifications/read-all',{method:'POST'});setMsg(`${out.marked_read} notification${out.marked_read===1?'':'s'} marked read.`);load()}catch(e:any){setMsg(e.message||'Could not mark notifications read')}}
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">NOTIFICATIONS</span><h1>Your NuBagz <em>signal feed.</em></h1><p>Private account events derived from real rewards, approvals and review outcomes. No cross-account activity is exposed here.</p></div><button className="btn primary" disabled={!d?.unread_count} onClick={readAll}><CheckCheck/> Mark all read</button></div>{msg&&<div className="form-note">{msg}</div>}
 <div className="stats-grid"><div className="stat-card hot"><span><Bell/>UNREAD</span><strong>{d?.unread_count??'—'}</strong><small>Needs your attention</small></div><div className="stat-card"><span>TOTAL</span><strong>{d?.notifications.length??'—'}</strong><small>Latest 100 persisted events</small></div></div>
 <section className="panel"><div className="panel-head"><div><span>INBOX</span><h2>Account activity</h2></div></div>{d?.notifications.length?d.notifications.map(n=><div className="activity-row" key={n.id}><div><span>{n.type} • {new Date(n.created_at).toLocaleString()}</span><strong>{n.title}</strong><small>{n.message}</small></div><b>{n.read?'READ':'NEW'}</b><div className="row-actions">{!n.read&&<button className="mini-action" onClick={()=>read(n.id)}><Circle/> Read</button>}{n.link_path&&<Link className="mini-action" to={n.link_path}>Open <ExternalLink/></Link>}</div></div>):<div className="empty-state"><Bell/><strong>No notifications yet.</strong><p>Real account events will appear here as your NuBagz activity grows.</p></div>}</section></div>}
