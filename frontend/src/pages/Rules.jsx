import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function RulesPage() {
  const [cats, setCats] = useState([])
  const [active, setActive] = useState(0)
  const [selectedRow, setSelectedRow] = useState(null)
  const [edit, setEdit] = useState(null)   // {plain: {}, json: {}}
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  useEffect(() => {
    api.listRules().then((d) => {
      setCats(d.categories || [])
    }).catch((e) => setError(e.message))
  }, [])

  const cat = cats[active]

  function openRow(row) {
    setSelectedRow(row)
    const plain = {}
    cat.plain_fields.forEach((f) => { plain[f] = row[f] ?? '' })
    const json = {}
    cat.json_fields.forEach(([f]) => {
      const v = row[f]
      json[f] = typeof v === 'string' ? v : JSON.stringify(v ?? {}, null, 2)
    })
    setEdit({ plain, json })
    setSaved('')
  }

  async function save() {
    if (!edit || !selectedRow) return
    setError('')
    try {
      const updated = await api.updateRule(cat.table, selectedRow[cat.pk], {
        plain: edit.plain, json_fields: edit.json,
      })
      setSelectedRow(updated)
      // 刷新列表行
      const d = await api.listRules()
      setCats(d.categories)
      setSaved(`已保存（${cat.key} #${selectedRow[cat.pk]}）——规则即时生效`)
    } catch (err) { setError(err.message) }
  }

  if (!cat) return <div className="content"><p>加载中…</p></div>

  return (
    <div className="rules">
      <h2>规则库维护（质控权限：仅管理员，保存即时生效）</h2>
      {error && <p className="error">{error}</p>}
      {saved && <p className="saved">{saved}</p>}
      <div className="rules-layout">
        <aside className="rule-nav">
          {cats.map((c, i) => (
            <button key={c.key} className={i === active ? 'tab-active' : ''}
                    onClick={() => { setActive(i); setSelectedRow(null); setEdit(null) }}>
              {c.key}
            </button>
          ))}
        </aside>
        <div className="rule-body">
          <table className="data-table">
            <thead>
              <tr>
                {cat.columns.map(([f, label]) => <th key={f}>{label}</th>)}
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {cat.rows.map((row) => (
                <tr key={row[cat.pk]} className={selectedRow && selectedRow[cat.pk] === row[cat.pk] ? 'row-selected' : ''}>
                  {cat.columns.map(([f]) => <td key={f}>{String(row[f] ?? '')}</td>)}
                  <td><button className="link" onClick={() => openRow(row)}>编辑</button></td>
                </tr>
              ))}
              {cat.rows.length === 0 && <tr><td colSpan={cat.columns.length + 1} className="empty">无数据</td></tr>}
            </tbody>
          </table>

          {edit && (
            <div className="rule-edit">
              <h3>编辑 #{(selectedRow || {})[cat.pk]}（{cat.key}）</h3>
              <div className="form-grid">
                {cat.plain_fields.map((f) => (
                  <label key={f}>{f}
                    <input value={edit.plain[f] ?? ''}
                           onChange={(e) => setEdit((s) => ({ ...s, plain: { ...s.plain, [f]: e.target.value } }))} />
                  </label>
                ))}
              </div>
              {cat.json_fields.map(([f, label]) => (
                <div key={f} className="json-edit">
                  <label>{label}（JSON，保存时校验语法）</label>
                  <textarea rows={6} value={edit.json[f] ?? ''}
                            onChange={(e) => setEdit((s) => ({ ...s, json: { ...s.json, [f]: e.target.value } }))} />
                </div>
              ))}
              <div className="form-actions">
                <button onClick={save}>保存规则</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
