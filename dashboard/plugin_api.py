"""Profile-scoped desktop backend; credentials stay on the backend."""
import importlib.util
from pathlib import Path
import hashlib
import time
import uuid
from fastapi import APIRouter
from pydantic import BaseModel, Field
from hermes_cli.config import load_config
from hermes_cli.plugins_state import PluginState
from hermes_constants import get_default_hermes_root

_spec = importlib.util.spec_from_file_location(
    "openrouter_spend_accounting", Path(__file__).resolve().parents[1] / "spend.py")
_spend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spend)
_analytics_spec = importlib.util.spec_from_file_location(
    'openrouter_spend_analytics', Path(__file__).resolve().parents[1] / 'analytics.py')
_analytics = importlib.util.module_from_spec(_analytics_spec)
_analytics_spec.loader.exec_module(_analytics)
router = APIRouter()


@router.get('/chat')
def chat(session_id: str = ''):
    try:
        namespace = PluginState('openrouter-spend').data_dir.name
        return {'ok': True, **_analytics.chat_cost(get_default_hermes_root(), session_id,
                                                  _spend.amount, namespace)}
    except Exception:
        return {'ok': False, 'error': 'Chat cost unavailable'}


def setting(key, default=None):
    return (load_config().get("plugins", {}).get("entries", {}).get(
        "openrouter-spend", {}).get("settings", {}).get(key, default))


@router.get("/summary")
def summary(refresh: bool = False):
    # Resolve the data directory inside the request's secret/profile scope, never at import time.
    plugin = _spend.SpendPlugin(PluginState("openrouter-spend").data_dir, setting)
    try:
        data = plugin.summary(refresh)
        rate = _spend.amount(data['fx'].get('rate'))
        data['analytics'] = _analytics.build_analytics(get_default_hermes_root(), rate,
                                                     _spend.is_openrouter, _spend.amount,plugin.ledger.directory.name,
                                                     active_key_fingerprint=hashlib.sha256(plugin.key().encode()).hexdigest(),
                                                     key_total_usd=data['periods']['total']['usd'])
        data['comparison'] = _analytics.monthly_comparison(
            data['periods']['month'],rate,setting('comparison_usd','110'),
            setting('comparison_inr','10699'),setting('comparison_label','Codex'))
        return {"ok": True, **data}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "Spend accounting unavailable"}


class OtherUsage(BaseModel):
    tokens: int = Field(gt=0,le=1_000_000_000,strict=True)
    cost_usd: str | None = Field(default=None,max_length=40)


@router.post('/other')
def add_other(body: OtherUsage):
    plugin = _spend.SpendPlugin(PluginState('openrouter-spend').data_dir,setting)
    cost = _spend.amount(body.cost_usd) if body.cost_usd else None
    if body.cost_usd and (cost is None or cost > 1_000_000):
        return {'ok':False,'error':'Enter a valid non-negative USD cost.'}
    ident = 'manual-' + uuid.uuid4().hex
    plugin.ledger.upsert(dict(attempt=ident,generation_id=None,occurred=time.time(),session='',
                             model='Other',category='manual',outcome='success',cost=None if cost is None else str(cost),
                             source='manual',prompt_tokens=body.tokens,completion_tokens=0,cached_tokens=None,
                             profile='Other',key_fingerprint=hashlib.sha256(plugin.key().encode()).hexdigest()))
    return {'ok':True,'id':ident}


@router.delete('/other/{ident}')
def undo_other(ident: str):
    plugin = _spend.SpendPlugin(PluginState('openrouter-spend').data_dir,setting)
    with plugin.ledger.connect() as con:
        con.execute("DELETE FROM requests WHERE attempt=? AND category='manual' AND key_fingerprint=?",
                    (ident,hashlib.sha256(plugin.key().encode()).hexdigest()))
    return {'ok':True}
