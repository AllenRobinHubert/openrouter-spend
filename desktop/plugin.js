import {
  host, useValue, useQuery, STATUSBAR_AREAS, icons,
  Popover, PopoverTrigger, PopoverContent
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState, useEffect } from 'react'

const ID = 'openrouter-spend'
const EMPTY_VALUE = { get:()=>null,listen:()=>()=>{} }
const CSS = `
.ors-chip,.ors-panel{--ors-accent:#10b981;--ors-cyan:#06b6d4;--ors-ink:color-mix(in srgb,var(--ui-text-primary) 65%,var(--ors-accent));--ors-cyan-ink:color-mix(in srgb,var(--ui-text-primary) 65%,var(--ors-cyan));--ors-amber-ink:color-mix(in srgb,var(--ui-text-primary) 65%,#f59e0b);--ors-red-ink:color-mix(in srgb,var(--ui-text-primary) 65%,#f43f5e)}
.ors-chip{display:inline-flex;align-items:center;gap:7px;height:25px;margin:0 4px 2px;padding:0 9px 2px;border:1px solid var(--ui-stroke-secondary);border-radius:7px;background:color-mix(in srgb,var(--ors-accent) 7%,transparent);color:var(--ui-text-secondary);font-size:11px;white-space:nowrap;cursor:pointer;transition:background .15s,border-color .15s}
.ors-chip:hover,.ors-chip[data-state="open"]{background:color-mix(in srgb,var(--ors-accent) 15%,transparent);border-color:color-mix(in srgb,var(--ors-accent) 45%,var(--ui-stroke-secondary))}
.ors-chip{background:color-mix(in srgb,var(--ors-accent) 16%,transparent);border-color:color-mix(in srgb,var(--ors-accent) 42%,var(--ui-stroke-secondary))}
.ors-chip:hover,.ors-chip[data-state="open"]{background:color-mix(in srgb,var(--ors-accent) 25%,transparent);border-color:var(--ors-accent)}
.ors-chip:focus-visible,.ors-refresh:focus-visible,.ors-details summary:focus-visible{outline:2px solid var(--ors-accent);outline-offset:2px}
.ors-icon{color:var(--ors-ink);flex-shrink:0}
.ors-usd{font-weight:650;color:var(--ors-ink);font-variant-numeric:tabular-nums}
.ors-chat-label{font-size:9px;color:var(--ui-text-tertiary)}
.ors-chat{margin:0 18px 16px;padding:12px;border:1px solid var(--ui-stroke-secondary);border-radius:9px;background:color-mix(in srgb,var(--ors-cyan) 7%,transparent)}
.ors-chat-values{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:5px 0}
.ors-chat-values strong{font-size:18px;color:var(--ors-ink);font-variant-numeric:tabular-nums}
.ors-inr{font-variant-numeric:tabular-nums;color:var(--ors-cyan-ink)}
.ors-divider{height:12px;width:1px;background:var(--ui-stroke-secondary)}
.ors-panel{width:390px;max-height:min(780px,calc(100vh - 70px));overflow-y:auto;overscroll-behavior:contain;max-width:calc(100vw - 24px);font-size:12px;line-height:1.45;color:var(--ui-text-primary)}
.ors-head{display:flex;align-items:center;gap:10px;padding:17px 18px 14px}
.ors-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:10px;background:color-mix(in srgb,var(--ors-accent) 12%,transparent);border:1px solid color-mix(in srgb,var(--ors-accent) 22%,transparent)}
.ors-brand{font-size:10px;font-weight:650;letter-spacing:.11em;color:var(--ors-ink)}
.ors-title{font-size:14px;font-weight:600;letter-spacing:-.02em}
.ors-status{margin-left:auto;display:flex;align-items:center;gap:5px;font-size:10px;color:var(--ui-text-tertiary)}
.ors-dot{width:5px;height:5px;border-radius:50%;background:var(--ors-accent)}
.ors-status[data-state="stale"]{color:var(--ors-amber-ink)}
.ors-status[data-state="stale"] .ors-dot{background:#f59e0b}
.ors-status[data-state="error"]{color:var(--ors-red-ink)}
.ors-status[data-state="error"] .ors-dot{background:#f43f5e}
.ors-hero{margin:0 12px;padding:17px 18px 18px;border:1px solid color-mix(in srgb,var(--ors-accent) 40%,var(--ui-stroke-secondary));border-radius:12px;background:linear-gradient(125deg,color-mix(in srgb,var(--ors-accent) 19%,transparent),color-mix(in srgb,var(--ors-cyan) 9%,transparent))}
.ors-hero .ors-eyebrow,.ors-total{color:var(--ors-ink)}
.ors-eyebrow{font-size:10px;color:var(--ui-text-tertiary);font-weight:550;letter-spacing:.08em;text-transform:uppercase}
.ors-total{margin:5px 0 1px;font-size:31px;line-height:1.2;letter-spacing:-.045em;font-weight:600;font-variant-numeric:tabular-nums}
.ors-total small{margin-left:7px;font-size:10px;letter-spacing:.05em;font-weight:500;color:var(--ui-text-quaternary)}
.ors-converted{font-size:16px;font-variant-numeric:tabular-nums;color:var(--ors-cyan-ink);letter-spacing:-.02em}
.ors-converted small{font-size:10px;margin-left:7px;letter-spacing:.04em;color:var(--ui-text-quaternary)}
.ors-periods{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));padding:18px 18px 17px;gap:12px}
.ors-period+.ors-period{border-left:1px solid var(--ui-stroke-secondary);padding-left:12px}
.ors-period-label{font-size:10px;color:var(--ui-text-quaternary);margin-bottom:6px}
.ors-period-usd{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.ors-period-inr{margin-top:2px;font-size:11px;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums}
.ors-period-label{color:var(--ors-ink)}
.ors-period-inr{color:var(--ors-cyan-ink)}
.ors-context{margin:0 18px 14px;display:flex;align-items:center;gap:6px;font-size:10px;color:var(--ui-text-quaternary)}
.ors-profile{display:inline-block;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:2px 6px;border:1px solid var(--ui-stroke-secondary);border-radius:4px;color:var(--ui-text-tertiary)}
.ors-profile{color:var(--ors-ink);background:color-mix(in srgb,var(--ors-accent) 10%,transparent);border-color:color-mix(in srgb,var(--ors-accent) 28%,var(--ui-stroke-secondary))}
.ors-footer{padding:11px 18px;border-top:1px solid var(--ui-stroke-secondary);display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:10px;color:var(--ui-text-quaternary)}
.ors-refresh{display:inline-flex;align-items:center;gap:5px;padding:4px 7px;border-radius:5px;font-size:10px;color:var(--ui-text-tertiary);cursor:pointer}
.ors-refresh:hover{background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.ors-refresh:disabled{opacity:.6;cursor:default}
.ors-details{padding:0 18px 12px;font-size:10px;color:var(--ui-text-quaternary)}
.ors-details summary{cursor:pointer;width:fit-content}
.ors-details p{margin:6px 0 0;line-height:1.5}
.ors-empty{padding:10px 18px 20px;color:var(--ui-text-tertiary);font-size:12px}
.ors-section{margin:0 18px 16px;padding-top:15px;border-top:1px solid var(--ui-stroke-secondary)}
.ors-section-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px;font-size:11px;font-weight:600}
.ors-muted{font-size:10px;color:var(--ui-text-quaternary);font-weight:400;line-height:1.5}
.ors-budget-values{display:flex;justify-content:space-between;gap:10px;font-size:11px;margin-bottom:8px;font-variant-numeric:tabular-nums}
.ors-track{height:7px;background:var(--ui-stroke-secondary);border-radius:8px;overflow:hidden}
.ors-fill{height:100%;background:linear-gradient(90deg,var(--ors-accent),var(--ors-cyan));border-radius:8px;min-width:2px;transition:width .3s}
.ors-track[data-level="near"] .ors-fill{background:#f59e0b}
.ors-track[data-level="over"] .ors-fill{background:#f43f5e}
.ors-saving{display:flex;justify-content:space-between;gap:8px;margin-top:9px;font-size:11px;font-variant-numeric:tabular-nums}
.ors-saving strong{color:var(--ors-ink)}
.ors-saving[data-negative="true"] strong{color:var(--ors-red-ink)}
.ors-average{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:10px 0}
.ors-average strong{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}
.ors-average strong{color:color-mix(in srgb,var(--ui-text-primary) 65%,#8b5cf6)}
.ors-tabs{display:flex;gap:3px;padding:2px;border:1px solid var(--ui-stroke-secondary);border-radius:6px}
.ors-tabs button{padding:3px 7px;font-size:10px;border-radius:4px;color:var(--ui-text-tertiary);cursor:pointer}
.ors-tabs button[aria-pressed="true"]{background:color-mix(in srgb,var(--ors-accent) 19%,transparent);color:var(--ors-ink)}
.ors-table{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}
.ors-table th{font-weight:400;font-size:9px;color:var(--ui-text-quaternary);text-align:right;padding:4px 0 7px}
.ors-table th:first-child{text-align:left}
.ors-table td{padding:7px 0;border-top:1px solid var(--ui-stroke-secondary);text-align:right;vertical-align:top}
.ors-table td:first-child{text-align:left;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ors-table td small{display:block;color:var(--ui-text-quaternary);font-size:9px;margin-top:1px}
.ors-table td:nth-child(2){color:var(--ors-cyan-ink)}
.ors-table td:nth-child(3){color:var(--ors-ink)}
.ors-manual{margin-top:10px}
.ors-manual summary{font-size:10px;cursor:pointer;color:var(--ui-text-tertiary)}
.ors-inputs{display:grid;grid-template-columns:1fr 1fr auto;gap:7px;align-items:end;margin:9px 0}
.ors-inputs label{font-size:9px;color:var(--ui-text-quaternary)}
.ors-inputs input{display:block;width:100%;margin-top:4px;padding:5px 6px;border-radius:5px;border:1px solid var(--ui-stroke-secondary);background:transparent;color:var(--ui-text-primary);font-size:11px}
@media(prefers-reduced-motion:reduce){.ors-chip,.ors-fill{transition:none}}
`

