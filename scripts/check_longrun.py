"""A real-model 100-turn memory run over a migrated community world, isolated from player saves."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
from roleplay_world.contracts import ActionCommand
from roleplay_world.gateway import ModelGateway
from roleplay_world.journal import digest
from roleplay_world.memory import retrieve
from roleplay_world.runtime import Runtime
from roleplay_world.store import Store, public_commit, uid
from roleplay_world.world import present

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--turns',type=int,default=100)
    p.add_argument('--source', required=True, help='Native world/story JSON export to exercise')
    p.add_argument('--output',default='outputs/validation/longrun-live')
    args = p.parse_args()
    if args.turns < 20 or args.turns > 200:
        raise ValueError('20 to 200 turns supported')
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / 'outputs/validation'):
        raise ValueError('Output outside validation folder')
    folder.mkdir(parents=True,exist_ok=False)
    config = json.loads((ROOT/'configs/models.local.json').read_text())
    gateway = ModelGateway(config,folder/'traces')
    source = json.loads((ROOT/args.source).read_text())
    template = compile_story(WorldBlueprint.model_validate(source['world']),
                             StoryBlueprint.model_validate(source['story']), 'memory_longrun', origin=source.get('origin'))
    store = Store(folder/'data'); runtime = Runtime(store,gateway)
    campaign = store.create_campaign('qa',template,'长团测试旅人'); bid = campaign['main_branch']
    state = store.branches[bid]['state']; pc = state['player']
    npc = next(a for a in present(state) if a != pc)
    name = state['actors'][npc]['name']
    report = {'status':'running','mode':'live_models','turns':[],'provider':await gateway.health()}
    started = time.monotonic()
    try:
        for i in range(args.turns):
            state = store.branches[bid]['state']
            if i == 0:
                text = f'我对{name}说：我们约定一个仅用于确认身份的暗号，青瓷风铃。请你记住，之后我会问你这个暗号；我不会要求你替我做决定。'
            elif i == args.turns-1:
                text = f'我问{name}：刚认识时，我们约定的确认身份暗号具体是什么？请直接说出那四个字。'
            else:
                subjects = ['今天窗外的天气','你平时喜欢的早餐','附近安静的散步地点','如何照料窗边植物',
                            '下雨时适合做的家务','街区里最有趣的声音','适合分享的小零食','你喜欢的书籍类型']
                text = f'我问{name}：关于{subjects[(i-1)%len(subjects)]}，你今天有什么新的想法？这是第{i+1}次随意交谈，只聊天，不替任何人决定事情。'
            command = ActionCommand(action_id=uid('longrun'), expected_world_version=state['version'], mode='say', text=text)
            a,_ = store.accept(campaign['id'],bid,'qa',command)
            await runtime.run(a['id'])
            a = store.actions[a['id']]
            if a['status'] != 'committed':
                raise AssertionError(f'Turn {i+1}: {a.get("error")}')
            c = a['result']
            report['turns'].append({'turn':i+1,'version':c['version'],'text':text,
                                    'segments':c['segments'],'traces':a.get('traces',[])})
            if i % 10 == 0 or i == args.turns-1:
                print('committed',i+1,flush=True)
                (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        state = store.branches[bid]['state']
        final = '\n'.join(s['text'] for s in report['turns'][-1]['segments'])
        assert '青瓷风铃' in final, 'The actual NPC reply failed to recall the password'
        old = retrieve(state,npc,'确认身份暗号')
        early_ids = {e['event_id'] for e in store.branches[bid]['commits'][0]['events'] if e['type']=='memory.recorded'}
        assert any(row['source_id'] in early_ids for row in old), 'Old source missing from retrieval'
        fork0 = store.fork(campaign['id'],bid,'qa',0,'认识之前')
        assert not any('青瓷风铃' in r['text'] for r in retrieve(fork0['state'],npc,'青瓷风铃'))
        fork1 = store.fork(campaign['id'],bid,'qa',1,'最初约定')
        assert any('青瓷风铃' in r['text'] for r in retrieve(fork1['state'],npc,'青瓷风铃'))
        for secret in [f for f in state['facts'] if f.startswith('fact_secret_') and f not in state['knowledge'][pc]]:
            assert not any(row['source_id']==secret for row in retrieve(state,pc,state['facts'][secret]['value']))
        snapshot = digest(state)
        (folder/'transcript.json').write_text(json.dumps([public_commit(c) for c in store.branches[bid]['commits']],ensure_ascii=False,indent=2))
        store.close(); store = Store(folder/'data')
        assert digest(store.branches[bid]['state']) == snapshot
        traces = [json.loads(path.read_text()) for path in (folder/'traces').rglob('*.json')]
        tokens = sum((t.get('usage') or {}).get('total_tokens',0) for t in traces)
        report.update(status='passed',elapsed_s=round(time.monotonic()-started,2),
                      actual_response=final,retrieved_sources=old,branch_isolation=True,
                      replay_hash=snapshot,trace_files=len(traces),total_tokens=tokens,
                      scope='One fixed scripted dialogue run; does not measure all narrative quality or long campaign success')
    except Exception as exc:
        report.update(status='failed',error=str(exc)[:2000])
        raise
    finally:
        await runtime.close();store.close()
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('LONGRUN PASSED',flush=True)


if __name__=='__main__':
    asyncio.run(main())
