import { NavLink } from 'react-router-dom'
import { LayoutDashboard, ShieldCheck, UsersRound } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export function AdminNav(){
  const {user}=useAuth()
  const linkClass=({isActive}:{isActive:boolean})=>isActive?'admin-subnav-link active':'admin-subnav-link'
  const fullAdmin=user?.role==='ADMIN'
  return <nav className="admin-subnav" aria-label={fullAdmin?'Admin workspace navigation':'Support investigation navigation'}>
    {fullAdmin&&<NavLink to="/app/admin" end className={linkClass}><LayoutDashboard size={16}/><span>Overview</span></NavLink>}
    <NavLink to="/app/admin/users" className={linkClass}><UsersRound size={16}/><span>Users & Trust</span></NavLink>
    {fullAdmin&&<NavLink to="/app/admin/security" className={linkClass}><ShieldCheck size={16}/><span>Security & Audit</span></NavLink>}
  </nav>
}