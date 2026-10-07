"""Read numeric Hermes accounting only. Never read messages, prompts or credentials."""
from collections import defaultdict
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def read_rows(path, table):
    if not path.is_file():
        return []
    # Fixed table allow-list; read-only connections never migrate the host databases.
    columns = {
        'sessions': 'id,profile_name,billing_provider,billing_base_url,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,last_activity_at',
        'session_model_usage': 'session_id,model,billing_provider,billing_base_url,task,input_tokens,output_tokens,cache_read_tokens,cache_write_tokens,last_seen',
        'requests': 'attempt,generation_id,occurred,session,model,category,cost,prompt_tokens,completion_tokens,total_tokens,profile,key_fingerprint',
    }
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        con.row_factory = sqlite3.Row
        existing = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        # Missing optional columns on older Hermes builds stay explicitly unknown.
        projection = ','.join(c if c in existing else f'NULL AS {c}' for c in columns[table].split(','))
        return [dict(r) for r in con.execute(f'SELECT {projection} FROM {table}')]
    finally:
        con.close()


def token_total(row):
    # Hermes stores uncached input separately; cache reads/writes count once.
    # Reasoning is already part of output and must not be added again.
    return sum(count(row.get(c)) for c in ('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens'))


def build_analytics(root, rate, is_openrouter, amount, ledger_namespace='openrouter-spend',
                    active_key_fingerprint=None, key_total_usd=None):
    root = Path(root)
    homes = [('default', root)]
    profiles_dir = root / 'profiles'
    if profiles_dir.is_dir():
        homes += [(p.name,p) for p in sorted(profiles_dir.iterdir()) if p.is_dir() and not p.is_symlink() and (p/'config.yaml').is_file()]
    known = {name for name,_ in homes}
    warnings = []
    sessions = {}
    ledgers = []
    for home_name, home in homes:
        try:
            stored_sessions = read_rows(home/'state.db','sessions')
            usage = read_rows(home/'state.db','session_model_usage')
            by_session = defaultdict(list)
            for row in usage:
                by_session[row['session_id']].append(row)
            for session in stored_sessions:
                tag = session.get('profile_name')
                profile = tag if tag in known else home_name if not tag and home_name != 'default' else 'Other'
                rows = by_session.pop(session['id'],[])
                stamp = max([session.get('last_activity_at') or 0] + [r.get('last_seen') or 0 for r in rows])
                old = sessions.get(session['id'])
                # Cross-profile handoff/import can leave duplicate snapshots. Keep the newest
                # whole session rather than double-counting its cumulative totals.
                if old is None or stamp > old[0]:
                    sessions[session['id']] = (stamp,profile,session,rows)
            for sid,rows in by_session.items():
                sessions.setdefault(sid,(0,'Other',{},rows))
        except (sqlite3.Error,OSError,ValueError):
            warnings.append(f'Could not read {home_name} token history')
        try:
            for row in read_rows(home/'plugin-data'/ledger_namespace/'spend.sqlite3','requests'):
                # History spans all keys. Legacy records lack a key fingerprint,
                # but their response-reported costs are still valid accounting.
                row['profile'] = row.get('profile') or home_name
                ledgers.append(row)
        except (sqlite3.Error,OSError,ValueError):
            warnings.append(f'Could not read {home_name} request ledger')

    groups = {'profiles': defaultdict(int), 'models': defaultdict(int)}
    for _,profile,session,rows in sessions.values():
        accounted_main = 0
        for row in rows:
            if not row.get('task'):
                accounted_main += token_total(row)
            if not is_openrouter({'provider':row.get('billing_provider'),'base_url':row.get('billing_base_url')}):
                continue
            tokens = token_total(row)
            groups['profiles'][profile] += tokens
            groups['models'][row.get('model') or 'Other'] += tokens
        residual = max(0, token_total(session) - accounted_main)
        if residual and is_openrouter({'provider':session.get('billing_provider'),'base_url':session.get('billing_base_url')}):
            # A cumulative session total cannot identify the model active on each request.
            groups['profiles'][profile] += residual
            groups['models']['Other'] += residual

    costs = {'profiles':defaultdict(lambda:Decimal(0)), 'models':defaultdict(lambda:Decimal(0))}
    priced = {'profiles':set(), 'models':set()}
    key_costs = {kind:defaultdict(lambda:Decimal(0)) for kind in costs}
    outside_costs = {kind:defaultdict(lambda:Decimal(0)) for kind in costs}
    paired_cost = Decimal(0)
    paired_tokens = 0
    unresolved = 0
    assigned_key_cost = Decimal(0)
    seen = set()
    for row in ledgers:
        ident = row.get('generation_id') or row['attempt']
        if ident in seen:
            continue
        seen.add(ident)
        prompt,completion = row.get('prompt_tokens'),row.get('completion_tokens')
        complete_tokens = all(isinstance(n,int) and not isinstance(n,bool) and n >= 0 for n in (prompt,completion))
        reported_total = row.get('total_tokens')
        total_known = isinstance(reported_total,int) and not isinstance(reported_total,bool) and reported_total >= 0
        tokens = prompt + completion if complete_tokens else reported_total if total_known else 0
        complete_tokens = complete_tokens or total_known
        cost = amount(row.get('cost'))
        belongs_to_key = bool(active_key_fingerprint and row.get('key_fingerprint') == active_key_fingerprint
                              and row['category'] != 'manual')
        if belongs_to_key and cost is not None:
            assigned_key_cost += cost
        profile = row['profile'] if row['profile'] in known else 'Other'
        model = row.get('model') or 'Other'
        if row['category'] == 'manual':
            profile = model = 'Other'
            groups['profiles']['Other'] += tokens
            groups['models']['Other'] += tokens
        elif row.get('session') not in sessions:
            # Observer-only/turn-less requests are absent from Hermes's session history.
            groups['profiles'][profile] += tokens
            groups['models'][model] += tokens
        for kind,name in [('profiles',profile),('models',model)]:
            if cost is not None:
                costs[kind][name] += cost
                priced[kind].add(name)
                (key_costs if belongs_to_key else outside_costs)[kind][name] += cost
        if cost is not None and complete_tokens and tokens > 0:
            paired_cost += cost
            paired_tokens += tokens
        else:
            unresolved += 1

    def dual(value):
        return {'usd':None if value is None else str(value),'inr':None if value is None or rate is None else str(value*rate)}

    total = amount(key_total_usd)
    remainder = None if total is None or not active_key_fingerprint or total < assigned_key_cost else total - assigned_key_cost
    result = {}
    for kind in groups:
        names = set(groups[kind]) | set(costs[kind]) | {'Other'}
        if kind == 'profiles':
            names |= known
        result[kind] = [dict(name=name,tokens=groups[kind].get(name,0),
                            cost=dual(costs[kind][name] if name in priced[kind] else None),
                            key_cost=dual(None if not active_key_fingerprint else
                                          key_costs[kind][name]+(remainder or Decimal(0)) if name=='Other' else key_costs[kind][name]),
                            outside_key_cost=dual(outside_costs[kind][name]),
                            unassigned_cost=dual(remainder if name=='Other' else None))
                        for name in sorted(names,key=lambda n:(n=='Other',-groups[kind].get(n,0),n))]
    result.update(total_tokens=sum(groups['profiles'].values()),
                  average=dual(paired_cost*1_000_000/paired_tokens if paired_tokens else None),
                  paired_tokens=paired_tokens,paired_cost_usd=str(paired_cost),unresolved_requests=unresolved,
                  warnings=warnings,scope='Hermes recorded history · all OpenRouter keys',
                  cost_scope='Confirmed plugin costs · all recorded OpenRouter keys',period='recorded_history')
    # Provider totals include requests made before installation and other apps.
    # Show the remainder without assigning it to a model, profile or token count.
    # Manual entries and records from an unidentified/other key cannot reduce it.
    result['attribution'] = dict(total=dual(total),assigned=dual(assigned_key_cost),
                                 other=dual(remainder),tokens=None,
                                 scope='Selected API key · all apps',
                                 pending=total is not None and total < assigned_key_cost)
    return result


