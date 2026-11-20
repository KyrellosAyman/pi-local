
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys, tempfile, threading, time, tkinter as tk
from PIL import Image
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
path=Path(__file__).resolve().parent
sys.path.insert(0,str(path))
import app
import pi_backend as backend
records=[]
browser_only = '--browser-session' in sys.argv
auto_browser = '--automatic-browser' in sys.argv
operation = ('mcp__windows__get_chrome_state' if browser_only else 'mcp__chrome__get_chrome_state' if auto_browser else 'powershell')
script_argument = r'literal "$HOME" \u000f & |'
script_name = 'script with spaces.cjs'
finish_call = 15 if browser_only else 19
last_plan_call = finish_call - 1
streaming=threading.Event()
release=threading.Event()
release_reasoning=threading.Event()
release_formatted=threading.Event()
release_tool_arguments=threading.Event()
release_after_read=threading.Event()
tool_wire_started=threading.Event()
after_read_started=threading.Event()
reasoning_text='Assess the pinned GUI fixture before replying.'
formatted_reply=('## Fixture result\n\nPi GUI fixture completed. **Verified** with `Pi`.\n\n'
                 '3. First\n4. Second\n\n| Check | Result |\n| --- | --- |\n| Stream | Pass |\n\n'
                 '```text\n  preserve indentation\n```\n\n[Reference](https://example.com/)')
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*_): pass
 def do_POST(self):
  if self.path!='/v1/chat/completions': self.send_error(403);return
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  assert self.headers.get('Authorization')=='Bearer mock-gui-only'
  image_parts=[part for message in body.get('messages', []) if isinstance(message.get('content'), list)
               for part in message['content'] if part.get('type') == 'image_url']
  records.append({'model':body.get('model'),'tools':sorted(x['function']['name'] for x in body.get('tools',[])),
                  'image_parts':len(image_parts),
                  'tool_choice':body.get('tool_choice'),
                  'messages':body.get('messages',[])})
  base=dict(id='mock-ui',object='chat.completion.chunk',created=int(time.time()),model=backend.MODEL)
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  n=len(records)
  tool=None
  if n in (4, 10, last_plan_call):
   steps=[{'id':'a','title':'Verify fixture','skillQuery':'general-task','status':'completed' if n > 4 else 'in_progress'},
          {'id':'b','title':'Check the revised requirement','skillQuery':'skill-creation',
           'status':{4:'pending',10:'completed',last_plan_call:'completed'}[n]}]
   tool=('update_plan', {'steps':steps,'reason':'New evidence changed the plan.' if n==10 else ''})
  elif n==2:
   tool=('prepare_prompt', {'brief':'Verify the mock GUI fixture.','checks':['Observe the tool result.']})
  elif n in (6, 12):
   tool=('find_skills', {'query':'general-task' if n==6 else 'skill-creation'})
  elif n in (7, 13):
   tool=('use_skill', {'name':'general-task' if n==7 else 'skill-creation', 'reason':'Applicable to the fixture.'})
  elif not browser_only and n in (14, 15, 16):
   tool=('powershell', {'command':'Write-Output PI_GUI_STALL'})
  elif not browser_only and n==17:
   tool=('run_script', {'path':script_name, 'args':[script_argument]})
  elif n in (1, 3, 5, 8, 9, 11):
   inputs=({'target_window':int(os.environ['PI_CHROME_TEST_WINDOW'])}
           if os.environ.get('PI_CHROME_TEST_WINDOW') else {}) if browser_only or auto_browser else {
               'command':'Write-Output PI_GUI_TOOL_OK','timeout':8}
   name=operation
   if n==9:
    if browser_only:
     with Image.new('RGB',(5,5),'blue') as image:
      image.save(downloads/'fresh.png')
     name='copy_downloaded_png'
     inputs={'download':'fresh.png','name':'route-probe.png'}
    else:
     name='view_image_file'
     inputs={'path':str(photo),'region':[1,1,3,3]}
   tool=(name, inputs)
  if tool:
   calls=[(f'fixture-{n}', *tool)]
   if not browser_only and n==7:
    calls.append(('after-skill', 'read', {'path':'nested/note.txt'}))
   if not browser_only and n==11:
    calls.insert(0, ('missing-skill-search', 'use_skill', {'name':'skill-creation', 'reason':'Check premature activation.'}))
   action={'role':'assistant','tool_calls':[
       {'index':i,'id':key,'type':'function','function':{'name':name,'arguments':json.dumps(inputs)}}
       for i,(key,name,inputs) in enumerate(calls)]}
   chunks=[(action,None),({},'tool_calls')]
   if not browser_only and n==17:
    call=action['tool_calls'][0]
    draft={**call,'function':{**call['function'],'arguments':''}}
    chunks=[({'role':'assistant','reasoning_content':'Preparing the fixture invocation.'},None),
            ({'tool_calls':[draft]},None),
            ({'tool_calls':[{'index':0,'function':{'arguments':call['function']['arguments']}}]},None),
            ({},'tool_calls')]
  elif n==finish_call:
   chunks=[({'role':'assistant','reasoning_content':reasoning_text},None),
           ({'content':formatted_reply},None),({},'stop')]
  else:
   streaming.set()
   chunks=[({'role':'assistant','content':'Waiting for GUI stop.'},None)]
  try:
   if n==8 and not browser_only:
    after_read_started.set()
    release_after_read.wait(10)
   for index,(delta,stop) in enumerate(chunks):
    self.wfile.write(('data: '+json.dumps(dict(base,choices=[dict(index=0,delta=delta,finish_reason=stop)]))+'\n\n').encode())
    self.wfile.flush()
    if n==finish_call and index==0:release_reasoning.wait(15)
    if n==finish_call and index==1:release_formatted.wait(15)
    if not browser_only and n==17 and index==1:
     tool_wire_started.set()
     release_tool_arguments.wait(10)
   if len(records)>finish_call:release.wait(22)
   usage={'prompt_tokens': 1007, 'completion_tokens': 18, 'total_tokens': 1025,
          'prompt_tokens_details': {'cached_tokens': 7}}
   self.wfile.write(('data: '+json.dumps(dict(base,choices=[],usage=usage))+'\n\n').encode())
   self.wfile.write(b'data: [DONE]\n\n')
  except OSError:
   pass
