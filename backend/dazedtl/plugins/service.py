"""Retained assistant investigation, exact text edits and reviewed runtime publication."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import shlex
import sys
import threading
import uuid

from dazedtl.storage import write_bytes, write_json
from dazedtl.translation import backups
from dazedtl.translation.files import digest, project_path, read_json
from dazedtl.translation.operations import lifecycle, lifecycle_path, require_source_backup
from .documents import Documents, JAPANESE, decode, leaves, occurrences, validate

WORK = ".dazedtl/plugin-work"
DISPOSITIONS = {"visible", "latent", "protected", "editor_only", "non_visible", "unresolved"}
VIEW = {"mode":"scope", "query":"", "filter":"all", "selectedOnly":False, "currentFile":"", "offset":0}
FILTERS = {'all', 'ready', 'selected', 'needs_revision', 'latent', 'unresolved', 'stale', 'applied', 'not_investigated', 'not_needed'}
DATABASE_JSON = {"Actors.json", "Classes.json", "Skills.json", "Items.json", "Weapons.json", "Armors.json",
                 "Enemies.json", "Troops.json", "States.json", "Animations.json", "Tilesets.json", "System.json",
                 "CommonEvents.json", "MapInfos.json"}


def now(): return datetime.now(timezone.utc).isoformat()


def bounded(value, label, limit=4000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(label + " must be bounded text.")
    return value


def safe_name(name):
    if not isinstance(name, str) or not name or any(c in name for c in '\\/:\x00\r\n') or name in {'.','..'}:
        raise ValueError("Configured plugin names must be exact safe filenames.")
    return name


class PluginService:
    def __init__(self, projects, translation, backend, *, documents=None):
        self.projects, self.translation, self.backend = projects, translation, backend
        self.documents = documents or Documents()
        self.lock = threading.RLock()
        self.previews, self.cache, self.observed = {}, {}, {}

    def record(self, project_id):
        project = self.projects.get(project_id)
        root = Path(project["source"]).resolve(strict=True)
        for protected in (self.translation.workspace, self.backend.source):
            path = Path(protected).resolve()
            if root.is_relative_to(path) or path.is_relative_to(root):
                raise ValueError("Plugin work needs a game separate from the app and profile.")
        return project, root

    def path(self, project_id, name):
        return project_path(self.record(project_id)[1], WORK + "/" + name, exists=False)

    def load(self, project_id):
        path = self.path(project_id, "state.json")
        if not path.exists():
            return {"version":1,"projectId":project_id,"files":{},"selection":[],"manual":{},"view":dict(VIEW),
                    "requests":{},"findings":{"status":"idle","errors":[]},"editing":{"status":"idle","errors":[]},
                    "receipts":[],"pending":[],"layout":"","originals":{},"binding":""}
        signature = (path.stat().st_mtime_ns, path.stat().st_size)
        saved = self.cache.get(project_id)
        value = deepcopy(saved[1]) if saved and saved[0] == signature else read_json(path, limit=64_000_000)
        if value.get("version") != 1 or value.get("projectId") != project_id:
            raise ValueError("Plugin state belongs to a different project or version. Its files were retained.")
        if value['view']['filter'] not in FILTERS:
            value['view'].update(filter='all', offset=0)
        self.cache[project_id] = (signature, deepcopy(value))
        return value

    def save(self, project_id, value):
        path = self.path(project_id, "state.json"); write_json(path, value)
        self.cache[project_id] = ((path.stat().st_mtime_ns,path.stat().st_size), deepcopy(value))

    @staticmethod
    def revision(value):
        # View drafts must survive the external agent updating findings and scope.
        return digest(value['view'])

    def source(self, root, path):
        target = project_path(root, path)
        if not target.is_file() or target.stat().st_size > 16_000_000:
            raise ValueError("Plugin files must be regular files below 16 MB.")
        before = target.stat(); raw = target.read_bytes(); after = target.stat()
        if (before.st_mtime_ns,before.st_size) != (after.st_mtime_ns,after.st_size):
            raise ValueError("A plugin file changed during reading. Refresh when its writer finishes.")
        raw.decode('utf-8')
        return raw

    def inventory(self, project_id):
        project, root = self.record(project_id)
        if project["engine"] == "ACE":
            raise ValueError("Ace scripts require a Ruby parser and native packing integration. Existing extracted scripts remain untouched; use the preserved Ruby assistant workflow separately.")
        if project["engine"] != "MVMZ":
            raise ValueError("Plugin text supports RPG Maker MV/MZ.")
        matches = [prefix for prefix in ('www/','') if (root / (prefix+'js/plugins.js')).is_file()]
        if len(matches) != 1:
            raise ValueError("Choose a game with one unambiguous js/plugins.js or www/js/plugins.js.")
        prefix = matches[0]; config = prefix+'js/plugins.js'
        parsed = self.documents.parse([{"path":config,"source":self.source(root,config).decode(),'kind':'parameters'}])[config]
        if parsed["issues"]: raise ValueError(parsed["issues"][0])
        rows = {config:{"path":config,"kind":"parameters","plugin":"Plugin parameters","enabled":True}}
        names = set(); statuses = {}
        for index, entry in enumerate(parsed["plugins"]):
            if not isinstance(entry, dict) or type(entry.get('status')) is not bool or not isinstance(entry.get('parameters'),dict):
                raise ValueError("Every plugin entry needs a static name, status and parameter object.")
            name = safe_name(entry.get('name'))
            if name in names: raise ValueError("Duplicate configured plugins need investigation before exact scope can be formed.")
            names.add(name); statuses[name]=entry['status']; path = prefix+'js/plugins/'+name+'.js'
            rows[path] = {"path":path,"kind":"source","plugin":name,"enabled":entry['status'],"pluginIndex":index}
        for path in sorted((root / (prefix+'js/plugins')).glob('*.js')):
            relative = path.relative_to(root).as_posix()
            owner=path.stem.removesuffix('Config') if path.stem.endswith('Config') else path.stem
            rows.setdefault(relative, {"path":relative,"kind":"config" if path.stem.endswith('Config') else "source","plugin":path.stem,"enabled":statuses.get(owner)})
        return prefix, rows, parsed

    def original_context(self, project_id, prefix):
        _, root = self.record(project_id); state = lifecycle(self.translation.workspace,project_id)
        require_source_backup(root,state); record = state['source_backup']
        location = backups.lookup(root,Path(record['path']).parent,record['id'])
        manifest = backups.manifest(location,root)
        names = [name for name in manifest['files'] if name.startswith(prefix+'data/') and name.endswith('.json')]
        if not names or prefix+'js/plugins.js' not in manifest['files']:
            raise ValueError("The preserved original lacks the Japanese database or plugin configuration. Recover the matching original source before editing.")
        keys, hashes = set(), {name:manifest['files'][name] for name in names}
        with backups.materialized(location,files=[*names,prefix+'js/plugins.js']) as (original,_):
            def nested(value):
                if isinstance(value,str):
                    keys.add(value)
                    try: inner = decode(value)
                    except ValueError: return
                    if isinstance(inner,(dict,list,str)): nested(inner)
                elif isinstance(value,dict):
                    keys.update(value)
                    for inner in value.values(): nested(inner)
                elif isinstance(value,list):
                    for inner in value: nested(inner)
            def fields(value, database):
                if isinstance(value,dict):
                    note = value.get('note')
                    if isinstance(note,str): keys.update(match.group(1).strip() for match in re.finditer(r'<([^<>:]+)(?::[^<>]*)?>',note))
                    if database and isinstance(value.get('name'),str): keys.add(value['name'])
                    if value.get('code') in {356,357} and isinstance(value.get('parameters'),list):
                        for item in value['parameters']:
                            if isinstance(item,str) and value['code']==356:
                                keys.update(item.split())
                            nested(item)
                    for item in value.values(): fields(item,database)
                elif isinstance(value,list):
                    for item in value: fields(item,database)
            for name in names:
                fields(read_json(original/name),Path(name).name in {'Actors.json','Classes.json','Skills.json','Items.json','Weapons.json','Armors.json','Enemies.json','States.json'})
            raw = (original/(prefix+'js/plugins.js')).read_bytes()
            parsed = self.documents.parse([{"path":prefix+'js/plugins.js',"source":raw.decode(),'kind':'parameters'}])[prefix+'js/plugins.js']
            if parsed['issues']: raise ValueError("The preserved original plugin configuration cannot be parsed.")
            structural_keys = sorted(keys)
            for entry in parsed['plugins']: nested(entry['parameters'])
        hashes[prefix+'js/plugins.js'] = manifest['files'][prefix+'js/plugins.js']
        return {"backupId":record['id'],"hashes":hashes,"keys":sorted(keys),"structuralKeys":structural_keys,"binding":digest(hashes)}

    def scan(self, project_id, value):
        _, root = self.record(project_id); prefix, rows, config = self.inventory(project_id)
        # Explicit JSON dependencies discovered in a previous request remain addressable.
        for path, row in value['files'].items():
            if row['kind']=='json': rows[path] = {key:row[key] for key in ('path','kind','plugin','enabled','dependency')}
        files, raw_files = [], {}
        for path,row in rows.items():
            try:
                raw = self.source(root,path); raw_files[path]=raw
                files.append({"path":path,"source":raw.decode(),'kind':row['kind']})
            except (OSError,ValueError,UnicodeError) as exc: row['issue']=str(exc)
        parsed = self.documents.parse(files)
        try: originals = self.original_context(project_id,prefix); original_issue = ''
        except (OSError,ValueError,UnicodeError) as exc: originals = {}; original_issue = str(exc)
        protected = set(originals.get('keys',[]))
        for path,row in rows.items():
            prior = value['files'].get(path,{})
            row['sourceHash'] = digest(raw_files[path]) if path in raw_files else ''
            row['issue'] = row.get('issue') or '; '.join(parsed.get(path,{}).get('issues',[]))
            try:
                row['occurrences'] = occurrences(path,raw_files[path],parsed[path]) if path in parsed and not row['issue'] else []
            except ValueError as exc:
                row['occurrences'],row['issue'] = [],str(exc)
            row['loaderLiterals'] = [{'id':digest({'file':path,'span':[item['start'],item['end']],'value':item['value']})[:24],
                                      'value':item['value'],'line':item['line']} for item in parsed.get(path,{}).get('literals',[])
                                    if isinstance(item['value'],str) and item['value'].endswith('.json')]
            code_keys = {item['value'] for item in parsed.get(path,{}).get('literals',[]) if item['protected']}
            if row['kind']=='parameters':
                for item in row['occurrences']:
                    logical = parsed[path]['literals'][item['token']]['path']
                    if len(logical)>=3 and type(logical[0]) is int and logical[1]=='parameters':
                        entry = config['plugins'][logical[0]]
                        item.update(plugin=entry['name'],enabled=entry['status'],parameterPath=logical[2:])
                    else: item['protected'] = True
            for item in row['occurrences']:
                item.setdefault('plugin',row['plugin']); item.setdefault('enabled',row['enabled'])
                lookup_keys = set(originals.get('structuralKeys',[])) if row['kind']=='parameters' else protected
                item['protected'] = item['protected'] or item['value'] in lookup_keys or item['value'] in code_keys
                item['latent'] = not item['enabled'] or item['kind']=='default'
                old = next((old for old in prior.get('occurrences',[]) if old['id']==item['id']),{})
                for key in ('finding','target'):
                    if key in old and row['sourceHash']==prior.get('sourceHash'): item[key]=old[key]
            if row['sourceHash']==prior.get('sourceHash'):
                for key in ('prepared','result','applied','examined'):
                    if key in prior: row[key]=prior[key]
            elif prior.get('applied') and row['sourceHash']==prior['applied'].get('afterHash'):
                # Applied source is displayed separately; frozen investigation remains meaningful.
                row = {**prior,'observedHash':row['sourceHash']}
            else:
                row['stale'] = bool(prior)
                if prior.get('prepared'): row['archivedPrepared'] = prior['prepared']
            rows[path] = row
        value.update(files=rows,layout=prefix+'js/plugins.js',originals=originals,originalIssue=original_issue)
        value['binding'] = digest({path:row['sourceHash'] for path,row in rows.items()})
        return parsed

    def eligible(self, value):
        return {item['id']:item for row in value['files'].values() if not row.get('issue') and not row.get('stale')
                for item in row['occurrences'] if not item['protected'] and item.get('finding',{}).get('disposition') in {'visible','latent'}
                and item.get('finding',{}).get('safe') is True}

    def recommended_selection(self, value):
        eligible = self.eligible(value)
        selected = {identity for identity,item in eligible.items()
                    if not item['latent'] and item['finding']['disposition']=='visible'}
        for identity,choice in value['manual'].items():
            if choice['selected'] and identity in eligible: selected.add(identity)
            if not choice['selected']: selected.discard(identity)
        return sorted(selected)

    def public_row(self, value, row):
        selected = set(value['selection'])
        items = row['occurrences']; visible = [item for item in items if item.get('finding',{}).get('disposition')=='visible' and not item['latent']]
        latent = [item for item in items if item['latent']]
        count = sum(item['id'] in selected for item in items)
        result = row.get('result',{}); status = result.get('status') or ('working_copy' if row.get('prepared') else 'selected' if count else 'not_investigated')
        if row.get('applied') and result.get('status')=='ready' and result.get('candidateHash')==row['applied'].get('afterHash'): status = 'applied'
        if row.get('examined') and not count and not result: status = 'latent' if latent and not visible else 'not_needed' if not visible else 'available'
        uncertain = sum(not item['protected'] and (not item.get('finding') or
                        item['finding']['disposition']=='unresolved' or
                        item['finding']['disposition'] in {'visible','latent'} and not item['finding']['safe']) for item in items)
        if uncertain and not count and not result and not row.get('stale'): status = 'unresolved'
        if row.get('stale'): status = 'stale'
        if row.get('issue'): status = 'unresolved'
        return {key:row.get(key) for key in ('path','plugin','enabled','kind','sourceHash','issue')} | {
            'selected':count,'visible':len(visible),'latent':len(latent),'occurrences':len(items),'status':status,
            'uncertain':uncertain,
            'recommended':sum(not item['protected'] and not item['latent'] and item.get('finding',{}).get('disposition')=='visible'
                              and item.get('finding',{}).get('safe') is True and not row.get('stale') and not row.get('issue') for item in items),
            'manual':sum(item['id'] in value['manual'] for item in items),'changed':len(result.get('targets',{})),
            'reason':result.get('reason','') or row.get('issue',''), 'candidateHash':result.get('candidateHash',''),
            'working':row.get('prepared',{}).get('candidate',''), 'ready':status=='ready', 'applied':bool(row.get('applied')) and not row.get('stale')}

    def observe(self, project_id, value):
        """Bounded observations invalidate displayed checks without rewriting assistant work."""
        _,root=self.record(project_id)
        def fingerprint(path):
            target=project_path(root,path); stat=target.stat(); signature=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            cached=self.observed.get(str(target))
            if not cached or cached[0]!=signature:
                cached=(signature,digest(self.source(root,path)));self.observed[str(target)]=cached
            return cached[1]
        for row in value['files'].values():
            try:
                result=row.get('result',{})
                expected=row.get('applied',{}).get('afterHash') or row['sourceHash']
                if fingerprint(row['path'])!=expected: row['stale']=True
                if not row.get('prepared'): continue
                prepared=row['prepared']
                if fingerprint(prepared['original'])!=prepared['originalHash']: row['issue']='Frozen original changed; recover it before continuing.'
                if result and fingerprint(prepared['candidate'])!=result['candidateHash']:
                    row['result']={**result,'status':'needs_revision','reason':'Working copy changed; refresh results to check its current bytes.','checks':{}}
                ids=sorted(item['id'] for item in row['occurrences'] if item['id'] in value['selection'])
                if result and ids and ids!=result['selection']:
                    row['result']={**result,'status':'needs_revision','reason':'Text selection changed; copy a new translation task and refresh its results.','checks':{}}
                if result and result.get('requestId')!=value['requests'].get('translation',{}).get('requestId'):
                    row['result']={**result,'status':'needs_revision','reason':'Saved results belong to an earlier task; refresh the current task report. Existing working copies are retained.','checks':{}}
            except (OSError,ValueError) as exc: row['issue']=str(exc)

    def state(self, project_id):
        with self.lock:
            value = self.load(project_id); self.recover(project_id,value)
            self.observe(project_id,value)
            project, root = self.record(project_id)
            rows = [self.public_row(value,row) for row in value['files'].values()]
            counts = {'files':len(rows),'selectedFiles':sum(row['selected']>0 for row in rows), 'selected':len(value['selection']),
                      'recommended':sum(row['recommended'] for row in rows),'ready':sum(row['selected']>0 and row['ready'] for row in rows),
                      'blocked':sum(row['selected']>0 and not row['ready'] and row['status']!='applied' for row in rows),
                      'applied':sum(row['applied'] for row in rows),'latent':sum(row['latent'] for row in rows)}
            counts['selectedNotPrepared']=sum(row['selected']>0 and not row['working'] for row in rows)
            return {'projectId':project_id,'revision':self.revision(value),'observationRevision':digest(value),
                    'supported':project['engine']=='MVMZ','limitation':'Ace Ruby scripts need parser and native packing support; this workspace cannot publish them.' if project['engine']=='ACE' else '',
                    'layout':value['layout'],'source':str(root),'view':value['view'],'counts':counts,
                    'findings':value['findings'],'editing':value['editing'],'originalIssue':value.get('originalIssue',''),
                    'originalBackup':value['originals'].get('backupId',''), 'receipts':value['receipts'][-12:],
                    'activeRequest':next((request['path'] for request in value['requests'].values() if request['requestId']==value.get('activeRequest')),''),
                    'requestPaths':{key:request['path'] for key,request in value['requests'].items()}}

    def list(self, project_id, query='', filter='all', selected_only=False, offset=0, limit=100):
        bounded(query,'Search',500); bounded(filter,'Filter',30)
        if filter not in FILTERS: filter = 'all'
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200: raise ValueError("Choose a bounded plugin table range.")
        with self.lock:
            value = self.load(project_id); self.observe(project_id,value); rows = [self.public_row(value,row) for row in value['files'].values()]
            rows = [row for row in rows if query.casefold() in (row['path']+' '+row['plugin']).casefold()
                    and (filter=='all' or row['status']==filter) and (not selected_only or row['selected'])]
            rows.sort(key=lambda row:row['path'])
            return {'items':rows[offset:offset+limit],'total':len(rows),'selectedMatched':sum(row['selected']>0 for row in rows),'offset':offset,'limit':limit}

    def detail(self, project_id, file):
        with self.lock:
            value = self.load(project_id)
            self.observe(project_id,value)
            if file not in value['files']: raise ValueError("Choose an inventoried plugin file.")
            row = value['files'][file]; _,root = self.record(project_id)
            result = row.get('result',{}); prepared = row.get('prepared',{})
            before = self.source(root,prepared['original']).decode() if prepared else self.source(root,file).decode()
            after = self.source(root,prepared['candidate']).decode() if prepared else before
            # Bounded source excerpts. Full files remain on disk for the scoped assistant.
            evidence = []
            lines,later=before.splitlines(),after.splitlines()
            for item in row['occurrences'][:500]:
                line = max(0,item['line']-1)
                evidence.append({**item,'selected':item['id'] in value['selection'],'manual':value['manual'].get(item['id']),
                                 'before':'\n'.join(lines[max(0,line-2):line+3])[:4000],
                                 'after':'\n'.join(later[max(0,line-2):line+3])[:4000],
                                 'target':result.get('targets',{}).get(item['id'],'')})
            return {**self.public_row(value,row),'items':evidence,'total':len(row['occurrences']),
                    'checks':result.get('checks',{}),'resultEvidence':result.get('evidence',''), 'rendered':'Pending playtest',
                    'original':prepared.get('original',''),'originalHash':prepared.get('originalHash','')}

    def update(self, project_id, revision, changes):
        with self.lock:
            value=self.load(project_id)
            if self.revision(value)!=revision: raise ValueError("Plugin choices changed. Reload before saving.")
            if not isinstance(changes,dict) or set(changes)-{'view'}: raise ValueError("Unknown plugin preference.")
            view = changes.get('view',{})
            if not isinstance(view,dict) or set(view)-set(VIEW): raise ValueError("Unknown plugin view.")
            for key,item in view.items():
                if key=='selectedOnly':
                    if type(item) is not bool: raise ValueError("Invalid selection filter.")
                elif key=='offset':
                    if type(item) is not int or not 0<=item<=1_000_000: raise ValueError("Invalid table position.")
                else: bounded(item,'Plugin view',2000)
            if view.get('mode',value['view']['mode']) not in {'scope','working'}: raise ValueError("Choose scope or working copies.")
            if view.get('filter',value['view']['filter']) not in FILTERS: view = {**view, 'filter':'all', 'offset':0}
            value['view'].update(view); self.save(project_id,value)
            return self.state(project_id)

    def action(self, project_id, action, options=None):
        options=options or {}
        if not isinstance(options,dict): raise ValueError("Plugin action options must be an object.")
        with self.lock:
            value=self.load(project_id)
            if action in {'investigate','plugin_task'}:
                self.scan(project_id,value); result=self.request(project_id,value,'investigation',automatic=action=='plugin_task')
            elif action in {'refresh_findings','refresh_results'}:
                result=self.refresh(project_id,value,'investigation' if action=='refresh_findings' else 'translation')
            elif action in {'recommended','select','select_files','clear'}:
                eligible=self.eligible(value); selected=set(value['selection'])
                if action=='recommended':
                    selected=set(self.recommended_selection(value))
                elif action=='clear':
                    for identity in selected: value['manual'][identity]={'selected':False,'reason':'Selection cleared by you'}
                    selected=set()
                else:
                    identities=options.get('ids',[])
                    if action=='select_files':
                        paths=options.get('paths',[])
                        if not isinstance(paths,list) or not paths or set(paths)-set(value['files']): raise ValueError("Choose exact inventoried file paths.")
                        identities=[item['id'] for path in paths for item in value['files'][path]['occurrences']
                                    if options.get('selected') is False or item['id'] in eligible and (not item['latent'] or options.get('includeLatent') is True)]
                    if not isinstance(identities,list) or len(set(identities))!=len(identities): raise ValueError("Choose exact unique occurrence IDs.")
                    wanted=options.get('selected')
                    if type(wanted) is not bool: raise ValueError("Choose include or exclude.")
                    known={item['id'] for row in value['files'].values() for item in row['occurrences']}
                    if set(identities)-known or wanted and set(identities)-set(eligible): raise ValueError("Unresolved or protected text needs new investigation evidence before inclusion.")
                    reason=bounded(options.get('reason',''),'Manual choice reason')
                    if wanted and any(eligible[identity]['latent'] for identity in identities) and not reason.strip():
                        raise ValueError("Give a reason before including disabled/default-only text.")
                    for identity in identities:
                        value['manual'][identity]={'selected':wanted,'reason':reason or ('Included by you' if wanted else 'Excluded by you')}
                        selected.add(identity) if wanted else selected.discard(identity)
                value['selection']=sorted(selected); result={'selected':len(selected)}
            elif action=='prepare': result=self.prepare(project_id,value)
            elif action=='translation_task':
                self.prepare(project_id,value)
                result=self.request(project_id,value,'translation')
            elif action in {'preview_apply','preview_restore'}: return {'preview':self.preview(project_id,value,'apply' if action=='preview_apply' else 'restore',options)}
            elif action in {'apply','restore'}: return self.publish(project_id,value,action,options)
            else: raise ValueError("Choose a supported Plugin workspace action.")
            self.save(project_id,value); return {**result,'state':self.state(project_id)}

    def guidance(self, root):
        paths=['.dazedtl/glossary.txt',*[path.relative_to(root).as_posix() for path in (root/'.dazedtl/skills').glob('*.md')]]
        return {path:{'sha256':digest(self.source(root,path)),'text':self.source(root,path).decode()} for path in paths if (root/path).is_file()}

    def request(self, project_id, value, kind, *, automatic=False, previous=''):
        _,root=self.record(project_id); identity=uuid.uuid4().hex
        request_path=self.path(project_id,'requests/'+identity+'.json'); report_path=self.path(project_id,'reports/'+identity+'.json')
        files=[]; selected=set(value['selection'])
        for path,row in value['files'].items():
            items=[item for item in row['occurrences'] if kind=='investigation' or item['id'] in selected]
            if kind=='translation' and not items: continue
            if kind=='translation' and not row.get('prepared'): raise ValueError("Make working copies for every selected file before copying the translation task.")
            files.append({'path':path,'sourceHash':row['sourceHash'],'kind':row['kind'],'enabled':row['enabled'],
                          'issue':row.get('issue',''),'occurrences':items,'loaderLiterals':row.get('loaderLiterals',[]),**row.get('prepared',{})})
        if kind=='translation' and not files: raise ValueError("Choose investigated display text before translation.")
        if kind=='translation':
            self.current_sources(project_id,value,files); self.current_originals(project_id,value)
        request={'version':1,'kind':kind,'projectId':project_id,'requestId':identity,'binding':value['binding'],
                 'guidance':self.guidance(root),'originals':value['originals'],'layout':value['layout'],'files':files,
                 'selection':value['selection'],'manual':value['manual'],'report':str(report_path),'path':str(request_path)}
        request=deepcopy(request)  # Requests never alias mutable findings, scope choices or results.
        value['findings' if kind=='investigation' else 'editing']={'status':'awaiting_report','errors':[],'requestId':identity}
        common=("This is one explicitly scoped DazedTL Plugin text task. Copying it did not start an assistant.\n"
                "Read the request JSON: "+str(request_path)+"\nSave a structured report at: "+str(report_path)+"\n"
                "Bind version, kind, projectId, requestId and binding exactly. Use only requested file/occurrence IDs and SHA-256 hashes. "
                "Read request-bound glossary/context. Event plugin commands belong to Other event text; do not edit event/database JSON or images. "
                "Never run plugin/game code, providers or translation APIs.\n")
        if kind=='investigation':
            schema={'version':1,'kind':kind,'projectId':project_id,'requestId':identity,'binding':value['binding'],'complete':False,
                    'files':[{'path':'exact requested path','sourceHash':'request hash','examined':True,'evidence':'complete source and recursive-parameter coverage',
                              'occurrences':[{'id':'request occurrence ID','disposition':'visible|latent|protected|editor_only|non_visible|unresolved','safe':True,'evidence':'runtime display usage and readback checks','reason':'why visible and safe'}]}],
                    'dependencies':[{'path':'exact plugin-loaded JSON path','sourceFile':'requested loader file','literalId':'requested literal ID containing the exact path','evidence':'static loader use'}]}
            text=common+("FIRST, INVESTIGATE. " if automatic else "INVESTIGATION ONLY. ")+"During investigation, do not edit runtime files, working copies, settings or source backups. Audit every configured enabled/disabled plugin and every listed source. "
            text+="Recursively decode every parameter layer, count repeated leaf occurrences, inspect executable strings/templates, defaults/fallbacks and usages; ordinary comments/editor metadata stay excluded. "
            text+="Every supplied occurrence needs a disposition. Missing/ambiguous sources remain unresolved. Disabled/default-only display text is latent. "
            text+="Protect exact lookup keys from pristine original note-tag names, 356/357 arguments, parameters and database names; both drawn and compared remains protected. "
            text+="No whole-file substring matching. The app rechecks original hashes and deterministic key guards. If originals are missing, report discovery only and leave safety unresolved. "
            text+="Additional JSON may be proposed only with an exact existing loader-path literal from the request. Its own text needs a subsequent bound investigation before selection.\nReport schema:\n"+json.dumps(schema,ensure_ascii=False,indent=2)
            text+="\nConfirmed active display text is included automatically when the app checks this report; do not ask the user to approve safe items or inspect each string. Ask focused questions only for ambiguous meaning, visibility or behavioral safety after completing all independent investigation. Leave uncertain items unresolved and explain the evidence needed. Disabled/default-only text stays excluded unless the user chooses it."
        else:
            schema={'version':1,'kind':kind,'projectId':project_id,'requestId':identity,'binding':value['binding'],'complete':False,
                    'files':[{'path':'exact scope path','sourceHash':'request hash','candidateHash':'working copy SHA-256','evidence':'Japanese/English meaning and layout review performed',
                              'targets':{'approved occurrence ID':'exact decoded English target'}}]}
            text=common+"TRANSLATE THE SCOPED WORKING COPIES ONLY. The app has included confirmed safe display text and retained user overrides. Proceed without asking for approval of these routine translations; ask only about ambiguity you cannot resolve and leave those occurrences unchanged. Runtime files and frozen originals are read-only. No new files, unrelated module edits, or scope expansion. "
            text+="Change only listed literal spans/decoded parameter paths. Preserve quote style, parameter keys/order/types/serialization depth, identifiers, lookup values, interpolation and control codes. "
            text+="Translate connected text with the saved guidance; revise failed/partial results in these same copies. Report every translated occurrence and exact decoded target. "
            text+="The app rejects any bytes outside approved spans, unapproved decoded leaves and stale hashes; syntax alone does not verify meaning. Apply is a separate user review. "
            text+="Do not claim rendered fit/playtest without testing it.\nReport schema:\n"+json.dumps(schema,ensure_ascii=False,indent=2)
        if automatic:
            helper = Path(__file__).resolve().parents[3] / 'scripts/project.py'
            arguments = [sys.executable,'-B',str(helper),'--workspace',str(self.translation.workspace),'--project',project_id,'plugins']
            def command(arguments):
                return ('& '+' '.join("'"+item.replace("'","''")+"'" for item in arguments)
                        if os.name=='nt' else shlex.join(arguments))
            resume=command(arguments); advance=command([*arguments,'--continue-request',identity])
            text=("Complete plugin investigation and translation in this same agent task. Keep DazedTL open. "
                  "Continue automatically through confirmed safe work; do not ask the user to copy a second prompt or approve routine steps. "
                  "Ask focused questions only for unresolved choices, and complete independent work first.\n\n"+text+
                  "\n\nAfter saving this stage's report, run:\n"+advance+
                  "\nThe helper validates the report and returns the next request with its instructions, or the final checked state. "
                  "Read and carry out those instructions in this same conversation. Additional plugin-loaded JSON is investigated before translation. "
                  "Working copies are prepared automatically. On failed translation checks, repair the same copies and report, then run this command again. "
                  "Runtime Apply remains in the app; this helper cannot approve or publish game files.\n"
                  "If loopback access is sandboxed, use your normal permission flow and retry this read-only status command first:\n"+resume+
                  "\nA lost response may follow a completed action. Read the activeRequest path from that status and follow its saved instructions; "
                  "do not restart investigation or blindly retry a mutation. Never expose the local connection token. "
                  "If permitted access still fails, save work and report the connection blocker.\n")
            request.update(automatic=True,previousRequestId=previous,instructions=text)
        value['activeRequest']=identity if automatic else ''
        write_json(request_path,request); value['requests'][kind]=request
        write_json(Path(self.translation.workspace)/'plugin-contracts'/project_id/(identity+'.json'),
                   {'projectId':project_id,'requestId':identity,'requestHash':digest(request)})
        return {'text':text,'request':str(request_path),'requestId':identity,'stage':kind}

    def continue_task(self, project_id, request_id):
        """Advance a copied task through reports and editable copies, never publication."""
        with self.lock:
            value=self.load(project_id)
            request=next((row for row in value['requests'].values()
                          if row['requestId']==value.get('activeRequest')),None)
            if not request or not request.get('automatic'):
                raise ValueError("Copy a plugin task in the app before continuing through the helper.")
            self.verify_request(project_id,request)
            if request_id!=request['requestId']:
                if request_id==request.get('previousRequestId'):
                    # A lost reply must not restart the next stage or replace edited copies.
                    return {'text':request['instructions'],'request':request['path'],
                            'requestId':request['requestId'],'stage':request['kind'],'state':self.state(project_id)}
                raise ValueError("This plugin task was replaced. Read plugin status and use its active request.")
            self.translation.idle(project_id); self.translation.clean_drafts(project_id)
            self.refresh(project_id,value,request['kind'])
            # Retain accepted findings even if later preparation cannot finish.
            self.save(project_id,value)
            result={}
            if request['kind']=='investigation':
                asked={row['path'] for row in request['files']}
                if set(value['files'])-asked:
                    self.scan(project_id,value)
                    result=self.request(project_id,value,'investigation',automatic=True,previous=request_id)
                elif value['selection']:
                    self.prepare(project_id,value,switch_view=False)
                    result=self.request(project_id,value,'translation',automatic=True,previous=request_id)
            self.save(project_id,value)
            state=self.state(project_id)
            if not result:
                incomplete=state['counts']['blocked'] or value['findings']['status']=='partial' or any(
                    row['uncertain'] or row['issue'] or row['status'] in {'stale','needs_revision','partial'}
                    for row in (self.public_row(value, row) for row in value['files'].values()))
                result={'stage':'partial' if incomplete else 'complete',
                        'message':'Saved work checked. Resolve reported uncertainty or failed checks; runtime Apply remains in the app.' if incomplete else 'Plugin work checked. Review and apply available translations in the app.'}
            return {**result,'state':state}

    def current_sources(self, project_id, value, rows):
        _,root=self.record(project_id)
        for row in rows:
            if not row['sourceHash'] and row.get('issue'): continue
            expected=value['files'][row['path']].get('applied',{}).get('afterHash') or row['sourceHash']
            if digest(self.source(root,row['path']))!=expected: raise ValueError("Source changed: "+row['path']+". Refresh investigation before editing or publication.")

    def current_originals(self, project_id, value):
        prefix=value['layout'].removesuffix('js/plugins.js'); current=self.original_context(project_id,prefix)
        if not value['originals'] or current['binding']!=value['originals']['binding']:
            raise ValueError("Original Japanese lookup evidence changed or is missing. Investigate again.")
        return current

    def verify_request(self, project_id, request):
        authority=read_json(Path(self.translation.workspace)/'plugin-contracts'/project_id/(request['requestId']+'.json'))
        if authority!={'projectId':project_id,'requestId':request['requestId'],'requestHash':digest(request)} or read_json(request['path'])!=request:
            raise ValueError("The scoped request changed. Copy and review a new task.")

    def runtime_allowlist(self, project_id, value, row):
        prefix,catalog,_=self.inventory(project_id)
        if row['path'] in catalog:
            if row['kind']!=catalog[row['path']]['kind']: raise ValueError("The exact runtime file kind changed.")
            return
        dependency=row.get('dependency',{})
        source=dependency.get('sourceFile'); literal=dependency.get('literalId'); name=dependency.get('path')
        if row['kind']!='json' or source not in catalog or not isinstance(name,str): raise ValueError("Runtime file is outside the exact plugin allowlist.")
        _,root=self.record(project_id)
        parsed=self.documents.parse([{'path':source,'source':self.source(root,source).decode(),'kind':catalog[source]['kind']}])[source]
        possible={digest({'file':source,'span':[item['start'],item['end']],'value':item['value']})[:24]:item['value'] for item in parsed['literals']}
        expected=prefix+name if prefix and not name.startswith(prefix) else name
        if possible.get(literal)!=name or expected!=row['path']: raise ValueError("The exact plugin-loaded JSON dependency changed.")

    def copy_boundary(self, root, prepared):
        copy_root=prepared.get('copyRoot')
        if not copy_root: raise ValueError("Working-copy scope is missing. Prepare a fresh owned copy.")
        directory=project_path(root,copy_root,exists=False)
        if not directory.is_dir(): raise ValueError("Working-copy directory is missing.")
        expected={prepared['original'],prepared['candidate']}
        actual=set()
        for target in directory.rglob('*'):
            if target.is_symlink(): raise ValueError("Working copies cannot contain symbolic links.")
            if target.is_file(): actual.add(target.relative_to(root).as_posix())
        if actual!=expected: raise ValueError("New or missing files in the working-copy scope are not authorized.")

    def refresh(self, project_id, value, kind):
        request=value['requests'].get(kind)
        if not request: raise ValueError("Copy the scoped task before refreshing its saved report.")
        _,root=self.record(project_id)
        self.verify_request(project_id,request)
        if not Path(request['report']).is_file():
            raise ValueError("No saved "+kind+" report yet. Have your agent finish the copied task, then check again.")
        report=read_json(request['report'],limit=32_000_000)
        if not isinstance(report,dict) or any(report.get(key)!=request[key] for key in ('version','kind','projectId','requestId','binding')):
            raise ValueError("Saved report is foreign, stale or belongs to another task. No findings were accepted.")
        if self.guidance(root)!=request['guidance']: raise ValueError("Saved guidance changed. Copy a new scoped task before accepting results.")
        rows=report.get('files'); allowed={row['path']:row for row in request['files']}
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows) or len({row.get('path') for row in rows})!=len(rows):
            raise ValueError("Report files must be unique exact entries.")
        if any(row.get('path') not in allowed for row in rows): raise ValueError("Report contains an out-of-scope file.")
        self.current_sources(project_id,value,request['files'])
        if kind=='translation': self.current_originals(project_id,value)
        accepted=0; errors=[]
        # Work on a copy so malformed reports never partially mutate trusted findings.
        updated=deepcopy(value)
        if kind=='investigation':
            # A partial replacement report cannot inherit safety from an earlier report.
            for path in allowed:
                updated['files'][path]['examined']=False
                for item in updated['files'][path]['occurrences']: item.pop('finding',None)
        for answer in rows:
            path=answer['path']; asked=allowed[path]; row=updated['files'][path]
            if answer.get('sourceHash')!=asked['sourceHash']: raise ValueError("Report source hash does not match: "+path)
            if kind=='investigation':
                answers=answer.get('occurrences',[]); known={item['id']:item for item in row['occurrences']}
                if not isinstance(answers,list) or len({item.get('id') for item in answers if isinstance(item,dict)})!=len(answers): raise ValueError("Occurrence findings must be unique entries.")
                for item in answers:
                    if item.get('id') not in known or item.get('disposition') not in DISPOSITIONS or type(item.get('safe')) is not bool:
                        raise ValueError("Unknown occurrence or invalid disposition.")
                    evidence=bounded(item.get('evidence',''),'Finding evidence'); reason=bounded(item.get('reason',''),'Finding reason')
                    if not evidence.strip() or not reason.strip(): raise ValueError("Every disposition needs concrete usage evidence and a reason.")
                    target=known[item['id']]; finding=deepcopy(item)
                    if target['protected']:
                        finding.update(disposition='protected',safe=False,reason='Protected original lookup value or code key. '+reason)
                    elif target['latent'] and finding['disposition']=='visible': finding['disposition']='latent'
                    if not updated['originals']: finding['safe']=False
                    target['finding']=finding
                row['examined']=answer.get('examined') is True and len(answers)==len(known) and bool(answer.get('evidence')) and not row.get('issue')
                row['stale']=False
                if not row['examined']: errors.append(path+': incomplete coverage')
                else: accepted+=1
            else:
                prepared=row.get('prepared')
                if not prepared: raise ValueError("This file has no owned working copy.")
                self.copy_boundary(root,prepared)
                candidate=self.source(root,prepared['candidate']); original=self.source(root,prepared['original'])
                if digest(original)!=prepared['originalHash']: raise ValueError("Frozen original changed: "+path)
                if answer.get('candidateHash')!=digest(candidate): raise ValueError("Candidate hash does not match: "+path)
                targets=answer.get('targets'); approved=asked['occurrences']; ids={item['id'] for item in approved}
                if not isinstance(targets,dict) or set(targets)-ids: raise ValueError("Results contain unapproved occurrence IDs.")
                evidence=bounded(answer.get('evidence',''),'Translation review evidence')
                if not evidence.strip(): raise ValueError("Results need saved meaning/review evidence.")
                try:
                    parsed=self.documents.parse([{'path':'original/'+path,'source':original.decode(),'kind':row['kind']},
                                                 {'path':'candidate/'+path,'source':candidate.decode(),'kind':row['kind']}])
                    checks=validate(original,candidate,parsed['original/'+path],parsed['candidate/'+path],approved,targets)
                    complete=set(targets)==ids
                    status='ready' if complete and candidate!=original else 'partial' if not complete else 'unchanged'
                    reason='' if status=='ready' else 'Awaiting remaining approved occurrences' if status=='partial' else 'No changed text to publish'
                except (ValueError,UnicodeError) as exc:
                    status,reason,checks='needs_revision',str(exc),{}
                row['result']={'status':status,'reason':reason,'checks':checks,'candidateHash':digest(candidate),'targets':targets,
                               'evidence':evidence,'requestId':request['requestId'],'selection':sorted(ids),'saved':now()}
                if status=='ready': accepted+=1
                else: errors.append(path+': '+reason)
        if kind=='investigation':
            for dependency in report.get('dependencies',[]):
                path=dependency.get('path'); source=dependency.get('sourceFile'); literal=dependency.get('literalId')
                if source not in allowed: raise ValueError("JSON dependency loader must belong to this investigation.")
                match=next((item for item in allowed[source]['occurrences'] if item['id']==literal),None)
                # Path literals generally contain no Japanese and are supplied separately below.
                parsed=self.documents.parse([{'path':source,'source':self.source(root,source).decode(),'kind':allowed[source]['kind']}])[source]
                possible={digest({'file':source,'span':[item['start'],item['end']],'value':item['value']})[:24]:item['value'] for item in parsed['literals']}
                if literal not in possible or possible[literal]!=path or not isinstance(path,str) or not path.endswith('.json'):
                    raise ValueError("Loaded JSON needs an exact static loader-path literal from the request.")
                prefix=value['layout'].removesuffix('js/plugins.js'); actual=prefix+path if prefix and not path.startswith(prefix) else path
                if not actual.startswith((prefix+'data/',prefix+'img/',prefix+'js/')) or Path(actual).name in DATABASE_JSON or re.fullmatch(r'Map\d+\.json',Path(actual).name):
                    raise ValueError("This JSON is outside the plugin-loaded runtime scope or belongs to an existing text phase.")
                self.source(root,actual)
                if not bounded(dependency.get('evidence',''),'Loader evidence').strip(): raise ValueError("Loaded JSON needs concrete loader-use evidence.")
                updated['files'].setdefault(actual,{'path':actual,'plugin':updated['files'][source]['plugin']+' data','kind':'json','enabled':allowed[source]['enabled'],
                    'dependency':dependency,'sourceHash':digest(self.source(root,actual)),'occurrences':[],'issue':'','stale':True})
                errors.append(actual+': needs its own request-bound investigation')
        key='findings' if kind=='investigation' else 'editing'
        completed=len(rows)==len(allowed) and not errors and (kind!='investigation' or all(updated['files'][path].get('examined') for path in allowed))
        updated[key]={'status':'current' if completed else 'partial','errors':errors,'accepted':accepted,'reported':len(rows),'expected':len(allowed),'saved':now(),'requestId':request['requestId']}
        if kind=='investigation': updated['selection']=self.recommended_selection(updated)
        value.clear(); value.update(updated)
        return {'accepted':accepted,'message':'Saved '+kind+' report checked.','errors':errors}

    def prepare(self, project_id, value, *, switch_view=True):
        self.translation.idle(project_id); self.translation.clean_drafts(project_id)
        eligible=self.eligible(value); selected=set(value['selection'])
        if not selected or selected-set(eligible): raise ValueError("Choose current, safe investigated text before making working copies.")
        self.current_originals(project_id,value); _,root=self.record(project_id)
        rows=[row for row in value['files'].values() if any(item['id'] in selected for item in row['occurrences'])]
        self.current_sources(project_id,value,rows); completed=0
        for row in rows:
            self.runtime_allowlist(project_id,value,row)
            if row.get('prepared'):
                prepared=row['prepared']; self.copy_boundary(root,prepared)
                if digest(self.source(root,prepared['original']))!=prepared['originalHash']:
                    raise ValueError("Frozen original changed: "+row['path'])
                self.source(root,prepared['candidate'])
                continue
            identity=uuid.uuid4().hex; base=WORK+'/copies/'+identity+'/'+row['path']
            raw=self.source(root,row['path'])
            original=base+'.original'; candidate=base
            write_bytes(project_path(root,original,exists=False),raw); write_bytes(project_path(root,candidate,exists=False),raw)
            row['prepared']={'original':original,'originalHash':digest(raw),'candidate':candidate,'copyRoot':WORK+'/copies/'+identity,'prepared':now()}; completed+=1
        if switch_view: value['view']['mode']='working'
        return {'completed':completed,'message':'Working copies prepared; runtime files are unchanged.'}

    def checked_rows(self, project_id, value, mode, options):
        _,root=self.record(project_id); selected=set(value['selection']); included=[]; blocked=[]
        receipt=None
        if mode=='restore':
            receipt=next((row for row in value['receipts'] if row['id']==options.get('receipt')),None)
            if not receipt: raise ValueError("Choose a saved application receipt to restore.")
            publication=self.approved_publication(project_id,receipt['id'])
            approved={row['path']:row for row in publication['files']}
            if (publication['mode']!='apply' or receipt['mode']!='apply' or receipt['manifest']!=publication['manifest']
                    or any(approved.get(row['path'])!=row for row in receipt['files'])):
                raise ValueError("Restore receipt differs from its exact approved publication.")
            rows=[value['files'][item['path']] for item in receipt['files'] if item['path'] in value['files']]
        else:
            rows=[row for row in value['files'].values() if any(item['id'] in selected for item in row['occurrences'])]
            originals=self.current_originals(project_id,value)
        for row in rows:
            path=row['path']; reason=''
            try:
                current=digest(self.source(root,path))
                if mode=='restore':
                    saved=next(item for item in receipt['files'] if item['path']==path)
                    if current!=saved['afterHash']: raise ValueError("Runtime changed since this receipt; recover/compare it before restore.")
                    output=self.source(root,saved['backup']); after=digest(output)
                    if after!=saved['beforeHash']: raise ValueError("Receipt backup changed.")
                    candidate=saved['backup']; original_hash=saved['originalHash']
                else:
                    result=row.get('result',{}); prepared=row.get('prepared',{})
                    self.runtime_allowlist(project_id,value,row)
                    self.copy_boundary(root,prepared)
                    expected=row.get('applied',{}).get('afterHash') or row['sourceHash']
                    if current!=expected: raise ValueError("Runtime source changed; refresh investigation.")
                    if result.get('status')!='ready': raise ValueError(result.get('reason') or "Saved validated translation results are needed.")
                    ids=sorted(item['id'] for item in row['occurrences'] if item['id'] in selected)
                    if result['selection']!=ids: raise ValueError("Approved occurrence scope changed; copy a new translation task.")
                    if digest(self.source(root,prepared['original']))!=prepared['originalHash']: raise ValueError("Frozen original changed.")
                    output=self.source(root,prepared['candidate']); after=digest(output)
                    if after!=result['candidateHash']: raise ValueError("Working copy changed; refresh its checks.")
                    candidate=prepared['candidate']; original_hash=prepared['originalHash']
                    request=value['requests'].get('translation')
                    if not request or request['requestId']!=result['requestId'] or self.guidance(root)!=request['guidance']:
                        raise ValueError("The translation request or saved guidance changed; review a new task.")
                    self.verify_request(project_id,request)
                    asked=next((item for item in request['files'] if item['path']==path),None)
                    if not asked or sorted(item['id'] for item in asked['occurrences'])!=ids: raise ValueError("The exact approved occurrence scope changed.")
                    original=self.source(root,prepared['original'])
                    parsed=self.documents.parse([{'path':'original/'+path,'source':original.decode(),'kind':row['kind']},
                                                 {'path':'candidate/'+path,'source':output.decode(),'kind':row['kind']}])
                    actual={item['id']:item for item in occurrences(path,original,parsed['original/'+path])}
                    lookup_keys=set(originals['structuralKeys'] if row['kind']=='parameters' else originals['keys'])
                    code_keys={item['value'] for item in parsed['original/'+path]['literals'] if item['protected']}
                    for occurrence in asked['occurrences']:
                        checked=actual.get(occurrence['id'])
                        if not checked or any(checked[key]!=occurrence[key] for key in ('value','token','logical','start','end')):
                            raise ValueError("Approved literal identity no longer matches its frozen bytes.")
                        if checked['protected'] or checked['value'] in lookup_keys or checked['value'] in code_keys:
                            raise ValueError("Protected original lookup or code value cannot be published.")
                    validate(original,output,parsed['original/'+path],parsed['candidate/'+path],asked['occurrences'],result['targets'])
                if current==after: raise ValueError("Runtime already matches this output.")
                included.append({'path':path,'destination':path,'beforeHash':current,'afterHash':after,'originalHash':original_hash,
                                 'candidate':candidate,'candidateHash':after,'backup':WORK+'/backups/'+uuid.uuid4().hex+'/'+path,
                                 'kind':row['kind'],'changes':len(row.get('result',{}).get('targets',{}))})
            except (ValueError,OSError) as exc: reason=str(exc)
            if reason: blocked.append({'path':path,'reason':reason})
        return included,blocked

    def preview(self, project_id, value, mode, options):
        self.translation.idle(project_id); self.translation.clean_drafts(project_id)
        included,blocked=self.checked_rows(project_id,value,mode,options)
        token=uuid.uuid4().hex
        prior_manifest=lifecycle(self.translation.workspace,project_id).get('runtime_manifest')
        _,root=self.record(project_id)
        prior_hash=digest(self.source(root,prior_manifest)) if prior_manifest else ''
        preview={'token':token,'mode':mode,'projectId':project_id,'files':included,'blocked':blocked,'created':now(),
                 'priorManifest':prior_manifest,'priorManifestHash':prior_hash,
                 'selection':value['selection'],'receipt':options.get('receipt',''),'originalBinding':value['originals'].get('binding',''),
                 'manifest':WORK+'/publications/'+token+'/runtime-manifest.json'}
        self.previews[token]=deepcopy(preview)
        return preview

    def _publish_file(self, root, path, raw):
        target=project_path(root,path); mode=target.stat().st_mode & 0o777
        write_bytes(target,raw); target.chmod(mode)

    def publication_manifest(self, project_id, rows):
        _,root=self.record(project_id); state=lifecycle(self.translation.workspace,project_id)
        prior=state.get('runtime_manifest'); document=read_json(project_path(root,prior)) if prior else {'version':1,'files':{}}
        files=document.get('files')
        if isinstance(files,list): files={name:{} for name in files}
        if not isinstance(files,dict): raise ValueError("The reviewed runtime manifest is malformed.")
        files=deepcopy(files)
        for row in rows: files[row['path']]={**files.get(row['path'],{}),'sha256':row['afterHash'],'original_sha256':row['originalHash']}
        return {**document,'files':files}

    def publish(self, project_id, value, mode, options):
        self.translation.idle(project_id); self.translation.clean_drafts(project_id)
        token=options.get('token'); preview=self.previews.pop(token,None)
        if not preview or preview['projectId']!=project_id or preview['mode']!=mode: raise ValueError("This publication review expired or was already used.")
        if datetime.fromisoformat(preview['created'])<datetime.now(timezone.utc)-timedelta(minutes=20): raise ValueError("This publication review expired. Review the exact current batch again.")
        if not preview['files']: raise ValueError("The reviewed batch is empty. Nothing was published.")
        if preview['selection']!=value['selection']: raise ValueError("Selection changed after review.")
        included,blocked=self.checked_rows(project_id,value,mode,{'receipt':preview['receipt']})
        keys=('path','destination','beforeHash','afterHash','originalHash','candidate','candidateHash')
        if [{key:row[key] for key in keys} for row in included]!=[{key:row[key] for key in keys} for row in preview['files']]:
            raise ValueError("Source, scope, candidate or original changed after review. Review the exact batch again.")
        _,root=self.record(project_id); publication=deepcopy(preview); publication['id']=token
        prior_manifest=lifecycle(self.translation.workspace,project_id).get('runtime_manifest')
        prior_hash=digest(self.source(root,prior_manifest)) if prior_manifest else ''
        if prior_manifest!=preview['priorManifest'] or prior_hash!=preview['priorManifestHash']:
            raise ValueError("The reviewed runtime manifest changed. Review publication again.")
        frozen=[]
        for row in publication['files']:
            raw=self.source(root,row['path']); candidate=self.source(root,row['candidate'])
            if digest(raw)!=row['beforeHash'] or digest(candidate)!=row['afterHash']: raise ValueError("Files changed during whole-batch preflight.")
            write_bytes(project_path(root,row['backup'],exists=False),raw)
            name=WORK+'/publications/'+token+'/output/'+row['path']; write_bytes(project_path(root,name,exists=False),candidate)
            row['frozen']=name; frozen.append((row,candidate,raw))
        manifest=self.publication_manifest(project_id,publication['files'])
        write_json(project_path(root,preview['manifest'],exists=False),manifest)
        journal=self.path(project_id,'publications/'+token+'/approval.json'); write_json(journal,publication)
        authority=Path(self.translation.workspace)/'plugin-approvals'/project_id/(token+'.json')
        write_json(authority,{'journalHash':digest(publication),'projectId':project_id,'id':token})
        value['pending'].append(token); self.save(project_id,value)
        written=[]; failure=''; conflicts=[]
        try:
            for row,candidate,raw in frozen:
                if digest(self.source(root,row['path']))!=row['beforeHash']: raise ValueError("Runtime changed during publication: "+row['path'])
                written.append((row,raw)); self._publish_file(root,row['path'],candidate)
        except Exception as exc:
            failure=str(exc)
            for row,raw in reversed(written):
                try:
                    current=digest(self.source(root,row['path']))
                    if current==row['beforeHash']: continue
                    if current!=row['afterHash']: raise ValueError("File changed after publication; rollback left it untouched.")
                    self._publish_file(root,row['path'],raw)
                except Exception as rollback: conflicts.append(row['path']+': '+str(rollback))
        completed=[row for row,_,_ in frozen if digest(self.source(root,row['path']))==row['afterHash']]
        receipt={'id':token,'mode':mode,'saved':now(),'status':'complete' if not failure else 'partial' if completed else 'rolled_back',
                 'files':completed,'reviewedFiles':publication['files'],'manifest':preview['manifest'],'failure':failure,'conflicts':conflicts}
        self.finish(project_id,value,receipt)
        if failure: raise ValueError("Publication failed; rollback attempted. "+failure+(' Recovery conflicts: '+'; '.join(conflicts) if conflicts else ''))
        return {'receipt':receipt,'state':self.state(project_id),'completed':len(completed)}

    def finish(self, project_id, value, receipt):
        _,root=self.record(project_id)
        for row in receipt['files']:
            item=value['files'][row['path']]
            if receipt['mode']=='apply': item['applied']={'receipt':receipt['id'],'afterHash':row['afterHash']}
            else: item.pop('applied',None)
        if receipt['files']:
            # The exact paths feed the existing runtime manifest owner, including plugin-loaded JSON.
            state=lifecycle(self.translation.workspace,project_id); state['runtime_manifest']=receipt['manifest']
            if receipt['status']!='complete':
                write_json(project_path(root,receipt['manifest'],exists=False),self.publication_manifest(project_id,receipt['files']))
            write_json(lifecycle_path(self.translation.workspace,project_id),state)
        value['receipts'].append(receipt); value['pending']=[identity for identity in value['pending'] if identity!=receipt['id']]
        self.save(project_id,value)

    def approved_publication(self, project_id, identity):
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):
            raise ValueError("Malformed publication journal identity.")
        publication=read_json(self.path(project_id,'publications/'+identity+'/approval.json'))
        authority=read_json(Path(self.translation.workspace)/'plugin-approvals'/project_id/(identity+'.json'))
        if authority!={'journalHash':digest(publication),'projectId':project_id,'id':identity}:
            raise ValueError("Publication approval journal changed. No recovery receipt was manufactured.")
        return publication

    def recover(self, project_id, value):
        if not value['pending']: return
        _,root=self.record(project_id)
        for identity in list(value['pending']):
            publication=self.approved_publication(project_id,identity)
            completed,conflicts=[],[]
            for row in publication['files']:
                try:
                    if digest(self.source(root,row['backup']))!=row['beforeHash'] or digest(self.source(root,row['frozen']))!=row['afterHash']:
                        raise ValueError("Frozen publication/backup bytes changed")
                    current=digest(self.source(root,row['path']))
                    if current==row['afterHash']: completed.append(row)
                    elif current!=row['beforeHash']: conflicts.append(row['path']+': runtime differs from approved before/after bytes')
                except (ValueError,OSError) as exc: conflicts.append(row['path']+': '+str(exc))
            receipt={'id':identity,'mode':publication['mode'],'saved':now(),'status':'recovered' if not conflicts else 'conflict',
                     'files':completed,'reviewedFiles':publication['files'],'manifest':publication['manifest'],
                     'failure':'Interrupted publication reconciled from exact approved bytes; review recovery.','conflicts':conflicts}
            self.finish(project_id,value,receipt)
