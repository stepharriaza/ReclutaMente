"""Corrige la FK de intento.id_postulacion para que apunte a core_postulacion.

La tabla ``intento`` es heredada y su llave foránea apuntaba a la tabla
``postulacion`` antigua, que está vacía. Django guarda las postulaciones en
``core_postulacion``, así que cualquier intento con postulación fallaba con
IntegrityError. Esta migración reapunta la FK a la tabla que realmente usa el
ORM, igual que ya se hizo con ``intento.id_persona`` -> ``core_persona``.
"""

from django.db import migrations


def fix_fk(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('intento')")
        if cursor.fetchone()[0] is None:
            return
        cursor.execute("SELECT to_regclass('core_postulacion')")
        if cursor.fetchone()[0] is None:
            return

        # Si la FK ya apunta a core_postulacion, no hay nada que hacer.
        cursor.execute(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'intento'::regclass
              AND contype = 'f'
              AND confrelid = to_regclass('core_postulacion')
              AND conkey = ARRAY[
                  (SELECT attnum FROM pg_attribute
                   WHERE attrelid = 'intento'::regclass
                     AND attname = 'id_postulacion')
              ]
            """
        )
        if cursor.fetchone():
            return

        # Eliminar la(s) FK existente(s) sobre la columna id_postulacion.
        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'intento'::regclass
              AND contype = 'f'
              AND conkey = ARRAY[
                  (SELECT attnum FROM pg_attribute
                   WHERE attrelid = 'intento'::regclass
                     AND attname = 'id_postulacion')
              ]
            """
        )
        for (nombre,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE intento DROP CONSTRAINT "{nombre}"')

        cursor.execute(
            """
            ALTER TABLE intento
            ADD CONSTRAINT intento_id_postulacion_fkey
            FOREIGN KEY (id_postulacion)
            REFERENCES core_postulacion(id)
            ON DELETE CASCADE
            DEFERRABLE INITIALLY DEFERRED
            """
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_fix_intento_respuesta_fks'),
    ]

    operations = [
        migrations.RunPython(fix_fk, migrations.RunPython.noop),
    ]
