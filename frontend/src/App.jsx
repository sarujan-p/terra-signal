import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3, CircleHelp, CloudRain, Database,
  Flame, KeyRound, Leaf, LogOut, MapPin, Menu, RefreshCw, Satellite, Settings as Cog, ShieldCheck,
  ChevronDown, Search, Thermometer, Target, Waves, X
} from 'lucide-react'
import { api, errorText, getToken, setToken, setUnauthorizedHandler } from './lib/api'
import Login from './components/Login'
import Settings from './components/Settings'
import EarthMap from './components/EarthMap'
import TrendChart from './components/TrendChart'
import IndicatorAnalysis from './components/IndicatorAnalysis'
import NdviReview from './components/NdviReview'

const fmt = (v, d = 1) => Number(v ?? 0).toFixed(d)
const initials = n => (n || '?').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()
const tone = (s = '') => {
  const v = s.toLowerCase()
  if (['critical', 'extreme', 'high', 'decline', 'drying', 'deficit'].some(x => v.includes(x))) return 'danger'
  if (['moderate', 'elevated', 'watch'].some(x => v.includes(x))) return 'warning'
  return 'good'
}
const fmtDate = d => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
const REFRESH_MS = 5 * 60 * 1000

function StatCard({ icon: Icon, label, value, unit, delta, status, hint, accent }) {
  const down = String(delta).trim().startsWith('-')
  return <section className="stat-card">
    <div className="stat-top"><div className={`stat-icon ${accent}`}><Icon size={18} /></div><span className={`status-tag ${tone(status)}`}><i /> {status}</span></div>
    <div className="stat-label">{label}</div>
    <div className="stat-value">{value}<small>{unit}</small></div>
    <div className="stat-bottom"><span className={`delta ${down ? 'negative' : 'positive'}`}>{down ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />} {delta}</span><span className="stat-hint">{hint}</span></div>
  </section>
}

