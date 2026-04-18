import psycopg2
conn = psycopg2.connect('postgresql://neondb_owner:npg_Gmn2i1rwNsbe@ep-rough-fire-a18ou8fq-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require')
cur = conn.cursor()
cur.execute("SELECT symbol, date, open, high, low, close, volume FROM stocks_stockdata WHERE category='stock' AND symbol='NABIL' ORDER BY date DESC LIMIT 5;")
print(cur.fetchall())
