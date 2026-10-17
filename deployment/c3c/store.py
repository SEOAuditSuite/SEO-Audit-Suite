"""Bounded durable queue shared by unprivileged controller and external agent.

No commands, image IDs, runtime arguments or credentials are accepted from jobs.
The deployment must enforce filesystem quotas/ACLs independently.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time


class Busy(RuntimeError):pass
class Missing(LookupError):pass


class Store:
    def __init__(self,path,queue_limit=2):
        self.path=Path(path);self.queue_limit=queue_limit
        if self.path.is_symlink() or self.path.parent.is_symlink():raise ValueError('Symlink state rejected')
        if not 1<=queue_limit<=4:raise ValueError('Invalid queue capacity')
        with self.connect() as db:
            db.executescript('''
            PRAGMA page_size=4096;
            PRAGMA max_page_count=16384;
            PRAGMA journal_mode=DELETE;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, envelope TEXT NOT NULL,
              created REAL NOT NULL, status TEXT NOT NULL, cancel INTEGER DEFAULT 0,
              result TEXT, finished REAL);
            CREATE TABLE IF NOT EXISTS requests (owner TEXT, nonce TEXT, created REAL,
              PRIMARY KEY(owner,nonce));
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=1)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA max_page_count=16384')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def consume_request(self,owner,nonce,now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM requests WHERE created < ?',(now-120,))
            if db.execute('SELECT count(*) FROM requests').fetchone()[0]>=4096:raise Busy('Authentication capacity exhausted')
            count=db.execute('SELECT count(*) FROM requests WHERE owner=? AND created>=?',(owner,now-60)).fetchone()[0]
            if count>=60:raise Busy('Owner request rate exceeded')
            try:db.execute('INSERT INTO requests VALUES (?,?,?)',(owner,nonce,now))
            except sqlite3.IntegrityError:raise ValueError('Request replay rejected') from None

    def admit(self,envelope,now=None):
        now=time.time() if now is None else now;job=envelope['job']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM jobs WHERE finished IS NOT NULL AND finished<?',(now-86400,))
            if db.execute("SELECT 1 FROM meta WHERE key='blocked'").fetchone():raise Busy('Admission quarantined')
            queued=db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]
            if queued>=self.queue_limit:raise Busy('Queue is full')
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0]>=32:raise Busy('Evidence retention capacity exhausted')
            stored=db.execute('SELECT coalesce(sum(length(result)),0) FROM jobs').fetchone()[0]
            outstanding=db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')").fetchone()[0]
            if stored+(outstanding+1)*8*1024*1024>48*1024*1024:raise Busy('Evidence storage reservation unavailable')
            try:db.execute('INSERT INTO jobs (id,owner,envelope,created,status) VALUES (?,?,?,?,?)',
                           (job['nonce'],job['owner'],json.dumps(envelope),now,'queued'))
            except sqlite3.IntegrityError:raise ValueError('Job replay rejected') from None
        return job['nonce']

    def read(self,ident,owner):
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise Missing()
        with self.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(ident,owner)).fetchone()
        if row is None:raise Missing('Job unavailable')
        return dict(row)

    def cancel(self,ident,owner):
        self.read(ident,owner)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET cancel=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE 'cancelling' END,finished=CASE WHEN status='queued' THEN ? ELSE NULL END WHERE id=? AND owner=? AND status IN ('queued','running','cancelling')",(time.time(),ident,owner))
        return self.read(ident,owner)

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM meta WHERE key='blocked'").fetchone():return None
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancelling')").fetchone():return None
            row=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:return None
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(row['id'],))
            return dict(row)

    def cancelled(self,ident):
        with self.connect() as db:
            row=db.execute('SELECT cancel FROM jobs WHERE id=?',(ident,)).fetchone()
        return row is None or bool(row[0])

    def finish(self,ident,result):
        raw=json.dumps(result,separators=(',',':'))
        if len(raw.encode())>8*1024*1024:raise Busy('Result exceeds reserved storage')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT cancel FROM jobs WHERE id=?',(ident,)).fetchone()
            if row is None:raise Missing()
            status=result.get('status','incomplete')
            if result.get('cleanup_confirmed') is not True:
                status='NOT VERIFIED'
                db.execute("INSERT OR REPLACE INTO meta VALUES ('blocked','Cleanup confirmation required')")
                result=dict(status=status,http_status=None,files={},reason='Cleanup confirmation required')
            elif row[0]:status='cancelled'
            db.execute('UPDATE jobs SET status=?,result=?,finished=? WHERE id=?',
                       (status,json.dumps(result,separators=(',',':')),time.time(),ident))

    def reconcile_startup(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancelling')").fetchone():
                db.execute("INSERT OR REPLACE INTO meta VALUES ('blocked','Interrupted operation; independent reconciliation required')")

    def clear_quarantine(self):
        # Only the trusted external agent calls this after native no-survivor proof.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='NOT VERIFIED',finished=? WHERE status IN ('running','cancelling')",(time.time(),))
            db.execute("DELETE FROM meta WHERE key='blocked'")
