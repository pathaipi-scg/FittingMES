"""Append-only Reject API send history."""
from app.lots import rows


def has_success(cursor, production_id):
    cursor.execute("SELECT 1 FROM dbo.RejectPISLog WHERE ProductionID=? AND Outcome='SUCCESS'", production_id)
    return cursor.fetchone() is not None


def latest_state(cursor, production_id):
    cursor.execute("""SELECT TOP (1) RejectPISLogID,ProductionID,LotNo,ProductionDate,
        RequestGroupID,FromOutputDetailID,HTTPStatus,Outcome,ErrorMessage,AttemptedAt,CreatedAt
        FROM dbo.RejectPISLog WHERE ProductionID=?
        ORDER BY AttemptedAt DESC,RejectPISLogID DESC""", production_id)
    found = cursor.fetchall()
    if not found:
        return None
    return dict(zip([column[0] for column in cursor.description], found[0]))


def latest_states(cursor, production_ids):
    production_ids = list(dict.fromkeys(production_ids))
    if not production_ids:
        return {}
    placeholders = ','.join('?' for _ in production_ids)
    cursor.execute(f"""WITH Ranked AS (
        SELECT RejectPISLogID,ProductionID,LotNo,ProductionDate,RequestGroupID,
            FromOutputDetailID,HTTPStatus,Outcome,ErrorMessage,AttemptedAt,CreatedAt,
            ROW_NUMBER() OVER (PARTITION BY ProductionID ORDER BY AttemptedAt DESC,RejectPISLogID DESC) AS rn
        FROM dbo.RejectPISLog WHERE ProductionID IN ({placeholders})
    ) SELECT RejectPISLogID,ProductionID,LotNo,ProductionDate,RequestGroupID,
        FromOutputDetailID,HTTPStatus,Outcome,ErrorMessage,AttemptedAt,CreatedAt
        FROM Ranked WHERE rn=1""", *production_ids)
    columns = [column[0] for column in cursor.description]
    return {row[1]: dict(zip(columns, row)) for row in cursor.fetchall()}


def read_history(cursor, production_id=None, request_group_id=None):
    clauses, params = [], []
    if production_id is not None:
        clauses.append('ProductionID=?')
        params.append(production_id)
    if request_group_id is not None:
        clauses.append('RequestGroupID=?')
        params.append(request_group_id)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    cursor.execute("""SELECT RejectPISLogID,ProductionID,LotNo,ProductionDate,
        RequestGroupID,FromOutputDetailID,RequestJSON,HTTPStatus,ResponseText,
        Outcome,ErrorMessage,AttemptedAt,CreatedAt FROM dbo.RejectPISLog""" + where +
                   ' ORDER BY AttemptedAt DESC,RejectPISLogID DESC', *params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def insert_attempts(conn, attempts):
    attempts = list(attempts)
    if not attempts:
        return
    cursor = conn.cursor()
    for attempt in attempts:
        cursor.execute("""INSERT INTO dbo.RejectPISLog
            (ProductionID,LotNo,ProductionDate,RequestGroupID,FromOutputDetailID,
             RequestJSON,HTTPStatus,ResponseText,Outcome,ErrorMessage,AttemptedAt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            attempt['ProductionID'], attempt['LotNo'], attempt['ProductionDate'],
            attempt['RequestGroupID'], attempt.get('FromOutputDetailID'),
            attempt.get('RequestJSON'), attempt.get('HTTPStatus'),
            attempt.get('ResponseText'), attempt['Outcome'], attempt.get('ErrorMessage'),
            attempt['AttemptedAt'])
