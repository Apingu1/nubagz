import { useEffect, useMemo, useState } from 'react'
import { Bell, CheckCheck, Circle, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { BagZMascot } from '../components/BagZMascot'
import { api } from '../lib/api'

type Notice={id:number;type:string;title:string;message:string;link_path:string|null;read:boolean;created_at:string;read_at:string|null}
type Payload={unread_count:number;total_count:number;notifications:Notice[]}

export default function Notifications(){
 const [d,setD]=useState<Payload|null>(null);const [msg,setMsg]=useState('');const [error,setError]=useState('');const [filter,setFilter]=useState<'ALL'|'UNREAD'>('ALL')
 const load=()=>api<Payload>('/notifications').then(data=>{setD(data);setError('')}).catch((e:any)=>setError(e.message||'Could not load notifications'))
 useEffect(()=>{load()},[])
 const read=async(id:number)=>{try{await api(`/notifications/${id}/read`,{method:'POST'});load()}catch(e:any){setMsg(e.message||'Could not mark notification read')}}
 const readAll=async()=>{try{const out=await api<{marked_read:number}>('/notifications/read-all',{method:'POST'});setMsg(`${out.marked_read} notification${out.marked_read===1?'':'s'} marked read.`);load()}catch(e:any){setMsg(e.message||'Could not mark notifications read')}}
 const visible=useMemo(()=>d?.notifications.filter(n=>filter==='ALL'||!n.read)??[],[d,filter])
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">NOTIFICATIONS</span><h1>Your NuBagz <em>signal feed.</em></h1><p>Private account events derived from real rewards, approvals and review outcomes. Read state is persisted per account, and no cross-account activity is exposed here.</p></div><button className="btn primary" disabled={!d?.unread_count} onClick={readAll}><CheckCheck/> Mark all read</button></div>{msg&&<div className="form-note">{msg}</div>}{error&&<div className="form-error bag-z-inline-state"><BagZMascot variant="confused"/><span>{error}</span></div>}
 <div className="stats-grid"><div className="stat-card hot"><span><Bell/>UNREAD</span><strong>{d?.unread_count??'—'}</strong><small>Needs your attention</small></div><div className="stat-card"><span>TOTAL</span><strong>{d?.total_count??'—'}</strong><small>Latest 100 persisted events</small></div></div>
 <section className="panel"><div className="panel-head"><div><span>INBOX</span><h2>Account activity</h2></div><div className="row-actions"><button className="mini-action" disabled={filter==='ALL'} onClick={()=>setFilter('ALL')}>All</button><button className="mini-action" disabled={filter==='UNREAD'} onClick={()=>setFilter('UNREAD')}>Unread {d?.unread_count??0}</button></div></div>{visible.length?visible.map(n=><div className="activity-row" key={n.id}><div><span>{n.type} • {new Date(n.created_at).toLocaleString()}</span><strong>{n.title}</strong><small>{n.message}</small></div><b>{n.read?'READ':'NEW'}</b><div className="row-actions">{!n.read&&<button className="mini-action" onClick={()=>read(n.id)}><Circle/> Read</button>}{n.link_path&&<Link className="mini-action" to={n.link_path} onClick={()=>{if(!n.read)void read(n.id)}}>Open <ExternalLink/></Link>}</div></div>):<div className="empty-state bag-z-empty-state"><BagZMascot variant={filter==='UNREAD'?'victory':'sleepy'}/><strong>{filter==='UNREAD'?'No unread notifications.':'No notifications yet.'}</strong><p>{filter==='UNREAD'?'You are all caught up.':'Real account events will appear here as your NuBagz activity grows.'}</p></div>}</section></div>
}