function Wallet({ size, className }) {
  return jsxs('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', className, 'aria-hidden': true,
    children: [jsx('path', { d: 'M20 8V6a2 2 0 0 0-2-2H6a3 3 0 0 0 0 6h14v10H6a3 3 0 0 1-3-3V7' }), jsx('path', { d: 'M20 12h-4a2 2 0 0 0 0 4h4' }), jsx('path', { d: 'M16 14h.01' })] })
}

function format(value, symbol, digits) {
  if (value == null || !Number.isFinite(Number(value))) return symbol + '—'
  return symbol + Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: digits, maximumFractionDigits: digits
  })
}

function tokenLabel(value) {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(2) + 'M'
  if (value >= 1000) return (value / 1000).toFixed(1) + 'K'
  return Number(value || 0).toLocaleString('en-IN')
}

function tableCost(row, attribution) {
  const extra = row.unassigned_cost
  return { cost: row.key_cost || { usd:null,inr:null },
    unassigned: extra?.usd != null && Number(extra.usd)>0,
    pending: row.name==='Other' && attribution?.pending,
    title: row.name==='Other' ? `Includes unassigned key spend: ${format(extra?.usd,'$',4)}` : 'Confirmed charges for the selected API key' }
}

function Comparison({ data }) {
  const fraction = data.fraction == null ? null : Number(data.fraction)
  const saved = data.saved
  const baseline = Number(data.baseline.usd)
  return jsxs('div', { className: 'ors-section', children: [
    jsxs('div', { className: 'ors-section-head', children: [`Monthly vs ${data.label || 'Comparison'}`, jsx('span', { className: 'ors-muted', children: fraction == null ? 'Unavailable' : `${(fraction * 100).toFixed(1)}% used` })] }),
    jsxs('div', { className: 'ors-budget-values', children: [jsx('span', { children: `${format(data.spent.usd,'$',2)} / ≈${format(data.spent.inr,'₹',2)}` }), jsx('span', { className: 'ors-muted', children: `${format(data.baseline.usd,'$',2)} / ${format(data.baseline.inr,'₹',2)}` })] }),
    jsx('div', { className: 'ors-track', 'data-level': fraction>=1?'over':fraction>=0.8?'near':'normal', role: 'progressbar', 'aria-label': `Monthly API spend compared with ${data.label || 'configured'} baseline`, 'aria-valuemin': 0, 'aria-valuemax': baseline, 'aria-valuenow': fraction == null ? undefined : Math.min(baseline,Number(data.spent.usd)), 'aria-valuetext': fraction == null ? 'Monthly spend unavailable' : `${(fraction*100).toFixed(1)} percent of baseline spent`, children: fraction == null ? null : jsx('div', { className: 'ors-fill', style: { width: `${Math.min(100,Math.max(0,fraction*100))}%`, minWidth: fraction === 0 ? 0 : undefined } }) }),
    jsxs('div', { className: 'ors-saving', 'data-negative': saved.usd != null && Number(saved.usd)<0, children: [jsx('span', { className: 'ors-muted', children: 'Saved so far' }), jsx('strong', { children: `${format(saved.usd,'$',2)} / ${saved.inr == null ? '₹—' : '≈'+format(saved.inr,'₹',2)}` })] })
  ] })
}

