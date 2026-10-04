"""Launch the pinned worker with project-owned outputs and configured existing environments."""

import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'configs/avatar.local.json').read_text())
runner=config.get('runner','gpuq')
if runner not in {'gpuq','local'}:
    raise ValueError('Avatar runner must be gpuq or local')
if runner == 'gpuq' and not os.environ.get('GPUQ_JOB_ID'):
    raise RuntimeError('GPUQ worker identity is required')
if sys.platform != 'linux':
    raise RuntimeError('The bundled Avatar creator requires Linux or WSL2 with NVIDIA CUDA')
env=dict(os.environ)
# Do not inherit inaccessible administrator executable directories on another node.
env['PATH']=':'.join([str(Path(config['python']).parent),'/usr/local/bin','/usr/bin','/bin'])
allowed={'AVATAR_VISION_PYTHON','AVATAR_FACE_PYTHON','AVATAR_PORTRAIT_PYTHON','AVATAR_ASSET_PYTHON',
         'AVATAR_QWEN_PYTHON','AVATAR_MODEL_ROOT','AVATAR_MODELS_CONFIG','AVATAR_IMAGE_BACKEND'}
if set(config.get('env',{}))-allowed:
    raise ValueError('Unsupported avatar worker environment option')
env.update(config['env'])
env.update(AVATAR_WORK_ROOT=str(ROOT),AVATAR_CREATION_RUNNER=runner,
           PYTHONPATH=str(ROOT/'vendor/avatar_worker/src'),
           PYTHONPYCACHEPREFIX=str(ROOT/'.cache/avatar-pycache'),TMPDIR=str(ROOT/'scratch'),
           HF_HOME=str(ROOT/'.cache/avatar-hf'),TORCH_HOME=str(ROOT/'.cache/avatar-torch'),
           XDG_CACHE_HOME=str(ROOT/'.cache/avatar-xdg'),U2NET_HOME=str(Path(env['AVATAR_MODEL_ROOT'])/'rembg'))
(ROOT/'characters').mkdir(exist_ok=True)
(ROOT/'scratch').mkdir(exist_ok=True)
for cache in ('avatar-hf','avatar-torch','avatar-xdg/torch/kernels','avatar-pycache'):
    (ROOT/'.cache'/cache).mkdir(parents=True,exist_ok=True)
folder=Path(sys.argv[1]).resolve()
try:
    folder.relative_to(ROOT/'outputs/creations')
except ValueError as exc:
    raise ValueError('Worker input must belong to this project') from exc
os.chdir(ROOT)
os.execve(config['python'],[config['python'],str(ROOT/'vendor/avatar_worker/services/create_character.py'),str(folder)],env)
