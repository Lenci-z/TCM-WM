import React, { useState } from 'react'
import { api, setToken } from '../api.js'

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await api.login(username, password)
      setToken(data.token)
      onLogin(data)
    } catch (err) {
      setError(err.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={submit}>
        <h1>中西医结合心血管康复系统</h1>
        <p className="sub">中医证型 × 心血管危险分层 双轴驱动</p>
        <input value={username} onChange={(e) => setUsername(e.target.value)}
               placeholder="用户名" autoFocus />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
               placeholder="密码" />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>{loading ? '登录中…' : '登录'}</button>
      </form>
    </div>
  )
}
