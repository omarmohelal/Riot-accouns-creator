import { Component, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const EXPECTED_VERSION = '2.4.0'

const DEFAULT_SETTINGS = {
  count: 20, username_min: 6, username_max: 12, password_length: 12,
  use_fixed_password: false, password_fixed: '', concurrency: 3,
  use_proxies: false, target_region: ''
}

function normalizeApiError(payload, fallback = 'Request failed') {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  if (payload.error?.message) {
    const fieldText = Array.isArray(payload.error.fields) ? payload.error.fields.map(x => `${x.field}: ${x.message}`).join(' · ') : ''
    return fieldText ? `${payload.error.message} — ${fieldText}` : payload.error.message
  }
  if (typeof payload.detail === 'string') return payload.detail
  return fallback
}

async function apiFetch(url, options = {}) {
  let response
  const controller = new AbortController()
  const timeoutMs = Number(options.timeoutMs || 15000)
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  const { timeoutMs: _ignoredTimeout, ...fetchOptions } = options
  try {
    response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal, ...fetchOptions })
  } catch (networkError) {
    const timedOut = networkError?.name === 'AbortError'
    const error = new Error(timedOut ? `Local server request timed out after ${Math.round(timeoutMs / 1000)}s: ${url}` : 'Cannot reach the local server. Keep START.bat open and reload this page.')
    error.status = 0
    error.cause = networkError
    throw error
  } finally {
    window.clearTimeout(timer)
  }
  let payload = null
  try { payload = await response.json() } catch { payload = null }
  if (!response.ok) {
    let message = normalizeApiError(payload, `${response.status} ${response.statusText}`)
    const serverVersion = response.headers.get('X-RC-Version')
    const requestId = response.headers.get('X-Request-ID') || payload?.error?.request_id
    if (response.status === 404 && String(url).startsWith('/api/')) {
      message = `API route not found: ${String(url).split('?')[0]}. ${serverVersion ? `Server v${serverVersion}. ` : ''}This usually means an old Riot Creator server is still using the port. Close old START windows and run this build's START.bat.`
    }
    if (requestId) message += ` · Request ${requestId}`
    const error = new Error(message)
    error.status = response.status
    error.serverVersion = serverVersion
    throw error
  }
  return payload
}