export default function App() {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(!!getToken())
  const [locations, setLocations] = useState([])
  const [location, setLocation] = useState('')
  const [countryFilter, setCountryFilter] = useState('global')
  const [areaFilter, setAreaFilter] = useState('')
  const [locationSearch, setLocationSearch] = useState('')
  const [areaSearchOpen, setAreaSearchOpen] = useState(false)
  const [data, setData] = useState(null)
  const [dataSource, setDataSource] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [layers, setLayers] = useState(['temperature', 'vegetation', 'precipitation', 'fires', 'anomalies'])
  const [metric, setMetric] = useState('temperature')
  const [tab, setTab] = useState('overview')
  const [menu, setMenu] = useState(false)
  const locRef = useRef('')
  locRef.current = location
  const areaInputRef = useRef(null)
  const areaOptionRefs = useRef([])

  const logout = useCallback(() => { setToken(null); setUser(null); setData(null); setLocations([]); setLocation(''); setCountryFilter('global'); setAreaFilter(''); setLocationSearch(''); setAreaSearchOpen(false) }, [])
  useEffect(() => { setUnauthorizedHandler(logout) }, [logout])

  // restore session
  useEffect(() => {
    if (!getToken()) return
    api.get('/api/auth/me').then(r => setUser(r.data)).catch(() => setToken(null)).finally(() => setBooting(false))
  }, [])

  const load = useCallback(async (loc, { quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    setError('')
    try {
      let id = loc
      if (!id) {
        const { data: locs } = await api.get('/api/locations')
        const globalLocation = locs.find(item => item.scope === 'national') || locs[0]
        if (!globalLocation) throw new Error('No areas with available data were returned.')
        setLocations(locs); id = globalLocation.id; setLocation(id); setCountryFilter('global'); setAreaFilter('')
      }
      if (id === 'ndvi_Canberra_Australia') { setData(null); return }
      const { data: d } = await api.get(`/api/dashboard/${id}`)
      setData(d)
    } catch (e) {
      setError(errorText(e, 'Could not load the dashboard.'))
    } finally { setLoading(false) }
  }, [])

  const loadSource = useCallback(() => api.get('/api/data-source').then(r => setDataSource(r.data)).catch(() => {}), [])

  useEffect(() => { if (user) { load(''); loadSource() } }, [user, load, loadSource])
  useEffect(() => {                                   // keep the dashboard live
    if (!user) return
    const t = setInterval(() => {
      if (locRef.current) load(locRef.current, { quiet: true })
    }, REFRESH_MS)
    return () => clearInterval(t)
  }, [user, load])

  const pick = id => {
    const selected = locations.find(item => item.id === id)
    if (!selected) {
      setError('Could not identify that map location. Select an area from the search list instead.')
      return
    }
    if (selected.scope === 'national') {
      setCountryFilter('global')
      setAreaFilter('')
    } else if (selected.scope === 'country') {
      setCountryFilter(selected.id)
      setAreaFilter(selected.id)
    } else {
      setCountryFilter(selected.country_id)
      setAreaFilter(selected.id)
    }
    setAreaSearchOpen(false)
    setLocationSearch('')
    setLocation(id)
    if (selected.cells === 0) {
      setData(null)
      setLoading(false)
      setError('')
    } else {
      load(id)
    }
  }
  const changeCountry = id => {
    setCountryFilter(id)
    setAreaSearchOpen(false)
    setLocationSearch('')
    if (id === 'global') {
      const globalLocation = locations.find(item => item.scope === 'national')
      if (globalLocation && (location !== globalLocation.id || !data)) {
        setAreaFilter('')
        setLocation(globalLocation.id)
        load(globalLocation.id)
      }
      return
    }
    const country = locations.find(item => item.id === id && item.scope === 'country')
    if (!country) return
    setAreaFilter(country.id)
    setLocation(country.id)
    if (country.cells === 0) {
      setData(null)
      setLoading(false)
      setError('')
    } else {
      load(country.id)
    }
  }
  const reload = async () => {
    setLoading(true)
    try {
      await api.post('/api/data/refresh')
      const refreshDashboard = locRef.current ? load(locRef.current, { quiet: true }) : Promise.resolve()
      await Promise.all([refreshDashboard, loadSource()])
    } finally { setLoading(false) }
  }
  const toggle = k => setLayers(p => p.includes(k) ? p.filter(x => x !== k) : [...p, k])

  if (booting) return <div className="login-page"><div className="loader" /></div>
  if (!user) return <Login onLogin={setUser} />

  const a = data?.overall_anomaly
  const tabs = [
    { id: 'overview', label: 'Overview', icon: BarChart3 }, { id: 'indicators', label: 'Indicators', icon: Activity },
    { id: 'hotspots', label: 'Hotspots', icon: Target }, { id: 'methodology', label: 'Methodology', icon: CircleHelp },
    { id: 'settings', label: 'Settings', icon: Cog }
  ]
  const modeLabel = data?.source_mode === 'ARCHIVE' ? 'NASA HISTORICAL ARCHIVE' : data?.source_mode === 'LIVE' ? 'NASA LIVE DATA' : data?.source_mode === 'MIXED' ? 'MIXED DATA' : 'SIMULATED DATA'
  const modeClass = ['ARCHIVE', 'LIVE'].includes(data?.source_mode) ? 'live' : 'mock'
  const fireAvailable = data?.fire?.available !== false
  const sourceColors = ['orange', 'green', 'blue', 'red']
  const selectedLocation = locations.find(l => l.id === location)
  const ndviSelected = selectedLocation?.ndvi_pilot === true
  const countryLocations = locations.filter(l => l.scope === 'country')
  const selectedCountry = countryLocations.find(country => country.id === countryFilter)
  const isArea = area => area.scope === 'area' || area.scope === 'region'
  const countryAreas = selectedCountry ? [
    { ...selectedCountry, name: `All areas in ${selectedCountry.name}` },
    ...locations.filter(area => isArea(area) && area.country_id === selectedCountry.id)
  ] : []
  const selectedArea = countryAreas.find(area => area.id === areaFilter)
  const metricLabel = data?.[metric]?.label || metric[0].toUpperCase() + metric.slice(1)
  const filteredAreas = countryAreas.filter(l => {
    const query = locationSearch.trim().toLowerCase()
    return !query || l.name.toLowerCase().includes(query) || l.id.toLowerCase().includes(query)
  })

  return <div className="app">
    <aside className={`sidebar ${menu ? 'open' : ''}`}>
      <div className="brand"><div className="brand-mark"><Satellite size={21} /></div><div><b>SAT<span>-</span>SCOPE</b><small>EARTH INTELLIGENCE</small></div><button className="mobile-close" onClick={() => setMenu(false)}><X size={18} /></button></div>
      <div className="workspace-label">WORKSPACE</div>
      <button className="workspace active"><div className="workspace-icon"><Waves size={17} /></div><span>Earth system monitor</span></button>
      <div className="nav-label">ANALYTICS</div>
      {tabs.map(t => <button key={t.id} onClick={() => { setTab(t.id); setMenu(false) }} className={`nav-item ${tab === t.id ? 'selected' : ''}`}><t.icon size={17} />{t.label}</button>)}
      <div className="sidebar-divider" />
      <div className="nav-label">DATA SOURCES</div>
      {(data?.sources || []).map((source, index) => <div className="source-item" key={source.indicator} title={source.dataset}>
        <span className={`source-dot ${sourceColors[index % sourceColors.length]}`} />{source.indicator}
      </div>)}
      <div className="sidebar-bottom">
        <div className="data-mode"><Database size={16} /><div><b>{ndviSelected ? 'MODIS NDVI candidate' : data ? (data.source_mode === 'ARCHIVE' ? 'NASA historical archive' : data.source_mode === 'LIVE' ? 'Live NASA data' : data.source_mode === 'MIXED' ? 'Mixed live / mock' : 'Local demo mode') : 'Connecting…'}</b><small>{ndviSelected ? 'Canberra study area only' : data ? `${data.sources.filter(s => s.source_mode !== 'UNAVAILABLE').length} available datasets` : ''}</small></div><span className="mode-dot" /></div>
        <div className="profile"><div className="avatar">{initials(user.display_name)}</div><div><b>{user.display_name}</b><small>@{user.username}</small></div><button className="icon-btn" onClick={logout} title="Sign out"><LogOut size={15} /></button></div>
      </div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div className="top-left"><button className="menu-btn" onClick={() => setMenu(true)}><Menu size={19} /></button><div className="breadcrumb">Workspace › <b>{tabs.find(t => t.id === tab).label}</b></div></div>
        <div className="top-actions">
          <div className="system-status"><span /> {ndviSelected ? 'MODIS vegetation workspace' : error ? 'API unavailable' : 'All systems operational'}</div>
          <button className="icon-btn" title="Account settings" onClick={() => setTab('settings')}><KeyRound size={17} /></button>
          <div className="top-avatar">{initials(user.display_name)}</div>
        </div>
      </header>

      <div className="content">
        {user.is_default_password && <div className="warn-banner"><AlertTriangle size={16} /><span>You are using the default password. Change it now to secure this dashboard.</span><button onClick={() => setTab('settings')}>Change password</button></div>}
        <div className="page-heading">
          <div><div className="eyebrow">NASA SPACE APPS CHALLENGE <span className="heading-dot">/</span> BE AN EARTH SYSTEM TREND DETECTIVE</div><h1>Earth system <span>intelligence</span></h1><p>{data?.source_mode === 'ARCHIVE' ? 'Explore global NASA climate reanalysis and compare environmental trends with seasonal baselines.' : 'Discover environmental patterns, connect satellite observations and investigate emerging anomalies.'}</p></div>
          <div className="heading-actions">
            {locations.length > 0 && <>
              <select className="scope-select" value={countryFilter} onChange={e => changeCountry(e.target.value)} aria-label="Country filter">
                <option value="global">Global</option>
                {countryLocations.map(country => <option key={country.id} value={country.id}>
                  {country.name}{country.cells === 0 ? ' · no data' : ''}
                </option>)}
              </select>
              <div className="area-search">
              <Search size={15} aria-hidden="true" />
              <input ref={areaInputRef} className="loc-select"
                value={countryFilter === 'global' ? 'Select a country first' : areaSearchOpen ? locationSearch : selectedArea?.name || ''}
                disabled={countryFilter === 'global'}
                onFocus={() => { if (countryFilter !== 'global') { if (!areaSearchOpen) setLocationSearch(''); setAreaSearchOpen(true) } }}
                onChange={e => {
                  setLocationSearch(e.target.value)
                  setAreaSearchOpen(true)
                }}
                onBlur={e => { if (e.relatedTarget?.getAttribute('role') !== 'option') setAreaSearchOpen(false) }}
                onKeyDown={e => {
                  if (e.key === 'ArrowDown' && filteredAreas.length) {
                    e.preventDefault()
                    areaOptionRefs.current[0]?.focus()
                  } else if (e.key === 'Enter' && filteredAreas.length === 1) {
                    e.preventDefault()
                    pick(filteredAreas[0].id)
                  } else if (e.key === 'Escape') {
                    setAreaSearchOpen(false)
                    setLocationSearch('')
                  }
                }}
                placeholder="Search local areas…" aria-label="Search or select local area" aria-expanded={countryFilter !== 'global' && areaSearchOpen}
                aria-controls="area-options" aria-autocomplete="list" role="combobox" />
              <ChevronDown size={14} aria-hidden="true" />
              {countryFilter !== 'global' && areaSearchOpen && <div className="area-search-options" id="area-options" role="listbox">
                {filteredAreas.map((l, index) => <button key={l.id} ref={element => { areaOptionRefs.current[index] = element }}
                  type="button" role="option" aria-selected={l.id === location}
                  onMouseDown={e => e.preventDefault()} onClick={() => pick(l.id)}
                  onKeyDown={e => {
                    if (e.key === 'ArrowDown') {
                      e.preventDefault()
                      areaOptionRefs.current[(index + 1) % filteredAreas.length]?.focus()
                    } else if (e.key === 'ArrowUp') {
                      e.preventDefault()
                      if (index === 0) areaInputRef.current?.focus()
                      else areaOptionRefs.current[index - 1]?.focus()
                    } else if (e.key === 'Escape') {
                      setAreaSearchOpen(false)
                      areaInputRef.current?.focus()
                    }
                  }}>
                  <span>{l.name}</span><small>{l.ndvi_pilot ? 'MODIS NDVI study area' : l.cells ? `${l.cells} NASA grid cell${l.cells === 1 ? '' : 's'}` : 'No data available'}</small>
                </button>)}
                {!filteredAreas.length && <span className="area-search-empty">No local areas listed for this country</span>}
              </div>}
              </div>
            </>}
            <button className="refresh-btn" onClick={() => load(location)} disabled={loading || !location}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh data</button>
          </div>
        </div>

        {error && <div className="error-banner"><AlertTriangle size={17} /><span>{error}</span><button onClick={() => load(location)}>Retry</button></div>}
        {data?.served_from_cache && <div className="warn-banner"><AlertTriangle size={16} /><span>{data.cache_warning}</span></div>}

        {tab === 'settings' && <Settings user={user} onUserChange={setUser} dataSource={dataSource} onReload={reload} reloading={loading} />}

        {ndviSelected && (tab === 'overview' || tab === 'indicators') && <>
          <NdviReview key={location} />
          <div className="detail-grid">{['Temperature', 'Precipitation', 'Fire detection', 'Compound anomaly'].map(label => <section className="detail-card" key={label}><span className="eyebrow">{label}</span><h3>Unavailable for this study area</h3><p>No aligned observations are connected to this Canberra MODIS footprint. Other locations retain their existing data.</p></section>)}</div>
        </>}
        {ndviSelected && tab === 'hotspots' && <section className="detail-card"><h2>Compound hotspots unavailable</h2><p>Canberra NDVI is not combined with unrelated archive locations or time periods.</p></section>}
        {ndviSelected && tab === 'methodology' && <section className="detail-card"><h2>Vegetation methodology</h2><p>MOD13Q1.061, QA-filtered seasonal matched-pixel comparison. Baseline: 2020-2024; evaluation: 2025. At least four historical observations per pixel and 80% matched coverage. Percentage change describes NDVI, not confirmed vegetation damage. Acquisition dates may cross the calendar-year boundary.</p></section>}
        {!ndviSelected && tab === 'indicators' && <section className="detail-card"><div className="detail-icon"><Leaf size={20} /></div><span className="eyebrow">VEGETATION / MODIS NDVI</span><h3>Unavailable for this area</h3><p>MODIS NDVI is currently available only for Australia, then Canberra (MODIS study area). Soil wetness below is a separate indicator.</p></section>}

        {tab !== 'settings' && !ndviSelected && (loading && !data ? <div className="loading-panel"><div className="loader" /><b>Connecting to Earth observation datasets</b><span>Preparing environmental intelligence…</span></div> : selectedLocation?.cells === 0 ? <div className="loading-panel no-data-panel"><MapPin size={22} /><b>Selected area data not available</b><span>NASA archive has no grid data for {selectedLocation.name}. Choose another area or select Global.</span></div> : data && <>
          <div className="overview-strip">
            <div className="location-block"><div className="location-icon"><MapPin size={18} /></div><div><small>SELECTED AREA</small><b>{data.location_name}</b><span>{fmt(Math.abs(data.center.lat), 4)}° {data.center.lat >= 0 ? 'N' : 'S'}&nbsp; {fmt(Math.abs(data.center.lon), 4)}° {data.center.lon >= 0 ? 'E' : 'W'}</span></div></div>
            <div className="strip-divider" />
            <div className="strip-stat"><small>OBSERVATION WINDOW</small><b>{fmtDate(data.observation_window.start)} — {fmtDate(data.observation_window.end)}</b></div>
            <div className="strip-divider" />
            <div className="strip-stat"><small>LAST PROCESSED</small><b>{new Date(data.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b></div>
            <div className="strip-divider" />
            <div className="strip-stat"><small>DATA PROVENANCE</small><b><span className={`mode-pill ${modeClass}`}>{modeLabel}</span></b></div>
          </div>

          {tab === 'overview' && <>
            <div className="section-heading"><div><span className="eyebrow">INDICATOR SNAPSHOT</span><h2>Environmental indicators</h2></div><span className="section-meta">{data.sources.filter(s => s.source_mode !== 'UNAVAILABLE').length} data streams <span className="meta-dot" /> {data.cells.length}{data.grid_spacing_degrees ? ` global ${data.grid_spacing_degrees}° grid cells` : ' grid cells'}</span></div>
            <div className="stats-grid">
              <StatCard icon={Thermometer} label={data.temperature.label} value={fmt(data.temperature.current)} unit={data.temperature.unit} delta={`${data.temperature.z_score >= 0 ? '+' : ''}${fmt(data.temperature.z_score, 2)}σ vs baseline`} status={data.temperature.status} hint={`(Z-score deviation; baseline: ${fmt(data.temperature.baseline)} ${data.temperature.unit})`} accent="orange" />
              <StatCard icon={Leaf} label={data.vegetation.label} value={fmt(data.vegetation.ndvi, 2)} unit={data.vegetation.unit === 'fraction' ? '' : data.vegetation.unit} delta={`${fmt(data.vegetation.change_percent)}% vs baseline`} status={data.vegetation.status} hint={`(same-month baseline: ${fmt(data.vegetation.baseline, 2)} ${data.vegetation.unit})`} accent="green" />
              <StatCard icon={CloudRain} label={data.precipitation.label} value={fmt(data.precipitation.current_mm)} unit={data.precipitation.unit} delta={`${fmt(data.precipitation.percentile)}th percentile`} status={data.precipitation.status} hint={`(baseline: ${fmt(data.precipitation.baseline_mm)} ${data.precipitation.unit})`} accent="blue" />
              <StatCard icon={Flame} label="Fire detection" value={fireAvailable ? data.fire.detections : '—'} unit="" delta={fireAvailable ? `${data.fire.change_percent >= 0 ? '+' : ''}${fmt(data.fire.change_percent)}% vs previous (national)` : 'Historical fire data unavailable'} status={fireAvailable ? data.fire.status : 'UNAVAILABLE'} hint={fireAvailable ? `${data.fire.clusters} spatial clusters · previous: ${data.fire.previous_period_detections} detections nationally` : 'No fire data bundled with this archive'} accent="red" />
            </div>

            <div className="section-heading map-heading"><div><span className="eyebrow">SPATIAL EXPLORER</span><h2>Earth observation map</h2></div><span className="section-meta"><span className="live-indicator"><span /> INTERACTIVE</span></span></div>
            <div className="main-grid">
              <EarthMap data={data} layers={layers} onToggle={toggle} onPickRegion={pick} loading={loading} />
              <div className="right-rail">
                <section className={`anomaly-card ${tone(a.severity)}`}>
                  <div className="anomaly-top"><div className="anomaly-icon"><Activity size={18} /></div><span className={`status-tag ${tone(a.severity)}`}><i /> {a.severity} SEVERITY</span></div>
                  <div className="anomaly-title">Compound anomaly</div>
                  <div className="anomaly-state">{a.is_anomaly ? 'Signals detected' : 'No compound anomaly'}</div>
                  <p>{data.explanation}</p>
                  <div className="anomaly-divider" />
                  <div className="anomaly-foot"><span>{a.rule_flags} indicator flag{a.rule_flags === 1 ? '' : 's'}</span><span>{a.isolation_forest_anomaly_points} ML outliers</span></div>
                </section>
                <section className="insight-card">
                  <div className="card-heading"><div><span className="eyebrow">DETECTION SUMMARY</span><h3>What stands out</h3></div><Activity size={17} /></div>
                  <div className="insight-row"><span className="insight-icon orange"><Thermometer size={15} /></span><div><b>Thermal signal</b><small>{data.temperature.status} · {fmt(data.temperature.z_score, 2)}σ from baseline</small></div></div>
                  <div className="insight-row"><span className="insight-icon green"><Leaf size={15} /></span><div><b>{data.vegetation.label} change</b><small>{fmt(Math.abs(data.vegetation.change_percent))}% {data.vegetation.change_percent <= 0 ? 'below' : 'above'} baseline</small></div></div>
                  <div className="insight-row"><span className="insight-icon blue"><CloudRain size={15} /></span><div><b>Rainfall pattern</b><small>{fmt(data.precipitation.percentile)}th percentile · {data.precipitation.status}</small></div></div>
                  <div className="insight-row"><span className="insight-icon red"><Flame size={15} /></span><div><b>Fire activity</b><small>{fireAvailable ? `${data.fire.detections} detections in ${data.fire.clusters} clusters` : 'Historical data unavailable'}</small></div></div>
                </section>
              </div>
            </div>

            <div className="section-heading chart-heading"><div><span className="eyebrow">TEMPORAL ANALYSIS</span><h2>Indicator trends</h2></div>
              <div className="segmented">{[['temperature', data.temperature.label], ['vegetation', data.vegetation.unit === 'fraction' ? 'Soil wetness' : data.vegetation.label], ['precipitation', data.precipitation.label]].map(([id, label]) => <button key={id} onClick={() => setMetric(id)} className={metric === id ? 'chosen' : ''}>{label}</button>)}</div></div>
            <section className="chart-card"><div className="chart-title"><div><b>{metricLabel} trend</b><small>Observed values compared with baseline · {data.timeseries_scope}-wide series</small></div></div><TrendChart rows={data[metric].timeseries} metric={metric} label={metricLabel} unit={data[metric].unit} monthly={Boolean(data.grid_spacing_degrees)} /></section>
            <IndicatorAnalysis data={data} onPickRegion={pick} />
          </>}

          {tab === 'indicators' && <div className="detail-grid">
            {[
              { key: 'temperature', name: data.temperature.label, icon: Thermometer, metric: `${fmt(data.temperature.current)} ${data.temperature.unit}`, base: `${fmt(data.temperature.baseline)} ${data.temperature.unit} baseline`, desc: 'Temperature deviation measured against the same-month climatology.' },
              { key: 'vegetation', name: data.vegetation.label, icon: Leaf, metric: fmt(data.vegetation.ndvi, 3), base: `${fmt(data.vegetation.baseline, 3)} ${data.vegetation.unit} baseline`, desc: data.methodology.vegetation },
              { key: 'precipitation', name: data.precipitation.label, icon: CloudRain, metric: `${fmt(data.precipitation.current_mm)} ${data.precipitation.unit}`, base: `${fmt(data.precipitation.baseline_mm)} ${data.precipitation.unit} baseline`, desc: 'Precipitation position within the historical same-month distribution.' },
              { key: 'fire', name: 'Fire detection', icon: Flame, metric: fireAvailable ? String(data.fire.detections) : 'Unavailable', base: fireAvailable ? `${data.fire.clusters} spatial clusters` : 'Not included in this archive', desc: fireAvailable ? 'Active fire detections grouped with density-based spatial clustering (DBSCAN).' : 'NASA POWER does not include a historical fire-detection product.' }
            ].map(i => <section className="detail-card" key={i.key}><div className="detail-icon"><i.icon size={20} /></div><span className="eyebrow">INDICATOR DETAIL</span><h3>{i.name}</h3><div className="detail-value">{i.metric}</div><div className="detail-baseline">{i.base}</div><p>{i.desc}</p><span className={`status-tag ${tone(data[i.key].status)}`}><i />{data[i.key].status}</span></section>)}
          </div>}

          {tab === 'hotspots' && <>
            <div className="section-heading"><div><span className="eyebrow">ISOLATION FOREST</span><h2>Regional hotspots</h2></div><span className="section-meta">Ranked by unusual cells, {data.timeseries_scope}-wide</span></div>
            <section className="settings-card wide"><div className="table-wrap"><table className="data-table"><thead><tr><th>Region</th><th>Outlier cells</th><th>Score</th><th>Temp Z</th><th>{data.vegetation.label} Δ%</th><th>Precip pctl</th><th>Fires</th><th /></tr></thead><tbody>
              {data.hotspots.map(h => <tr key={h.id}><td><b>{h.name}</b></td><td>{h.outlier_cells}/{h.cells}</td><td>{fmt(h.score, 2)}</td><td>{fmt(h.temperature_z, 2)}</td><td>{fmt(h.ndvi_change)}</td><td>{fmt(h.rain_percentile)}</td><td>{fireAvailable ? h.fires : '—'}</td><td><button className="link-btn" onClick={() => { pick(h.id); setTab('overview') }}>Open</button></td></tr>)}
            </tbody></table></div></section>
            <div className="section-heading"><div><span className="eyebrow">CELL LEVEL</span><h2>Unusual cells in {data.location_name}</h2></div></div>
            <section className="settings-card wide"><div className="table-wrap"><table className="data-table"><thead><tr><th>Cell</th><th>Score</th><th>Why it stands out</th></tr></thead><tbody>
              {data.cells.filter(c => c.is_outlier).sort((x, y) => y.anomaly_score - x.anomaly_score).map(c => <tr key={c.id}><td><b>{c.name}</b></td><td>{fmt(c.anomaly_score, 2)}</td><td>{c.drivers.join(', ') || 'unusual combination of indicators'}</td></tr>)}
              {!data.cells.some(c => c.is_outlier) && <tr><td colSpan="3" className="muted">No outlier cells in this region.</td></tr>}
            </tbody></table></div></section>
          </>}

          {tab === 'methodology' && <section className="method-panel"><div className="section-heading"><div><span className="eyebrow">TRANSPARENT ANALYTICS</span><h2>Detection methodology</h2></div></div>
            <div className="method-list">
              {[['01', 'Temperature · Z-Score', 'Z = (x − μ) / σ', data.methodology.temperature], ['02', data.vegetation.unit === 'fraction' ? 'Vegetation · Soil Wetness Delta' : 'Vegetation · NDVI Delta', data.vegetation.unit === 'fraction' ? 'MERRA-2 root-zone soil wetness fraction' : 'NDVI = (NIR − Red) / (NIR + Red)', data.methodology.vegetation],
                ['03', 'Precipitation · Quantiles', 'Historical distribution quantiles (percentile rank)', data.methodology.precipitation], ['04', 'Fire detection · DBSCAN', 'Density-based spatial clustering', data.methodology.fire],
                ['05', 'Compound anomaly · Isolation Forest', fireAvailable ? 'V = [Z_temp, Δ%vegetation, Z_rain, Δ%Fire]' : 'V = [Z_temp, Δ%soil wetness, Z_precipitation]', data.methodology.compound]
              ].map(m => <div className="method-row" key={m[0]}><span className="method-number">{m[0]}</span><div><h3>{m[1]}</h3><code>{m[2]}</code><p>{m[3]}</p></div></div>)}
            </div>
            <div className="method-note"><ShieldCheck size={17} /><span>{data.source_mode === 'ARCHIVE' ? 'Historical NASA POWER data are bundled locally. Meteorological variables come from MERRA-2 reanalysis, not direct satellite observations; fire history is unavailable.' : data.source_mode === 'LIVE' ? 'Values come from the configured live NASA sources; see Settings → Data source for products and retrieval times.' : 'This build is running on simulated demonstration data, not NASA observations. Do not use it for operational decisions.'}</span></div>
          </section>}
        </>)}

        <footer className="footer"><div><span className="footer-brand">© {new Date().getFullYear()} TerraSignal</span></div><div><span className="footer-dot" /> {data ? `${data.source_mode} DATA` : '…'} <span className="footer-sep" /> API v2.0.0</div></footer>
      </div>
    </main>
  </div>
}
