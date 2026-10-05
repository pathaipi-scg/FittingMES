"""Product-family lookup and mapping operations use ProductFamilyID as identity."""
import re


def read_families(cursor):
    cursor.execute("""SELECT ProductFamilyID,ProductFamily,LotPrefixLetter
        FROM dbo.ProductFamilyMaster ORDER BY ProductFamily""")
    return [dict(ProductFamilyID=row[0], ProductFamily=row[1], LotPrefixLetter=row[2])
            for row in cursor.fetchall()]


def lot_prefix(cursor, product_family_id, product_code, plan_date):
    if not isinstance(product_family_id, int) or product_family_id < 1 \
            or not re.fullmatch(r'[0-9]{2}', product_code or ''):
        raise ValueError('Select a valid Product Family ID and two-digit ProductCode.')
    cursor.execute('SELECT LotPrefixLetter FROM dbo.ProductFamilyMaster WHERE ProductFamilyID=?',
                   product_family_id)
    row = cursor.fetchone()
    if not row:
        raise ValueError('The selected Product Family is not available.')
    return f"{row[0]}{product_code}{(plan_date.year + 543) % 100:02d}{plan_date.month:02d}"


def month_start(plan_date):
    return plan_date.replace(day=1)


def read_products(cursor):
    cursor.execute("""SELECT pcm.ProductFamilyID,pf.ProductFamily,pcm.ProductCode,pcm.ProductName
        FROM dbo.ProductCodeMaster pcm
        JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=pcm.ProductFamilyID
        WHERE pcm.IsActive=1 ORDER BY pf.ProductFamily,pcm.ProductCode""")
    return [dict(ProductFamilyID=row[0], ProductFamily=row[1],
                 ProductCode=row[2], ProductName=row[3]) for row in cursor.fetchall()]


def read_mapping(cursor, material_prefix):
    cursor.execute("""SELECT ProductFamilyID,ProductCode
        FROM dbo.MaterialProductMap WHERE MaterialPrefix=?""", material_prefix)
    mapped = cursor.fetchone()
    return (mapped[0], mapped[1]) if mapped and mapped[0] is not None else None


def require_product(cursor, product_family_id, product_code):
    if not isinstance(product_family_id, int) or product_family_id < 1 \
            or not re.fullmatch(r'[0-9]{2}', product_code or ''):
        raise ValueError('Select exactly one active family/product.')
    cursor.execute("""SELECT pf.ProductFamily FROM dbo.ProductCodeMaster pcm
        JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=pcm.ProductFamilyID
        WHERE pcm.ProductFamilyID=? AND pcm.ProductCode=? AND pcm.IsActive=1""",
        product_family_id, product_code)
    row = cursor.fetchone()
    if not row:
        raise ValueError('The selected family/product is not available in the product master.')
    return row[0]


def confirm_mapping(conn, material_prefix, product_family_id, product_code, edit=False):
    from app.lots import lock_lots
    try:
        cursor = conn.cursor()
        lock_lots(cursor)
        require_product(cursor, product_family_id, product_code)
        cursor.execute('''SELECT m.ProductFamilyID,m.ProductCode,pf.ProductFamily
            FROM dbo.MaterialProductMap m WITH (UPDLOCK,HOLDLOCK)
            LEFT JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=m.ProductFamilyID
            WHERE m.MaterialPrefix=?''', material_prefix)
        existing = cursor.fetchone()
        cursor.execute('SELECT ProductFamily FROM dbo.ProductFamilyMaster WHERE ProductFamilyID=?',
                       product_family_id)
        family = cursor.fetchone()
        if not family:
            raise ValueError('The selected Product Family is no longer available.')
        family_name = family[0]
        if existing and existing[0] is not None:
            if (existing[0], existing[1]) != (product_family_id, product_code) and not edit:
                raise ValueError('This material was confirmed in another session. Refresh to use its mapping.')
            if (existing[0], existing[1]) != (product_family_id, product_code):
                cursor.execute("""INSERT INTO dbo.MaterialProductMapHistory
                    (MaterialPrefix,OldProductFamilyID,OldProductFamily,OldProductCode,
                     NewProductFamilyID,NewProductFamily,NewProductCode)
                    VALUES (?,?,?,?,?,?,?)""", material_prefix, existing[0], existing[2],
                               existing[1], product_family_id, family_name, product_code)
                cursor.execute("""UPDATE dbo.MaterialProductMap SET ProductFamilyID=?,
                    ProductFamily=?,ProductCode=?,UpdatedAt=SYSDATETIME() WHERE MaterialPrefix=?""",
                    product_family_id, family_name, product_code, material_prefix)
        elif existing:
            cursor.execute("""UPDATE dbo.MaterialProductMap SET ProductFamilyID=?,
                ProductFamily=?,ProductCode=?,UpdatedAt=SYSDATETIME() WHERE MaterialPrefix=?""",
                product_family_id, family_name, product_code, material_prefix)
        else:
            cursor.execute("""INSERT INTO dbo.MaterialProductMap
                (MaterialPrefix,ProductFamilyID,ProductFamily,ProductCode,UpdatedAt)
                VALUES (?,?,?,?,SYSDATETIME())""",
                material_prefix, product_family_id, family_name, product_code)
        conn.commit()
        return product_family_id, product_code
    except Exception:
        conn.rollback()
        raise


def selected_product(choices):
    selected = []
    for family_id, code in choices:
        if code:
            try:
                family_id = int(family_id)
            except (TypeError, ValueError):
                raise ValueError('Select a valid Product Family ID.') from None
            selected.append((family_id, str(code)))
    if len(selected) != 1:
        raise ValueError('Select exactly one product across the product families.')
    return selected[0]
