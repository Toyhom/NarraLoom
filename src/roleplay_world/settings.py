"""Session-owned provider settings and a prompt-free usage ledger."""
import contextvars
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .contracts import Contract, DomainError, Identifier

MODEL_OWNER = contextvars.ContextVar('rpw_model_owner', default=None)
ROLES = ('world_builder','story_builder','rules_builder','simulation_builder','state_builder','content_reviewer','import_builder','game_master','character_actor','narrator','world_actor')
DECISION_ROLES = ('action_router',)


def validate_url(value):
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('请填写不含密钥和查询参数的服务地址')
    return value


class NamedProvider(Contract):
    backend: Identifier = 'openai'
    url: Annotated[str, Field(min_length=8, max_length=300)]
    api_key: Annotated[str, Field(max_length=500)] = ''
    clear_key: bool = False
    json_mode: Literal['object', 'schema', 'prompt'] = 'object'
    thinking_disabled: bool = False
    context_chars: Annotated[int, Field(ge=1000, le=1000000)] = 120000
    timeout_s: Annotated[float, Field(ge=1, le=120, allow_inf_nan=False)] = 90

    @model_validator(mode='after')
    def check(self):
        validate_url(self.url)
        return self


class TaskBinding(Contract):
    provider: Identifier
    model: Annotated[str, Field(min_length=1, max_length=120)]
    revision: Annotated[str, Field(max_length=120)] = ''


class DecisionPolicy(Contract):
    mode: Literal['off', 'shadow', 'auto'] = 'off'
    min_probability: Annotated[float, Field(ge=0.5, le=1, allow_inf_nan=False)] = 0.95
    min_margin: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.5


def provider_config(value):
    return {'backend': value.get('backend', 'openai'), 'url': value['url'].rstrip('/'),
            'api_key': value.get('api_key', ''), 'api_key_env': 'RPW_NO_INHERITED_KEY',
            'context_chars': value.get('context_chars', 120000), 'timeout_s': value.get('timeout_s', 90),
            'json_object': value.get('json_mode') == 'object', 'json_schema': value.get('json_mode') == 'schema',
            'extra_body': {'thinking': {'type': 'disabled'}} if value.get('thinking_disabled') else {}}

class ProviderSettings(Contract):
    url: Annotated[str, Field(min_length=8,max_length=300)]
    model: Annotated[str, Field(min_length=1,max_length=120)]
    api_key: Annotated[str, Field(max_length=500)] = ''
    json_mode: Literal['object','schema','prompt'] = 'object'
    thinking_disabled: bool = True
    context_chars: Annotated[int, Field(ge=10000,le=1000000)] = 120000
    roles: dict[str, Annotated[str,Field(min_length=1,max_length=120)]] = Field(default_factory=dict)
    input_price: Annotated[float,Field(ge=0,le=1000)] = 0
    output_price: Annotated[float,Field(ge=0,le=1000)] = 0
    currency: Literal['CNY','USD'] = 'CNY'
    providers: Annotated[dict[Identifier, NamedProvider], Field(max_length=16)] = Field(default_factory=dict)
    bindings: dict[str, TaskBinding] = Field(default_factory=dict)
    decision_policy: DecisionPolicy = Field(default_factory=DecisionPolicy)

    @model_validator(mode='after')
    def check(self):
        validate_url(self.url)
        if set(self.roles)-set(ROLES):raise ValueError('未知模型角色')
        if set(self.bindings) - set(ROLES + DECISION_ROLES):
            raise ValueError('未知模块绑定')
        for role, binding in self.bindings.items():
            provider = self.providers.get(binding.provider)
            if provider is None:
                raise ValueError('模块引用的服务商不存在')
            if (provider.backend == 'systemone' and role in ROLES
                    or provider.backend == 'openai' and role in DECISION_ROLES):
                raise ValueError('生成模块需要生成后端，决策模块需要决策后端')
        if self.decision_policy.mode != 'off' and 'action_router' not in self.bindings:
            raise ValueError('请先为行动路由绑定决策模型')
        return self

