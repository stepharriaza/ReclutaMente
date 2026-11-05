"""Corrige las FK de core_analisisia y core_certificado para que apunten a intento.

Las tablas ``core_analisisia`` y ``core_certificado`` son las que usa el ORM
para los modelos ``AnalisisIA`` y ``Certificado``, pero sus llaves foráneas
apuntaban a ``core_intento``, una tabla heredada que está prácticamente vacía.
Los intentos reales se guardan en la tabla ``intento`` (modelo ``Intento``,
PK ``id_intento``), así que cualquier análisis o certificado fallaba con
IntegrityError. Esta migración reapunta esas FK a la tabla correcta, siguiendo
el mismo patrón idempotente de la migración 0014.
"""

from django.db import migrations


def _remap_fk(cursor, table, column, old_ref, new_ref, new_column, new_constraint):
    """Reapunta la FK de ``table.column`` de ``old_ref`` a ``new_ref``."""
    cursor.execute("SELECT to_regclass(%s)", [table])
    if cursor.fetchone()[0] is None:
        return
    cursor.execute("SELECT to_regclass(%s)", [old_ref])
    if cursor.fetchone()[0] is None:
        return
    cursor.execute("SELECT to_regclass(%s)", [new_ref])
    if cursor.fetchone()[0] is None:
        return

    # Si la FK ya apunta a la tabla correcta, no hay nada que hacer.
    cursor.execute(
        """
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = %s::regclass
          AND contype = 'f'
          AND confrelid = to_regclass(%s)
          AND conkey = ARRAY[
              (SELECT attnum FROM pg_attribute
               WHERE attrelid = %s::regclass
                 AND attname = %s)
          ]
        """,
        [table, new_ref, table, column],
    )
    if cursor.fetchone():
        return

    # Eliminar la(s) FK existente(s) sobre la columna.
    cursor.execute(
        """
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = %s::regclass
          AND contype = 'f'
          AND conkey = ARRAY[
              (SELECT attnum FROM pg_attribute
               WHERE attrelid = %s::regclass
                 AND attname = %s)
          ]
        """,
        [table, table, column],
    )
    for (nombre,) in cursor.fetchall():
        cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{nombre}"')

    cursor.execute(
        f'ALTER TABLE {table} ADD CONSTRAINT "{new_constraint}" '
        f'FOREIGN KEY ({column}) REFERENCES {new_ref}({new_column}) '
        f'ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED'
    )


def fix_fks(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        _remap_fk(
            cursor,
            'core_analisisia',
            'intento_id',
            'core_intento',
            'intento',
            'id_intento',
            'core_analisisia_intento_id_fk_intento',
        )
        _remap_fk(
            cursor,
            'core_certificado',
            'intento_id',
            'core_intento',
            'intento',
            'id_intento',
            'core_certificado_intento_id_fk_intento',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_fix_intento_postulacion_fk'),
    ]

    operations = [
        migrations.RunPython(fix_fks, migrations.RunPython.noop),
    ]
