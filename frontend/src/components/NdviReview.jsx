import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-basic-dist-min'
import { api, errorText } from '../lib/api'
import './NdviReview.css'

const Plot = createPlotlyComponent(Plotly)
const fmt = (v, digits = 2) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : 'Unavailable'

function ReviewMap({ geojson }) {
  const container = useRef(null)
  useEffect(() => {
    const map = L.map(container.current, { preferCanvas: true }).setView([-35.3, 149.15], 11)
    L.rectangle([[-35.45,149],[-35.15,149.3]], { color: '#5eead4', weight: 2, fill: false }).addTo(map)
    L.control.scale({ imperial: false }).addTo(map)
    // No external basemap requests: pilot points remain available offline.
    const layer = L.geoJSON(geojson, {
      pointToLayer: (f, latlng) => L.circleMarker(latlng, {
        radius: 2, stroke: false, fillOpacity: 0.75,
        fillColor: f.properties.status === 'LOW_BASELINE' ? '#777' :
          f.properties.absolute_difference < 0 ? '#c2410c' : '#0369a1',
      }),
      onEachFeature: (f, item) => {
        const node = document.createElement('div')
        node.textContent = `${f.geometry.coordinates[1].toFixed(4)}°, ${f.geometry.coordinates[0].toFixed(4)}° | NDVI ${fmt(f.properties.ndvi, 4)}; baseline ${fmt(f.properties.baseline, 4)}; difference ${fmt(f.properties.absolute_difference, 4)}`
        item.bindPopup(node)
      },
    }).addTo(map)
    map.fitBounds([[-35.45,149],[-35.15,149.3]], { padding: [20,20] })
    const resize = new ResizeObserver(() => map.invalidateSize())
    resize.observe(container.current)
    return () => { resize.disconnect(); map.remove() }
  }, [geojson])
  return <div ref={container} className="ndvi-map" aria-label="Canberra NDVI difference map" />
}

export default function NdviReview() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const alive = useRef(true)
  const request = useRef(0)
  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; request.current += 1 } }, [])
  async function load() {
    const id = ++request.current
    setLoading(true); setError(''); setData(null)
    try {
      const response = await api.get('/api/ndvi/canberra/review')
      if (alive.current && request.current === id) setData(response.data)
    } catch (e) { if (alive.current && request.current === id) setError(errorText(e, 'NDVI review unavailable.')) }
    finally { if (alive.current && request.current === id) setLoading(false) }
  }
  const r = data?.result
  const rows = data?.timeseries || []
  const gaps = rows.filter(x => !x.reportable)
  return <section className="ndvi-review chart-card" aria-busy={loading}>
    <header className="ndvi-header"><div><span className="ndvi-eyebrow">VEGETATION · MODIS NDVI</span>
    <h2>Canberra, Australia</h2><p>Selected study area · Historical satellite observations for 2025.</p></div>
    <button className="ndvi-button" onClick={load} disabled={loading}>{loading ? 'Loading observations…' : data ? 'Refresh NDVI' : 'Retry NDVI'}</button></header>
    {loading && <p role="status">Checking the observed-data package…</p>}
    {error && <p className="ndvi-error" role="alert">{error}</p>}
    {data && <>
      <div className="ndvi-context"><span>Composite: <strong>{r.date}</strong></span><span>Seasonal baseline: <strong>2020–2024</strong></span><span>Source: <strong>{data.source}</strong></span></div>
      <dl className="ndvi-metrics stats-grid">
        {[['Observed NDVI', fmt(r.current, 4)], ['Seasonal baseline', fmt(r.baseline, 4)],
          ['Change (%)', fmt(r.change_percent)], ['Matched coverage (%)', fmt(r.matched_coverage_percent)],
          ['Status', r.status.replaceAll('_', ' ')]].map(([label, value]) => <div className="stat-card" key={label}><dt className="stat-label">{label}</dt><dd className="stat-value">{value}</dd></div>)}
      </dl>
      <h3>2025 observations and seasonal baseline</h3>
      <Plot data={[
        { x: rows.map(x => x.date), y: rows.map(x => x.current), name: 'Observed NDVI', line: {color:'#5eead4'}, mode: 'lines+markers', connectgaps: false },
        { x: rows.map(x => x.date), y: rows.map(x => x.baseline), name: 'Seasonal baseline', line: {color:'#fbbf24',dash:'dash'}, mode: 'lines', connectgaps: false },
      ]} layout={{ autosize: true, height: 340, margin: { t: 20, r: 20, b: 85, l: 55 },
        paper_bgcolor:'#0d1c29', plot_bgcolor:'#0d1c29',font:{color:'#cbd5e1'},
        xaxis: { title: {text:'Composite start date'}, range:['2025-01-01','2025-12-31'],gridcolor:'#243747' },
        yaxis: { title: {text:'NDVI'},gridcolor:'#243747' }, legend: { orientation: 'h',y:-.25 } }}
        config={{ responsive: true, displaylogo: false }} useResizeHandler style={{ width: '100%' }} />
      <p>Gaps are withheld observations, not zero NDVI. Matched locations may vary between dates.</p>
      {gaps.length > 0 && <details className="ndvi-details"><summary>Why {gaps.length} observations are withheld</summary><div className="ndvi-table-wrap"><table><thead><tr><th>Composite</th><th>Coverage</th><th>Reason</th></tr></thead><tbody>{gaps.map(x=><tr key={x.date}><td>{x.date}</td><td>{fmt(x.matched_coverage_percent)}%</td><td>{x.status.replaceAll('_',' ').toLowerCase()}</td></tr>)}</tbody></table></div></details>}
      <h3>Spatial difference · {r.date} composite</h3>
      <div className="ndvi-legend"><span><i style={{background:'#c2410c'}} />Lower NDVI</span><span><i style={{background:'#0369a1'}} />At or above baseline</span><span><i style={{background:'#777'}} />Low baseline</span><span>Outline: study boundary</span></div>
      {data.geojson.features.length ? <ReviewMap geojson={data.geojson} /> : <p>No reportable map is available for this composite.</p>}
      <p>35.45°S–35.15°S · 149.00°E–149.30°E. Pixel centres shown; background has no observations or is outside the study area. No external basemap is required.</p>
      <details className="ndvi-details"><summary>Method and interpretation</summary><p>Quality-filtered MOD13Q1 NDVI compared with pixel-level seasonal historical medians on matched locations. Regional values are medians; at least four historical observations per pixel and 80% matched study-area coverage are required by the pilot reporting policy.</p><p>Lower NDVI is not confirmed vegetation damage. Colours show direction, not severity. Composite labels are not exact pixel acquisition bounds; December pixels may include early January. This candidate is excluded from compound analysis and is not approved for deployment.</p></details>
    </>}
  </section>
}
