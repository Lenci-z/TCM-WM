import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const LEVEL_CLASS = { '红': 'risk-high', '黄': 'risk-mid', '蓝': 'risk-low' }

export default function AlertsPage() {
  const [tab, setTab] = useState('open')   // open=待处置 / all=全部
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setRows(await api.listAlerts(tab))
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [tab])

  async function handle(a) {
    const content = window.prompt(`处置预警 #${a.alert_id}（${a.rule_name}）：\n请输入处置内容`, '')
    if (content === null) return
    if (!content.trim()) { setError('处置内容不能为空'); return }
    try {
      await api.handleAlert(a.alert_id, { content: content.trim() })
      load()
    } catch (err) { setError(err.message) }
  }

  const openCount = tab === 'all' ? rows.filter((r) => r.status === '待处置').length : rows.length

  return (
    <div className="alerts">
      <h2>预警管理（分级联动患者/评估/处方，处置留痕）</h2>
      {error && <p className="error">{error}</p>}
      <div className="tabs">
        <button className={tab === 'open' ? 'tab-active' : ''} onClick={() => setTab('open')}>待处置</button>
        <button className={tab === 'all' ? 'tab-active' : ''} onClick={() => setTab('all')}>全部历史（{openCount} 条待处置）</button>
      </div>

      <table className="data-table">
        <thead>
          <tr><th>ID</th><th>级别</th><th>规则</th><th>患者</th><th>触发时间</th><th>详情</th><th>状态</th><th>处置人</th><th>操作</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.alert_id}>
              <td>{a.alert_id}</td>
              <td><span className={LEVEL_CLASS[a.level] || ''}><strong>{a.level}</strong></span></td>
              <td>{a.rule_name}</td>
              <td>{a.patient_name || `#${a.patient_id}`}</td>
              <td>{a.alert_date || a.trigger_time}</td>
              <td>{a.detail}</td>
              <td>{a.status}</td>
              <td>{a.handler || ''}</td>
              <td>
                {a.status === '待处置' && (
                  <button className="link" onClick={() => handle(a)}>处置</button>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan="9" className="empty">{tab === 'open' ? '暂无待处置预警' : '暂无预警记录'}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
