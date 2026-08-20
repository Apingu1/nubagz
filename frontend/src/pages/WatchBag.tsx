import { useEffect, useState } from 'react'
import { ArrowRight, Bookmark, BookmarkX, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

type Watched={id:number;campaign_id:number;title:string;project_name:string;symbol:string;category:string;reward_asset:string;user_reward:string;status:string;watchable:boolean;watchability_reason:string;verified_funding:string|null;remaining_reward_inventory:string;spots_left:number;watched_at:string;reservation:boolean}

export default function WatchBag(){const [rows,setRows]=useState<Watched[]>([]);const [msg,setMsg]=useState('');const load=()=>api<Watched[]>('/watchbag').then(setRows);useEffect(()=>{load()},[])
 const remove=async(id:number)=>{try{await api(`/watchbag/${id}`,{method:'DELETE'});setMsg('Removed from WatchBag.');load()}catch(e:any){setMsg(e.message||'Could not remove Bag')}}
 return <div className="page"><div className="page-head"><div><span className="eyebrow small">WATCHBAG</span><h1>Save the Bagz worth <em>watching.</em></h1><p>Keep a personal shortlist of live funded opportunities and see their current reward inventory, availability and remaining spots.</p></div></div>{msg&&<div className="form-note">{msg}</div>}
 <section className="panel"><div className="panel-head"><div><span><Bookmark/> YOUR WATCHLIST</span><h2>Saved opportunities</h2></div></div>{rows.length?rows.map(r=><div className="activity-row" key={r.id}><div><span>{r.category} • ${r.symbol} • {r.status}</span><strong>{r.title} — {r.project_name}</strong><small>{r.user_reward} {r.reward_asset} user reward • {r.spots_left.toLocaleString()} spots left</small><small>{r.watchability_reason} • {Number(r.remaining_reward_inventory).toLocaleString(undefined,{maximumFractionDigits:8})} {r.reward_asset} verified campaign inventory remaining</small></div><b>{r.watchable?'WATCHING':'PAUSED'}</b><div className="row-actions"><Link className="mini-action" to={`/app/bagz/${r.campaign_id}`}>Open <ArrowRight/></Link><button className="mini-action" onClick={()=>remove(r.campaign_id)}><BookmarkX/> Remove</button></div></div>):<div className="empty-state"><Bookmark/><strong>Your WatchBag is empty.</strong><p>Open a funded Bag and tap Watch Bag to save it here.</p></div>}</section>
 <div className="custody-note"><ShieldCheck/><p>Watching a Bag is only a saved-interest signal. It does not enroll you, reserve a place or reward, move funds, or imply investment intent. Availability always reflects current verified campaign inventory.</p></div></div>
}