class Synthetic:
 config={'model':'Qwen3.8-27B-Uncensored-noMTP-IQ4_XS.gguf'}
 state='ready'
 busy=False
 start_calls=0
 stop_calls=0
 foreign_listener=False
 fail_start=False
 directory=None
 def status(self):return {'status':self.state,'model':backend.MODEL}
 def request(self,uri):
  assert uri=='/slots'
  return [{'is_processing':self.busy}]
 def key(self):return 'mock-gui-only'
 def lock(self):return nullcontext()
 def port_owners(self):return {999} if self.foreign_listener else {123} if self.state=='ready' else set()
 def stop(self):
  self.stop_calls += 1
  self.state='stopped'
 def start(self):
  self.start_calls += 1
  if self.fail_start:
   raise RuntimeError('Synthetic native startup refused.')
  if not release_native_start.wait(6):
   raise RuntimeError('Synthetic native startup was never released.')
  self.state='ready'

release_native_start=threading.Event()

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
port=server.server_address[1];assert port!=1235
threading.Thread(target=server.serve_forever,daemon=True).start()
prepare=backend.prepare
def mock_profile(state,key,**options):
 env=prepare(state,key,**options)
 backend.profile(state, f'http://127.0.0.1:{port}/v1', target=Path(env['PI_CODING_AGENT_DIR']), preserve_settings=True)
 if browser_only:
  env['PI_IMAGE_DOWNLOADS'] = str(downloads)
 return env
backend.prepare=mock_profile
root=tk.Tk()
root.withdraw()
def wait_for(condition, seconds=18):
 stop=time.monotonic()+seconds
 while time.monotonic()<stop:
  root.update()
  if condition():return
  time.sleep(.025)
 raise RuntimeError(f'UI condition timed out with status {ui.status.get()!r}. {ui.chat.get("1.0","end")[:650]}')
def shown_while_waiting(text, ready=lambda:True):
 try:
  wait_for(lambda:ready() and text in ui.activity_indicator.get(),seconds=2)
  return ui.chat_activity.winfo_manager()=='pack'
 except (AttributeError,RuntimeError):
  return False
