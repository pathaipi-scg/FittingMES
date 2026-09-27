"""Press machine configuration backed by the existing history-aware SQL model."""
import logging
from app.lots import rows

CHANGED_BY = 'FittingMES'
logger = logging.getLogger(__name__)


def read_press_list(cursor):
    cursor.execute("""SELECT PressCode,PressName,DisplayOrder,IsActive,CurrentLine,CurrentLineName,LineAssignedAt
        FROM dbo.vw_PressMcPressList ORDER BY DisplayOrder,PressCode""")
    return rows(cursor)


def read_lines(cursor):
    cursor.execute("""SELECT EquipmentCode,EquipmentName,DisplayOrder FROM dbo.EquipmentMaster
        WHERE EquipmentType='LINE' AND IsActive=1 ORDER BY DisplayOrder,EquipmentCode""")
    return rows(cursor)


def read_capability_matrix(cursor, press_code):
    cursor.execute("""SELECT PressCode,PressName,CurrentLine,CurrentLineName,ProductFamily,
        ProductCode,ProductName,ProductNameTH,CanProduce
        FROM dbo.vw_PressMcCapabilityMatrix WHERE PressCode=?
        ORDER BY ProductFamily,ProductCode""", press_code)
    return rows(cursor)


def read_history(cursor, press_code):
    cursor.execute("""SELECT 'LINE' AS HistoryType,LineEquipmentCode AS Detail,
        ChangeType,EffectiveFrom AS OccurredAt,EffectiveTo,Remark,ChangedBy
        FROM dbo.EquipmentLineHistory WHERE PressEquipmentCode=?
        UNION ALL
        SELECT 'STATUS',CASE WHEN IsActive=1 THEN 'ACTIVE' ELSE 'INACTIVE' END,
        ChangeType,EffectiveFrom,EffectiveTo,Remark,ChangedBy
        FROM dbo.EquipmentStatusHistory WHERE EquipmentCode=?
        ORDER BY OccurredAt DESC""", press_code, press_code)
    return rows(cursor)


def page_context(cursor, selected_code=None):
    presses = read_press_list(cursor)
    lines = read_lines(cursor)
    selected = next((press for press in presses if press['PressCode'] == selected_code), None)
    if selected is None and presses:
        selected = presses[0]
    matrix = read_capability_matrix(cursor, selected['PressCode']) if selected else []
    groups = []
    for row in matrix:
        if not groups or groups[-1]['ProductFamily'] != row['ProductFamily']:
            groups.append(dict(ProductFamily=row['ProductFamily'], products=[]))
        groups[-1]['products'].append(row)
    history = read_history(cursor, selected['PressCode']) if selected else []
    return dict(presses=presses, lines=lines, selected=selected,
                capability_groups=groups, history=history)


def add_press(conn, press_code, press_name, line_code, remark):
    press_code = str(press_code or '').strip()
    press_name = str(press_name or '').strip()
    line_code = str(line_code or '').strip() or None
    remark = str(remark or '').strip()
    if not press_code or len(press_code) > 20:
        raise ValueError('Press Code is required (maximum 20 characters).')
    if not press_name or len(press_name) > 100:
        raise ValueError('Press Name is required (maximum 100 characters).')
    if len(remark) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ISNULL(MAX(DisplayOrder),0)+1 FROM dbo.vw_PressMcPressList")
        display_order = int(cursor.fetchone()[0])
        cursor.execute("""EXEC dbo.sp_Press_Add @PressCode=?,@PressName=?,@DisplayOrder=?,
            @LineCode=?,@ChangedBy=?,@Remark=?""",
            press_code, press_name, display_order, line_code, CHANGED_BY, remark)
        conn.commit()
        return press_code
    except Exception:
        conn.rollback()
        raise


def update_press_name(conn, press_code, press_name):
    press_name = str(press_name or '').strip()
    if not press_name or len(press_name) > 100:
        raise ValueError('Press Name is required (maximum 100 characters).')
    cursor = conn.cursor()
    cursor.execute("SELECT DisplayOrder FROM dbo.EquipmentMaster WHERE EquipmentCode=? AND EquipmentType='PRESS'", press_code)
    found = cursor.fetchone()
    if not found:
        raise ValueError('Press machine not found.')
    cursor.execute("EXEC dbo.sp_Press_UpdateInfo @PressCode=?,@PressName=?,@DisplayOrder=?",
                   press_code, press_name, found[0])
    conn.commit()


