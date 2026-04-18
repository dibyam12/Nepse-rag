import psycopg2
conn = psycopg2.connect('postgresql://neondb_owner:npg_Gmn2i1rwNsbe@ep-rough-fire-a18ou8fq-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require')
cur = conn.cursor()
cur.execute("SELECT category, COUNT(*) FROM stocks_stockdata GROUP BY category;")
print(cur.fetchall())