checks={}
try:
 with tempfile.TemporaryDirectory(prefix='pi-gui-verify-') as directory:
  tmp=Path(directory); project=tmp/'work'; project.mkdir()
  (project/script_name).write_text('console.log(JSON.stringify(process.argv.slice(2)));\n', encoding='utf-8')
  downloads=tmp/'downloads'; downloads.mkdir()
  photo=project/'photo.png'
  with Image.new('RGB',(8,8),'green') as image:
   image.save(photo)
  folder=project/'nested'; folder.mkdir(); (folder/'note.txt').write_text('workspace fixture')
  trace=tmp/'latency.jsonl'
  ui=app.App(root,Synthetic(),project,tmp/'state',browser_only=browser_only,latency_trace=trace)
  ui.show_files()
  row=next(row for row,(item,_) in ui.file_rows.items() if item==folder)
  ui.file_tree.focus(row)
  ui._expand_folder()
  checks['files_panel_lists_nested_files']=any(item==folder/'note.txt' for item,_ in ui.file_rows.values())
  checks['files_panel_can_switch_to_workspace_view']=ui.book.select()==str(ui.files_page)
  ui.toggle_inspector()
  checks['inspector_can_hide']=str(ui.inspector) not in map(str, ui.panes.panes())
  ui.show_files()
  checks['files_control_restores_inspector']=str(ui.inspector) in map(str, ui.panes.panes())
  ui.toggle_sidebar()
  ui.toggle_sidebar()
  checks['sidebar_restores_original_position']=str(ui.panes.panes()[0])==str(ui.sidebar)
  checks['logo_icon_loaded']=ui.brand_icon.width()>16
  sample={'toolCallId':'sample','toolName':'powershell'}
  ui._tool({**sample,'type':'tool_execution_start','args':{'command':'Write-Output first'}})
  wait_for(lambda:ui.tool_cards['sample']['expanded'])
  visible=lambda:ui.chat.tk.call(str(ui.chat), 'get', '-displaychars', '1.0', 'end')
  for text in ('superseded partial','first'):
   ui.queue.put({**sample,'type':'tool_execution_update','partialResult':{'content':[{'type':'text','text':text}]}})
  wait_for(lambda:'\nfirst\n' in visible())
  checks['long_running_tool_expands_with_live_output']='\nfirst\n' in visible()
  checks['burst_tool_updates_show_latest_snapshot']='superseded partial' not in ui.chat.get('1.0','end')
  ui._tool({**sample,'type':'tool_execution_end','result':{'content':[{'type':'text','text':'first\nsecond'}]}})
  checks['finished_tool_collapses_in_place']='\nfirst\n' not in visible() and visible().count('   ·   Done')==1
  ui._event({'type':'compaction_start'})
  checks['compaction_start_status']=ui.status.get()=='Compacting context'
  failure='Auto-compaction failed: Summarization failed: generation hit the token cap and the summary is incomplete'
  ui._event({'type':'compaction_end','aborted':False,'errorMessage':failure})
  checks['compaction_failure_visible_and_uncounted']=failure in visible() and ui.compactions==0
  ui._event({'type':'compaction_end','aborted':True})
  checks['compaction_cancelled_visible_and_uncounted']='Context compaction cancelled.' in visible() and ui.compactions==0
  ui._event({'type':'compaction_end','aborted':False})
  checks['uncommitted_compaction_uncounted']='without a saved checkpoint' in visible() and ui.compactions==0
  ui._event({'type':'compaction_end','aborted':False,'result':{'summary':'Exact checkpoint'}})
  checks['only_saved_checkpoint_counted']='Context checkpoint saved.' in visible() and ui.compactions==1
  ui._reset()
  copied=[]
  ui._copy_text=copied.append
  ui.theme_choice.set('hermes')
  ui._set_theme()
  checks['hermes_palette_and_prompt_alignment_persist']=ui.theme=='hermes' and (
       ui.chat.cget('background')==app.HERMES[app.BG] and ui.chat.tag_cget('user_message','justify')=='left' and
       json.loads(ui.settings_path.read_text(encoding='utf-8'))['theme']=='hermes')
  ui.prompt.insert('1.0','Synthetic Pi GUI acceptance check.')
  if not browser_only:
   ui.attachments=[photo]
  root.deiconify()
  root.update()
  idle_height=ui.chat.winfo_height()
  if browser_only:
   ui.send_button.invoke()
  else:
   native=ui.server
   native.directory=tmp/'native'
   real_hermes_active=backend.hermes_active
   with patch.object(backend,'Launcher',return_value=native), patch.object(
        backend,'hermes_active',side_effect=lambda:real_hermes_active(tmp/'isolated-appdata')):
    native.busy=True
    ui.send_button.invoke()
    checks['occupied_model_does_not_start_or_submit']=native.start_calls==0 and not records and (
        'Qwen is serving another session.' in visible())
    native.busy=False
    native.state='stopped'
    native.fail_start=True
    ui.send_button.invoke()
    wait_for(lambda:'Synthetic native startup refused.' in visible())
    checks['failed_model_start_keeps_draft_and_attachments']=not records and not ui.starting_backend and (
        ui.prompt.get('1.0','end-1c')=='Synthetic Pi GUI acceptance check.' and ui.attachments==[photo])
    native.fail_start=False
    ui.send_button.invoke()
    wait_for(lambda:native.start_calls==2)
    ui.send()
    checks['cold_start_blocks_duplicate_send']=ui.starting_backend and native.start_calls==2 and not records and (
        ui.send_button.instate(('disabled',)) and str(ui.prompt.cget('state'))=='disabled')
    release_native_start.set()
    wait_for(lambda:bool(records))
    checks['cold_start_submits_saved_draft_with_attachment']=native.start_calls==2 and (
        records[0]['image_parts']==1 and any('Synthetic Pi GUI acceptance check.' in str(message.get('content'))
                                             for message in records[0]['messages'] if message['role']=='user'))
  if not browser_only:
   wait_for(after_read_started.is_set)
   try:
    checks['tool_results_show_next_work_before_provider_token']=shown_while_waiting('Processing tool results',
         lambda:'after-skill' in ui.tool_cards and ui.tool_cards['after-skill']['state']=='done')
   finally:
    release_after_read.set()
   wait_for(tool_wire_started.is_set)
   try:
    checks['tool_draft_is_visible_before_any_arguments_arrive']=shown_while_waiting('Preparing tool · Run script') and (
         'fixture-17' not in ui.tool_cards and 'Preparing the fixture invocation.' not in visible())
   finally:
    release_tool_arguments.set()
  wait_for(lambda:reasoning_text in visible() and 'Thinking' in visible())
  first_animation=ui.activity_indicator.get()
  wait_for(lambda:ui.activity_indicator.get()!=first_animation)
  checks['reasoning_and_animation_stream_before_final_answer']=bool(first_animation) and 'Fixture completed.' not in visible()
  checks['activity_animation_keeps_the_chat_viewport_height']=idle_height>1 and ui.chat.winfo_height()==idle_height
  release_reasoning.set()
  wait_for(lambda: 'Stream │ Pass' in visible() and ui.chat.tag_ranges('heading'))
  checks['markdown_renders_during_stream_and_reasoning_has_folded']=ui.active and (
       reasoning_text not in visible() and '▸  Thought' in visible() and '```' not in visible())
  release_formatted.set()
  wait_for(lambda:ui.status.get()=='Finished')
  checks['reasoning_collapses_without_duplicate_after_settling']=reasoning_text not in visible() and (
       ui.chat.get('1.0','end').count(reasoning_text)==1 and
       visible().count('▸  Thought')==(1 if browser_only else 2))
  card_key=next(reversed(ui.thought_cards))
  ui.chat.mark_set('insert', ui.chat.tag_ranges(ui.thought_cards[card_key]['tags'][0])[0])
  ui._toggle_focused_tool(None)
  checks['reasoning_expands_by_keyboard_and_copy_excludes_it']=reasoning_text in visible() and (
       '▾  Thought' in visible() and ui.last_answer==formatted_reply)
  ui.show_reasoning.set(False)
  ui._set_show_reasoning()
  checks['reasoning_visibility_setting_persists']=reasoning_text not in visible() and 'Thought' not in visible() and (
       json.loads(ui.settings_path.read_text(encoding='utf-8'))['show_reasoning'] is False)
  ui.show_reasoning.set(True)
  ui._set_show_reasoning()
  checks['settled_markdown_uses_native_tags']=all(ui.chat.tag_ranges(tag) for tag in (
       'heading','strong','inline_code','code','table','link')) and all(part in visible() for part in (
       '3. First','4. Second','  preserve indentation','Stream │ Pass')) and '```' not in visible()
  copy_tag, speak_tag = list(ui.reply_actions)[-2:]
  ui.chat.mark_set('insert', ui.chat.tag_ranges(copy_tag)[0])
  ui._toggle_focused_tool(None)
  checks['per_reply_copy_uses_exact_answer']=copied==[formatted_reply]
  from types import SimpleNamespace
  spoken=[]
  ui.voice=SimpleNamespace(Status=SimpleNamespace(RunningState=1), Speak=lambda *args: spoken.append(args))
  ui._reply_action(speak_tag)
  ui.voice.Status.RunningState=2
  ui._reply_action(speak_tag)
  checks['per_reply_speech_uses_visible_answer_and_can_stop']=len(spoken)==2 and (
       'preserve indentation' in spoken[0][0] and 'Pi GUI fixture completed. Verified with Pi.' in spoken[0][0] and
       reasoning_text not in spoken[0][0] and spoken[1]==('',19))
  checks['prompt_from_native_button']=len(records)==finish_call and all(x['model']==backend.MODEL for x in records)
  discovery_requests=(4,5,10,11)
  selection_requests=(6,12)
  work_requests=[record for i,record in enumerate(records)
                 if i not in (0,1,2,3,last_plan_call,*discovery_requests,*selection_requests)]
  selected=backend.BROWSER_TOOLS if browser_only else backend.DESKTOP_TOOLS
  windows_tools={'mcp__windows__'+x for x in selected}
  driver_configured=backend.desktop_driver().is_file()
  checks['windows_tools_match_driver_availability']=all(
      windows_tools & set(r['tools']) == (windows_tools if driver_configured else set()) for r in work_requests)
  if not browser_only:
   chrome_tools={'mcp__chrome__'+x for x in backend.BROWSER_TOOLS}
   checks['normal_chat_keeps_powershell_and_scopes_chrome_to_driver']=all(
      chrome_tools & set(r['tools']) == (chrome_tools if driver_configured else set())
      and 'powershell' in r['tools'] for r in work_requests)
  checks['plan_updates']=len(ui.plan_steps)==2 and all(x['status']=='completed' for x in ui.plan_steps)
  checks['reopened_stage_visible']=any('Pi kept b in progress' in str(m.get('content')) for m in records[10]['messages'])
  if browser_only:
   checks['browser_without_process_control']=all(not {'powershell','bash','run_script'} & set(r['tools'])
        and 'copy_downloaded_png' in r['tools']
        and 'mcp__windows__browser_prepare' not in r['tools']
        and 'mcp__windows__click' not in r['tools'] for r in work_requests)
   checks['scoped_copy_preserves_png_bytes']=(project/'output/route-probe.png').read_bytes()==(downloads/'fresh.png').read_bytes()
  checks['chat_stream_displayed']='Pi GUI fixture completed.' in ui.chat.get('1.0','end')
  ids=ui.activity.get_children()
  tool_count=len(ids)
  compact=ui.chat.tk.call(str(ui.chat), 'get', '-displaychars', '1.0', 'end')
  checks['one_compact_inline_card_per_tool']=len(ui.tool_cards)==len(ids) and (
      compact.count('   ·   Done')+compact.count('   ·   Failed') == len(ids)
      and 'No additional details.' not in compact)
  if not browser_only:
   checks['skill_search_names_next_action_on_provider_wire']=any(
       m.get('tool_call_id')=='fixture-6' and 'call use_skill alone' in str(m['content'])
       for m in records[6]['messages'])
   checks['same_batch_read_runs_after_successful_skill_activation']=(
       ui.activity.item('after-skill')['values'][1]=='Done' and
       any(m.get('tool_call_id')=='after-skill' and 'workspace fixture' in str(m['content'])
           for m in records[7]['messages']))
   checks['failed_skill_activation_leaves_work_blocked']=(
       ui.activity.item('missing-skill-search')['values'][1]=='Error' and
       ui.activity.item('fixture-11')['values'][1]=='Error')
   ids=tuple(item for item in ids if item not in ('after-skill','missing-skill-search'))
  card=ui.tool_cards[ids[7]]
  ui._toggle_tool(ids[7])
  expanded=ui.chat.tk.call(str(ui.chat), 'get', '-displaychars', '1.0', 'end')
  checks['inline_tool_details_toggle']=card['expanded'] and expanded!=compact and card['output'][:100] in expanded
  checks['opening_older_activity_pauses_follow']=not ui.chat_following
  ui._toggle_tool(ids[7])
  checks['inline_tool_folds_again']=ui.chat.tk.call(str(ui.chat), 'get', '-displaychars', '1.0', 'end')==compact
  ui._show_latest()
  checks['latest_reenables_follow']=ui.chat_following
  ui.activity.selection_set(ids[7]);root.update()
  checks['work_blocked_until_prompt_and_skill']=(
      'prepare_prompt' in ui.tasks[ids[0]][2] and 'load a relevant skill' in ui.tasks[ids[4]][2])
  checks['work_blocked_until_plan']=ui.activity.item(ids[2])['values'][1]=='Error' and 'update_plan' in ui.tasks[ids[2]][2]
  checks['old_skill_cannot_do_new_stage']=(ui.activity.item(ids[10])['values'][1]=='Error' and
      'skill-creation' in ui.tasks[ids[10]][2] and 'Stage needs a skill' in ui.skill_log.get('1.0','end'))
  web_enabled=backend.runtime_config().get('web_tools') is True
  omitted_skill_tools={'prepare_prompt','publish_skill'} | (set() if web_enabled else {'research_skill'})
  checks['skill_workflow_on_provider_wire']=all(
      set(backend.SKILL_TOOLS)-omitted_skill_tools <= set(records[i]['tools']) for i in (7,13))
  checks['skill_reference_and_publishing_are_only_offered_when_available']=(
      all('read_skill_reference' not in records[i]['tools'] for i in selection_requests) and
      all('publish_skill' not in record['tools'] for record in records[:finish_call]))
  checks['prepared_workflow_stops_offering_prepare_prompt']=(
      all('prepare_prompt' in record['tools'] for record in records[:2]) and
      all('prepare_prompt' not in record['tools'] for record in records[2:finish_call]))
  checks['only_prepare_is_offered_until_the_brief_exists']=all(
      record['tools']==['prepare_prompt'] and record['tool_choice']=='required' for record in records[:2])
  checks['before_plan_only_callable_workflow_tools_are_offered']=all(
      set(records[i]['tools'])=={'find_skills','update_plan'} for i in (2,3))
  checks['new_plan_stage_requires_the_exact_next_skill_search']=(
      all(records[i]['tool_choice']=='required' and records[i]['tools']==['find_skills'] for i in discovery_requests) and
      all(records[i]['tool_choice'] in (None,'auto') for i in (3,6,7,12,13)))
  checks['skill_selection_excludes_gated_work_on_provider_wire']=(
      all({'use_skill','update_plan'} <= set(records[i]['tools']) and
          operation not in records[i]['tools'] and 'write' not in records[i]['tools'] for i in selection_requests) and
      all(operation in records[i]['tools'] for i in (7,13)))
  checks['web_tools_require_explicit_opt_in']=(
      all(('research_skill' in records[i]['tools']) == web_enabled for i in selection_requests) and
      (web_enabled or all('read_website' not in record['tools'] for record in records)))
  checks['bootstrap_and_active_skill_on_wire']=(
      'Prompt Engineer' in json.dumps(records[0]['messages']) and 'Skill Creation' in json.dumps(records[0]['messages'])
      and 'pi_skill_state' in json.dumps(records[5]['messages']))
  checks['normal_workflow_keeps_system_prefix_stable']=all(
      record['messages'][0]['content']==records[0]['messages'][0]['content'] for record in records[:finish_call])
  checks['active_skill_state_is_on_workflow_receipt']=any(
      m['role']=='tool' and '<pi_skill_state>' in str(m.get('content')) for m in records[5]['messages'])
  seen_states={}
  immutable_states=True
  for record in records[:finish_call]:
   states={m['tool_call_id']:m['content'] for m in record['messages']
           if m['role']=='tool' and '<pi_skill_state>' in str(m.get('content'))}
   immutable_states=immutable_states and all(states.get(k)==v for k,v in seen_states.items())
   seen_states.update(states)
  checks['workflow_state_receipts_stay_immutable']=immutable_states and len(seen_states)>=5
  checks['actual_skill_store_on_wire']=str(tmp/'state/profile/skills') in records[0]['messages'][0]['content']
  if not checks['bootstrap_and_active_skill_on_wire']:
   print('Skill markers:', [(i,[word for word in ('Prompt Engineer','Skill Creation','pi_skill_state','Active skill') if word in json.dumps(record['messages'])],
          [m['role'] for m in record['messages']]) for i, record in enumerate(records[:8])])
  checks['switch_skills_in_one_chat']=(ui.active_skill.get()=='skill-creation'
      and 'Loaded general-task' in ui.skill_log.get('1.0','end') and 'Prepared brief' in ui.skill_log.get('1.0','end'))
  expected='Attached to Chrome' if browser_only or auto_browser else 'PI_GUI_TOOL_OK'
  checks['tool_result_and_status_visible']=len(ids)==finish_call-1 and ui.activity.item(ids[7])['values'][1]=='Done' and expected in ui.tasks[ids[7]][2]
  if not checks['tool_result_and_status_visible']:
   print(ui.activity.item(ids[7])['values'], ui.tasks[ids[7]][2][:400])
  if not browser_only:
   checks['stall_prompts_change_and_blocks_same_check']=('independent reference' in ui.tasks[ids[14]][2]
       and ui.activity.item(ids[15])['values'][1]=='Error' and 'Repeated check refused' in ui.tasks[ids[15]][2]
       and ui.activity.item(ids[16])['values'][1]=='Done' and json.dumps([script_argument]) in ui.tasks[ids[16]][2])
   checks['saved_script_argv_reaches_model_exactly']=all('run_script' in r['tools'] for r in work_requests) and any(
       m.get('tool_call_id')=='fixture-17' and json.dumps([script_argument]) in str(m['content'])
       for m in records[17]['messages'])
   checks['inline_tool_command_and_recovery_visible']=all(word in ui.chat.get('1.0','end') for word in
       ('Write-Output PI_GUI_STALL','Repeated check refused',script_name))
   checks['media_tools_and_repo_navigation_on_wire']=all(
       (set(backend.ANALYSIS_TOOLS) - (set() if web_enabled else {'read_website'}))
       | {'grep','find','ls'} <= set(record['tools'])
       for record in work_requests)
   checks['image_attachment_on_wire']=records[0]['image_parts']==1
   checks['tool_image_reaches_the_next_request']=ui.activity.item(ids[8])['values'][1]=='Done' and (
       records[9]['image_parts']>records[8]['image_parts'])
   wait_for(lambda: bool(ui.visible_chats))
   ui.search.set('synthetic pi gui')
   checks['chat_history_search']=len(ui.visible_chats)==1
   ui._pin_chat(str(ui.visible_chats[0][2]))
   checks['pinned_chat_persists']=ui.chat_list.get(0).strip()=='Pinned' and (tmp/'state/pinned-chats.json').is_file()
   ui.chat_list.selection_set(next(iter(ui.history_rows)))
   saved_path=ui.visible_chats[0][2]
   saved_bytes=saved_path.read_bytes()
   with patch.object(backend,'Launcher',return_value=native), patch.object(
        backend,'hermes_active',side_effect=lambda:real_hermes_active(tmp/'isolated-appdata')):
    native.busy=True
    ui.settings()
    ui.unload_button.invoke()
    wait_for(lambda:not ui.starting_backend)
    checks['unload_refuses_an_occupied_model']=native.stop_calls==0 and native.state=='ready'
    native.busy=False
    with patch.object(ui,'jobs',SimpleNamespace(current=lambda:{'id':'saved-job'})):
     ui.settings()
     ui.unload_button.invoke()
     wait_for(lambda:not ui.starting_backend)
     checks['unload_refuses_a_saved_pi_job']=native.stop_calls==0 and 'A saved Pi job' in visible()
    ui.settings()
    ui.unload_button.invoke()
    wait_for(lambda:ui.status.get()=='Local model unloaded')
    checks['settings_unloads_idle_model_and_preserves_chat']=native.stop_calls==1 and (
        not native.port_owners() and saved_path.read_bytes()==saved_bytes and len(records)==finish_call)
    native.foreign_listener=True
    ui.settings()
    ui.unload_button.invoke()
    wait_for(lambda:not ui.starting_backend)
    checks['unload_does_not_touch_a_foreign_listener']=native.stop_calls==1 and (
        native.port_owners()=={999} and 'Its owner was left running.' in visible())
    native.foreign_listener=False
    ui.resume_chat()
    wait_for(lambda: native.start_calls==3 and not ui.starting_backend and ui.pending is None
             and 'Pi GUI fixture completed.' in ui.chat.get('1.0','end'))
   checks['cold_start_reopens_saved_chat_without_inference']=native.state=='ready' and len(records)==finish_call
   checks['resume_replays_plan_without_inference']=len(records)==finish_call and len(ui.plan_steps)==2
   checks['resume_restores_skill_history']=ui.active_skill.get()=='skill-creation' and 'Loaded general-task' in ui.skill_log.get('1.0','end')
   checks['resume_restores_inline_tool_receipts']='Repeated check refused' in ui.chat.get('1.0','end')
   checks['resume_keeps_local_reasoning_in_collapsed_history']=reasoning_text not in visible() and (
        ui.chat.get('1.0','end').count(reasoning_text)==1 and '▸  Thought' in visible())
   checks['resume_restores_single_cards']=len(ui.tool_cards)==tool_count and (
        ui.chat.tk.call(str(ui.chat), 'get', '-displaychars', '1.0', 'end').count('   ·   Failed')==
        compact.count('   ·   Failed'))
   attachment=project/'example.txt'
   attachment.write_text('An attachment fixture.',encoding='utf-8')
   ui.attachments=[attachment]
   checks['attachment_payload']=ui._prompt_payload('Fixture')['message'].endswith('--- End attachment ---')
   ui.clear_attachments()
   original_chat=ui.visible_chats[0][2]
   source_before=original_chat.read_bytes()
   fork_choices=[]
   ui._show_branch_messages=fork_choices.extend
   ui.branch_button.invoke()
   wait_for(lambda: len(fork_choices)==1 and ui.pending is None)
   ui._fork_at(fork_choices[0]['entryId'])
   wait_for(lambda: ui.pending is None and ui.status.get()=='Ready')
   checks['branch_preserves_source_and_leaves_a_draft_without_inference']=original_chat.read_bytes()==source_before and (
        ui.prompt.get('1.0','end-1c').startswith('Synthetic Pi GUI acceptance check.') and
        'Pi GUI fixture completed.' not in visible() and len(records)==finish_call)
   ui.prompt.delete('1.0','end')
  ui.new_chat()
  wait_for(lambda:ui.pending is None)
  checks['new_chat_resets_visible_events']=not ui.activity.get_children() and 'Pi GUI fixture completed.' not in ui.chat.get('1.0','end')
  ui.prompt.insert('1.0','Synthetic Pi GUI stop check.')
  ui.send_button.invoke()
  wait_for(lambda:streaming.is_set() and ui.active and str(ui.stop_button['state'])=='normal')
  ui._event({'type':'local_metrics', 'sampled_ns':time.perf_counter_ns(),
             'data':{'slot':'Busy','cpu':25,'ram_used':2,'ram_total':4,'gpus':[]}})
  ui.stop_button.invoke()
  wait_for(lambda:ui.status.get()=='Stopped')
  checks['abort_settled']=not ui.active
  transport=ui.rpc
  ui.close()
  transport.process.wait(timeout=12)
  checks['rpc_shutdown']=transport.process.returncode==0
  timeline=[json.loads(line) for line in trace.read_bytes().splitlines()]
  post_tool=[row for row in timeline if row['type']=='post_tool']
  checks['post_tool_timing_separates_transport_and_tk']=(
   timeline[0]['type']=='clock' and bool(post_tool) and all(
    row['type']=='post_tool' and row['tool'] and row['first_output'] in ('thinking_delta','text_delta')
    and row['tool_result_to_output_ms']>=0 and row['transport_to_tk_ms']>=0 for row in post_tool))
  checks['post_tool_timing_omits_chat_and_tool_arguments']=all(
   set(row)=={'type','tool','first_output','tool_end_ns','first_output_ns','tool_result_to_output_ms','transport_to_tk_ms'}
   for row in post_tool)
  tool_intervals=[row for row in timeline if row['type']=='tool_interval']
  model_intervals=[row for row in timeline if row['type']=='model_interval']
  checks['trace_attributes_completed_tool_and_model_intervals']=(
   bool(tool_intervals and model_intervals) and
   len({row['call'] for row in tool_intervals})==len(tool_intervals) and
   all(row['start_ns']<=row['end_ns'] and set(row)=={'type','call','tool','start_ns','end_ns','ok'}
       for row in tool_intervals) and
   all(row['turn_start_ns']<=row['first_token_ns']<=row['last_token_ns']<=row['end_ns']
       and row['output_tokens']==18 and row['input_tokens']==1007
       and set(row)=={'type','turn_start_ns','first_token_ns','last_token_ns','end_ns',
                                               'input_tokens','output_tokens','stop_reason'}
       for row in model_intervals))
  host_samples=[row for row in timeline if row['type']=='host_sample']
  checks['resource_samples_omit_process_and_chat_data']=bool(host_samples) and all(
   0<=row['cpu_percent']<=100 and 0<=row['ram_percent']<=100
   and set(row)=={'type','at_ns','cpu_percent','ram_percent','slot','context_tokens','max_context_tokens'}
   for row in host_samples)
finally:
 release.set()
 release_reasoning.set()
 release_formatted.set()
 release_tool_arguments.set()
 release_after_read.set()
 server.shutdown();server.server_close()
if not all(checks.values()):raise RuntimeError(checks)
print(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'checks':checks,'actual_pinned_pi_rpc':True,'genuine_qwen_requests':0,'mock_request_count':len(records)},indent=2))
