"""Ephemeral RAM-backed snapshots for TraceCart's same-origin live graph stream.

SQLite remains the durable source of truth. Cache holds at most 24 job views,
signals invalidate only the relevant job and a Condition wakes listeners.
No GPU buffers exposed over HTTP and no untrusted source bytes in memory APIs.
"""
from collections import OrderedDict
from threading import Condition
from time import monotonic


class MemoryLiveGraphCache:
    def __init__(self, max_jobs=24):
        self.max_jobs=max_jobs
        self._lock=Condition()
        self._versions=OrderedDict()
        self._cache=OrderedDict()

    def signal(self, job_id):
        """Signal a real persisted change, never a fake completed finding."""
        with self._lock:
            self._versions[job_id]=self._versions.get(job_id,0)+1
            self._versions.move_to_end(job_id)
            # Retain revisions for recent sessions without permanent growth.
            while len(self._versions)>256:
                oldest=next(iter(self._versions))
                if oldest in self._cache:
                    self._versions.move_to_end(oldest)
                    if all(x in self._cache for x in self._versions):
                        break
                else:
                    self._versions.popitem(last=False)
            self._cache.pop(job_id,None)
            self._lock.notify_all()

    def snapshot(self, job_id, loader):
        """Cache the completed graph in RAM until the next worker update."""
        while True:
            with self._lock:
                rev=self._versions.get(job_id,0)
                cached=self._cache.get(job_id)
                if cached and cached[0]==rev:
                    self._cache.move_to_end(job_id)
                    return cached
            value=loader()  # No long-lived lock during SQLite+graph projection.
            with self._lock:
                if self._versions.get(job_id,0)!=rev:
                    # Worker changed state during build: recompute.
                    continue
                self._cache[job_id]=(rev,value)
                self._cache.move_to_end(job_id)
                while len(self._cache)>self.max_jobs:
                    self._cache.popitem(last=False)
                return rev,value

    def wait_change(self, job_id, version, timeout=12):
        deadline=monotonic()+max(0,min(20,float(timeout)))
        with self._lock:
            while self._versions.get(job_id,0)==version:
                remaining=deadline-monotonic()
                if remaining<=0:
                    break
                self._lock.wait(remaining)
            return self._versions.get(job_id,0)!=version

    def stats(self):
        with self._lock:
            return {"cached_jobs":len(self._cache),
                    "capacity":self.max_jobs,
                    "known_job_revisions":len(self._versions)}
