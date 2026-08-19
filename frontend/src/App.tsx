import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Landing from './pages/Landing'
import Auth from './pages/Auth'
import WalletOnboarding from './pages/WalletOnboarding'
import AppShell from './components/AppShell'
import Dashboard from './pages/Dashboard'
import DailyEarn from './pages/DailyEarn'
import Discover from './pages/Discover'
import BagDetail from './pages/BagDetail'
import BagDrops from './pages/BagDrops'
import MyBag from './pages/MyBag'
import Earnings from './pages/Earnings'
import Leaderboard from './pages/Leaderboard'
import CreatorStudio from './pages/CreatorStudio'
import CreateProject from './pages/CreateProject'
import CreateCampaign from './pages/CreateCampaign'
import Admin from './pages/Admin'
import { useAuth } from './context/AuthContext'

function Protected({children}:{children:ReactNode}){const {user,loading}=useAuth();if(loading)return <div className="boot">NUBAGZ<span>↗</span></div>;return user?<>{children}</>:<Navigate to="/login" replace/>}
function AdminOnly(){const {user}=useAuth();return user?.role==='ADMIN'?<Admin/>:<Navigate to="/app" replace/>}
export default function App(){return <Routes><Route path="/" element={<Landing/>}/><Route path="/login" element={<Auth mode="login"/>}/><Route path="/register" element={<Auth mode="register"/>}/><Route path="/wallet-setup" element={<Protected><WalletOnboarding/></Protected>}/><Route path="/app" element={<Protected><AppShell/></Protected>}><Route index element={<Dashboard/>}/><Route path="daily" element={<DailyEarn/>}/><Route path="discover" element={<Discover/>}/><Route path="drops" element={<BagDrops/>}/><Route path="bagz/:id" element={<BagDetail/>}/><Route path="bag" element={<MyBag/>}/><Route path="earnings" element={<Earnings/>}/><Route path="leaderboard" element={<Leaderboard/>}/><Route path="studio" element={<CreatorStudio/>}/><Route path="studio/projects/new" element={<CreateProject/>}/><Route path="studio/campaigns/new" element={<CreateCampaign/>}/><Route path="admin" element={<AdminOnly/>}/></Route><Route path="*" element={<Navigate to="/"/>}/></Routes>}
