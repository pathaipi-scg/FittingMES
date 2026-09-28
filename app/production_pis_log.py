"""Append-only Production API send history."""
from app.lots import rows


def has_success(cursor, production_id):
    cursor.execute("""SELECT 1 FROM dbo.ProductionPISLog
        WHERE ProductionID=? AND Outcome='SUCCESS'""", production_id)
    return cursor.fetchone() is not None


def latest_state(cursor, production_id):
    cursor.execute("""SELECT TOP (1) PISLogID,ProductionID,LotNo,ProductionDate,
        ShiftCode,PlantCode,MachineCode,RequestGroupID,HTTPStatus,Outcome,
        ErrorMessage,AttemptedAt,CreatedAt
        FROM dbo.ProductionPISLog
        WHERE ProductionID=? ORDER BY AttemptedAt DESC,PISLogID DESC""", production_id)
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
        SELECT PISLogID,ProductionID,LotNo,ProductionDate,ShiftCode,PlantCode,
            MachineCode,RequestGroupID,HTTPStatus,Outcome,ErrorMessage,
            AttemptedAt,CreatedAt,
            ROW_NUMBER() OVER (PARTITION BY ProductionID ORDER BY AttemptedAt DESC,PISLogID DESC) AS rn
        FROM dbo.ProductionPISLog
        WHERE ProductionID IN ({placeholders})
    )
    SELECT PISLogID,ProductionID,LotNo,ProductionDate,ShiftCode,PlantCode,
        MachineCode,RequestGroupID,HTTPStatus,Outcome,ErrorMessage,AttemptedAt,CreatedAt
    FROM Ranked WHERE rn=1""", *production_ids)
    columns = [column[0] for column in cursor.description]
    return {row[1]: dict(zip(columns, row)) for row in cursor.fetchall()}


def read_history(cursor, production_id=None, request_group_id=None):
    clauses, parameters = [], []
    if production_id is not None:
        clauses.append('ProductionID=?')
        parameters.append(production_id)
    if request_group_id is not None:
        clauses.append('RequestGroupID=?')
        parameters.append(request_group_id)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    cursor.execute("""SELECT PISLogID,ProductionID,LotNo,ProductionDate,
        ShiftCode,PlantCode,MachineCode,RequestGroupID,RequestJSON,HTTPStatus,
        ResponseText,Outcome,ErrorMessage,AttemptedAt,CreatedAt
        FROM dbo.ProductionPISLog""" + where +
                   ' ORDER BY AttemptedAt DESC,PISLogID DESC', *parameters)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def insert_attempts(conn, attempts):
    attempts = list(attempts)
    if not attempts:
        return
    cursor = conn.cursor()
    for attempt in attempts:
        cursor.execute("""INSERT INTO dbo.ProductionPISLog
            (ProductionID,LotNo,ProductionDate,ShiftCode,PlantCode,MachineCode,
             RequestGroupID,RequestJSON,HTTPStatus,ResponseText,Outcome,ErrorMessage,AttemptedAt)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            attempt['ProductionID'], attempt['LotNo'], attempt['ProductionDate'],
            attempt.get('ShiftCode'), attempt.get('PlantCode'), attempt.get('MachineCode'),
            attempt['RequestGroupID'], attempt.get('RequestJSON'), attempt.get('HTTPStatus'),
            attempt.get('ResponseText'), attempt['Outcome'], attempt.get('ErrorMessage'),
            attempt['AttemptedAt'])