function Analytics({ data, ctx, refresh }) {
  const [tab,setTab] = useState('profiles')
  const [tokens,setTokens] = useState('')
  const [cost,setCost] = useState('')
  const [busy,setBusy] = useState(false)
  const [message,setMessage] = useState('')
  const [undo,setUndo] = useState(null)
  async function add(event) {
    event.preventDefault()
    setBusy(true); setMessage('')
    try {
      const value = Number(tokens)
      if (!Number.isSafeInteger(value) || value <= 0) throw new Error('Enter a positive whole token count.')
      const response = await ctx.rest('/other', { method:'POST',body:{tokens:value,cost_usd:cost.trim() || null} })
      if (!response.ok) throw new Error(response.error || 'Could not add usage.')
      setUndo(response.id); setTokens(''); setCost(''); setMessage('Added to Other.'); await refresh()
    } catch(error) { setMessage(error.message || 'Could not add usage.') }
    finally { setBusy(false) }
  }
  async function undoLast() {
    setBusy(true)
    try { await ctx.rest('/other/'+undo,{method:'DELETE'}); setUndo(null); setMessage('Entry removed.'); await refresh() }
    catch { setMessage('Could not undo. Try again.') }
    finally { setBusy(false) }
  }
  return jsxs('div', { className:'ors-section',children:[
    jsxs('div', { className:'ors-average',children:[
      jsxs('div', { children:[jsx('div',{className:'ors-eyebrow',children:'Tracked average / 1M tokens'}),jsx('div',{className:'ors-muted',children:data.paired_tokens ? `${tokenLabel(data.paired_tokens)} tokens with matched costs` : 'Waiting for matched costs + tokens'})] }),
      jsxs('div',{style:{textAlign:'right'},children:[jsx('strong',{children:format(data.average.usd,'$',2)}),jsx('div',{className:'ors-muted',children:data.average.inr == null ? '₹—' : '≈'+format(data.average.inr,'₹',2)})]})
    ]}),
    jsxs('div',{className:'ors-section-head',style:{marginTop:'10px'},children:[jsx('span',{children:`Token consumption · ${tokenLabel(data.total_tokens)}`}),jsx('div',{className:'ors-tabs',children:['profiles','models'].map(kind=>jsx('button',{type:'button','aria-pressed':tab===kind,onClick:()=>setTab(kind),children:kind==='profiles'?'Profiles':'Models'},kind))})]}),
    jsx('div',{className:'ors-muted',style:{marginBottom:'7px'},children:'Hermes recorded history · all OpenRouter keys'}),
    jsxs('table',{className:'ors-table',children:[jsx('thead',{children:jsxs('tr',{children:[jsx('th',{children:tab==='profiles'?'Profile':'Model'}),jsx('th',{children:'TOKENS¹'}),jsx('th',{children:'KEY SPEND'})]})}),jsx('tbody',{children:data[tab].map(row=>{
      const displayed = tableCost(row,data.attribution)
      return jsxs('tr',{children:[jsx('td',{title:row.name,children:row.name}),jsxs('td',{title:Number(row.tokens).toLocaleString('en-IN')+' recorded tokens'+(displayed.unassigned?' · unassigned spend has unknown tokens':''),children:[tokenLabel(row.tokens),displayed.unassigned?jsx('small',{children:'+ unknown'}):null]}),jsxs('td',{title:displayed.title,children:[format(displayed.cost.usd,'$',4),jsx('small',{children:displayed.cost.inr==null?'₹—':'≈'+format(displayed.cost.inr,'₹',2)}),Number(row.outside_key_cost?.usd)>0?jsx('small',{title:'Confirmed history or manual costs excluded from the selected key total',children:'Outside key: '+format(row.outside_key_cost.usd,'$',4)}):null,displayed.pending?jsx('small',{children:'Unassigned spend syncing…'}):null]})]},row.name)
    })})]}),
    jsx('div',{className:'ors-muted',style:{marginTop:'8px'},children:'¹ Tokens and tracked average cover recorded history across all keys. Key spend uses only this API key. Outside-key costs are excluded.'}),
    data.attribution ? jsx('div',{className:'ors-muted',children:'Other includes this API key’s unassigned spend, with unknown tokens. Key spend reconciles to the provider total once synced.'}) : null,
    ...data.warnings.map((warning,i)=>jsx('div',{className:'ors-muted',children:warning},i)),
    jsxs('details',{className:'ors-manual',children:[jsx('summary',{children:'Add untracked usage to Other'}),jsx('div',{className:'ors-muted',style:{marginTop:'6px'},children:'Add tokens absent from Hermes history. Use the actual cost if known. This does not increase OpenRouter’s spend total.'}),jsxs('form',{onSubmit:add,children:[jsxs('div',{className:'ors-inputs',children:[jsxs('label',{children:['Total tokens',jsx('input',{type:'number',min:1,max:1000000000,step:1,required:true,value:tokens,onChange:e=>setTokens(e.target.value)})]}),jsxs('label',{children:['Cost in USD (optional)',jsx('input',{type:'number',min:0,step:'any',value:cost,onChange:e=>setCost(e.target.value)})]}),jsx('button',{type:'submit',className:'ors-refresh',disabled:busy,children:busy?'Saving…':'Add'})]}),jsxs('div',{className:'ors-muted',role:'status',children:[message,undo?jsx('button',{type:'button',className:'ors-refresh',disabled:busy,onClick:undoLast,children:'Undo'}):null]})]})]})
  ]})
}

