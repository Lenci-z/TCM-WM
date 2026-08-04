import React, { useState, useEffect } from 'react'
import { api, getToken, clearToken } from './api.js'
import LoginPage from './pages/Login.jsx'
import PatientsPage from './pages/Patients.jsx'

// 极简 hash 路由：login / patients（后续 B-T3~B-T7 扩充视图）
function route() {
  return window.location.hash.replace(/^#/, '') || '/patients'
}

export default function App() {
  const [hash, setHash] = useState(route())
  const [user, setUser] = useState(null)

  useEffect(() => {
    const onHash = () => setHash(route())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (getToken()) {
      api.me().then(setUser).catch(() => setUser(null))
    }
  }, [hash])

  // 未登录 → 登录页
  if (!getToken()) {
    return <LoginPage onLogin={(u) => { setUser(u); window.location.hash = '#/patients' }} />
  }

  const logout = () => { clearToken(); setUser(null); window.location.hash = '#/login' }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">中西医结合心血管康复全程管理系统</span>
        <span className="user">
          {user ? `${user.display_name || user.username} ｜ ${user.role}` : ''}
          <button className="link" onClick={logout}>退出</button>
        </span>
      </header>
      <nav className="nav">
        <a className={hash.startsWith('/patients') ? 'active' : ''} href="#/patients">患者管理</a>
        {/* B-T3~B-T7 视图占位 */}
        <span className="disabled">评估录入</span>
        <span className="disabled">处方管理</span>
        <span className="disabled">随访管理</span>
        <span className="disabled">预警处理</span>
        <span className="disabled">规则库</span>
      </nav>
      <main className="content">
        {hash.startsWith('/patients') ? <PatientsPage /> : <PatientsPage />}
      </main>
    </div>
  )
}
