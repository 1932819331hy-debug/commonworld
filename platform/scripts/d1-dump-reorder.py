import sqlite3,sys
src,dst=sys.argv[1],sys.argv[2]
db=sqlite3.connect(':memory:'); db.executescript(open(src).read())
objs=db.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'").fetchall()
out=["PRAGMA defer_foreign_keys = true;"]
tables=[o for o in objs if o[0]=='table']
for t in tables: out.append(o:=t[2]+';')
for _,name,_ in tables:
    cols=[r[1] for r in db.execute(f'PRAGMA table_info("{name}")')]
    for row in db.execute(f'SELECT * FROM "{name}"'):
        vals=[]
        for v in row:
            if v is None: vals.append('NULL')
            elif isinstance(v,(int,float)): vals.append(repr(v))
            elif isinstance(v,bytes): vals.append("X'"+v.hex()+"'")
            else: vals.append("'"+v.replace("'","''")+"'")
        out.append(f'INSERT INTO "{name}" ({",".join(chr(34)+c+chr(34) for c in cols)}) VALUES({",".join(vals)});')
for o in objs:
    if o[0] in ('index','trigger','view'): out.append(o[2]+';')
open(dst,'w').write("\n".join(out)+"\n")
print(len(tables),"tables", sum(1 for l in out if l.startswith('INSERT')),"rows")
