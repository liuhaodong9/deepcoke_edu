"""数据库连接 - 从 MySQL 读取煤样数据"""

import pymysql

DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "123456"
DB_NAME = "coaldata"


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8", cursorclass=pymysql.cursors.DictCursor,
    )


def get_all_coals() -> list[dict]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, coal_name, coal_type, coal_price,
                       coal_mad, coal_ad, coal_vdaf, coal_std,
                       G, X, Y,
                       coke_CRI, coke_CSR, coke_M10, coke_M25, coke_M40
                FROM coaldata_table
                WHERE coal_name IS NOT NULL
                  AND G IS NOT NULL
                  AND coke_CRI IS NOT NULL
                ORDER BY coal_name
            """)
            return cur.fetchall()
    finally:
        conn.close()
