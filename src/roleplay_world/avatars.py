"""Versioned optional Avatar adapter. Presentation never writes world state."""

import asyncio
import base64
import hashlib
import importlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

from pydantic import Field

from .contracts import Contract, DomainError, Identifier

ROOT=Path(__file__).resolve().parents[2]
MAX_AVATAR_UPLOAD=14_100_000


class AvatarCreate(Contract):
    request_id: Identifier
    description: Annotated[str,Field(min_length=2,max_length=1500)]
    image_base64: Annotated[str,Field(min_length=32,max_length=14_000_000)]
    seed: Annotated[int,Field(ge=0,le=2147483647)]=42


def vendor_module(name):
    alias='_rpw_avatar_v1'
    if alias not in sys.modules:
        path=ROOT/'vendor/avatar_worker/src/roleplay_avatar/__init__.py'
        spec=importlib.util.spec_from_file_location(alias,path,submodule_search_locations=[str(path.parent)])
        module=importlib.util.module_from_spec(spec);sys.modules[alias]=module;spec.loader.exec_module(module)
    return importlib.import_module(alias+'.'+name)


class AvatarService:
    def __init__(self,store,config=None,executor=None,*,workspace_root=None):
        self.root=Path(workspace_root or ROOT).resolve()
        path=self.root/'configs/avatar.local.json'
        self.config=config if config is not None else (json.loads(path.read_text()) if path.exists() else {})
        self.store=store;self.lock=asyncio.Lock();self.executor=executor
        self.enabled=bool(self.config.get('enabled'))
        if self.enabled and not executor:
            runner=self.config.get('runner','gpuq')
            if runner not in {'gpuq','local'}:
                raise ValueError('Avatar runner must be gpuq or local')
            if sys.platform != 'linux':
                raise ValueError('The bundled Avatar creator requires Linux or WSL2 with NVIDIA CUDA')
            self.executor=vendor_module('creation').CreationStore(self.root,runner=runner)

    def public(self,value):
        return {k:value[k] for k in ('id','description','state','stage','progress','error','created_at','character_id','name') if k in value}

    def record(self,aid,owner):
        return self.store.studio_get('avatars',aid,owner)

    async def status(self,aid,owner):
        async with self.lock:
            return await self._status(aid,owner)

    async def _status(self,aid,owner):
        value=self.record(aid,owner)
        if self.executor and value.get('job_id'):
            try:
                status=await asyncio.to_thread(self.executor.get,value['job_id'])
            except (FileNotFoundError,ValueError):
                status={}
            patch={k:status[k] for k in ('state','stage','progress','error','character_id') if k in status}
            if status:
                patch['error']=status.get('error')
            if patch.get('state')=='ready' and value.get('state')!='ready':
                folder=self.root/'characters'/patch['character_id']
                try:
                    package=await asyncio.to_thread(vendor_module('assets').load_package,folder,True)
                    patch['name']=package.profile.display_name
                except (ValueError,OSError):
                    patch.update(state='failed',stage='validation',error='形象资源未通过完整性检查，请修复后重试。')
            if any(value.get(k)!=v for k,v in patch.items()):
                value={**value,**patch}
                self.store.studio_save('avatars',value)
        return self.public(value)

    async def create(self,owner,payload):
        if not self.enabled:
            raise DomainError('avatar_unavailable','尚未配置2D角色创建服务',503)
        from PIL import Image, UnidentifiedImageError

        try:
            image=base64.b64decode(payload.image_base64,validate=True)
            if len(image)>10_000_000:
                raise ValueError('Image too large')
            with Image.open(io.BytesIO(image)) as picture:
                if picture.format not in {'PNG','JPEG','WEBP'} or min(picture.size)<128 or picture.width*picture.height>24_000_000:
                    raise ValueError('Image size or format unsupported')
                picture.verify()
        except (ValueError,UnidentifiedImageError,Image.DecompressionBombError,OSError) as exc:
            raise DomainError('avatar_image','请使用128像素以上、10MB以内的PNG、JPEG或WebP图片',422) from exc
        raw=payload.model_dump_json()
        fingerprint=hashlib.sha256(raw.encode()).hexdigest()
        key=hashlib.sha256((owner+':'+payload.request_id).encode()).hexdigest()
        aid='avatar_'+key[:24];job_id=key[:32]
        async with self.lock:
            if aid in self.store.avatars:
                value=self.record(aid,owner)
                if value['request_hash']!=fingerprint:
                    raise DomainError('avatar_conflict','同一创建请求不能换成不同图片或描述',409)
                return await self._status(aid,owner)
            for existing in list(self.store.avatars.values()):
                if existing['owner']==owner and existing['state'] in {'submitting','queued','running','submission_error'}:
                    await self._status(existing['id'],owner)
            if sum(v['owner']==owner and v['state'] in {'submitting','queued','running','submission_error'} for v in self.store.avatars.values())>=2:
                raise DomainError('avatar_busy','已有两个角色创建任务，请等待或取消后再创建',409)
            request=vendor_module('creation').CreationRequest(description=payload.description,
                image_base64=payload.image_base64,presentation='2d',voice_candidates=3,seed=payload.seed)
            value={'id':aid,'owner':owner,'job_id':job_id,'request_hash':fingerprint,'description':payload.description,
                   'state':'submitting','stage':'queued','progress':0,'created_at':time.time()}
            self.store.studio_save('avatars',value)
            try:
                await asyncio.to_thread(self.executor.create,request,job_id)
            except (ValueError,OSError,subprocess.SubprocessError,RuntimeError):
                # A submission receipt may have been lost; retain the same job ID and do not submit twice.
                value.update(state='submission_error',error='角色任务未确认。请查看状态，避免重复提交。')
                self.store.studio_save('avatars',value)
                return self.public(value)
        return await self.status(aid,owner)

    async def control(self,aid,owner,operation):
        value=self.record(aid,owner)
        if value.get('asset_digest'):
            raise DomainError('avatar_imported','这是导入的成品形象；需要新形象时请提交新的创建任务',409)
        if not self.executor:
            raise DomainError('avatar_unavailable','角色创建服务未配置',503)
        async with self.lock:
            try:
                if operation=='cancel':
                    await asyncio.to_thread(self.executor.cancel,value['job_id'])
                elif operation=='retry':
                    await asyncio.to_thread(self.executor.retry,value['job_id'])
                else:
                    raise DomainError('avatar_operation','不支持此操作',422)
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                raise DomainError('avatar_state','任务状态尚未确认，不能重启；请稍后刷新',409) from exc
        return await self.status(aid,owner)

    def asset(self,aid,owner,filename):
        value=self.record(aid,owner)
        if value.get('state')!='ready' or not re.fullmatch(r'char_[a-f0-9]{16}',value.get('character_id','')):
            raise DomainError('avatar_pending','2D资源尚未就绪',404)
        if filename not in {'puppet/rig.json','puppet/portrait.png','puppet/mouth-atlas.png','profile.json'}:
            raise DomainError('asset_missing','没有此资源',404)
        if value.get('asset_digest'):
            if not re.fullmatch(r'[a-f0-9]{64}',value['asset_digest']):
                raise DomainError('asset_missing','无效的资源摘要',404)
            root=(self.store.journal.root/'package-assets'/value['asset_digest']).resolve()
        else:
            root=(self.root/'characters'/value['character_id']).resolve()
        path=(root/filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise DomainError('asset_missing','没有此资源',404)
        return path
