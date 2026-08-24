import { useEffect, useMemo, useState } from 'react'
import { Search, SlidersHorizontal, Sparkles } from 'lucide-react'
import { api } from '../lib/api'
import type { Campaign } from '../types'
import BagCard from '../components/BagCard'

const cats=['ALL','DISCOVER','LEARN','PLAY','CREATE']
export default function Discover(){const [items,setItems]=useState<Campaign[]>([]);const [cat,setCat]=useState('ALL');const [q,setQ]=useState('');const [loading,setLoading]=useState(true)
 useEffect(()=>{api<Campaign[]>('/campaigns').then(setItems).finally(()=>setLoading(false))},[])
 const filtered=useMemo(()=>items.filter(c=>(cat==='ALL'||c.category===cat)&&(!q||`${c.title} ${c.description} ${c.project?.name} ${c.reward_asset} ${c.challenges?.map(w=>`${w.title} ${w.description}`).join(' ')||''}`.toLowerCase().includes(q.toLowerCase()))),[items,cat,q])
 return <div className="page"><div className="page-head marketplace"><div><span className="eyebrow small">THE BAG MARKET</span><h1>Find your <em>next Bag.</em></h1><p>Every reward shown here is backed by verified project reward inventory — not by your deposit. Project Trust remains separate from reward-funding verification.</p></div></div>
 <div className="market-toolbar"><div className="search-box"><Search/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search projects, tokens or Bag Work…"/></div><button className="filter-button"><SlidersHorizontal/> Filters</button></div>
 <div className="chips">{cats.map(c=><button key={c} className={cat===c?'chip active':'chip'} onClick={()=>setCat(c)}>{c==='ALL'?'All Bagz':c[0]+c.slice(1).toLowerCase()}</button>)}</div>
 {loading?<div className="loading-grid">{[1,2,3,4,5,6].map(x=><div className="skeleton" key={x}/>)}</div>:filtered.length?<div className="cards-grid market">{filtered.map((c,i)=><BagCard key={c.id} campaign={c} index={i}/>)}</div>:<div className="empty-market"><Sparkles/><h2>No Bagz match that signal.</h2><p>Try a different category or search term.</p></div>}
 </div>}
