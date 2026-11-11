import copy
import contextlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import privacy as p
import installer as i

BASE = dict(name='DP-2',width=2560,height=1440,scale=1.25,refreshRate=59.95,x=0,y=0,
            transform=0,vrr=False,disabled=False,dpmsStatus=True,mirrorOf='none',id=0,
            currentFormat='XRGB8888',colorManagementPreset='srgb')


def result(text='',code=0,err=''):
    return subprocess.CompletedProcess([],code,text,err)


class WidgetSafetyTests(unittest.TestCase):
    def test_markup_is_not_passed_to_tooltip(self):
        value=p.ui_text('<img src="https://example.invalid/pixel">')
        self.assertNotIn('<',value);self.assertNotIn('>',value)
    def test_dynamic_text_is_bounded_and_strips_controls(self):
        value=p.ui_text('\x00\n\t\x7f\x85'+'x'*2000)
        self.assertEqual(len(value),512)
        self.assertTrue(all(ord(c)>=32 and not 127<=ord(c)<160 for c in value))


class DetectionTests(unittest.TestCase):
    def test_connector_resolution_matrix(self):
        for name,w,h,scale in [('DP-2',2560,1440,1.25),('HDMI-A-1',1920,1080,1),('eDP-1',3840,2160,2),('DP-3',3440,1440,1.5)]:
            with self.subTest(name=name):
                m=dict(BASE,name=name,width=w,height=h,scale=scale,x=-1920)
                d=p.select_display([m])
                self.assertEqual((d['name'],d['width'],d['height'],d['scale'],d['x']),(name,w,h,scale,-1920))
    def test_unsupported_matrix(self):
        for outputs in ([],[BASE,dict(BASE,name='HDMI-A-1')],[dict(BASE,name='HEADLESS-1')],
                        [dict(BASE,disabled=True)],[dict(BASE,dpmsStatus=False)],
                        [dict(BASE,transform=1)],[dict(BASE,vrr=True)],[dict(BASE,mirrorOf='2')],
                        [dict(BASE,currentFormat='XRGB2101010')],[dict(BASE,colorManagementPreset='hdr')],
                        [dict(BASE,name='DP-1";os.execute("bad")')],[dict(BASE,scale=0)]):
            with self.subTest(outputs=outputs),self.assertRaises(RuntimeError):p.select_display(outputs)
    def test_lua_quote(self):
        s=p.rule('DP-2','2560x1440@59.95',-1920,0,1.25,True,p.VIRTUAL)
        self.assertIn('position="-1920x0"',s)
        self.assertIn('disabled=true',s)
        self.assertIn('mirror="HEADLESS-9"',s)