def monthly_comparison(month, rate, baseline_usd='110', baseline_inr='10699', label='Codex'):
    try:
        usd = Decimal(str(baseline_usd))
        inr = Decimal(str(baseline_inr)) if baseline_inr not in ('', None) else None if rate is None else usd*rate
        if not usd.is_finite() or usd <= 0 or (inr is not None and (not inr.is_finite() or inr < 0)):
            raise ValueError
    except (ValueError, ArithmeticError):
        raise ValueError('Comparison baseline must be a positive USD amount and a non-negative INR amount.') from None
    spent = None if month['usd'] is None else Decimal(month['usd'])
    spent_inr = None if month['inr'] is None else Decimal(month['inr'])
    return {'label':str(label or 'Comparison')[:80],
            'baseline':{'usd':str(usd),'inr':None if inr is None else str(inr)},'spent':month,
            'fraction':None if spent is None else str(spent/usd),
            'saved':{'usd':None if spent is None else str(usd-spent),
                     'inr':None if spent_inr is None or inr is None else str(inr-spent_inr)},
            'percentage_basis':'USD','period':'OpenRouter current UTC month'}


def chat_cost(root, session_id, amount, ledger_namespace='openrouter-spend'):
    """Confirmed charges for one conversation, including compression continuations.

    Read only identifiers and accounting metadata; no transcript or credentials.
    Unknown history stays unknown rather than becoming a zero-cost chat.
    """
    root = Path(root)
    homes = [root]
    if (root/'profiles').is_dir():
        homes += [p for p in sorted((root/'profiles').iterdir())
                  if p.is_dir() and not p.is_symlink() and (p/'config.yaml').is_file()]
    sessions, ledgers, warnings = {}, [], []
    for home in homes:
        path = home/'state.db'
        try:
            if path.is_file():
                with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as con:
                    con.row_factory = sqlite3.Row
                    existing = {r[1] for r in con.execute('PRAGMA table_info(sessions)')}
                    fields = ['id','parent_session_id','end_reason','last_activity_at',
                              'input_tokens','output_tokens','cache_read_tokens','cache_write_tokens']
                    projection = [c if c in existing else f'NULL AS {c}' for c in fields]
                    # Extract just fork flags, never read the full model configuration.
                    forks = ["source = 'tool'"] if 'source' in existing else []
                    if 'model_config' in existing:
                        forks += [f"json_extract(CASE WHEN json_valid(model_config) THEN model_config ELSE '{{}}' END,'$.{k}') = parent_session_id"
                                  for k in ('_branched_from','_delegate_from','_reset_from')]
                    projection.append('('+(' OR '.join(forks) or '0')+') AS separate_chat')
                    for row in con.execute('SELECT '+','.join(projection)+' FROM sessions'):
                        row = dict(row)
                        old = sessions.get(row['id'])
                        if old is None or (row['last_activity_at'] or 0) > (old['last_activity_at'] or 0):
                            sessions[row['id']] = row
        except (sqlite3.Error,OSError,ValueError):
            warnings.append('Some chat history is unavailable.')
        try:
            ledgers += read_rows(home/'plugin-data'/ledger_namespace/'spend.sqlite3','requests')
        except (sqlite3.Error,OSError,ValueError):
            warnings.append('Some recorded charges are unavailable.')
    ids = {session_id} if session_id else set()
    # Compression alone continues the same conversation; branches/resets do not.
    changed = True
    while changed:
        changed = False
        for sid, row in sessions.items():
            parent = row.get('parent_session_id')
            if row.get('separate_chat') or sessions.get(parent,{}).get('end_reason') != 'compression':
                continue
            if (sid in ids or parent in ids) and not {sid,parent} <= ids:
                ids.update((sid,parent)); changed = True
    total, confirmed, unresolved, captured_tokens, seen = Decimal(0), 0, 0, 0, set()
    for row in ledgers:
        if row.get('session') not in ids or row.get('category') == 'manual':
            continue
        ident = row.get('generation_id') or row['attempt']
        if ident in seen:
            continue
        seen.add(ident)
        cost = amount(row.get('cost'))
        if cost is None:
            unresolved += 1
            continue
        total += cost; confirmed += 1
        prompt, completion = row.get('prompt_tokens'), row.get('completion_tokens')
        captured_tokens += (prompt+completion if all(isinstance(n,int) and n >= 0 for n in (prompt,completion))
                            else count(row.get('total_tokens')))
    history_tokens = sum(token_total(sessions[sid]) for sid in ids if sid in sessions)
    empty = not session_id or (session_id in sessions and not history_tokens and not seen and not warnings)
    partial = bool(unresolved or warnings or history_tokens > captured_tokens)
    return dict(session_id=session_id,usd=str(total) if confirmed or empty else None,
                confirmed_requests=confirmed,unresolved_requests=unresolved,
                partial=partial,warnings=sorted(set(warnings)))
