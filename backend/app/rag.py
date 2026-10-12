"""Real embeddings -> cosine nearest neighbors over signed-off, local, versioned demo guidelines."""
import hashlib, json, math, os, time

class Rag:
    def __init__(self, store, model_client, directory):
        self.store=store; self.model_client=model_client; self.directory=directory

    def reindex(self):
        import glob
        count=0
        paths=sorted(glob.glob(os.path.join(self.directory, '*.json')))
        if not paths: raise RuntimeError('No approved guideline documents found')
        for path in paths:
            with open(path,encoding='utf8') as f: doc=json.load(f)
            if doc.get('approved_for_demo') is not True or doc.get('clinical_use_approved') is not False:
                continue
            sid=doc['source_id']; text=doc['content']
            if not sid.startswith('DEMO-') or len(text)>5000: raise ValueError('Untrusted or oversized knowledge source')
            sha=hashlib.sha256(text.encode()).hexdigest()
            with self.store._lock:
                row=self.store.db.execute('SELECT sha256 FROM knowledge WHERE source_id=?',(sid,)).fetchone()
            if row and row['sha256']==sha: continue
            vec=self.model_client.embed(text)
            with self.store._lock:
                self.store.db.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET version=excluded.version,title=excluded.title,content=excluded.content,sha256=excluded.sha256,embedded_json=excluded.embedded_json,indexed_at=excluded.indexed_at',
                                      (sid,doc['version'],doc['title'],text,sha,json.dumps(vec),time.time()))
            count+=1
        return {'indexed':count,'approved_total':len(paths)}

    def retrieve(self, query, k=3):
        with self.store._lock:
            with self.store._lock:
                rows=self.store.db.execute('SELECT * FROM knowledge').fetchall()
        if not rows:
            self.reindex()
            rows=self.store.db.execute('SELECT * FROM knowledge').fetchall()
        q=self.model_client.embed(query[:600])
        def cosine(a,b):
            if len(a)!=len(b): return -1.0
            norm=math.sqrt(sum(x*x for x in a))*math.sqrt(sum(x*x for x in b))
            return sum(x*y for x,y in zip(a,b))/norm if norm else -1.0
        results=[]
        for r in rows:
            score=cosine(q,json.loads(r['embedded_json']))
            results.append({'source_id':r['source_id'],'title':r['title'],'version':r['version'],
                            'sha256':r['sha256'],'snippet':r['content'],'similarity':round(score,4)})
        results.sort(key=lambda r:r['similarity'],reverse=True)
        return results[:k]
