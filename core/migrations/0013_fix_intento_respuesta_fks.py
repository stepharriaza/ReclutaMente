from django.db import migrations


def _remap_fk(cursor, table, column, old_ref, new_ref, new_column, new_constraint):
    cursor.execute("SELECT to_regclass(%s)", [old_ref])
    if cursor.fetchone()[0] is None:
        return

    cursor.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND contype = 'f' "
        "AND confrelid = to_regclass(%s)",
        [table, old_ref],
    )
    row = cursor.fetchone()
    if not row:
        return

    cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {row[0]}')
    cursor.execute(
        f'ALTER TABLE {table} ADD CONSTRAINT {new_constraint} '
        f'FOREIGN KEY ({column}) REFERENCES {new_ref}({new_column}) '
        f'DEFERRABLE INITIALLY DEFERRED'
    )


def fix_fks(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    with schema_editor.connection.cursor() as cursor:
        _remap_fk(
            cursor,
            'core_intento',
            'test_id',
            'core_test',
            'test',
            'id_test',
            'core_intento_test_id_fk_test',
        )
        _remap_fk(
            cursor,
            'core_respuesta',
            'pregunta_id',
            'core_pregunta',
            'pregunta',
            'id_pregunta',
            'core_respuesta_pregunta_id_fk_pregunta',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_alter_intento_postulacion'),
    ]

    operations = [
        migrations.RunPython(fix_fks, migrations.RunPython.noop),
    ]