class Settings:
    def __init__(self, root, default):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.default=deepcopy(default)
        self.values={};self.usage={}
        for path in self.root.glob('*.json'):
            self.values[path.stem]=json.loads(path.read_text())
        ledger=self.root/'usage.jsonl'
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                self.usage.setdefault(row['owner'],[]).append(row)

    def effective(self, owner):
        value=self.values.get(owner)
        if not value:return deepcopy(self.default)
        cfg={'default':{'url':value['url'].rstrip('/'),'model':value['model'],'api_key':value.get('api_key',''),
                        'api_key_env':'RPW_NO_INHERITED_KEY','context_chars':value['context_chars'],
                        'json_object':value['json_mode']=='object','json_schema':value['json_mode']=='schema',
                        'extra_body':{'thinking':{'type':'disabled'}} if value['thinking_disabled'] else {}},'roles':{}}
        for role in ROLES:
            budget=self.default.get('roles',{}).get(role,{})
            cfg['roles'][role]={k:budget[k] for k in ('max_tokens','output_chars') if k in budget}
            if value.get('roles',{}).get(role):cfg['roles'][role]['model']=value['roles'][role]
        cfg['providers'] = {name: provider_config(provider) for name, provider in value.get('providers', {}).items()}
        cfg['bindings'] = deepcopy(value.get('bindings', {}))
        cfg['decision_policy'] = deepcopy(value.get('decision_policy', {'mode': 'off'}))
        return cfg

    def public(self,owner):
        value=self.values.get(owner)
        if value:
            return {**{k:v for k,v in value.items() if k not in {'api_key', 'providers'}},
                    'providers': {name: {**{k: v for k, v in provider.items() if k != 'api_key'},
                                         'has_key': bool(provider.get('api_key'))}
                                  for name, provider in value.get('providers', {}).items()},
                    'has_key':bool(value.get('api_key')),'using_default':False}
        cfg=self.default.get('default',{})
        return {'url':cfg.get('url',''),'model':cfg.get('model',''),'has_key':bool(cfg.get('api_key_file') or cfg.get('api_key_env')),
                'json_mode':'object' if cfg.get('json_object') else 'schema' if cfg.get('json_schema') else 'prompt',
                'thinking_disabled':bool(cfg.get('extra_body',{}).get('thinking')),'context_chars':cfg.get('context_chars',120000),
                'roles':{},'using_default':True,'input_price':0,'output_price':0,'currency':'CNY',
                'providers': {}, 'bindings': {}, 'decision_policy': DecisionPolicy().model_dump()}

    def save(self,owner,payload):
        old=self.values.get(owner,{})
        value=payload.model_dump();value['url']=value['url'].rstrip('/')
        # A changed endpoint never receives a key from the previous provider or deployment default.
        if not value['api_key'] and old.get('url')==value['url']:
            value['api_key']=old.get('api_key','')
        for name, provider in value['providers'].items():
            provider['url'] = provider['url'].rstrip('/')
            previous = old.get('providers', {}).get(name, {})
            if provider.pop('clear_key', False):
                provider['api_key'] = ''
            elif (not provider['api_key'] and previous.get('url') == provider['url']
                  and previous.get('backend') == provider['backend']):
                provider['api_key'] = previous.get('api_key', '')
        path=self.root/(owner+'.json');temporary=path.with_suffix('.pending')
        with temporary.open('w') as out:
            json.dump(value,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
        directory=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        self.values[owner]=value
        return self.public(owner)

    def reset(self,owner):
        (self.root/(owner+'.json')).unlink(missing_ok=True);self.values.pop(owner,None)
        return self.public(owner)

    def record_usage(self,owner,trace):
        if not owner:return
        row={'owner':owner,'time':time.time(),**{k:trace.get(k) for k in (
            'role','model','response_model','duration_s','usage','provider','backend','revision','status')}}
        with (self.root/'usage.jsonl').open('a') as out:out.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.usage.setdefault(owner,[]).append(row)

    def report(self,owner):
        rows=self.usage.get(owner,[]);buckets={}
        for row in rows:
            provider = row.get('provider') or 'default'
            b=buckets.setdefault((provider,row['model']),{'provider':provider,'model':row['model'],'calls':0,'prompt_tokens':0,'completion_tokens':0,'unreported_calls':0,'duration_s':0})
            b['calls']+=1;b['duration_s']+=row['duration_s'] or 0
            usage=row.get('usage')
            if not usage:b['unreported_calls']+=1;continue
            b['prompt_tokens']+=usage.get('prompt_tokens',usage.get('input_tokens',0));b['completion_tokens']+=usage.get('completion_tokens',usage.get('output_tokens',0))
        value=self.public(owner)
        return {'models':list(buckets.values()),'calls':len(rows),'estimate':sum(
            b['prompt_tokens']*value['input_price']+b['completion_tokens']*value['output_price'] for b in buckets.values() if b['provider']=='default')/1_000_000,
            'unpriced_provider_calls':sum(b['calls'] for b in buckets.values() if b['provider']!='default'),
            'priced':bool(value['input_price'] or value['output_price']),'currency':value['currency'],
            'scope':'启用用量记录之后的本浏览器会话调用；试跑也计入。不含未返回usage的请求与Avatar GPU任务。单价仅估算默认服务；命名服务商单独列出用量，不计入该费用估算。估算不等于账单。'}


def require_idle(store,owner):
    if any(a['owner']==owner and a['status'] in {'accepted','planning','characters','narrating'} for a in store.actions.values()) or any(
        j['owner']==owner and j['status'] in {'queued','generating_world','generating_story','testing'} for j in store.jobs.values()):
        raise DomainError('provider_busy','请等待当前行动与创作结束后再切换模型',409)
