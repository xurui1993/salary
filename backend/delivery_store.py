"""Flat user-facing deliveries; durable internal indexes preserve artifact identity."""
from contextlib import contextmanager
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid

LOCK = threading.RLock()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def leaf(value):
    text = str(value)
    if not text or Path(text).name != text or any(c in text for c in '/\\:\x00\r\n') or text in ('.','..'):
        raise ValueError('交付文件名无效')
    return text


class DeliveryStore:
    def __init__(self, database, root):
        self.path = Path(database).resolve()
        self.private = self.path.parent / 'delivery_internal'
        self.root = Path(root).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS deliveries(key TEXT PRIMARY KEY, folder TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts(run_id TEXT, file_id TEXT, task_key TEXT, path TEXT, sha256 TEXT, bytes INTEGER,
                PRIMARY KEY(run_id,file_id));
                CREATE TABLE IF NOT EXISTS moves(id TEXT PRIMARY KEY, source TEXT, destination TEXT, sha256 TEXT, bytes INTEGER, committed INTEGER DEFAULT 0);''')
            if 'root' not in {row[1] for row in db.execute('PRAGMA table_info(deliveries)')}:
                db.execute('ALTER TABLE deliveries ADD COLUMN root TEXT')
                for row in db.execute('SELECT key,folder FROM deliveries').fetchall():
                    db.execute('UPDATE deliveries SET root=? WHERE key=?',(str(Path(row['folder']).parent),row['key']))
            if 'include_manifest' not in {row[1] for row in db.execute('PRAGMA table_info(deliveries)')}:
                db.execute('ALTER TABLE deliveries ADD COLUMN include_manifest INTEGER NOT NULL DEFAULT 1')

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def directory(self, key):
        with self.db() as db:
            row = db.execute('SELECT folder,root FROM deliveries WHERE key=?', (key,)).fetchone()
        if not row:return None
        folder=Path(row['folder'])
        if not Path(row['root']).is_absolute() or folder.parent != Path(row['root']) or folder.resolve()!=folder or folder.is_symlink():
            raise ValueError('交付目录无效')
        return folder

    def location(self, run_id, file_id):
        with self.db() as db:
            row = db.execute('SELECT a.*,d.folder FROM artifacts a JOIN deliveries d ON d.key=a.task_key WHERE run_id=? AND file_id=?', (run_id,file_id)).fetchone()
            if row is None:
                # A publication interrupted between rename and index commit is
                # still readable by its original entry via the durable move log.
                return None
        path = Path(row['path'])
        allowed = (self.directory(row['task_key']), self.private.resolve())
        if path.is_symlink() or path.resolve() != path or not any(path.is_relative_to(root) for root in allowed):
            raise ValueError('交付文件位置无效')
        return path

    def relocated(self, original):
        with self.db() as db:
            rows = db.execute('SELECT destination,sha256,bytes FROM moves WHERE source=? ORDER BY rowid DESC',(str(original),)).fetchall()
            keys=[row[0] for row in db.execute('SELECT key FROM deliveries')]
        allowed=tuple(self.directory(key) for key in keys)+(self.private.resolve(),)
        for row in rows:
            path = Path(row['destination'])
            if path.resolve()==path and any(path.is_relative_to(root) for root in allowed) and path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes'] and digest(path) == row['sha256']:
                return path
        return None

    def publish(self, key, created, label, files, incomplete=(), move=True, include_manifest=False,
                sequence_collision=False):
        """Verify first; journal every rename. Unregistered files are never overwritten."""
        from download_archive import archive_component, beijing_time
        with LOCK:
            folder = self.directory(key)
            if folder is None:
                if isinstance(created,str):
                    parsed=dt.datetime.fromisoformat(created.replace('Z','+00:00'))
                    created=parsed.astimezone() if parsed.tzinfo is None else parsed
                moment = beijing_time(created)
                title = archive_component(label[:65])
                short=key.split(':')[-1][:6].upper()
                # 成品按任务创建日期（北京时间 YYMMDD）分目录；已登记的历史目录保持原位。
                dated_root = self.root / f'{moment:%y%m%d}'
                folder = dated_root / title
                if folder.exists() or folder.is_symlink():
                    if sequence_collision:
                        suffix = 2
                        while True:
                            candidate = dated_root / f'{title}_{suffix}'
                            if not candidate.exists() and not candidate.is_symlink():
                                folder = candidate
                                break
                            suffix += 1
                    else:
                        # 同名任务重跑时追加生成时间与短编号，绝不写入未登记目录。
                        folder = dated_root / f'{title}_{moment:%Y%m%d-%H%M%S}_{short}'
                        if folder.exists() or folder.is_symlink():
                            raise ValueError('交付目录已存在且未登记，未覆盖')
                folder.mkdir(parents=True)
                with self.db() as db:
                    db.execute('INSERT INTO deliveries (key,folder,root) VALUES (?,?,?)', (key,str(folder),str(dated_root)))
            if folder.resolve() != folder or folder.is_symlink():
                raise ValueError('交付目录无效')
            # Prepare the complete set before touching any source file.
            prepared, used = [], set()
            for entry in files:
                entry = dict(entry)
                original = Path(entry['path'])
                source = original.resolve()
                if not source.is_file() or original.is_symlink() or source != original.absolute():
                    raise ValueError('交付来源文件不存在')
                checksum = entry.get('sha256') or digest(source)
                length = entry.get('bytes', source.stat().st_size)
                if source.stat().st_size != length or digest(source) != checksum:
                    raise ValueError('交付来源校验失败，原文件保留')
                name = leaf(entry.get('name') or source.name)
                city = entry.get('city','')
                if city == '多城市汇总':
                    name = name.replace('多城市汇总','汇总_',1)
                elif city and city not in name and entry.get('dataset') not in ('rider_daily', 'rider_archive',
                                                                                 'rider_order_detail',
                                                                                 'xiaoxiang_attendance_detail'):
                    # 日维度骑手分析/灯塔骑手档案按「名称+日期」交付，不额外加城市前缀。
                    name = archive_component(city) + '_' + name
                if name.casefold() in used:
                    name = f"{Path(name).stem}_{entry['run_id'][:6]}_{entry['id'][:6]}{Path(name).suffix}"
                used.add(name.casefold())
                target = folder / leaf(name)
                prepared.append((entry,source,target,checksum,length))
            desired = {(e['run_id'],e['id']) for e,_,_,_,_ in prepared}
            with self.db() as db:
                old = [dict(r) for r in db.execute('SELECT * FROM artifacts WHERE task_key=?',(key,))]
            known={Path(row['path']):row for row in old}
            for entry,source,target,checksum,length in prepared:
                if target.exists() and target!=source:
                    prior=known.get(target)
                    if prior is None or target.stat().st_size!=prior['bytes'] or digest(target)!=prior['sha256']:
                        raise ValueError('目标文件未登记或已被修改，原文件保留')
            # Superseded artifacts remain retrievable from processing history.
            for entry in old:
                if (entry['run_id'],entry['file_id']) in desired:
                    continue
                source = Path(entry['path'])
                if source.is_relative_to(folder) and source.is_file():
                    if source.stat().st_size!=entry['bytes'] or digest(source)!=entry['sha256']:
                        raise ValueError('原交付文件已被修改，未移动')
                    identity=hashlib.sha256((entry['run_id']+'\0'+entry['file_id']).encode()).hexdigest()[:20]
                    retired = self.private / 'history' / hashlib.sha256(key.encode()).hexdigest() / (identity+'_'+source.name)
                    retired.parent.mkdir(parents=True,exist_ok=True)
                    if not retired.exists():
                        self._transfer(source,retired,entry['sha256'],entry['bytes'],True)
                    with self.db() as db:
                        db.execute('UPDATE artifacts SET path=? WHERE run_id=? AND file_id=?',(str(retired),entry['run_id'],entry['file_id']))
            for entry,source,target,checksum,length in prepared:
                registered = self.location(entry['run_id'],entry['id'])
                if target.exists() and target == registered and digest(target) != checksum:
                    with self.db() as db:
                        prior=db.execute('SELECT sha256,bytes FROM artifacts WHERE run_id=? AND file_id=?',(entry['run_id'],entry['id'])).fetchone()
                    if digest(target)!=prior['sha256']:
                        raise ValueError('原交付文件已被修改，未覆盖')
                    retired=self.private/'history'/hashlib.sha256(key.encode()).hexdigest()/(prior['sha256'][:12]+'_'+target.name)
                    retired.parent.mkdir(parents=True,exist_ok=True)
                    self._transfer(target,retired,prior['sha256'],prior['bytes'],True)
                    with self.db() as db:
                        db.execute('UPDATE artifacts SET path=? WHERE run_id=? AND file_id=?',(str(retired),entry['run_id'],entry['id']))
                if target.exists() and target != registered and target != source:
                    raise ValueError('同名交付文件未登记，原文件保留')
                if target.exists():
                    if target.stat().st_size != length or digest(target) != checksum:
                        raise ValueError('交付文件已变化，未覆盖')
                elif source != target:
                    self._transfer(source,target,checksum,length,move)
                with self.db() as db:
                    db.execute('INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)',
                               (entry['run_id'],entry['id'],key,str(target),checksum,length))
            if include_manifest:
                temporary = folder / ('.清单_' + uuid.uuid4().hex + '.tmp')
                with temporary.open('w',encoding='utf-8-sig',newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['任务','城市','资料','范围开始','范围结束','文件','字节数','SHA256'])
                    for entry,_,target,checksum,length in prepared:
                        from download_archive import artifact_scope
                        writer.writerow([key,entry.get('city',''),entry.get('dataset',''),*artifact_scope(entry),target.name,length,checksum])
                    for item in incomplete:
                        writer.writerow([key,item.get('city',''),item.get('dataset',''),item.get('start',''),item.get('end',''),'未生成：'+item.get('status','未完成'),'',''])
                os.replace(temporary,folder/'文件清单.csv')
            with self.db() as db:
                db.execute('UPDATE deliveries SET include_manifest=? WHERE key=?',(int(include_manifest),key))
            return folder

    def _transfer(self, source, target, checksum, length, move):
        if source.is_symlink() or source.stat().st_size!=length or digest(source)!=checksum:
            raise ValueError('转移前文件校验失败')
        transaction = uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO moves VALUES (?,?,?,?,?,0)',(transaction,str(source),str(target),checksum,length))
        if move:
            # Workspaces and delivery folders normally share a disk. A cross-disk
            # copy is verified before the original is removed.
            try:
                os.replace(source,target)
            except OSError:
                if target.exists():
                    raise
                shutil.copy2(source,target)
                if digest(target) != checksum or target.stat().st_size != length:
                    raise ValueError('交付复制校验失败，原文件保留')
                source.unlink()
        else:
            shutil.copy2(source,target)
        if target.stat().st_size != length or digest(target) != checksum:
            raise ValueError('交付校验失败')
        with self.db() as db:
            db.execute('UPDATE moves SET committed=1 WHERE id=?',(transaction,))


def project_store():
    from download_jobs import ROOT, configured_output_root
    return DeliveryStore(ROOT/'backend/.local_downloads/deliveries.sqlite3',configured_output_root())


def external_delivery(key, created, label, output, move=True, store=None):
    source = Path(output).resolve()
    candidates = sorted(source.rglob('*')) if source.is_dir() else [source]
    files = [path for path in candidates if path.is_file() and not path.is_symlink() and path.suffix.lower() in ('.xlsx','.xls','.csv') and not path.name.startswith('.')]
    if not files and source.is_file():
        files=[source]
    entries=[dict(run_id=key,id=hashlib.sha256(str(path.relative_to(source) if source.is_dir() else path.name).encode()).hexdigest(),
                  path=str(path),name=path.name,city='',dataset=label) for path in files]
    if not entries:
        raise ValueError('尚无可交付的结果文件')
    return (store or project_store()).publish(key,created,label,entries,move=move)


def approval_delivery(manager, scope, key, store=None):
    """Serialize an existing approval receipt. Does not send an approval."""
    if store is None:
        from lanorange_approvals import ROOT
        store=project_store() if manager.path.resolve()==ROOT.resolve() else DeliveryStore(manager.path.parent/'deliveries.sqlite3',manager.path.parent/'deliveries')
    batch=manager.batch(scope,key)
    content=manager.export(scope,key)
    base=store.private/'staging';base.mkdir(parents=True,exist_ok=True)
    path=base/(uuid.uuid4().hex+'.csv');path.write_bytes(content)
    try:
        folder=store.publish('approval:'+key,dt.datetime.fromtimestamp(batch['created'],dt.timezone.utc),
            '蓝橙_价格审批回执',[dict(run_id='approval:'+key,id='result',path=str(path),name='蓝橙_价格审批回执.csv',dataset='价格审批',city='')])
        return folder/'蓝橙_价格审批回执.csv'
    finally:
        path.unlink(missing_ok=True)


def delivery_bundle(store, key):
    import tempfile
    import zipfile
    import io
    folder=store.directory(key)
    if folder is None:
        raise ValueError('本任务尚无结果目录')
    with store.db() as db:
        include_manifest = db.execute('SELECT include_manifest FROM deliveries WHERE key=?',(key,)).fetchone()[0]
        rows=[dict(row) for row in db.execute('SELECT * FROM artifacts WHERE task_key=? ORDER BY path',(key,)) if Path(row['path']).parent==folder]
    if not rows:
        raise ValueError('本任务没有可领取文件')
    base=store.private/'bundles';base.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(suffix='.zip',dir=base);os.close(handle)
    target=Path(name)
    try:
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            table=io.StringIO(newline='');writer=csv.writer(table);writer.writerow(['任务','文件','字节数','SHA256'])
            for row in rows:
                source=store.location(row['run_id'],row['file_id'])
                if not source or not source.is_file() or source.stat().st_size!=row['bytes'] or digest(source)!=row['sha256']:
                    raise ValueError('结果文件已变化或不存在，请检查任务目录')
                checksum=hashlib.sha256();length=0
                with source.open('rb') as original,archive.open(source.name,'w',force_zip64=True) as output:
                    while chunk:=original.read(1024*1024):
                        output.write(chunk);checksum.update(chunk);length+=len(chunk)
                if length!=row['bytes'] or checksum.hexdigest()!=row['sha256']:
                    raise ValueError('打包期间结果文件发生变化')
                writer.writerow([key,source.name,row['bytes'],row['sha256']])
            if include_manifest:archive.writestr('文件清单.csv',table.getvalue().encode('utf-8-sig'))
        return target,folder.name+'.zip'
    except BaseException:
        target.unlink(missing_ok=True)
        raise