class FakeDisplay:
    def __init__(self,physical=True,virtual=True):
        self.outputs=[]
        if physical:self.outputs.append(dict(BASE,mirrorOf='1' if virtual else 'none'))
        if virtual:self.outputs.append(dict(BASE,name=p.VIRTUAL,id=1,mirrorOf='none'))
        self.calls=[]
        self.input_wake_armed=False
    def __call__(self,args,**kwargs):
        self.calls.append(args)
        if args[1:4]==['monitors','all','-j']:return result(json.dumps(self.outputs))
        if args[1:3]==['monitors','-j']:return result(json.dumps([m for m in self.outputs if not m['disabled'] and m['mirrorOf']=='none']))
        if args[:4]==['hyprctl','output','create','headless']:
            self.outputs.append(dict(BASE,name=args[4],id=1,mirrorOf='none'))
            return result('ok')
        if args[0]=='hyprctl' and args[1]=='eval':
            code=args[2]
            if 'hl.monitor(' in code:
                name=re.search(r'output="([^"\n]+)"',code)[1]
                monitor=next(m for m in self.outputs if m['name']==name)
                if name=='DP-2':
                    was_disabled=monitor['disabled']
                    monitor['disabled']='disabled=true' in code
                    monitor['mirrorOf']='1' if 'mirror="HEADLESS-9"' in code else 'none'
                    # Enabling/modesetting may wake a panel even without DPMS-on.
                    if not monitor['disabled'] and getattr(self,'mode_wakes_panel',True):monitor['dpmsStatus']=True
                else:
                    monitor['dpmsStatus']=True
            if 'hl.dsp.dpms(' in code:
                name=re.search(r'monitor="([^"\n]+)"',code)
                enabled='action="enable"' in code
                # Real Hyprland silently falls back to global for a mirror or
                # missing selector. Catch regressions against that behavior.
                if name and not any(m['name']==name[1] and not m['disabled'] and m['mirrorOf']=='none' for m in self.outputs):name=None
                for monitor in self.outputs:
                    if not monitor['disabled'] and (name is None or monitor['name']==name[1]):
                        monitor['dpmsStatus']=enabled
                        self.input_wake_armed=not enabled
            return result('ok\n')
        raise AssertionError(args)
    def user_input(self):
        if self.input_wake_armed:
            for monitor in self.outputs:
                if not monitor['disabled']:monitor['dpmsStatus']=True
            self.input_wake_armed=False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fake=FakeDisplay()
        self.c=p.Controller(dict(physical=p.select_display([BASE]),virtual=p.VIRTUAL,sunshine_unit='sunshine.service'),self.temp.name,self.fake,lambda _:None)
        self.c.session='test-session'
    def test_off_and_restore(self):
        self.c.screen(False);self.assertTrue(self.c.off());self.assertEqual(self.c.marker.read_text(),'test-session')
        self.c.screen(True);self.assertFalse(self.c.off());self.assertFalse(self.c.marker.exists())
    def test_off_refused_without_virtual(self):
        self.fake.outputs=self.fake.outputs[:1]
        with self.assertRaises(RuntimeError):self.c.screen(False)
        self.assertFalse(any(a[1]=='eval' for a in self.fake.calls))
    def test_hotplug_does_not_change_other_outputs(self):
        self.fake.outputs.append(dict(BASE,name='HDMI-A-1'))
        with self.assertRaises(RuntimeError):self.c.screen(False)
        self.assertFalse(any(a[1]=='eval' for a in self.fake.calls))
    def test_missing_physical_reports_unknown(self):
        self.fake.outputs=self.fake.outputs[1:]
        self.assertEqual(self.c.status()['text'],'!')
    def test_status_states(self):
        self.assertEqual(self.c.status()['text'],p.ICON)
        self.assertIn('Black out screen',self.c.status()['tooltip'])
        self.c.screen(False)
        self.assertEqual(self.c.status()['class'],'active')
        self.assertIn('Turn screen back on',self.c.status()['tooltip'])
    def test_override_scoped_to_session(self):
        self.c.set_override(False);self.assertIs(self.c.override(),False)
        self.c.session='new';self.assertIsNone(self.c.override())
        self.c.set_override(None);self.assertFalse(self.c.override_path.exists())
    def test_recovery_with_extra_output_targets_only_configured_panel(self):
        self.fake.outputs.append(dict(BASE,name='HDMI-A-1'))
        self.c.recover_direct()
        mutations=[a[2] for a in self.fake.calls if a[1]=='eval']
        self.assertFalse(any('output="HDMI-A-1"' in s for s in mutations))
        self.assertIs(self.c.override(),True)
    def test_restart_setup_preserves_blackout(self):
        self.c.screen(False);self.c.setup();self.assertTrue(self.c.off())
    def test_stale_blackout_does_not_hide_new_session(self):
        self.c.marker.write_text('old-session');self.c.setup();self.assertFalse(self.c.off())
    def test_paused_warning(self):
        p.atomic(self.c.runtime/(p.NAME+'.health.json'),json.dumps(dict(session=self.c.session,error='test error')))
        self.assertIn('AUTOMATIC CONTROL PAUSED',self.c.status()['tooltip'])