function Button({ children, tone = 'cyan', className = '', ...props }) {
  const tones = {
    cyan: 'bg-cyan-500 hover:bg-cyan-400 text-slate-950',
    red: 'bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 text-red-300',
    green: 'bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-emerald-300',
    amber: 'bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300',
    slate: 'bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200',
  }
  return <button className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${tones[tone]} ${className}`} {...props}>{children}</button>
}

function StatCard({ label, value, tone = 'slate', hint }) {
  const tones = {
    slate: 'border-slate-800 bg-slate-900/70', cyan: 'border-cyan-500/20 bg-cyan-500/10',
    green: 'border-emerald-500/20 bg-emerald-500/10', red: 'border-red-500/20 bg-red-500/10',
    amber: 'border-amber-500/20 bg-amber-500/10', violet: 'border-violet-500/20 bg-violet-500/10'
  }
  return <div className={`rounded-xl border p-4 ${tones[tone]}`}><div className="text-xs uppercase tracking-wider text-slate-500">{label}</div><div className="mt-1 text-2xl font-bold">{value}</div>{hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}</div>
}

function Section({ title, subtitle, actions, children }) {
  return <div className="space-y-5"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="text-xl font-semibold text-slate-50">{title}</h2>{subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}</div>{actions && <div className="flex flex-wrap gap-2">{actions}</div>}</div>{children}</div>
}

function Modal({ title, children, onClose, wide = false }) {
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" onMouseDown={onClose}><div className={`max-h-[88vh] overflow-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl ${wide ? 'w-full max-w-4xl' : 'w-full max-w-xl'}`} onMouseDown={e => e.stopPropagation()}><div className="mb-4 flex items-center justify-between"><h3 className="text-lg font-semibold">{title}</h3><button onClick={onClose} className="rounded-lg px-3 py-1 text-slate-400 hover:bg-slate-800 hover:text-white">✕</button></div>{children}</div></div>
}

function Pager({ page, total, pageSize, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return <div className="flex items-center justify-between text-sm text-slate-500"><span>{total} total · page {page}/{pages}</span><div className="flex gap-2"><Button tone="slate" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button><Button tone="slate" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button></div></div>
}

function Field({ label, children }) {
  return <label className="block text-sm"><span className="mb-2 block text-slate-400">{label}</span>{children}</label>
}

const inputClass = 'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition focus:border-cyan-500'

function LoginPage({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setBusy(true); setError('')
    try {
      await apiFetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) })
      onLogin()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <div className="min-h-screen bg-slate-950 text-slate-100 grid place-items-center p-6"><div className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/80 p-7 shadow-2xl shadow-black/30"><div className="mb-7"><div className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-400">Owner Console</div><h1 className="mt-2 text-3xl font-bold">Riot Creator Control</h1><p className="mt-2 text-sm text-slate-500">Sign in to access the local workspace. Sessions use an HttpOnly cookie.</p></div><form onSubmit={submit} className="space-y-4"><Field label="Owner email"><input className={inputClass} value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" /></Field><Field label="Password"><input className={inputClass} type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" autoFocus /></Field>{error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>}<Button className="w-full py-3" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</Button></form></div></div>
}

function AppContent() {
  const [auth, setAuth] = useState('checking')
  const [runtimeError, setRuntimeError] = useState(null)
  const [serverOnline, setServerOnline] = useState(true)
  const [user, setUser] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [toast, setToast] = useState(null)
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [provider, setProvider] = useState({ service: 'capsolver', api_key: '', configured: false, masked: '' })
  const [emailStats, setEmailStats] = useState({ total: 0, available: 0, reserved: 0, used: 0, failed: 0 })
  const [proxyStats, setProxyStats] = useState({ total: 0, working: 0, unchecked: 0, by_region: {} })
  const [availableRegions, setAvailableRegions] = useState({})
  const [creation, setCreation] = useState({ active: false, total: 0, success: 0, failed: 0, pending: 0, by_region: {} })
  const [profiles, setProfiles] = useState([])
  const [recentJobs, setRecentJobs] = useState([])
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)

  const showToast = (message, type = 'info') => {
    setToast({ message, type }); window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => setToast(null), 4200)
  }

  const guarded = async (fn) => {
    try { return await fn() } catch (err) { if (err.status === 401) { setAuth('unauth'); setUser(null) } throw err }
  }

  const loadBootstrap = async () => {
    const data = await guarded(() => apiFetch('/api/bootstrap'))
    setUser(data.user); setSettings({ ...DEFAULT_SETTINGS, ...(data.settings || {}) })
    setProvider({ service: data.provider?.service || 'capsolver', api_key: '', configured: Boolean(data.provider?.configured), masked: data.provider?.masked || '' })
    setEmailStats(data.email_stats || {}); setProxyStats(data.proxy_stats || {}); setAvailableRegions(data.available_regions || {})
    setCreation(data.creation || {}); setProfiles(data.profiles || []); setRecentJobs(data.jobs || []); setAuth('ok')
  }

  useEffect(() => {
    let disposed = false
    const boot = async () => {
      try {
        const health = await apiFetch('/health')
        if (disposed) return
        if (health?.app !== 'riot-creator-control' || health?.version !== EXPECTED_VERSION) {
          setRuntimeError({
            title: 'Wrong or stale local server detected',
            message: `This frontend expects v${EXPECTED_VERSION}, but port ${window.location.port || '80'} returned ${health?.version ? `v${health.version}` : 'an unknown service'}. Close older START.bat windows and launch this folder again.`,
            actual: health?.version || 'unknown', expected: EXPECTED_VERSION,
          })
          return
        }
        setServerOnline(true)
        try { await apiFetch('/api/auth/me'); await loadBootstrap() }
        catch (err) { if (err.status === 401) setAuth('unauth'); else throw err }
      } catch (err) {
        if (!disposed) setRuntimeError({ title: 'Local server is unavailable', message: err.message, actual: 'offline', expected: EXPECTED_VERSION })
      }
    }
    boot()
    return () => { disposed = true }
  }, [])

  useEffect(() => {
    if (auth !== 'ok') return
    const timer = window.setInterval(async () => {
      try {
        const health = await apiFetch('/health')
        const ok = health?.version === EXPECTED_VERSION
        setServerOnline(ok)
        if (!ok) setRuntimeError({ title: 'Server version changed', message: `Expected v${EXPECTED_VERSION}, received ${health?.version || 'unknown'}. Restart this build.`, actual: health?.version || 'unknown', expected: EXPECTED_VERSION })
      } catch { setServerOnline(false) }
    }, 30000)
    return () => window.clearInterval(timer)
  }, [auth])

  useEffect(() => {
    if (auth !== 'ok') return
    let disposed = false; let pingTimer = null
    const connect = () => {
      if (disposed) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`); wsRef.current = ws
      ws.onopen = () => { pingTimer = window.setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send('ping') }, 20000) }
      ws.onmessage = ev => {
        try {
          const data = JSON.parse(ev.data)
          if (['status_update', 'account_created', 'creation_complete', 'creation_stopped'].includes(data.type)) {
            setCreation(prev => ({ ...prev, active: Boolean(data.active), total: data.total ?? prev.total, success: data.success ?? prev.success, failed: data.failed ?? prev.failed, pending: data.pending ?? prev.pending, by_region: data.by_region ?? prev.by_region }))
            if (data.email_accounts) setEmailStats(data.email_accounts)
          }
          if (data.type === 'creation_complete' || data.type === 'creation_stopped') refreshRecentJobs()
        } catch { /* ignore malformed event */ }
      }
      ws.onclose = e => { if (pingTimer) clearInterval(pingTimer); if (e.code === 4401) { setAuth('unauth'); return }; if (!disposed) reconnectRef.current = setTimeout(connect, 1500) }
    }
    connect()
    return () => { disposed = true; if (pingTimer) clearInterval(pingTimer); if (reconnectRef.current) clearTimeout(reconnectRef.current); wsRef.current?.close() }
  }, [auth])

  const refreshRecentJobs = async () => {
    try { const data = await guarded(() => apiFetch('/api/jobs?page_size=10')); setRecentJobs(data.items || data.jobs || []) } catch { /* ignore */ }
  }

  const logout = async () => { try { await apiFetch('/api/auth/logout', { method: 'POST' }) } catch { /* local logout anyway */ } setAuth('unauth'); setUser(null) }

  if (runtimeError) return <RuntimeErrorPage error={runtimeError} />
  if (auth === 'checking') return <div className="min-h-screen bg-slate-950 text-slate-500 grid place-items-center"><div className="text-center"><div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400"></div><div>Checking local server v{EXPECTED_VERSION}…</div></div></div>
  if (auth !== 'ok') return <LoginPage onLogin={() => loadBootstrap().catch(err => showToast(err.message, 'error'))} />

  const tabs = [
    ['dashboard','◫','Dashboard'], ['creation','▶','Creation'], ['emails','✉','Emails'], ['proxies','◎','Proxies'],
    ['settings','⚙','Settings'], ['provider','⌁','Provider'], ['results','▤','Results'], ['jobs','◷','Jobs'],
    ['audit','≡','Audit'], ['system','◉','System'], ['security','⌾','Security']
  ]

  return <div className="min-h-screen bg-slate-950 text-slate-100">
    {toast && <div className={`fixed right-4 top-4 z-[80] max-w-lg rounded-xl border px-4 py-3 text-sm shadow-2xl ${toast.type === 'error' ? 'border-red-400/40 bg-red-500/90' : toast.type === 'success' ? 'border-emerald-400/40 bg-emerald-500/90 text-slate-950' : 'border-cyan-400/40 bg-cyan-500/90 text-slate-950'}`}>{toast.message}</div>}
    <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur"><div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-4"><div><div className="text-xl font-bold"><span className="text-cyan-400">Riot</span> Creator Control <span className="ml-1 text-xs font-normal text-slate-600">v2.4</span></div><div className="mt-1 text-xs text-slate-600">Owner-only · SQLite · encrypted secrets · audit trail</div></div><div className="flex items-center gap-3"><div className={`hidden rounded-full border px-2.5 py-1 text-xs sm:block ${serverOnline?'border-emerald-500/20 bg-emerald-500/10 text-emerald-300':'border-red-500/20 bg-red-500/10 text-red-300'}`}>{serverOnline?'● Local server online':'● Server disconnected'}</div><div className="hidden text-right md:block"><div className="text-sm text-slate-300">{user?.email}</div><div className="text-xs text-slate-600">{creation.active ? 'Job running' : 'Idle'}</div></div><Button tone="slate" onClick={()=>window.location.reload()}>Reload</Button><Button tone="slate" onClick={logout}>Logout</Button></div></div></header>
    <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-5 px-5 py-6 lg:grid-cols-[220px_1fr]">
      <aside className="h-fit rounded-2xl border border-slate-800 bg-slate-900/60 p-2 lg:sticky lg:top-24">{tabs.map(([id,icon,label]) => <button key={id} onClick={() => setActiveTab(id)} className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition ${activeTab === id ? 'bg-cyan-500 text-slate-950' : 'text-slate-400 hover:bg-slate-800 hover:text-white'}`}><span className="w-5 text-center">{icon}</span><span>{label}</span></button>)}</aside>
      <main className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/40 p-5 sm:p-6">
        {activeTab === 'dashboard' && <Dashboard emailStats={emailStats} proxyStats={proxyStats} creation={creation} jobs={recentJobs} provider={provider} onNavigate={setActiveTab} />}
        {activeTab === 'creation' && <CreationPage settings={settings} creation={creation} provider={provider} emailStats={emailStats} proxyStats={proxyStats} onCreation={setCreation} showToast={showToast} guarded={guarded} />}
        {activeTab === 'emails' && <EmailsPage stats={emailStats} setStats={setEmailStats} showToast={showToast} guarded={guarded} />}
        {activeTab === 'proxies' && <ProxiesPage stats={proxyStats} setStats={data => { setProxyStats(data); setAvailableRegions(data.by_region || {}) }} availableRegions={availableRegions} showToast={showToast} guarded={guarded} />}
        {activeTab === 'settings' && <SettingsPage settings={settings} setSettings={setSettings} profiles={profiles} setProfiles={setProfiles} regions={availableRegions} showToast={showToast} guarded={guarded} />}
        {activeTab === 'provider' && <ProviderPage provider={provider} setProvider={setProvider} showToast={showToast} guarded={guarded} />}
        {activeTab === 'results' && <ResultsPage showToast={showToast} guarded={guarded} />}
        {activeTab === 'jobs' && <JobsPage showToast={showToast} guarded={guarded} />}
        {activeTab === 'audit' && <AuditPage guarded={guarded} />}
        {activeTab === 'system' && <SystemPage showToast={showToast} guarded={guarded} onReauth={() => setAuth('unauth')} />}
        {activeTab === 'security' && <SecurityPage showToast={showToast} guarded={guarded} />}
      </main>
    </div>
  </div>
}

function Dashboard({ emailStats, proxyStats, creation, jobs, provider, onNavigate }) {
  return <Section title="Control Center" subtitle="Everything important in one place."><div className="grid grid-cols-2 gap-3 xl:grid-cols-5"><StatCard label="Emails available" value={emailStats.available || 0} tone="green" /><StatCard label="Saved emails" value={emailStats.total || 0} /><StatCard label="Healthy proxies" value={`${proxyStats.working || 0}/${proxyStats.total || 0}`} tone="cyan" /><StatCard label="Provider" value={provider.configured ? 'Ready' : 'Missing'} tone={provider.configured ? 'green' : 'red'} /><StatCard label="Current job" value={creation.active ? 'Running' : 'Idle'} tone={creation.active ? 'cyan' : 'slate'} /></div><div className="grid gap-5 xl:grid-cols-2"><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><div className="mb-4 flex items-center justify-between"><h3 className="font-medium">Recent jobs</h3><button className="text-xs text-cyan-400" onClick={() => onNavigate('jobs')}>View all</button></div><div className="space-y-2">{jobs.length ? jobs.map(job => <div key={job.id} className="flex items-center justify-between rounded-lg bg-slate-900 px-3 py-2 text-sm"><div><div className="font-mono text-xs text-slate-300">{job.id}</div><div className="text-xs text-slate-600">{job.created_at}</div></div><div className="text-right"><div className={job.status === 'completed' ? 'text-emerald-400' : job.status === 'interrupted' ? 'text-amber-400' : 'text-cyan-400'}>{job.status}</div><div className="text-xs text-slate-600">{job.success_count}/{job.requested_count}</div></div></div>) : <div className="py-8 text-center text-sm text-slate-600">No jobs yet.</div>}</div></div><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h3 className="mb-4 font-medium">Live status</h3><div className="grid grid-cols-2 gap-3"><StatCard label="Processed" value={creation.total || 0} /><StatCard label="Success" value={creation.success || 0} tone="green" /><StatCard label="Failed" value={creation.failed || 0} tone="red" /><StatCard label="Pending" value={creation.pending || 0} tone="amber" /></div></div></div></Section>
}

function CreationPage({ settings, creation, provider, emailStats, proxyStats, onCreation, showToast, guarded }) {
  const start = async () => { try { const data = await guarded(() => apiFetch('/api/creation/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ count:settings.count, captcha_settings:{service:provider.service}, use_proxies:settings.use_proxies, concurrency:settings.concurrency, target_region:settings.target_region || null }) })); onCreation(prev => ({...prev, active:true, job_id:data.job_id,total:0,success:0,failed:0})); showToast(`Job ${data.job_id} started`, 'success') } catch(err){ showToast(err.message,'error') } }
  const stop = async () => { try { await guarded(() => apiFetch('/api/creation/stop',{method:'POST'})); onCreation(prev => ({...prev,active:false})); showToast('Stop requested','info') } catch(err){ showToast(err.message,'error') } }
  const blockers=[]; if(!provider.configured) blockers.push('Provider key is not configured'); if(emailStats.available < settings.count) blockers.push(`Need ${settings.count} available emails, only ${emailStats.available} available`); if(settings.use_proxies && proxyStats.working < 1) blockers.push('Proxy mode is enabled but there are no healthy proxies')
  return <Section title="Account Creation" subtitle="Run a saved configuration. Live events never stream stored passwords." actions={<Button tone={creation.active?'red':'cyan'} onClick={creation.active?stop:start} disabled={!creation.active && blockers.length>0}>{creation.active?'Stop safely':'Start creation'}</Button>}><div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><StatCard label="Requested" value={settings.count} /><StatCard label="Success" value={creation.success || 0} tone="green" /><StatCard label="Failed" value={creation.failed || 0} tone="red" /><StatCard label="Available emails" value={emailStats.available || 0} tone="cyan" /></div>{blockers.length>0 && !creation.active && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">{blockers.map(x => <div key={x}>• {x}</div>)}</div>}<div className="grid gap-4 md:grid-cols-2"><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h3 className="mb-3 font-medium">Saved run configuration</h3><dl className="space-y-2 text-sm">{[['Count',settings.count],['Concurrency',settings.concurrency],['Username length',`${settings.username_min}–${settings.username_max}`],['Password',settings.use_fixed_password?'Fixed':'Generated'],['Proxies',settings.use_proxies?'Enabled':'Disabled'],['Region',settings.target_region || 'Any']].map(([k,v]) => <div key={k} className="flex justify-between border-b border-slate-800/70 pb-2"><dt className="text-slate-500">{k}</dt><dd>{v}</dd></div>)}</dl></div><div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"><h3 className="mb-3 font-medium">Job state</h3><div className={`rounded-lg p-4 text-sm ${creation.active?'bg-cyan-500/10 text-cyan-300':'bg-slate-900 text-slate-500'}`}>{creation.active ? `Running ${creation.job_id || ''}` : 'No active job. Refreshing the browser does not delete job history.'}</div></div></div></Section>
}

function EmailsPage({ stats, setStats, showToast, guarded }) {
  const [importText,setImportText]=useState(''); const [preview,setPreview]=useState(null); const [data,setData]=useState({items:[],total:0,page:1,page_size:50}); const [query,setQuery]=useState(''); const [status,setStatus]=useState(''); const [selected,setSelected]=useState(new Set()); const [revealed,setRevealed]=useState({}); const [edit,setEdit]=useState(null)
  const load=async(page=1)=>{try{const d=await guarded(()=>apiFetch(`/api/emails?page=${page}&page_size=50&query=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}`));setData(d);setSelected(new Set())}catch(e){showToast(e.message,'error')}}
  useEffect(()=>{load(1)},[query,status])
  const doPreview=async()=>{try{setPreview(await guarded(()=>apiFetch('/api/emails/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email_accounts:importText.split('\n')})})))}catch(e){showToast(e.message,'error')}}
  const add=async()=>{try{const d=await guarded(()=>apiFetch('/api/emails/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email_accounts:importText.split('\n')})}));setPreview(d.import);setStats(d.statistics);if(d.import.new)setImportText('');await load(1);showToast(`Added ${d.import.new}; ${d.import.duplicates||0} duplicates; ${d.import.conflicts||0} conflicts`,'success')}catch(e){showToast(e.message,'error')}}
  const reveal=async(id)=>{try{const d=await guarded(()=>apiFetch(`/api/emails/${id}/secret`));setRevealed(v=>({...v,[id]:d.password}))}catch(e){showToast(e.message,'error')}}
  const bulk=async(action)=>{if(!selected.size)return; if(action==='delete'&&!confirm(`Delete ${selected.size} selected email accounts?`))return; try{const d=await guarded(()=>apiFetch('/api/emails/bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...selected],action})}));setStats(d.statistics);await load(data.page);showToast(`${d.changed} rows changed`,'success')}catch(e){showToast(e.message,'error')}}
  const saveEdit=async()=>{try{const d=await guarded(()=>apiFetch(`/api/emails/${edit.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:edit.email,password:edit.password||undefined,status:edit.status})}));setStats(d.statistics);setEdit(null);await load(data.page);showToast('Email account updated','success')}catch(e){showToast(e.message,'error')}}
  return <Section title="Email Inventory" subtitle="Persistent, duplicate-safe inventory with explicit secret reveal." actions={<><Button tone="slate" onClick={()=>bulk('set_available')} disabled={!selected.size}>Set available</Button><Button tone="red" onClick={()=>bulk('delete')} disabled={!selected.size}>Delete selected</Button></>}><div className="grid grid-cols-2 gap-3 lg:grid-cols-5"><StatCard label="Total" value={stats.total||0}/><StatCard label="Available" value={stats.available||0} tone="green"/><StatCard label="Reserved" value={stats.reserved||0} tone="cyan"/><StatCard label="Used" value={stats.used||0} tone="amber"/><StatCard label="Failed" value={stats.failed||0} tone="red"/></div><div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><div className="mb-3 text-sm font-medium">Import email:password lines</div><textarea className={`${inputClass} min-h-28 font-mono`} value={importText} onChange={e=>{setImportText(e.target.value);setPreview(null)}} placeholder="email@example.com:password"/>{preview&&<div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-5"><StatCard label="Received" value={preview.received||0}/><StatCard label="New" value={preview.new||0} tone="green"/><StatCard label="Duplicates" value={preview.duplicates||0} tone="amber"/><StatCard label="Conflicts" value={preview.conflicts||0} tone="red"/><StatCard label="Invalid" value={preview.invalid||0} tone="red"/></div>}<div className="mt-3 flex gap-2"><Button tone="slate" disabled={!importText.trim()} onClick={doPreview}>Preview</Button><Button disabled={!importText.trim()} onClick={add}>Add new only</Button></div></div><div className="flex flex-col gap-2 sm:flex-row"><input className={inputClass} placeholder="Search email…" value={query} onChange={e=>setQuery(e.target.value)}/><select className={inputClass} value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option><option value="available">Available</option><option value="reserved">Reserved</option><option value="used">Used</option><option value="failed">Failed</option></select></div><div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[850px] text-left text-sm"><thead className="bg-slate-950 text-xs uppercase text-slate-500"><tr><th className="p-3"><input type="checkbox" checked={data.items.length>0&&selected.size===data.items.length} onChange={e=>setSelected(e.target.checked?new Set(data.items.map(x=>x.id)):new Set())}/></th><th className="p-3">Email</th><th className="p-3">Password</th><th className="p-3">Status</th><th className="p-3">Attempts</th><th className="p-3">Updated</th><th className="p-3">Actions</th></tr></thead><tbody>{data.items.map(item=><tr key={item.id} className="border-t border-slate-800"><td className="p-3"><input type="checkbox" checked={selected.has(item.id)} onChange={e=>setSelected(prev=>{const n=new Set(prev);e.target.checked?n.add(item.id):n.delete(item.id);return n})}/></td><td className="p-3 font-mono text-xs text-cyan-300">{item.email}</td><td className="p-3 font-mono text-xs">{revealed[item.id]||item.password_masked}<button className="ml-2 text-cyan-400" onClick={()=>reveal(item.id)}>Reveal</button></td><td className="p-3">{item.status}</td><td className="p-3">{item.attempts}</td><td className="p-3 text-xs text-slate-500">{item.updated_at}</td><td className="p-3"><Button tone="slate" onClick={()=>setEdit({...item,password:''})}>Edit</Button></td></tr>)}</tbody></table>{!data.items.length&&<div className="py-12 text-center text-sm text-slate-600">No matching email accounts.</div>}</div><Pager page={data.page} total={data.total} pageSize={data.page_size} onPage={load}/>{edit&&<Modal title="Edit email account" onClose={()=>setEdit(null)}><div className="space-y-4"><Field label="Email"><input className={inputClass} value={edit.email} onChange={e=>setEdit({...edit,email:e.target.value})}/></Field><Field label="New password (leave blank to keep)"><input type="password" className={inputClass} value={edit.password} onChange={e=>setEdit({...edit,password:e.target.value})}/></Field><Field label="Status"><select className={inputClass} value={edit.status} onChange={e=>setEdit({...edit,status:e.target.value})}><option value="available">Available</option><option value="reserved">Reserved</option><option value="used">Used</option><option value="failed">Failed</option></select></Field><Button className="w-full" onClick={saveEdit}>Save changes</Button></div></Modal>}</Section>
}

