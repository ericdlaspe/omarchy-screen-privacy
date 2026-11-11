#!/usr/bin/env python3
"""Omarchy Screen Privacy 0.1.2. See README.md for the limited support contract."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import uuid

NAME = 'omarchy-screen-privacy'
VERSION = '0.1.2'
UNIT = NAME + '.service'
VIRTUAL = 'HEADLESS-9'
ICON = '\U000f0d90'


def run(args, check=True, timeout=15):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Command failed: ' + args[0])
    return p


def atomic(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(content)
    temp.chmod(mode)
    temp.replace(path)


def env():
    for line in run(['systemctl', '--user', 'show-environment']).stdout.splitlines():
        key, sep, value = line.partition('=')
        if sep and key in ('HYPRLAND_INSTANCE_SIGNATURE', 'WAYLAND_DISPLAY', 'DISPLAY', 'OMARCHY_PATH', 'XDG_RUNTIME_DIR'):
            os.environ[key] = value
    if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        raise RuntimeError('Run inside the active Hyprland user session.')


def select_display(outputs):
    if any(str(m.get('name', '')).startswith('HEADLESS') for m in outputs):
        raise RuntimeError('An existing headless output needs manual integration; refusing to replace it.')
    if len(outputs) != 1:
        raise RuntimeError('Version 0.1 supports exactly one physical display. Disconnect extra outputs first.')
    m = outputs[0]
    if m.get('disabled') or not m.get('dpmsStatus', True):
        raise RuntimeError('The physical display must be enabled and awake during setup.')
    if m.get('transform', 0) != 0 or m.get('vrr', False):
        raise RuntimeError('Rotated displays and VRR are outside the version 0.1 support scope.')
    if m.get('mirrorOf', 'none') not in ('none', '', None, '-1', -1):
        raise RuntimeError('Existing mirror configuration needs manual integration.')
    if m.get('currentFormat', 'XRGB8888') not in ('XRGB8888', 'ARGB8888') or m.get('colorManagementPreset', 'srgb') not in ('srgb', ''):
        raise RuntimeError('Use an ordinary 8-bit SDR output; HDR/wide-gamut output is not supported in 0.1.')
    name = m.get('name', '')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', name):
        raise RuntimeError('Unexpected output name.')
    w, h, scale, rate = int(m['width']), int(m['height']), float(m['scale']), float(m['refreshRate'])
    if not (640 <= w <= 7680 and 480 <= h <= 4320 and .5 <= scale <= 4 and 20 <= rate <= 360):
        raise RuntimeError('Display mode is outside tested configuration limits.')
    return dict(name=name, width=w, height=h, scale=scale, rate=rate, x=int(m['x']), y=int(m['y']))


def ui_text(value, limit=512):
    """Neutralize rich-text markers before sending dynamic text to shell widgets."""
    text = ''.join(' ' if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(value))
    return text.replace('<', '‹').replace('>', '›')[:limit]


def rule(output, mode, x, y, scale, disabled=False, mirror=''):
    return 'hl.monitor({output=%s,mode=%s,position=%s,scale=%s,disabled=%s,mirror=%s})' % (
        json.dumps(output), json.dumps(mode), json.dumps(f'{x}x{y}'), scale,
        str(disabled).lower(), json.dumps(mirror))


class Controller:
    def __init__(self, config, runtime=None, runner=run, sleeper=time.sleep):
        self.c, self.run, self.sleep = config, runner, sleeper
        self.p = config['physical']
        self.virtual = config.get('virtual', VIRTUAL)
        self.runtime = Path(runtime or os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
        self.marker = self.runtime / (NAME + '.off')
        self.override_path = self.runtime / (NAME + '.override.json')
        self.test_token = self.runtime / (NAME + '.test-token')
        self.session = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')

    def outputs(self):
        return json.loads(self.run(['hyprctl', 'monitors', 'all', '-j']).stdout)

    def lua(self, code):
        result = self.run(['hyprctl', 'eval', code])
        if result.stdout.strip() != 'ok':
            raise RuntimeError(result.stdout.strip() or 'Hyprland rejected the display operation.')

    def physical_rule(self, visible=True, mirror=True):
        p = self.p
        return rule(p['name'], f"{p['width']}x{p['height']}@{p['rate']}", p['x'], p['y'], p['scale'], not visible, self.virtual if mirror else '')

    def virtual_rule(self):
        p = self.p
        return rule(self.virtual, f"{p['width']}x{p['height']}@60", p['x'], p['y'], p['scale'])

    def topology(self, outputs, require_virtual=False):
        names = {m['name'] for m in outputs}
        if names - {self.p['name'], self.virtual}:
            raise RuntimeError('Display topology changed. Automatic control is paused; check every physical display.')
        physical = next((m for m in outputs if m['name'] == self.p['name']), None)
        virtual = next((m for m in outputs if m['name'] == self.virtual and not m.get('disabled')), None)
        if not physical:
            raise RuntimeError('Configured physical display is disconnected; reconnect it before continuing.')
        if require_virtual and not virtual:
            raise RuntimeError('No active virtual display. Refusing to blank the physical screen.')
        return physical, virtual

    @contextlib.contextmanager
    def locked(self):
        with (self.runtime / (NAME + '.lock')).open('a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield

    def setup(self):
        current = self.outputs()
        self.topology(current)
        if self.virtual not in {m['name'] for m in current}:
            self.run(['hyprctl', 'output', 'create', 'headless', self.virtual])
            for _ in range(30):
                if self.virtual in {m['name'] for m in self.outputs()}:
                    break
                self.sleep(.1)
        self.topology(self.outputs(), require_virtual=True)
        self.lua(self.virtual_rule())
        # Preserve a deliberate blackout across an automatic Sunshine restart.
        hidden = self.marker.exists() and self.marker.read_text() == self.session
        self.screen(not hidden)

    def off(self):
        p, _ = self.topology(self.outputs())
        return bool(p.get('disabled') or not p.get('dpmsStatus', True))

    def screen(self, visible):
        p, virtual = self.topology(self.outputs(), require_virtual=not visible)
        if visible:
            self.marker.unlink(missing_ok=True)
            mirrored = virtual and str(p.get('mirrorOf')) in (self.virtual, str(virtual.get('id')))
            if p.get('disabled') or (virtual and not mirrored):
                self.lua(self.physical_rule(mirror=bool(virtual)))
            if not p.get('dpmsStatus', True):
                self.lua('hl.dispatch(hl.dsp.dpms({action="enable"}))')
        else:
            atomic(self.marker, self.session)
            if not p.get('disabled'):
                self.lua(self.physical_rule(visible=False))
        for _ in range(50):
            if self.off() != visible:
                return
            self.sleep(.1)
        raise RuntimeError('Display state did not settle. Use the documented recovery command.')

    def set_override(self, value):
        if value is None:
            self.override_path.unlink(missing_ok=True)
        else:
            atomic(self.override_path, json.dumps(dict(session=self.session, visible=bool(value))))

    def override(self):
        try:
            data = json.loads(self.override_path.read_text())
            return data['visible'] if data['session'] == self.session else None
        except (FileNotFoundError, ValueError, KeyError):
            return None

    def status(self):
        try:
            off = self.off()
            warning = ''
            try:
                health = json.loads((self.runtime / (NAME + '.health.json')).read_text())
                if health.get('session') == self.session:
                    warning = ' AUTOMATIC CONTROL PAUSED: ' + ui_text(health['error'])
            except (FileNotFoundError, ValueError, KeyError):
                pass
            return dict(text=ICON, **{'class': 'active' if off else ''}, tooltip=(
                'Turn screen back on' if off else 'Black out screen') +
                ' (click). Physical screen is ' + ('off' if off else 'on') +
                '. Sunshine keeps streaming. Right-click or Super+Ctrl+Shift+F12 restores. Not a session lock.' + warning)
        except Exception as exc:
            return dict(text='!', **{'class': 'active'}, tooltip='Screen privacy status unknown: ' + ui_text(exc))

    def cancel_test(self):
        self.test_token.unlink(missing_ok=True)

    def restore_test(self, token):
        # A stale timer must never reveal a later private session. Caller holds the lock.
        if token and self.test_token.exists() and self.test_token.read_text() == token:
            self.cancel_test()
            self.recover_direct()

    def recover_direct(self):
        # Independent of current topology validation; targets only the configured panel.
        self.marker.unlink(missing_ok=True)
        virtual = any(m['name'] == self.virtual and not m.get('disabled') for m in self.outputs())
        self.lua(self.physical_rule(mirror=virtual))
        self.lua('hl.dispatch(hl.dsp.dpms({action="enable"}))')
        self.set_override(True)


class Connections:
    """Best-effort journal accounting. A stopped service establishes a known zero."""
    def __init__(self, unit, runner=run):
        self.unit, self.run = unit, runner
        self.invocation, self.cursor, self.count = None, None, None
        self.saw_stopped = False
        self.seen = set()

    def poll(self):
        raw = self.run(['systemctl', '--user', 'show', self.unit, '-p', 'ActiveState', '-p', 'InvocationID']).stdout
        props = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        active = props.get('ActiveState')
        if active in ('inactive', 'failed'):
            self.invocation, self.cursor, self.count = None, None, 0
            self.saw_stopped = True
            self.seen.clear()
            return 0
        if active not in ('active', 'activating'):
            raise RuntimeError('Sunshine state is uncertain; not restoring the display.')
        invocation = props.get('InvocationID')
        if not invocation:
            raise RuntimeError('Sunshine invocation is unknown.')
        if invocation != self.invocation:
            known_zero = self.saw_stopped
            self.invocation, self.cursor = invocation, None
            self.seen.clear()
            self.count = 0 if known_zero else None
            self.saw_stopped = False
        if self.count is None:
            raise RuntimeError('Started during an existing Sunshine process. Run screen-privacy restart-auto to reestablish session tracking.')
        args = ['journalctl', '--user', '-u', self.unit, '_SYSTEMD_INVOCATION_ID=' + invocation,
                '--no-pager', '-o', 'json', '--grep=CLIENT (CONNECTED|DISCONNECTED)']
        if self.cursor:
            args.append('--after-cursor=' + self.cursor)
        result = self.run(args, check=False)
        if result.returncode and not (result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip()):
            self.count = None
            raise RuntimeError('Cannot reconcile Sunshine journal; keeping the current physical display state.')
        for line in result.stdout.splitlines():
            record = json.loads(line)
            cursor = record.get('__CURSOR')
            if not cursor:
                self.count = None
                raise RuntimeError('Journal event has no cursor.')
            if cursor in self.seen:
                continue
            self.seen.add(cursor)
            match = re.search(r'\bCLIENT (CONNECTED|DISCONNECTED)\b', record.get('MESSAGE', ''))
            if match:
                change = 1 if match[1] == 'CONNECTED' else -1
                if self.count + change < 0:
                    self.count = None
                    raise RuntimeError('Unmatched Sunshine disconnect. Session state is unknown.')
                self.count += change
            self.cursor = cursor
        return self.count


def notify_ready():
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(b'READY=1')


def watch(controller):
    tracker = Connections(controller.c['sunshine_unit'])
    previous, announced, last_error = None, False, None
    health = controller.runtime / (NAME + '.health.json')
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            try:
                count = tracker.poll()
                state = (tracker.invocation, count > 0)
                with controller.locked():
                    if previous is not None and state != previous:
                        controller.cancel_test()
                        controller.set_override(None)
                    visible = controller.override()
                    if visible is None:
                        visible = count == 0
                    # No headless is expected before Sunshine ExecStartPre creates it.
                    if tracker.invocation is not None or controller.off():
                        controller.screen(visible)
                if state != previous:
                    print(f'Observed clients={count}; physical screen {"off" if controller.off() else "on"}', flush=True)
                previous, last_error = state, None
                health.unlink(missing_ok=True)
            except Exception as exc:
                message = str(exc)
                if message != last_error:
                    print('Automatic control paused: ' + message + ' Use screen-privacy on for intentional local recovery.', file=sys.stderr, flush=True)
                last_error = message
                atomic(health, json.dumps(dict(session=controller.session, error=message)))
            if not announced and not getattr(tracker, 'saw_stopped', False):
                raise RuntimeError('Automatic startup requires a known stopped Sunshine process. Use screen-privacy restart-auto.')
            if not announced:
                notify_ready()
                announced = True
            time.sleep(1)
    except KeyboardInterrupt:
        # Do not expose an active private desktop just because this watcher stopped.
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'status', 'on', 'off', 'toggle', 'auto', 'watch', 'activate', 'test', 'enable-auto', 'restart-auto', 'disable-auto', 'restore-layout', 'diagnose', 'uninstall', 'restore-test'])
    parser.add_argument('--token', help=argparse.SUPPRESS)
    parser.add_argument('--verified', action='store_true', help='I checked remote capture and the physical screen in the 20-second test.')
    parser.add_argument('--yes', action='store_true', help='Approve uninstall, including disconnecting Sunshine.')
    args = parser.parse_args(argv)
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
    config = json.loads((config_home/NAME/'config.json').read_text())
    os.umask(0o077)
    env()
    ctl = Controller(config)
    executable = str(Path(config['executable']))
    action = args.action
    if action == 'uninstall':
        if not args.yes:
            raise RuntimeError('Uninstall disconnects Sunshine and restores the local screen. Run screen-privacy uninstall --yes to proceed.')
        from installer import uninstall
        uninstall(config)
    elif action == 'status':
        print(json.dumps(ctl.status()))
    elif action == 'watch':
        watch(ctl)
    elif action == 'diagnose':
        print(json.dumps({'version': VERSION, 'outputs': [{k:m.get(k) for k in ('name','width','height','scale','disabled','dpmsStatus','mirrorOf')} for m in ctl.outputs()],
                          'sunshine': run(['systemctl','--user','is-active',config['sunshine_unit']],check=False).stdout.strip(),
                          'automatic':run(['systemctl','--user','is-active',UNIT],check=False).stdout.strip()}, indent=2))
    elif action in ('activate', 'enable-auto', 'restart-auto'):
        if action == 'enable-auto' and not args.verified:
            raise RuntimeError('First run screen-privacy test while streaming and verify the actual panel. Then run enable-auto --verified.')
        # Explicit user command: this deliberately disconnects any current client.
        run(['systemctl','--user','stop',config['sunshine_unit']])
        run(['systemctl','--user','stop',UNIT],check=False)
        with ctl.locked():
            ctl.cancel_test()
            ctl.setup()
            ctl.set_override(None if action != 'activate' else True)
        if action != 'activate':
            run(['systemctl','--user','enable','--now',UNIT])
        run(['systemctl','--user','start',config['sunshine_unit']])
        print('Ready. Reconnect Moonlight. ' + ('Test the physical screen before enabling automatic control.' if action == 'activate' else 'Automatic control enabled; verify the physical panel after reconnecting.'))
    elif action == 'disable-auto':
        run(['systemctl','--user','disable','--now',UNIT])
        with ctl.locked():
            ctl.cancel_test()
        print('Automatic control disabled. Physical screen state retained; run screen-privacy on to reveal it.')
    elif action == 'test':
        # Arm restoration before blanking; tokens invalidate older guards.
        token = uuid.uuid4().hex
        guard = NAME + '-test-' + token
        with ctl.locked():
            atomic(ctl.test_token, token)
            try:
                run(['systemd-run','--user','--collect','--unit='+guard,'--on-active=20s','--timer-property=AccuracySec=1s',executable,'restore-test','--token',token])
            except Exception:
                ctl.cancel_test()
                raise
            ctl.screen(False)
            ctl.set_override(False)
        print('Physical screen disabled for 20 seconds. Check the actual panel and remote desktop now. Automatic restore is armed.')
    elif action == 'restore-test':
        with ctl.locked():
            ctl.restore_test(args.token)
    elif action == 'restore-layout':
        # Only safe after stopping Sunshine; used by the uninstall path.
        if run(['systemctl','--user','is-active',config['sunshine_unit']],check=False).stdout.strip() not in ('inactive','failed','unknown'):
            raise RuntimeError('Stop Sunshine before restoring the original layout.')
        with ctl.locked():
            ctl.cancel_test()
            ctl.marker.unlink(missing_ok=True)
            ctl.lua(ctl.physical_rule(mirror=False))
            ctl.sleep(.5)
            if ctl.virtual in {m['name'] for m in ctl.outputs()}:
                ctl.run(['hyprctl','output','remove',ctl.virtual])
            ctl.set_override(None)
    else:
        with ctl.locked():
            if action != 'setup':
                ctl.cancel_test()
            if action == 'setup':
                ctl.setup()
            elif action == 'on':
                ctl.recover_direct()
            elif action == 'auto':
                ctl.set_override(None)
            else:
                visible = action == 'toggle' and ctl.off()
                ctl.screen(visible)
                ctl.set_override(visible)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Screen privacy: ' + str(exc), file=sys.stderr)
        sys.exit(1)
