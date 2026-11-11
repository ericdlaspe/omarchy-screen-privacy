#!/usr/bin/env python3
"""Per-user, conflict-detecting installer. No dependencies are downloaded."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from privacy import NAME, VERSION, UNIT, VIRTUAL, ICON, Controller, atomic, env, rule, run, select_display

BEGIN = '-- BEGIN OMARCHY SCREEN PRIVACY'
END = '-- END OMARCHY SCREEN PRIVACY'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def marked(code):
    return '\n' + BEGIN + '\n' + code + '\n' + END + '\n'


def sunshine_config(text):
    lines = [line for line in text.splitlines() if not re.match(r'^\s*(capture|output_name)\s*=', line)]
    return '\n'.join(lines).rstrip() + '\n\ncapture = wlr\noutput_name = ' + VIRTUAL + '\n'


def make_plan(home, config_home, state_home, physical, sunshine_unit, source):
    home, config_home, state_home, source = map(Path, (home, config_home, state_home, source))
    share = home/'.local/share'/NAME
    exe = home/'.local/bin/screen-privacy'
    state = state_home/NAME
    config = dict(version=VERSION, physical=physical, virtual=VIRTUAL, sunshine_unit=sunshine_unit,
                  executable=str(exe), state=str(state))
    files = {}
    for name in ('privacy.py','installer.py','README.md','LICENSE','CHANGELOG.md'):
        files[share/name] = (source/name).read_text()
    files[exe] = '#!/bin/sh\nexec /usr/bin/python3 ' + "'" + str(share/'privacy.py').replace("'", "'\\''") + "' \"$@\"\n"
    files[config_home/NAME/'config.json'] = json.dumps(config, indent=2)+'\n'
    p = physical
    physical_mode = f"{p['width']}x{p['height']}@{p['rate']}"
    virtual_mode = f"{p['width']}x{p['height']}@60"
    virtual_rule = rule(VIRTUAL, virtual_mode, p['x'], p['y'], p['scale'])
    physical_rule = rule(p['name'], physical_mode, p['x'], p['y'], p['scale'], mirror=VIRTUAL).replace('disabled=false','disabled=screen_off')
    monitor_code = '''-- Created by Omarchy Screen Privacy. Keep the current visibility on config reload.
if hl.get_monitor(%s) then
  local runtime = os.getenv("XDG_RUNTIME_DIR")
  local marker = runtime and io.open(runtime .. "/%s.off", "r") or nil
  local screen_off = false
  if marker then
    screen_off = marker:read("*a") == (os.getenv("HYPRLAND_INSTANCE_SIGNATURE") or "")
    marker:close()
  end
  %s
  %s
end''' % (json.dumps(VIRTUAL), NAME, virtual_rule, physical_rule)
    binding_code = 'o.bind("SUPER + CTRL + SHIFT + F12", "Restore physical screen", %s, { locked = true })' % json.dumps(str(exe)+' on')
    for name, code in (('monitors.lua',monitor_code),('bindings.lua',binding_code)):
        path = config_home/'hypr'/name
        original = path.read_text()
        if BEGIN in original or END in original:
            raise RuntimeError('A previous privacy integration exists. Uninstall or restore it first.')
        files[path] = original.rstrip()+'\n'+marked(code)
    shell = config_home/'omarchy/shell.json'
    data = json.loads(shell.read_text())
    layout = data['bar']['layout']
    if any(e.get('id') == NAME for entries in layout.values() for e in entries):
        raise RuntimeError('The privacy bar button already exists.')
    entry = dict(id=NAME, type='command', interval=2, text=ICON, tooltip='Black out the physical screen; Sunshine keeps streaming.',
                 exec=str(exe)+' status', onClick=str(exe)+' toggle', onRightClick=str(exe)+' on')
    index = next((i for i,e in enumerate(layout['right']) if e.get('id') == 'omarchy.monitor'), len(layout['right']))
    layout['right'].insert(index,entry)
    files[shell] = json.dumps(data,ensure_ascii=False,indent=2)+'\n'
    sunshine = config_home/'sunshine/sunshine.conf'
    files[sunshine] = sunshine_config(sunshine.read_text() if sunshine.exists() else '')
    # The controller is ready before Sunshine starts, so a fresh journal epoch is known.
    files[config_home/'systemd/user'/UNIT] = f'''[Unit]
Description=Physical screen privacy for Sunshine
Before={sunshine_unit}
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=notify
NotifyAccess=main
ExecStart="{exe}" watch
Restart=on-failure
RestartSec=2
TimeoutStartSec=30
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target
'''
    files[config_home/'systemd/user'/f'{sunshine_unit}.d'/f'{NAME}.conf'] = f'''[Service]
ExecStartPre="{exe}" setup
'''
    return files, config


def select_sunshine(records):
    units = {r['Id']:r for r in records if r.get('LoadState') == 'loaded'}
    if len(units) != 1:
        raise RuntimeError('Expected one distinct Sunshine user service; missing or ambiguous service configuration.')
    unit, props = next(iter(units.items()))
    if not re.fullmatch(r'[A-Za-z0-9_.@:-]+\.service',unit):
        raise RuntimeError('Unexpected Sunshine service name.')
    command = props.get('ExecStart','')
    match = re.search(r'argv\[\]=([^;]+);',command)
    if not match or match[1].strip() != '/usr/bin/sunshine':
        raise RuntimeError('Custom Sunshine launch/config arguments need manual integration. Expected /usr/bin/sunshine with no arguments.')
    if re.search(r'(HOME|XDG_CONFIG_HOME|SUNSHINE[^= ]*)=',props.get('Environment','')) or props.get('EnvironmentFiles',''):
        raise RuntimeError('Custom Sunshine environment/configuration needs manual integration.')
    return unit


def preflight(home, config_home, state_home, source):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('Run as your ordinary Omarchy desktop user on Linux, not root.')
    if any(c in str(home) for c in ('\n','\r','%','"','\\',"'",' ')):
        raise RuntimeError('Version 0.1 requires a home path without whitespace or shell/systemd quoting characters.')
    if (state_home/NAME/'manifest.json').exists():
        raise RuntimeError('Already installed. No files changed. Use screen-privacy uninstall --yes before reinstalling.')
    for command in ('hyprctl','systemctl','journalctl','systemd-run','sunshine','omarchy-shell'):
        if not shutil.which(command):
            raise RuntimeError('Missing dependency: '+command+'. Install it through Omarchy before continuing.')
    env()
    for rel in ('hypr/hyprland.lua','hypr/monitors.lua','hypr/bindings.lua','omarchy/shell.json'):
        if not (config_home/rel).is_file():
            raise RuntimeError('Requires Lua-based Omarchy with Quickshell: missing '+rel)
    root = (config_home/'hypr/hyprland.lua').read_text()
    if not all(name in root for name in ('hypr.monitors','hypr.bindings')):
        raise RuntimeError('The Hyprland root must load hypr.monitors and hypr.bindings.')
    bindings = (config_home/'hypr/bindings.lua').read_text()
    if re.search(r'SUPER\s*\+\s*CTRL\s*\+\s*SHIFT\s*\+\s*F12', bindings):
        raise RuntimeError('The recovery shortcut is already assigned. Resolve that conflict first.')
    shell_root = Path(os.environ.get('OMARCHY_PATH','/usr/share/omarchy'))/'shell'
    bar = shell_root/'plugins/bar/Bar.qml'
    if not bar.exists() or 'CustomCommandModule' not in bar.read_text():
        raise RuntimeError('This Omarchy bar does not have the supported command-widget interface.')
    api = run(['hyprctl','eval','assert(type(hl.monitor) == "function" and type(hl.get_monitor) == "function")'])
    if api.stdout.strip() != 'ok':
        raise RuntimeError('Unsupported Hyprland Lua monitor API.')
    physical = select_display(json.loads(run(['hyprctl','monitors','all','-j']).stdout))
    if config_home != home/'.config':
        raise RuntimeError('Version 0.1 supports the standard ~/.config location only.')
    records = []
    for unit in ('app-dev.lizardbyte.app.Sunshine.service','sunshine.service'):
        result = run(['systemctl','--user','show',unit,'-p','LoadState','-p','Id','-p','ExecStart','-p','Environment','-p','EnvironmentFiles'],check=False)
        records.append(dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line))
    sunshine_unit = select_sunshine(records)
    conf = config_home/'sunshine/sunshine.conf'
    old_conf = conf.read_text() if conf.exists() else ''
    if re.search(r'^\s*output_name\s*=\s*\S',old_conf,re.M):
        raise RuntimeError('Sunshine already selects an output. Manual integration is required.')
    if re.search(r'^\s*capture\s*=\s*(?!wlr\s*$)\S+',old_conf,re.M):
        raise RuntimeError('Sunshine uses another capture backend. This package only supports wlr.')
    files, config = make_plan(home,config_home,state_home,physical,sunshine_unit,source)
    managed_existing = [p for p in files if p.exists() and (p == home/'.local/bin/screen-privacy' or NAME in p.parts or p.name == NAME+'.conf' or p.name == UNIT)]
    if managed_existing:
        raise RuntimeError('Owned paths already exist: '+', '.join(map(str,managed_existing)))
    return files, config


def apply_plan(files, state):
    state = Path(state)
    state.mkdir(parents=True,exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns() % 1000000000)
    backup = state/'backups'/stamp
    backup.mkdir(parents=True,exist_ok=False)
    entries = []
    for i,(path,text) in enumerate(files.items()):
        existing = path.exists()
        if path.is_symlink():
            raise RuntimeError('Refusing to replace a symlink: '+str(path))
        record = dict(path=str(path), existed=existing, installed_sha256=digest(text.encode()), mode=path.stat().st_mode & 0o777 if existing else None)
        if existing:
            original = backup/str(i)
            shutil.copy2(path,original)
            record['backup'] = str(original)
            record['original_sha256'] = digest(original.read_bytes())
        entries.append(record)
    configuration = next(json.loads(text) for path,text in files.items() if path.name == 'config.json' and path.parent.name == NAME)
    manifest = dict(version=VERSION,phase='prepared',files=entries,configuration=configuration)
    atomic(state/'manifest.json',json.dumps(manifest,indent=2)+'\n')
    applied = []
    try:
        for record in entries:
            path = Path(record['path'])
            mode = 0o755 if path.name == 'screen-privacy' else (record['mode'] or 0o600)
            atomic(path,files[path],mode)
            applied.append(record)
        manifest['phase'] = 'installed'
        atomic(state/'manifest.json',json.dumps(manifest,indent=2)+'\n')
    except BaseException:
        for record in reversed(applied):
            restore_record(record)
        manifest['phase'] = 'rolled-back'
        atomic(state/'last-rollback.json',json.dumps(manifest,indent=2)+'\n')
        (state/'manifest.json').unlink(missing_ok=True)
        raise
    return manifest


def restore_record(record):
    target = Path(record['path'])
    if record['existed']:
        source = Path(record['backup'])
        temp = target.with_name(target.name+'.restore-tmp')
        shutil.copy2(source,temp)
        temp.replace(target)
    else:
        target.unlink(missing_ok=True)


def original_matches(record):
    path = Path(record['path'])
    if not record['existed']:
        return not path.exists() and not path.is_symlink()
    return path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == record.get('original_sha256')


def check_uninstall(manifest):
    conflicts = []
    for record in manifest['files']:
        path = Path(record['path'])
        installed = path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == record['installed_sha256']
        restored = manifest['phase'] == 'uninstalling' and original_matches(record)
        if not installed and not restored:
            conflicts.append(str(path))
        if record['existed'] and not Path(record['backup']).is_file():
            conflicts.append('Missing backup for '+str(path))
    if conflicts:
        raise RuntimeError('Uninstall stopped before making changes: files changed since installation. Preserve your changes and follow README manual cleanup. Conflicts: '+', '.join(conflicts))


def uninstall(config):
    state = Path(config['state'])
    manifest_path = state/'manifest.json'
    if not manifest_path.exists():
        print('No active installation manifest. Nothing changed.')
        return
    manifest = json.loads(manifest_path.read_text())
    check_uninstall(manifest)
    if manifest['phase'] != 'uninstalling':
        manifest['restart_sunshine'] = run(['systemctl','--user','is-active',config['sunshine_unit']],check=False).stdout.strip() == 'active'
    manifest['phase'] = 'uninstalling'
    def save():
        atomic(manifest_path,json.dumps(manifest,indent=2)+'\n')
    save()
    run(['systemctl','--user','stop',config['sunshine_unit']])
    run(['systemctl','--user','disable','--now',UNIT],check=False)
    if not manifest.get('layout_restored'):
        run([config['executable'],'restore-layout'])
        manifest['layout_restored'] = True
        save()
    # Keep helper, code, and its config until display/config recovery and reloads succeed.
    def recovery_file(record):
        path = Path(record['path'])
        return path == Path(config['executable']) or '/.local/share/'+NAME+'/' in str(path) or (path.name == 'config.json' and path.parent.name == NAME)
    for cleanup_phase in (False,True):
        for record in reversed(manifest['files']):
            if recovery_file(record) != cleanup_phase:
                continue
            if not original_matches(record):
                restore_record(record)
            record['restored'] = True
            save()
        if not cleanup_phase:
            run(['systemctl','--user','daemon-reload'])
            run(['hyprctl','reload','config-only'])
            run(['omarchy-shell','shell','reloadConfig'])
    if manifest.get('restart_sunshine'):
        run(['systemctl','--user','start',config['sunshine_unit']])
    manifest['phase'] = 'uninstalled'
    atomic(state/'last-uninstall.json',json.dumps(manifest,indent=2)+'\n')
    manifest_path.unlink()
    print('Uninstalled. Original configuration restored; backups retained at '+str(state/'backups'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall',action='store_true',help='Uninstall or resume an interrupted uninstall using the saved manifest.')
    parser.add_argument('--yes',action='store_true',help='Approve uninstall and Sunshine disconnect.')
    parser.add_argument('--dry-run',action='store_true',help='Validate and print the plan; do not write or restart anything.')
    args = parser.parse_args(argv)
    os.umask(0o077)
    home = Path.home()
    config_home = Path(os.environ.get('XDG_CONFIG_HOME',home/'.config'))
    state_home = Path(os.environ.get('XDG_STATE_HOME',home/'.local/state'))
    if args.uninstall:
        if not args.yes:
            raise RuntimeError('Uninstall disconnects Sunshine and reveals the physical desktop; add --yes to proceed.')
        manifest = state_home/NAME/'manifest.json'
        if not manifest.exists():
            print('No active installation manifest. Nothing changed.')
            return
        env()
        uninstall(json.loads(manifest.read_text())['configuration'])
        return
    files, config = preflight(home,config_home,state_home,Path(__file__).resolve().parent)
    print('Display:',config['physical']['name'],str(config['physical']['width'])+'x'+str(config['physical']['height']),'scale',config['physical']['scale'])
    print('Files to back up/update:')
    for p in files:
        print('  '+str(p))
    if args.dry_run:
        print('Dry run complete. Nothing changed.')
        return
    apply_plan(files,config['state'])
    run(['systemctl','--user','daemon-reload'])
    run(['omarchy-shell','shell','reloadConfig'],check=False)
    print('Installed, not activated. No stream restarted. Run ~/.local/bin/screen-privacy activate when ready for a brief disconnect, then follow README.md.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Install: '+str(exc),file=sys.stderr)
        sys.exit(1)