function ProxiesPage({ stats, setStats, availableRegions, showToast, guarded }) {
  const [importText,setImportText]=useState(''); const [data,setData]=useState({items:[],total:0,page:1,page_size:50}); const [query,setQuery]=useState(''); const [stateFilter,setStateFilter]=useState(''); const [region,setRegion]=useState(''); const [selected,setSelected]=useState(new Set()); const [revealed,setRevealed]=useState({}); const [edit,setEdit]=useState(null); const [checking,setChecking]=useState(false)
  const load=async(page=1)=>{try{const d=await guarded(()=>apiFetch(`/api/proxies?page=${page}&page_size=50&query=${encodeURIComponent(query)}&state=${encodeURIComponent(stateFilter)}&region=${encodeURIComponent(region)}`));setData(d);setSelected(new Set())}catch(e){showToast(e.message,'error')}}
  useEffect(()=>{load(1)},[query,stateFilter,region])
  const add=async()=>{try{const d=await guarded(()=>apiFetch('/api/proxies/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proxy_list:importText.split('\n'),proxy_type:'http'})}));setStats(d);if(d.import.new)setImportText('');await load(1);showToast(`Added ${d.import.new}; ${d.import.duplicates||0} duplicates; ${d.import.conflicts||0} conflicts`,'success')}catch(e){showToast(e.message,'error')}}
  const checkAll=async()=>{setChecking(true);try{const d=await guarded(()=>apiFetch('/api/proxies/check',{method:'POST',timeoutMs:600000}));setStats(d);await load(data.page);showToast(`${d.working}/${d.total} proxies healthy`,'success')}catch(e){showToast(e.message,'error')}finally{setChecking(false)}}
  const reveal=async id=>{try{const d=await guarded(()=>apiFetch(`/api/proxies/${id}/secret`));setRevealed(v=>({...v,[id]:d.password||''}))}catch(e){showToast(e.message,'error')}}
  const bulkDelete=async()=>{if(!selected.size||!confirm(`Delete ${selected.size} selected proxies?`))return;try{const d=await guarded(()=>apiFetch('/api/proxies/bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...selected],action:'delete'})}));setStats(d.statistics);await load(data.page);showToast(`${d.changed} proxies deleted`,'success')}catch(e){showToast(e.message,'error')}}
  const saveEdit=async()=>{try{const payload={ip:edit.ip,port:edit.port,username:edit.username||'',region:edit.region||'',proxy_type:edit.type};if(edit.password!=='')payload.password=edit.password;const d=await guarded(()=>apiFetch(`/api/proxies/${edit.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}));setStats(d.statistics);setEdit(null);await load(data.page);showToast('Proxy updated','success')}catch(e){showToast(e.message,'error')}}
  return <Section title="Proxy Inventory" subtitle="Saved once, deduplicated, searchable and editable." actions={<><Button tone="slate" disabled={checking||!stats.total} onClick={checkAll}>{checking?'Checking…':'Check all saved'}</Button><Button tone="red" disabled={!selected.size} onClick={bulkDelete}>Delete selected</Button></>}><div className="grid grid-cols-3 gap-3"><StatCard label="Saved" value={stats.total||0}/><StatCard label="Healthy" value={stats.working||0} tone="green"/><StatCard label="Down / unchecked" value={stats.unchecked||0} tone="amber"/></div><div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><textarea className={`${inputClass} min-h-28 font-mono`} placeholder="host:port:user:password · user:password@host:port · socks5://user:password@host:port" value={importText} onChange={e=>setImportText(e.target.value)}/><div className="mt-3"><Button disabled={!importText.trim()} onClick={add}>Save new only</Button></div></div><div className="grid gap-2 md:grid-cols-3"><input className={inputClass} placeholder="Search host/user/country…" value={query} onChange={e=>setQuery(e.target.value)}/><select className={inputClass} value={stateFilter} onChange={e=>setStateFilter(e.target.value)}><option value="">All states</option><option value="working">Healthy</option><option value="down">Down/unchecked</option></select><select className={inputClass} value={region} onChange={e=>setRegion(e.target.value)}><option value="">All regions</option>{Object.entries(availableRegions).map(([k,v])=><option key={k} value={k}>{v.name||k}</option>)}</select></div><div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[1000px] text-left text-sm"><thead className="bg-slate-950 text-xs uppercase text-slate-500"><tr><th className="p-3"><input type="checkbox" checked={data.items.length>0&&selected.size===data.items.length} onChange={e=>setSelected(e.target.checked?new Set(data.items.map(x=>x.id)):new Set())}/></th><th className="p-3">Endpoint</th><th className="p-3">User</th><th className="p-3">Password</th><th className="p-3">Health</th><th className="p-3">Region</th><th className="p-3">Location</th><th className="p-3">Actions</th></tr></thead><tbody>{data.items.map(item=><tr key={item.id} className="border-t border-slate-800"><td className="p-3"><input type="checkbox" checked={selected.has(item.id)} onChange={e=>setSelected(prev=>{const n=new Set(prev);e.target.checked?n.add(item.id):n.delete(item.id);return n})}/></td><td className="p-3 font-mono text-xs text-cyan-300">{item.ip}:{item.port}</td><td className="p-3 text-xs">{item.username||'—'}</td><td className="p-3 font-mono text-xs">{revealed[item.id]??item.password_masked}<button className="ml-2 text-cyan-400" onClick={()=>reveal(item.id)}>Reveal</button></td><td className={`p-3 ${item.working?'text-emerald-400':'text-slate-500'}`}>{item.working?'Healthy':'Down'}</td><td className="p-3">{item.region||'—'}</td><td className="p-3 text-xs text-slate-500">{[item.city,item.country].filter(Boolean).join(', ')||'—'}</td><td className="p-3"><Button tone="slate" onClick={()=>setEdit({...item,password:''})}>Edit</Button></td></tr>)}</tbody></table>{!data.items.length&&<div className="py-12 text-center text-sm text-slate-600">No matching proxies.</div>}</div><Pager page={data.page} total={data.total} pageSize={data.page_size} onPage={load}/>{edit&&<Modal title="Edit proxy" onClose={()=>setEdit(null)}><div className="grid gap-4 sm:grid-cols-2"><Field label="Host"><input className={inputClass} value={edit.ip} onChange={e=>setEdit({...edit,ip:e.target.value})}/></Field><Field label="Port"><input className={inputClass} value={edit.port} onChange={e=>setEdit({...edit,port:e.target.value})}/></Field><Field label="Username"><input className={inputClass} value={edit.username||''} onChange={e=>setEdit({...edit,username:e.target.value})}/></Field><Field label="New password"><input type="password" className={inputClass} value={edit.password} onChange={e=>setEdit({...edit,password:e.target.value})} placeholder="Leave blank to keep"/></Field><Field label="Type"><select className={inputClass} value={edit.type||'http'} onChange={e=>setEdit({...edit,type:e.target.value})}><option>http</option><option>https</option><option>socks5</option><option>socks5h</option></select></Field><Field label="Region"><input className={inputClass} value={edit.region||''} onChange={e=>setEdit({...edit,region:e.target.value})}/></Field></div><Button className="mt-5 w-full" onClick={saveEdit}>Save proxy</Button></Modal>}</Section>
}

function SettingsPage({ settings, setSettings, profiles, setProfiles, regions, showToast, guarded }) {
  const [profileName,setProfileName]=useState('')
  const save=async()=>{try{const d=await guarded(()=>apiFetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)}));setSettings(d.settings);showToast('Settings saved','success')}catch(e){showToast(e.message,'error')}}
  const saveProfile=async()=>{if(!profileName.trim())return;try{const d=await guarded(()=>apiFetch('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:profileName,settings})}));setProfiles(d.profiles);setProfileName('');showToast('Profile saved','success')}catch(e){showToast(e.message,'error')}}
  const apply=async id=>{try{const d=await guarded(()=>apiFetch(`/api/profiles/${id}/apply`,{method:'POST'}));setSettings(d.settings);showToast(`Applied ${d.profile.name}`,'success')}catch(e){showToast(e.message,'error')}}
  const del=async id=>{if(!confirm('Delete this profile?'))return;try{const d=await guarded(()=>apiFetch(`/api/profiles/${id}`,{method:'DELETE'}));setProfiles(d.profiles)}catch(e){showToast(e.message,'error')}}
  return <Section title="Settings & Profiles" subtitle="Saved configuration survives refresh and restart." actions={<Button onClick={save}>Save settings</Button>}><div className="grid gap-4 md:grid-cols-2">{[['count','Number of accounts',1,1000],['concurrency','Concurrency',1,20],['username_min','Username minimum',3,32],['username_max','Username maximum',3,32],['password_length','Generated password length',8,128]].map(([k,l,min,max])=><Field key={k} label={l}><input type="number" min={min} max={max} className={inputClass} value={settings[k]} onChange={e=>setSettings({...settings,[k]:Number(e.target.value)})}/></Field>)}<Field label="Target region"><select className={inputClass} value={settings.target_region||''} onChange={e=>setSettings({...settings,target_region:e.target.value})}><option value="">Any healthy region</option>{Object.entries(regions).map(([k,v])=><option key={k} value={k}>{v.name||k} ({v.count||0})</option>)}</select></Field></div><div className="grid gap-3 md:grid-cols-2"><label className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/40 p-4"><input type="checkbox" checked={settings.use_proxies} onChange={e=>setSettings({...settings,use_proxies:e.target.checked})}/><span>Use saved proxies</span></label><label className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/40 p-4"><input type="checkbox" checked={settings.use_fixed_password} onChange={e=>setSettings({...settings,use_fixed_password:e.target.checked})}/><span>Use fixed account password</span></label></div>{settings.use_fixed_password&&<Field label="Fixed password"><input type="password" className={inputClass} value={settings.password_fixed} onChange={e=>setSettings({...settings,password_fixed:e.target.value})} placeholder={settings.fixed_password_configured?'Saved securely — leave blank to keep':'Enter once to save securely'}/>{settings.fixed_password_configured&&<div className="mt-2 text-xs text-emerald-500">A fixed password is already stored encrypted.</div>}</Field>}<div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><h3 className="mb-3 font-medium">Profiles</h3><div className="mb-4 flex gap-2"><input className={inputClass} placeholder="Profile name (e.g. Turkey Default)" value={profileName} onChange={e=>setProfileName(e.target.value)}/><Button onClick={saveProfile} disabled={!profileName.trim()}>Save profile</Button></div><div className="grid gap-2 md:grid-cols-2">{profiles.map(p=><div key={p.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900 p-3"><div><div className="font-medium">{p.name}</div><div className="text-xs text-slate-600">{p.settings?.count||0} accounts · {p.settings?.concurrency||0} concurrency</div></div><div className="flex gap-2"><Button tone="slate" onClick={()=>apply(p.id)}>Apply</Button><Button tone="red" onClick={()=>del(p.id)}>Delete</Button></div></div>)}{!profiles.length&&<div className="text-sm text-slate-600">No profiles saved yet.</div>}</div></div></Section>
}

function ProviderPage({ provider, setProvider, showToast, guarded }) {
  const [busy,setBusy]=useState(false)
  const save=async()=>{if(busy)return;setBusy(true);try{const body={service:provider.service};if(provider.api_key.trim())body.api_key=provider.api_key.trim();const d=await guarded(()=>apiFetch('/api/provider/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));setProvider({service:d.service,api_key:'',configured:d.configured,masked:d.masked});showToast(`Provider saved${d.masked?` · ${d.masked}`:''}`,'success')}catch(e){showToast(e.message,'error')}finally{setBusy(false)}}
  const balance=async()=>{if(busy)return;setBusy(true);try{const body={service:provider.service};if(provider.api_key.trim())body.api_key=provider.api_key.trim();const d=await guarded(()=>apiFetch('/api/captcha/balance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),timeoutMs:30000}));showToast(`Balance: $${d.balance}`,'success')}catch(e){showToast(e.message,'error')}finally{setBusy(false)}}
  return <Section title="Provider" subtitle="The saved API key is encrypted at rest and never returned in full."><div className={`rounded-xl border p-4 ${provider.configured?'border-emerald-500/20 bg-emerald-500/10':'border-red-500/20 bg-red-500/10'}`}><div className="text-xs uppercase text-slate-500">Stored state</div><div className="mt-1 font-mono">{provider.configured?`Configured ${provider.masked}`:'Not configured'}</div></div><Field label="Service"><select className={inputClass} value={provider.service} onChange={e=>setProvider({...provider,service:e.target.value})}><option value="capsolver">CapSolver</option><option value="2captcha">2Captcha</option><option value="anticaptcha">Anti-Captcha</option></select></Field><Field label="API key"><input type="password" className={inputClass} value={provider.api_key} onChange={e=>setProvider({...provider,api_key:e.target.value})} placeholder={provider.configured?'Leave blank to keep saved key':'Enter API key'}/></Field><div className="flex gap-2"><Button onClick={save} disabled={busy}>{busy?'Saving…':'Save'}</Button><Button tone="slate" onClick={balance} disabled={busy||(!provider.configured&&!provider.api_key.trim())}>Check balance</Button></div></Section>
}

function ResultsPage({ showToast, guarded }) {
  const [data,setData]=useState({items:[],total:0,page:1,page_size:50}); const [query,setQuery]=useState(''); const [status,setStatus]=useState(''); const [region,setRegion]=useState(''); const [selected,setSelected]=useState(new Set()); const [secrets,setSecrets]=useState({})
  const load=async(page=1)=>{try{const d=await guarded(()=>apiFetch(`/api/results?page=${page}&page_size=50&query=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&region=${encodeURIComponent(region)}`));setData(d);setSelected(new Set())}catch(e){showToast(e.message,'error')}}
  useEffect(()=>{load(1)},[query,status,region])
  const reveal=async id=>{try{const d=await guarded(()=>apiFetch(`/api/results/${id}/secret`));setSecrets(v=>({...v,[id]:d}))}catch(e){showToast(e.message,'error')}}
  const del=async()=>{if(!selected.size||!confirm(`Delete ${selected.size} results?`))return;try{await guarded(()=>apiFetch('/api/results/bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...selected],action:'delete'})}));await load(data.page);showToast('Selected results deleted','success')}catch(e){showToast(e.message,'error')}}
  const exportData=async format=>{try{const d=await guarded(()=>apiFetch(`/api/results/export?format=${format}`));const blob=new Blob([d.data],{type:d.mime});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`riot-results-${Date.now()}.${format}`;a.click();URL.revokeObjectURL(url);showToast(`Exported ${d.count} results`,'success')}catch(e){showToast(e.message,'error')}}
  return <Section title="Results" subtitle="Passwords stay masked until explicitly revealed." actions={<><Button tone="slate" onClick={()=>exportData('txt')}>TXT</Button><Button tone="slate" onClick={()=>exportData('csv')}>CSV</Button><Button tone="slate" onClick={()=>exportData('json')}>JSON</Button><Button tone="red" disabled={!selected.size} onClick={del}>Delete selected</Button></>}><div className="grid gap-2 md:grid-cols-3"><input className={inputClass} placeholder="Search username/email/error…" value={query} onChange={e=>setQuery(e.target.value)}/><select className={inputClass} value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option><option value="SUCCESS">Success</option><option value="FAILED">Failed</option></select><input className={inputClass} placeholder="Region filter" value={region} onChange={e=>setRegion(e.target.value)}/></div><div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[1100px] text-left text-sm"><thead className="bg-slate-950 text-xs uppercase text-slate-500"><tr><th className="p-3"><input type="checkbox" checked={data.items.length>0&&selected.size===data.items.length} onChange={e=>setSelected(e.target.checked?new Set(data.items.map(x=>x.history_id)):new Set())}/></th><th className="p-3">Username</th><th className="p-3">Password</th><th className="p-3">Email</th><th className="p-3">Email password</th><th className="p-3">Status</th><th className="p-3">Region</th><th className="p-3">Job</th><th className="p-3">Created</th></tr></thead><tbody>{data.items.map(item=>{const sec=secrets[item.history_id];return <tr key={item.history_id} className="border-t border-slate-800"><td className="p-3"><input type="checkbox" checked={selected.has(item.history_id)} onChange={e=>setSelected(prev=>{const n=new Set(prev);e.target.checked?n.add(item.history_id):n.delete(item.history_id);return n})}/></td><td className="p-3 font-mono text-xs text-cyan-300">{item.username||'—'}</td><td className="p-3 font-mono text-xs">{sec?.password||item.password_masked}{!sec&&item.password_masked&&<button onClick={()=>reveal(item.history_id)} className="ml-2 text-cyan-400">Reveal</button>}</td><td className="p-3 text-xs">{item.email||'—'}</td><td className="p-3 font-mono text-xs">{sec?.email_password||item.email_password_masked}</td><td className={`p-3 ${item.status==='SUCCESS'?'text-emerald-400':'text-red-400'}`}>{item.status}</td><td className="p-3">{item.region||'—'}</td><td className="p-3 font-mono text-xs text-slate-500">{item.job_id||'—'}</td><td className="p-3 text-xs text-slate-600">{item.created_at}</td></tr>})}</tbody></table>{!data.items.length&&<div className="py-12 text-center text-sm text-slate-600">No matching results.</div>}</div><Pager page={data.page} total={data.total} pageSize={data.page_size} onPage={load}/></Section>
}

function JobsPage({ showToast, guarded }) {
  const [data,setData]=useState({items:[],total:0,page:1,page_size:30}); const [status,setStatus]=useState(''); const [detail,setDetail]=useState(null)
  const load=async(page=1)=>{try{setData(await guarded(()=>apiFetch(`/api/jobs?page=${page}&page_size=30&status=${encodeURIComponent(status)}`)))}catch(e){showToast(e.message,'error')}}
  useEffect(()=>{load(1)},[status])
  const open=async id=>{try{setDetail(await guarded(()=>apiFetch(`/api/jobs/${id}`)))}catch(e){showToast(e.message,'error')}}
  return <Section title="Job History" subtitle="Completed, stopped and interrupted runs are preserved."><select className={`${inputClass} max-w-xs`} value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option><option value="running">Running</option><option value="completed">Completed</option><option value="stopped">Stopped</option><option value="interrupted">Interrupted</option></select><div className="overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[850px] text-left text-sm"><thead className="bg-slate-950 text-xs uppercase text-slate-500"><tr><th className="p-3">Job</th><th className="p-3">Status</th><th className="p-3">Requested</th><th className="p-3">Success</th><th className="p-3">Failed</th><th className="p-3">Region</th><th className="p-3">Created</th><th className="p-3"></th></tr></thead><tbody>{data.items.map(job=><tr key={job.id} className="border-t border-slate-800"><td className="p-3 font-mono text-xs text-cyan-300">{job.id}</td><td className="p-3">{job.status}</td><td className="p-3">{job.requested_count}</td><td className="p-3 text-emerald-400">{job.success_count}</td><td className="p-3 text-red-400">{job.failed_count}</td><td className="p-3">{job.target_region||'Any'}</td><td className="p-3 text-xs text-slate-600">{job.created_at}</td><td className="p-3"><Button tone="slate" onClick={()=>open(job.id)}>Details</Button></td></tr>)}</tbody></table></div><Pager page={data.page} total={data.total} pageSize={data.page_size} onPage={load}/>{detail&&<Modal title={`Job ${detail.job.id}`} onClose={()=>setDetail(null)} wide><div className="grid grid-cols-2 gap-3 md:grid-cols-4"><StatCard label="Status" value={detail.job.status}/><StatCard label="Requested" value={detail.job.requested_count}/><StatCard label="Success" value={detail.job.success_count} tone="green"/><StatCard label="Failed" value={detail.job.failed_count} tone="red"/></div><h4 className="mb-2 mt-5 font-medium">Timeline</h4><div className="max-h-80 space-y-2 overflow-auto">{detail.events.map(ev=><div key={ev.id} className="rounded-lg border border-slate-800 bg-slate-950 p-3 text-sm"><div className="flex justify-between gap-4"><span className="text-cyan-300">{ev.event_type}</span><span className="text-xs text-slate-600">{ev.created_at}</span></div><div className="mt-1 text-slate-400">{ev.message}</div></div>)}</div></Modal>}</Section>
}

function AuditPage({ guarded }) {
  const [data,setData]=useState({items:[],total:0,page:1,page_size:50}); const [query,setQuery]=useState('')
  const load=async(page=1)=>{try{setData(await guarded(()=>apiFetch(`/api/audit?page=${page}&page_size=50&query=${encodeURIComponent(query)}`)))}catch{/* auth handled */}}
  useEffect(()=>{load(1)},[query])
  return <Section title="Audit Trail" subtitle="Owner actions, secret reveals, exports, imports and authentication events."><input className={`${inputClass} max-w-xl`} placeholder="Search audit trail…" value={query} onChange={e=>setQuery(e.target.value)}/><div className="space-y-2">{data.items.map(ev=><div key={ev.id} className="rounded-xl border border-slate-800 bg-slate-950/50 p-3"><div className="flex flex-col justify-between gap-1 sm:flex-row"><div className="font-mono text-xs text-cyan-300">{ev.event_type}</div><div className="text-xs text-slate-600">{ev.created_at}</div></div><div className="mt-1 text-sm text-slate-400">{ev.actor_email||'system'} {ev.entity_type?`· ${ev.entity_type}${ev.entity_id?` #${ev.entity_id}`:''}`:''}</div>{Object.keys(ev.detail||{}).length>0&&<div className="mt-2 overflow-x-auto font-mono text-xs text-slate-600">{JSON.stringify(ev.detail)}</div>}</div>)}</div><Pager page={data.page} total={data.total} pageSize={data.page_size} onPage={load}/></Section>
}

function SystemPage({ showToast, guarded, onReauth }) {
  const [diag,setDiag]=useState(null); const [backups,setBackups]=useState([]); const [restoreFile,setRestoreFile]=useState(null); const [busy,setBusy]=useState(false)
  const loadBackups=async()=>{try{const d=await guarded(()=>apiFetch('/api/backups'));setBackups(d.backups||[])}catch(e){showToast(e.message,'error')}}
  useEffect(()=>{loadBackups()},[])
  const run=async()=>{try{setDiag(await guarded(()=>apiFetch('/api/diagnostics',{timeoutMs:60000})))}catch(e){showToast(e.message,'error')}}
  const create=async()=>{try{const d=await guarded(()=>apiFetch('/api/backups/create',{method:'POST',timeoutMs:120000}));await loadBackups();showToast(`Backup ${d.backup.name} created`,'success')}catch(e){showToast(e.message,'error')}}
  const restore=async()=>{if(!restoreFile||!confirm('Restore this backup? Current data will be replaced and a safety backup will be created first.'))return;setBusy(true);try{const fd=new FormData();fd.append('file',restoreFile);const d=await guarded(()=>apiFetch('/api/backups/restore',{method:'POST',body:fd,timeoutMs:120000}));showToast(d.restart_required?'Restore staged. Restart START.bat to apply it.':'Backup restore staged','success')}catch(e){showToast(e.message,'error')}finally{setBusy(false)}}
  return <Section title="System, Diagnostics & Backups" subtitle="Run local checks and keep app.db + encryption key together." actions={<><Button tone="slate" onClick={run}>Run diagnostics</Button><Button onClick={create}>Create backup</Button></>}><div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><h3 className="mb-3 font-medium">Diagnostics</h3>{diag?<><div className="mb-3 text-sm text-slate-400">{diag.passed}/{diag.total} checks passed</div><div className="grid gap-2 md:grid-cols-2">{diag.checks.map(c=><div key={c.name} className={`rounded-lg border p-3 ${c.ok?'border-emerald-500/20 bg-emerald-500/10':'border-amber-500/20 bg-amber-500/10'}`}><div className={c.ok?'text-emerald-300':'text-amber-300'}>{c.ok?'✓':'!'} {c.name}</div><div className="mt-1 break-all text-xs text-slate-500">{typeof c.detail==='string'?c.detail:JSON.stringify(c.detail)}</div></div>)}</div></>:<div className="text-sm text-slate-600">Run diagnostics to inspect the database, encryption key, frontend, browser runtime and inventory.</div>}</div><div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"><h3 className="mb-3 font-medium">Backups</h3><div className="space-y-2">{backups.map(b=><div key={b.name} className="flex flex-col justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 sm:flex-row sm:items-center"><div><div className="font-mono text-xs text-cyan-300">{b.name}</div><div className="text-xs text-slate-600">{Math.round(b.size_bytes/1024)} KB · {b.modified_at}</div></div><a href={`/api/backups/${encodeURIComponent(b.name)}`}><Button tone="slate">Download</Button></a></div>)}{!backups.length&&<div className="text-sm text-slate-600">No backups created yet.</div>}</div></div><div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4"><h3 className="font-medium text-red-300">Restore backup</h3><p className="mb-3 mt-1 text-xs text-slate-500">A safety backup is created before replacement. Existing sessions are invalidated after restore.</p><input type="file" accept=".zip" onChange={e=>setRestoreFile(e.target.files?.[0]||null)} className="block w-full text-sm text-slate-400"/><Button tone="red" className="mt-3" disabled={!restoreFile||busy} onClick={restore}>{busy?'Restoring…':'Restore selected backup'}</Button></div></Section>
}

function SecurityPage({ showToast, guarded }) {
  const [current,setCurrent]=useState(''); const [next,setNext]=useState(''); const [confirmValue,setConfirmValue]=useState('')
  const change=async()=>{if(next!==confirmValue){showToast('New passwords do not match','error');return}try{await guarded(()=>apiFetch('/api/auth/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:current,new_password:next})}));setCurrent('');setNext('');setConfirmValue('');showToast('Owner password changed and other sessions were revoked','success')}catch(e){showToast(e.message,'error')}}
  return <Section title="Security" subtitle="Change the owner credential without editing source files."><div className="max-w-xl space-y-4"><Field label="Current password"><input type="password" className={inputClass} value={current} onChange={e=>setCurrent(e.target.value)}/></Field><Field label="New password"><input type="password" className={inputClass} value={next} onChange={e=>setNext(e.target.value)}/></Field><Field label="Confirm new password"><input type="password" className={inputClass} value={confirmValue} onChange={e=>setConfirmValue(e.target.value)}/></Field><Button disabled={!current||next.length<10||!confirmValue} onClick={change}>Change owner password</Button></div><div className="max-w-xl rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-500">Login passwords are PBKDF2-hashed. Session tokens are stored only as SHA-256 hashes in SQLite and sent to the browser as HttpOnly SameSite cookies.</div></Section>
}

function RuntimeErrorPage({ error }) {
  return <div className="min-h-screen bg-slate-950 p-6 text-slate-100 grid place-items-center"><div className="w-full max-w-2xl rounded-3xl border border-red-500/20 bg-slate-900 p-7 shadow-2xl"><div className="text-xs font-semibold uppercase tracking-[0.25em] text-red-400">Runtime protection</div><h1 className="mt-2 text-2xl font-bold">{error.title}</h1><p className="mt-3 text-sm leading-6 text-slate-400">{error.message}</p><div className="mt-5 grid grid-cols-2 gap-3"><StatCard label="Expected" value={`v${error.expected}`} tone="cyan"/><StatCard label="Detected" value={error.actual==='offline'?'Offline':`v${error.actual}`} tone="red"/></div><div className="mt-5 rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400"><div className="font-medium text-slate-200">Fix</div><div className="mt-2">1. Close older Riot Creator START.bat / command windows.</div><div>2. Run START.bat from this v2.4 folder.</div><div>3. The launcher will choose a safe free port automatically and open the correct page.</div></div><div className="mt-5 flex gap-2"><Button onClick={()=>window.location.reload()}>Try again</Button><Button tone="slate" onClick={()=>window.location.href='/'}>Go to root</Button></div></div></div>
}

class ErrorBoundary extends Component {
  constructor(props){super(props);this.state={error:null}}
  static getDerivedStateFromError(error){return {error}}
  componentDidCatch(error,info){console.error('UI crash recovered by ErrorBoundary',error,info)}
  render(){if(!this.state.error)return this.props.children;return <div className="min-h-screen bg-slate-950 p-6 text-slate-100 grid place-items-center"><div className="w-full max-w-2xl rounded-3xl border border-amber-500/20 bg-slate-900 p-7"><div className="text-xs font-semibold uppercase tracking-[0.25em] text-amber-400">UI recovery</div><h1 className="mt-2 text-2xl font-bold">The interface hit an error instead of going white.</h1><p className="mt-3 break-words rounded-xl bg-slate-950 p-4 font-mono text-xs text-slate-400">{String(this.state.error?.message||this.state.error)}</p><div className="mt-5 flex gap-2"><Button onClick={()=>window.location.reload()}>Reload workspace</Button><Button tone="slate" onClick={()=>this.setState({error:null})}>Try render again</Button></div></div></div>}
}

function App(){ return <ErrorBoundary><AppContent /></ErrorBoundary> }

export default App