class IdlePowerTests(ControllerTests):
    def panel(self):return next(m for m in self.fake.outputs if m['name']=='DP-2')
    def virtual(self):return next(m for m in self.fake.outputs if m['name']==p.VIRTUAL)
    def sleep_all(self):
        for monitor in self.fake.outputs:
            if not monitor['disabled']:monitor['dpmsStatus']=False
        self.fake.input_wake_armed=True
    def test_repeated_visible_polls_respect_idle(self):
        self.panel()['dpmsStatus']=False
        for _ in range(5):self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus'])
        self.assertFalse(any('dpms(' in a[-1] for a in self.fake.calls))
    def test_visible_idle_leaves_both_asleep_and_preserves_local_wake(self):
        self.sleep_all();self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
        self.assertTrue(self.fake.input_wake_armed)
        self.fake.user_input();self.assertTrue(self.panel()['dpmsStatus'])
    def test_visible_override_is_not_keep_awake(self):
        self.c.set_override(True);self.sleep_all()
        for _ in range(4):self.c.screen(self.c.override())
        self.assertFalse(self.panel()['dpmsStatus'])
    def test_idle_connect_disconnect_preserves_idle(self):
        self.sleep_all();self.c.screen(False)
        self.assertTrue(self.panel()['disabled']);self.assertTrue(self.virtual()['dpmsStatus'])
        self.c.screen(True)
        self.assertFalse(self.panel()['disabled']);self.assertFalse(self.panel()['dpmsStatus'])
    def test_idle_during_stream_preserved_on_disconnect(self):
        self.c.screen(False);self.virtual()['dpmsStatus']=False;self.c.screen(False)
        self.assertTrue(self.virtual()['dpmsStatus']);self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus'])
    def test_idle_coinciding_with_last_disconnect_stays_off(self):
        self.c.screen(False);self.virtual()['dpmsStatus']=False
        self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
    def test_setup_preserves_idle_during_hidden_stream(self):
        self.c.screen(False);self.virtual()['dpmsStatus']=False
        self.c.setup();self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
    def test_setup_existing_virtual_keeps_idle(self):
        self.sleep_all();self.c.setup()
        self.assertFalse(self.panel()['dpmsStatus'])
        self.assertTrue(self.fake.input_wake_armed)
    def test_setup_new_virtual_keeps_idle(self):
        self.fake.outputs=self.fake.outputs[:1];self.panel()['mirrorOf']='none';self.panel()['dpmsStatus']=False
        self.c.setup()
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
    def test_explicit_restore_is_one_shot(self):
        self.sleep_all();self.c.screen(True,wake=True)
        self.assertTrue(self.panel()['dpmsStatus'])
        self.sleep_all();self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus'])
    def test_recovery_does_not_wake_unrelated_display(self):
        self.fake.outputs.append(dict(BASE,name='HDMI-A-1',dpmsStatus=False))
        self.sleep_all();self.c.recover_direct()
        self.assertTrue(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
        self.assertFalse(self.fake.outputs[-1]['dpmsStatus'])
        self.assertTrue(all('monitor=' in a[-1] for a in self.fake.calls if 'dpms(' in a[-1]))
    def test_restore_rearms_wake_when_modeset_keeps_panel_asleep(self):
        self.fake.mode_wakes_panel=False
        self.sleep_all();self.c.screen(False);self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
        self.assertTrue(self.fake.input_wake_armed)
        self.fake.user_input();self.assertTrue(self.panel()['dpmsStatus'])
    def test_mirror_targeting_refused_before_dispatch(self):
        with self.assertRaisesRegex(RuntimeError,'not eligible'):self.c.power('DP-2',False)
        self.assertFalse(any('dpms(' in a[-1] for a in self.fake.calls))
    def test_unknown_targeting_refused_before_dispatch(self):
        with self.assertRaisesRegex(RuntimeError,'not eligible'):self.c.power('missing',False)
        self.assertFalse(any('dpms(' in a[-1] for a in self.fake.calls))
    def test_global_power_refuses_hotplug(self):
        self.fake.outputs.append(dict(BASE,name='HDMI-A-1'))
        with self.assertRaises(RuntimeError):self.c.power_all(False)
        self.assertFalse(any('dpms(' in a[-1] for a in self.fake.calls))
    def test_hidden_is_verified_before_virtual_wake(self):
        self.sleep_all();self.c.screen(False)
        mutations=[a[2] for a in self.fake.calls if a[1]=='eval']
        self.assertIn('disabled=true',mutations[0]);self.assertIn('dpms(',mutations[-1])
        self.assertTrue(self.virtual()['dpmsStatus'])
    def test_disconnect_idle_rearms_local_input_wake(self):
        self.sleep_all();self.c.screen(False);self.c.screen(True)
        self.assertTrue(self.fake.input_wake_armed)
        self.fake.user_input();self.assertTrue(self.panel()['dpmsStatus'])
    def test_forced_visible_stream_follows_normal_idle(self):
        self.c.set_override(True);self.sleep_all();self.c.screen(True)
        self.assertFalse(self.panel()['dpmsStatus']);self.assertFalse(self.virtual()['dpmsStatus'])
        self.assertTrue(self.fake.input_wake_armed)
    def test_remembered_power_does_not_cross_sessions(self):
        self.c.remember_power(False);self.c.session='new-session'
        self.assertIsNone(self.c.remembered_power());self.c.screen(True)
        self.assertTrue(self.panel()['dpmsStatus'])
    def test_watcher_startup_asleep_without_virtual_does_not_wake(self):
        self.fake.outputs=self.fake.outputs[:1];self.panel()['mirrorOf']='none';self.panel()['dpmsStatus']=False
        class StoppedTracker:
            def __init__(self,*_):self.invocation=None;self.saw_stopped=True
            def poll(self):return 0
        with patch.object(p,'Connections',StoppedTracker),patch.object(p.signal,'signal'),patch.object(p,'notify_ready'),patch.object(p.time,'sleep',side_effect=KeyboardInterrupt),contextlib.redirect_stdout(io.StringIO()):
            p.watch(self.c)
        self.assertFalse(self.panel()['dpmsStatus'])
        self.assertFalse(any(a[1]=='eval' for a in self.fake.calls))


class FakeJournal:
    def __init__(self):self.state='inactive';self.invocation='';self.events=[];self.failure=None;self.calls=[]
    def __call__(self,args,**kwargs):
        self.calls.append(args)
        if args[0]=='systemctl':return result(f'ActiveState={self.state}\nInvocationID={self.invocation}\n')
        if self.failure:return self.failure
        events=self.events;self.events=[]
        return result('\n'.join(json.dumps(e) for e in events),0 if events else 1)
    def event(self,cursor,message):self.events.append(dict(__CURSOR=cursor,MESSAGE='Info: CLIENT '+message))


class JournalTests(unittest.TestCase):
    def setUp(self):self.fake=FakeJournal();self.t=p.Connections('sunshine.service',self.fake)
    def start(self):
        self.assertEqual(self.t.poll(),0)
        self.fake.state='active';self.fake.invocation='one'
    def test_empty_after_known_stopped(self):self.start();self.assertEqual(self.t.poll(),0)
    def test_existing_active_epoch_unknown(self):
        self.fake.state='active';self.fake.invocation='one'
        with self.assertRaises(RuntimeError):self.t.poll()
    def test_two_clients_last_disconnect(self):
        self.start();self.fake.event('1','CONNECTED');self.fake.event('2','CONNECTED');self.assertEqual(self.t.poll(),2)
        self.fake.event('3','DISCONNECTED');self.assertEqual(self.t.poll(),1)
        self.fake.event('4','DISCONNECTED');self.assertEqual(self.t.poll(),0)
        self.assertIn('--after-cursor=3',self.fake.calls[-1])
    def test_duplicate_replay(self):
        self.start();self.fake.event('1','CONNECTED');self.fake.event('2','CONNECTED');self.assertEqual(self.t.poll(),2)
        self.fake.event('3','DISCONNECTED');self.assertEqual(self.t.poll(),1)
        self.fake.event('1','CONNECTED');self.fake.event('3','DISCONNECTED');self.assertEqual(self.t.poll(),1)
    def test_unmatched_disconnect_unknown(self):
        self.start();self.fake.event('1','DISCONNECTED')
        with self.assertRaises(RuntimeError):self.t.poll()
        self.assertIsNone(self.t.count)
    def test_unobserved_sunshine_restart_unknown(self):
        self.start();self.t.poll();self.fake.invocation='two'
        with self.assertRaises(RuntimeError):self.t.poll()
    def test_observed_stop_allows_new_epoch(self):
        self.start();self.fake.event('1','CONNECTED');self.t.poll()
        self.fake.state='inactive';self.assertEqual(self.t.poll(),0)
        self.fake.state='active';self.fake.invocation='two';self.assertEqual(self.t.poll(),0)
    def test_journal_failure_never_assumes_zero(self):
        self.start();self.fake.event('1','CONNECTED');self.t.poll()
        self.fake.failure=result('',1,'journal unavailable')
        with self.assertRaises(RuntimeError):self.t.poll()
        self.assertIsNone(self.t.count)
    def test_malformed_event(self):
        self.start();self.fake.events=[dict(MESSAGE='CLIENT CONNECTED')]
        with self.assertRaises(RuntimeError):self.t.poll()
    def test_deactivating_unknown(self):
        self.fake.state='deactivating'
        with self.assertRaises(RuntimeError):self.t.poll()


class LifecycleTests(ControllerTests):
    def test_watcher_error_does_not_restore(self):
        self.c.screen(False)
        class BrokenTracker:
            def __init__(self,*_):pass
            def poll(self):raise RuntimeError('journal unavailable')
        with patch.object(p,'Connections',BrokenTracker), patch.object(p.signal,'signal'), patch.object(p,'notify_ready'), patch.object(p.time,'sleep',side_effect=KeyboardInterrupt):
            with self.assertRaises(RuntimeError):p.watch(self.c)
        self.assertTrue(self.c.off())
        self.assertIn('AUTOMATIC CONTROL PAUSED',self.c.status()['tooltip'])
    def test_stale_guard_cannot_reveal_later_session(self):
        self.c.test_token.write_text('old-test')
        self.c.cancel_test()  # enable-auto/restart-auto invalidates while holding the display lock
        self.c.screen(False)
        self.c.restore_test('old-test')
        self.assertTrue(self.c.off())
        self.assertIsNone(self.c.override())
    def test_only_latest_guard_can_restore(self):
        self.c.test_token.write_text('new-test')
        self.c.screen(False)
        self.c.restore_test('old-test');self.assertTrue(self.c.off())
        self.c.restore_test('new-test');self.assertFalse(self.c.off())
        self.assertFalse(self.c.test_token.exists())
    def test_auto_connection_transition_invalidates_guard(self):
        controller=self.c
        class Tracker:
            def __init__(self,*_):self.n=0;self.invocation=None;self.saw_stopped=True
            def poll(self):
                self.n+=1
                if self.n==1:return 0
                self.invocation='new';return 1
        calls=0
        def tick(_):
            nonlocal calls
            calls+=1
            if calls==1:controller.test_token.write_text('earlier-test')
            else:raise KeyboardInterrupt
        with patch.object(p,'Connections',Tracker),patch.object(p.signal,'signal'),patch.object(p,'notify_ready'),patch.object(p.time,'sleep',side_effect=tick),contextlib.redirect_stdout(io.StringIO()):
            p.watch(controller)
        self.assertTrue(controller.off())
        self.assertFalse(controller.test_token.exists())
        controller.restore_test('earlier-test');self.assertTrue(controller.off())
    def test_guard_failure_never_blanks(self):
        config_home=Path(self.temp.name)/'config'
        target=config_home/p.NAME/'config.json';target.parent.mkdir(parents=True)
        target.write_text(json.dumps(dict(self.c.c,executable='/example/screen-privacy')))
        with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(config_home)}),patch.object(p,'env'),patch.object(p,'Controller',return_value=self.c),patch.object(p,'run',side_effect=RuntimeError('timer could not be scheduled')):
            with self.assertRaises(RuntimeError):p.main(['test'])
        self.assertFalse(self.c.off())
    def test_enable_auto_requires_physical_verification(self):
        config_home=Path(self.temp.name)/'config'
        target=config_home/p.NAME/'config.json';target.parent.mkdir(parents=True)
        target.write_text(json.dumps(dict(self.c.c,executable='/example/screen-privacy')))
        with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(config_home)}),patch.object(p,'env'),patch.object(p,'Controller',return_value=self.c),patch.object(p,'run') as runner:
            with self.assertRaises(RuntimeError):p.main(['enable-auto'])
            runner.assert_not_called()


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.config=self.home/'.config';self.state=self.home/'.local/state'
        for rel,text in {'hypr/monitors.lua':'-- existing\nhl.monitor({output="",mode="preferred",scale=1})\n',
                         'hypr/bindings.lua':'-- existing bindings\n','omarchy/shell.json':json.dumps({'bar':{'layout':{'right':[{'id':'omarchy.monitor'}]}}}),
                         'sunshine/sunshine.conf':'# retain\ncapture = wlr\nfps = [30,60]\n'}.items():
            file=self.config/rel;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
        self.source=Path(__file__).resolve().parents[1]
    def plan(self):return i.make_plan(self.home,self.config,self.state,p.select_display([BASE]),'sunshine.service',self.source)
    def test_complete_supported_dry_run_writes_nothing(self):
        (self.config/'hypr/hyprland.lua').write_text('require("hypr.monitors")\nrequire("hypr.bindings")\n')
        omarchy=self.home/'omarchy';bar=omarchy/'shell/plugins/bar/Bar.qml';bar.parent.mkdir(parents=True);bar.write_text('CustomCommandModule')
        def read_only(args,**kwargs):
            if args[:2]==['hyprctl','eval']:return result('ok')
            if args[:2]==['hyprctl','monitors']:return result(json.dumps([BASE]))
            if args[:3]==['systemctl','--user','show']:
                return result('LoadState=loaded\nId=sunshine.service\nExecStart={ argv[]=/usr/bin/sunshine ; }\nEnvironment=\nEnvironmentFiles=\n')
            raise AssertionError('Unexpected mutation or command: '+str(args))
        before={str(x):x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        with patch.object(i.sys,'platform','linux'),patch.object(i.os,'geteuid',return_value=1000),patch.object(i.Path,'home',return_value=self.home),patch.object(i,'env'),patch.object(i.shutil,'which',return_value='/example/bin'),patch.object(i,'run',side_effect=read_only),patch.dict(os.environ,{'OMARCHY_PATH':str(omarchy),'XDG_CONFIG_HOME':str(self.config),'XDG_STATE_HOME':str(self.state)}),contextlib.redirect_stdout(io.StringIO()):
            i.main(['--dry-run'])
        after={str(x):x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        self.assertEqual(before,after)
    def test_plan_is_read_only(self):
        before={str(x):x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        files,config=self.plan()
        after={str(x):x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        self.assertEqual(before,after);self.assertEqual(len(files),13)
    def test_generated_config_generic_and_preserves_settings(self):
        files,config=self.plan()
        self.assertIn('fps = [30,60]',files[self.config/'sunshine/sunshine.conf'])
        self.assertIn('output_name = HEADLESS-9',files[self.config/'sunshine/sunshine.conf'])
        unit=files[self.config/'systemd/user'/p.UNIT]
        self.assertIn('Type=notify',unit);self.assertNotIn('ExecStopPost',unit)
        self.assertIn('Before=sunshine.service',unit)
    def test_stage_and_restore(self):
        original={x:x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        files,config=self.plan();manifest=i.apply_plan(files,config['state']);i.check_uninstall(manifest)
        self.assertEqual(manifest['phase'],'installed')
        self.assertTrue(os.access(self.home/'.local/bin/screen-privacy',os.X_OK))
        for record in reversed(manifest['files']):i.restore_record(record)
        for path,data in original.items():self.assertEqual(path.read_bytes(),data)
        self.assertFalse((self.home/'.local/bin/screen-privacy').exists())
    def test_later_user_edits_block_uninstall(self):
        files,config=self.plan();manifest=i.apply_plan(files,config['state'])
        file=self.config/'hypr/monitors.lua';file.write_text(file.read_text()+'-- new user edit\n')
        with self.assertRaises(RuntimeError):i.check_uninstall(manifest)
        self.assertIn('new user edit',file.read_text())
    def test_missing_backup_blocks_uninstall(self):
        files,config=self.plan();manifest=i.apply_plan(files,config['state'])
        next(Path(r['backup']) for r in manifest['files'] if r['existed']).unlink()
        with self.assertRaises(RuntimeError):i.check_uninstall(manifest)
    def test_duplicate_plan_rejected(self):
        files,config=self.plan();i.apply_plan(files,config['state'])
        with self.assertRaises(RuntimeError):self.plan()
    def test_staging_failure_rolls_back(self):
        files,config=self.plan();original={x:x.read_bytes() for x in self.home.rglob('*') if x.is_file()}
        real=i.atomic;calls=0
        def broken(path,content,mode=0o600):
            nonlocal calls
            calls+=1
            if calls==5:raise OSError('simulated disk write failure')
            return real(path,content,mode)
        with patch.object(i,'atomic',side_effect=broken),self.assertRaises(OSError):i.apply_plan(files,config['state'])
        for path,data in original.items():self.assertEqual(path.read_bytes(),data)
        manifest=json.loads((Path(config['state'])/'last-rollback.json').read_text())
        self.assertEqual(manifest['phase'],'rolled-back')
        self.assertFalse((Path(config['state'])/'manifest.json').exists())
        i.apply_plan(files,config['state'])
    def test_symlinks_rejected(self):
        files,config=self.plan();target=self.home/'.local/bin/screen-privacy';target.parent.mkdir(parents=True);target.symlink_to(self.config/'hypr/monitors.lua')
        with self.assertRaises(RuntimeError):i.apply_plan(files,config['state'])


class ServiceSelectionTests(unittest.TestCase):
    def record(self,unit='sunshine.service',command='/usr/bin/sunshine'):
        return dict(LoadState='loaded',Id=unit,ExecStart='{ path=/usr/bin/sunshine ; argv[]='+command+' ; ignore_errors=no ; }',Environment='',EnvironmentFiles='')
    def test_aliases_resolve_to_one_service(self):
        self.assertEqual(i.select_sunshine([self.record(),self.record()]),'sunshine.service')
    def test_distinct_services_rejected(self):
        with self.assertRaises(RuntimeError):i.select_sunshine([self.record(),self.record('other.service')])
    def test_custom_config_rejected(self):
        with self.assertRaises(RuntimeError):i.select_sunshine([self.record(command='/usr/bin/sunshine /custom/config')])
    def test_custom_environment_rejected(self):
        with self.assertRaises(RuntimeError):i.select_sunshine([dict(self.record(),Environment='XDG_CONFIG_HOME=/other')])
    def test_missing_service_rejected(self):
        with self.assertRaises(RuntimeError):i.select_sunshine([dict(LoadState='not-found')])


class UninstallRecoveryTests(PackagingTests):
    def fake_run(self,args,**kwargs):
        return result('active' if 'is-active' in args else 'ok')
    def test_resume_after_every_file_restore_failure(self):
        for failure_index in range(13):
            # A new staging state for each interrupted-uninstall boundary.
            files,config=self.plan();manifest=i.apply_plan(files,config['state'])
            real=i.restore_record;count=0
            def broken(record):
                nonlocal count
                current=count;count+=1
                if current==failure_index:raise OSError('simulated restore interruption')
                return real(record)
            with patch.object(i,'run',side_effect=self.fake_run),patch.object(i,'restore_record',side_effect=broken),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError):i.uninstall(config)
            with patch.object(i,'run',side_effect=self.fake_run),contextlib.redirect_stdout(io.StringIO()):i.uninstall(config)
            self.assertFalse((Path(config['state'])/'manifest.json').exists())
            self.assertFalse((self.home/'.local/bin/screen-privacy').exists())
    def test_resume_after_reload_or_restart_failure(self):
        for target in ('daemon-reload','config-only','reloadConfig','start'):
            files,config=self.plan();i.apply_plan(files,config['state'])
            failed=False
            def broken(args,**kwargs):
                nonlocal failed
                if target in args and not failed:
                    failed=True;raise RuntimeError('simulated command failure')
                return self.fake_run(args,**kwargs)
            with patch.object(i,'run',side_effect=broken),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):i.uninstall(config)
            if target!='start':self.assertTrue((self.home/'.local/bin/screen-privacy').exists())
            with patch.object(i,'run',side_effect=self.fake_run),contextlib.redirect_stdout(io.StringIO()):i.uninstall(config)
            self.assertFalse((Path(config['state'])/'manifest.json').exists())


if __name__=='__main__':unittest.main()
