"""Explicit product-family identities; never infer a product from material text."""
import re

FAMILIES = (
    ('NeuFit / NeuStile', 'B'),
    ('Oriental', 'B'),
    ('Special Ridge', 'I'),
    ('Prestige Common', 'I'),
)
FAMILY_PREFIXES = dict(FAMILIES)


def lot_prefix(product_family, product_code, plan_date):
    if product_family not in FAMILY_PREFIXES or not re.fullmatch(r'[0-9]{2}', product_code or ''):
        raise ValueError('Select a valid ProductFamily and two-digit ProductCode.')
    return f"{FAMILY_PREFIXES[product_family]}{product_code}{(plan_date.year + 543) % 100:02d}{plan_date.month:02d}"


def month_start(plan_date):
    return plan_date.replace(day=1)


def read_products(cursor):
    cursor.execute("""SELECT ProductFamily,ProductCode,ProductName FROM dbo.ProductCodeMaster
        WHERE IsActive=1 ORDER BY ProductFamily,ProductCode""")
    return [dict(ProductFamily=r[0], ProductCode=r[1], ProductName=r[2]) for r in cursor.fetchall()]


def read_mapping(cursor, material_prefix):
    cursor.execute('SELECT ProductFamily,ProductCode FROM dbo.MaterialProductMap WHERE MaterialPrefix=?', material_prefix)
    mapped = cursor.fetchone()
    # Null family means legacy/unconfirmed: it is never usable for new lots.
    return (mapped[0], mapped[1]) if mapped and mapped[0] else None


def require_product(cursor, family, code):
    if family not in FAMILY_PREFIXES or not re.fullmatch(r'[0-9]{2}', code or ''):
        raise ValueError('Select exactly one active family/product.')
    cursor.execute("""SELECT ProductCode FROM dbo.ProductCodeMaster
        WHERE ProductFamily=? AND ProductCode=? AND IsActive=1""", family, code)
    if not cursor.fetchone():
        raise ValueError('The selected family/product is not available in the product master.')


def confirm_mapping(conn, material_prefix, family, code):
    from app.lots import lock_lots
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        require_product(cursor, family, code)
        cursor.execute("""SELECT ProductFamily,ProductCode FROM dbo.MaterialProductMap
            WITH (UPDLOCK,HOLDLOCK) WHERE MaterialPrefix=?""", material_prefix)
        existing = cursor.fetchone()
        if existing and existing[0]:
            if (existing[0], existing[1]) != (family, code):
                raise ValueError('This material was confirmed in another session. Refresh to use its mapping.')
        elif existing:
            # Only an explicit operator confirmation may resolve this legacy row.
            cursor.execute("""UPDATE dbo.MaterialProductMap SET ProductFamily=?,ProductCode=?,
                UpdatedAt=SYSDATETIME() WHERE MaterialPrefix=?""", family, code, material_prefix)
        else:
            cursor.execute("""INSERT INTO dbo.MaterialProductMap
                (MaterialPrefix,ProductFamily,ProductCode,UpdatedAt)
                VALUES (?,?,?,SYSDATETIME())""", material_prefix, family, code)
        conn.commit()
        return family, code
    except Exception:
        conn.rollback()
        raise


def selected_product(choices):
    selected = [(family, code) for (family, _), code in zip(FAMILIES, choices) if code]
    if len(selected) != 1:
        raise ValueError('Select exactly one product across the four families.')
    return selected[0]
