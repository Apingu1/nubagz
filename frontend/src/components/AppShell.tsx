import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Compass, LayoutDashboard, Trophy, BriefcaseBusiness, Shield, LogOut, WalletCards, Zap, BadgePoundSterling, Gift, CalendarDays, RadioTower } from 'lucide-react'
import { Logo } from './Logo'
import { useAuth } from '../context/AuthContext'

export default function AppShell(){
 const {user,logout}=useAuth(); const nav=useNavigate()
 const items=[['/app','Home',LayoutDashboard],['/app/daily','Daily Earn',CalendarDays],['/app/discover','Discover',Compass],['/app/drops','BagDrops',Gift],['/app/onchain','Onchain Lab',RadioTower],['/app/earnings','Earnings',BadgePoundSterling],['/app/bag','My Bag',WalletCards],['/app/leaderboard','Leaderboard',Trophy],['/app/studio','Creator Studio',BriefcaseBusiness]] as const
 return <div className="app-shell">
  <aside className="sidebar">
    <Logo/><div className="side-kicker">EARN YOUR WAY IN</div>
    <nav>{items.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/app'} className={({isActive})=>isActive?'side-link active':'side-link'}><Icon size={18}/><span>{label}</span></NavLink>)}
      {user?.role==='ADMIN'&&<NavLink to="/app/admin" className={({isActive})=>isActive?'side-link active':'side-link'}><Shield size={18}/>Admin</NavLink>}
    </nav>
    <div className="sidebar-bottom">
      <div className="mini-profile"><div className="avatar">{user?.username?.slice(0,2).toUpperCase()}</div><div><strong>{user?.username}</strong><small>BagScore {user?.bag_score}</small></div></div>
      <button className="icon-btn" onClick={()=>{logout();nav('/')}}><LogOut size={18}/></button>
    </div>
  </aside>
  <main className="app-main"><div className="mobile-top"><Logo/><div className="pulse-pill"><Zap size={14}/> {user?.streak_days} day streak</div></div><Outlet/></main>
 </div>
}