def assign_line(conn, press_code, line_code, remark):
    line_code = str(line_code or '').strip()
    remark = str(remark or '').strip()
    if not line_code:
        raise ValueError('Choose a Line or use Remove from Line.')
    if len(remark) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC dbo.sp_Press_AssignLine @PressCode=?,@LineCode=?,@ChangedBy=?,@Remark=?",
                       press_code, line_code, CHANGED_BY, remark)
        conn.commit()
    except Exception:
        logger.exception('Press Line assignment failed; rolling back press=%s line=%s',press_code,line_code)
        conn.rollback()
        raise


def remove_from_line(conn, press_code, remark):
    remark = str(remark or '').strip()
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC dbo.sp_Press_RemoveFromLine @PressCode=?,@ChangedBy=?,@Remark=?",
                       press_code, CHANGED_BY, remark)
        conn.commit()
    except Exception:
        logger.exception('Press Line removal failed; rolling back press=%s',press_code)
        conn.rollback()
        raise


def set_active(conn, press_code, is_active, remark):
    remark = str(remark or '').strip()
    cursor = conn.cursor()
    cursor.execute("EXEC dbo.sp_Press_SetActive @PressCode=?,@IsActive=?,@ChangedBy=?,@Remark=?",
                   press_code, bool(is_active), CHANGED_BY, remark)
    conn.commit()


def save_capabilities(conn, press_code, changes, remark=''):
    if not isinstance(changes, list):
        raise ValueError('Capability changes must be a list.')
    requested = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError('Invalid capability change.')
        family = str(change.get('ProductFamily') or '').strip()
        code = str(change.get('ProductCode') or '').strip()
        active = change.get('CanProduce')
        if not family or len(family) > 30 or not code or len(code) != 2 or not isinstance(active, bool):
            raise ValueError('Invalid Product capability selection.')
        identity = family, code
        if identity in seen:
            raise ValueError('Duplicate Product capability selection.')
        seen.add(identity)
        requested.append((family, code, active))
    if len(str(remark or '')) > 1000:
        raise ValueError('Remark must be at most 1000 characters.')
    try:
        cursor = conn.cursor()
        current_matrix = read_capability_matrix(cursor, press_code)
        current = {(row['ProductFamily'], row['ProductCode']): bool(row['CanProduce'])
                   for row in current_matrix}
        normalized = []
        for family, code, active in requested:
            key = family, code
            if key not in current:
                raise ValueError('The selected Product is not active in the Product master.')
            if current[key] != active:
                normalized.append((family, code, active))
        if not normalized:
            conn.commit()
            logger.info('Press capability save had no changes: press=%s requested=%s', press_code, len(requested))
            return 0
        logger.info('Press capability save: press=%s requested=%s changes=%s keys=%s',
                    press_code, len(requested), len(normalized),
                    [(family, code, active) for family, code, active in normalized])
        # pyodbc autocommit=False already has a connection-owned transaction
        # from the matrix read. The stored procedure uses BEGIN/COMMIT itself;
        # an extra BEGIN here would nest the transaction, leaving one level
        # open after conn.commit() and causing close() to roll the work back.
        for family, code, active in normalized:
            logger.info('Calling sp_SetPressProductCapability press=%s family=%s product=%s active=%s',
                        press_code, family, code, active)
            cursor.execute("""EXEC dbo.sp_SetPressProductCapability
                @PressEquipmentCode=?,@ProductFamily=?,@ProductCode=?,@IsActive=?,@Remark=?,@ChangedBy=?""",
                press_code, family, code, active, str(remark or '').strip(), CHANGED_BY)
        conn.commit()
        logger.info('Press capability save committed: press=%s changes=%s',press_code,len(normalized))
        return len(normalized)
    except Exception:
        logger.exception('Press capability save failed; rolling back press=%s',press_code)
        conn.rollback()
        raise