function SpendStatus({ ctx }) {
  const profile = useValue(host.state.profile)
  const connection = useValue(host.state.connectionId)
  const gateway = useValue(host.state.gateway)
  const session = useValue(host.state.focusedStoredSessionId || EMPTY_VALUE)
  const owner = useValue(host.state.focusedSessionOwner || EMPTY_VALUE)
  const busy = useValue(host.state.busy || EMPTY_VALUE)
  const chatQuery = useQuery({
    queryKey: [ID, 'chat', owner?.connectionId || connection, session],
    queryFn: async () => {
      if (!host.state.focusedStoredSessionId) throw new Error('This Hermes build cannot identify the focused chat.')
      if (owner?.connectionId && connection && owner.connectionId !== connection)
        throw new Error('Chat belongs to another connection.')
      const response = await ctx.rest('/chat?session_id=' + encodeURIComponent(session || ''), { timeoutMs: 10000 })
      if (!response?.ok) throw new Error(response?.error || 'Chat cost endpoint unavailable.')
      return response
    },
    staleTime: 0, refetchInterval: busy ? 5000 : 15000,
    refetchIntervalInBackground: false, retry: 1
  })
  useEffect(() => { if (!busy) chatQuery.refetch() }, [busy, session])
  const query = useQuery({
    queryKey: [ID, 'summary', connection, profile, gateway],
    queryFn: () => ctx.rest('/summary', { timeoutMs: 25000 }),
    staleTime: 30000, refetchInterval: 45000,
    refetchIntervalInBackground: false, retry: 1
  })
  const data = query.data
  const total = data?.ok ? data.periods.total : null
  const unavailable = query.isError || (data && !data.ok)
  const stale = data?.stale || (total && query.isError)
  const usd = total ? format(total.usd, '$', 4) : unavailable ? '$—' : '$…'
  const inr = total ? (total.inr == null ? '₹—' : '≈' + format(total.inr, '₹', 2)) : unavailable ? '₹—' : '₹…'
  const fx = data?.fx
  const chat = host.state.focusedStoredSessionId && chatQuery.data?.ok && chatQuery.data.session_id === (session || '') ? chatQuery.data : null
  const chatUsd = chat ? format(chat.usd, '$', 4) : chatQuery.isError || chatQuery.data?.ok === false ? '$—' : '$…'
  const chatInr = chat?.usd != null && fx?.rate != null
    ? '≈' + format(Number(chat.usd) * Number(fx.rate), '₹', 2) : '₹—'
  const chatNote = !chat || chat.usd == null
    ? 'No confirmed cost recorded for this chat yet.'
    : chat.partial ? 'Confirmed charges so far. Some chat usage has no recorded cost.'
    : 'Confirmed charges for this conversation, including image generation.'
  async function refresh() { await Promise.all([query.refetch(), chatQuery.refetch()]) }
  const rateDescription = fx?.rate
    ? `₹${fx.rate} per USD · ${fx.date || 'manual rate'} · ${fx.source}${fx.stale ? ' · cached rate' : ''}`
    : 'INR exchange rate unavailable'
  const status = stale ? 'Cached' : unavailable ? 'Offline' : query.isFetching ? 'Updating' : 'Synced'

  return jsxs(Popover, { children: [
    jsx(PopoverTrigger, { asChild: true, children: jsxs('button', {
      type: 'button', className: 'ors-chip',
      title: `Total ${usd} · ${inr} | This chat ${chatUsd} · ${chatInr}${chat?.partial ? ' · partial recorded cost' : ''}${stale ? ' · cached totals' : ''}`,
      'aria-label': `OpenRouter total ${usd} · ${inr} · This chat ${chatUsd} · ${chatInr}${stale ? ' · cached' : ''}`,
      children: [
        jsx(Wallet, { size: 12, className: 'ors-icon' }),
        jsx('span', { className: 'ors-usd', children: usd }),
        jsx('span', { className: 'ors-divider', 'aria-hidden': true }),
        jsx('span', { className: 'ors-inr', children: inr }),
        jsx('span', { className: 'ors-divider', 'aria-hidden': true }),
        jsx('span', { className: 'ors-chat-label', children: 'This chat' }),
        jsx('span', { className: 'ors-usd', children: chatUsd }),
        jsx(icons.ChevronUp, { size: 10, 'aria-hidden': true })
      ]
    }) }),
    jsx(PopoverContent, {
      side: 'top', align: 'end', className: 'w-auto p-0', style: { padding: 0, width: 'auto', overflow: 'hidden', borderRadius: '14px' },
      'aria-label': 'OpenRouter spend breakdown',
      children: jsxs('div', { className: 'ors-panel', children: [
        jsxs('div', { className: 'ors-head', children: [
          jsx('div', { className: 'ors-mark', children: jsx(Wallet, { size: 17, className: 'ors-icon' }) }),
          jsxs('div', { children: [jsx('div', { className: 'ors-brand', children: 'OPENROUTER' }), jsx('div', { className: 'ors-title', children: 'API spend' })] }),
          jsxs('div', { className: 'ors-status', 'data-state': stale ? 'stale' : unavailable ? 'error' : 'ready', children: [jsx('span', { className: 'ors-dot' }), status] })
        ] }),
        jsxs('div', { className: 'ors-chat', children: [
          jsx('div', { className: 'ors-eyebrow', children: 'This chat' }),
          jsxs('div', { className: 'ors-chat-values', children: [jsx('strong', { children: chatUsd }), jsx('span', { className: 'ors-inr', children: chatInr })] }),
          jsx('div', { className: 'ors-muted', children: chatQuery.isError ? 'Chat cost unavailable. Try refreshing.' : chatNote })
        ] }),
        ...(total ? [
          jsxs('div', { className: 'ors-hero', children: [
            jsx('div', { className: 'ors-eyebrow', children: 'Total spend' }),
            jsxs('div', { className: 'ors-total', children: [format(total.usd, '$', 4), jsx('small', { children: 'USD' })] }),
            jsxs('div', { className: 'ors-converted', children: [inr, jsx('small', { children: 'INR' })] })
          ] }),
          jsx('div', { className: 'ors-periods', children: ['today', 'week', 'month'].map(period =>
            jsxs('div', { className: 'ors-period', children: [
              jsx('div', { className: 'ors-period-label', children: { today: 'Today', week: 'This week', month: 'This month' }[period] }),
              jsx('div', { className: 'ors-period-usd', children: format(data.periods[period].usd, '$', 4) }),
              jsx('div', { className: 'ors-period-inr', children: data.periods[period].inr == null ? '₹—' : '≈' + format(data.periods[period].inr, '₹', 2) })
            ] }, period)) }),
          jsxs('div', { className: 'ors-context', children: [jsx('span', { className: 'ors-profile', title: profile || 'default', children: profile || 'default' }), jsx('span', { children: 'All apps using this API key' })] })
          ,data.comparison ? jsx(Comparison,{data:data.comparison}) : null
          ,data.analytics ? jsx(Analytics,{data:data.analytics,ctx,refresh}) : null
        ] : [jsx('div', { className: 'ors-empty', role: unavailable ? 'status' : undefined, children: data?.error || (query.isError ? 'Unable to reach spend accounting. Try refreshing.' : 'Fetching your spend…') })]),
        jsxs('div', { className: 'ors-footer', children: [
          jsx('span', { children: data?.fetched_at ? `${stale ? 'Cached' : 'Updated'} ${new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Refreshes every 45 seconds' }),
          jsxs('button', { type: 'button', className: 'ors-refresh', disabled: query.isFetching || chatQuery.isFetching, onClick: refresh, children: [jsx(icons.RefreshCw, { size: 11, 'aria-hidden': true }), query.isFetching ? 'Refreshing' : 'Refresh'] })
        ] }),
        jsxs('details', { className: 'ors-details', children: [jsx('summary', { children: 'About these totals' }), jsx('p', { children: `Spend is reported by OpenRouter for this API key. INR is approximate. ${rateDescription}. Purchase fees are excluded.` })] })
      ] })
    })
  ] })
}

export default {
  id: ID, name: 'OpenRouter Spend · USD / INR',
  description: 'Live API spend in the status bar, with USD and INR breakdowns.',
  register(ctx) {
    const style = document.createElement('style')
    style.textContent = CSS
    document.head.append(style)
    ctx.onDispose(() => style.remove())
    ctx.register({ id: 'spend-status', area: STATUSBAR_AREAS.right, order: 125,
      render: () => jsx(SpendStatus, { ctx }) })
  }
}
