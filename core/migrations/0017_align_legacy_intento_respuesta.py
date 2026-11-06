"""Alinea las tablas heredadas ``intento`` y ``respuesta`` con los modelos.

En produccion el esquema es heredado y ya usa los nombres ``intento`` /
``respuesta`` con columnas como ``id_intento`` e ``id_persona``. En una base
nueva, en cambio, las migraciones iniciales crean ``core_intento`` /
``core_respuesta`` con nombres que no coinciden con los modelos, por lo que
cualquier consulta del ORM falla con ``no such table: intento``.

Esta migracion actualiza el estado de Django con los cambios que faltaban y,
en la base de datos, renombra tablas/columnas solo cuando es necesario. Asi
funciona tanto en una base nueva (tests) como en la base heredada existente.
"""

import django.db.models.deletion
from django.db import migrations, models


def _table_exists(connection, table):
    return table in connection.introspection.table_names()


def _table_columns(connection, table):
    with connection.cursor() as cursor:
        return {
            column.name
            for column in connection.introspection.get_table_description(cursor, table)
        }


def _rename_table(connection, cursor, old, new):
    if _table_exists(connection, old) and not _table_exists(connection, new):
        cursor.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')


def _rename_column(connection, cursor, table, old, new):
    columns = _table_columns(connection, table)
    if old in columns and new not in columns:
        cursor.execute(
            f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'
        )


def align_legacy_schema(apps, schema_editor):
    connection = schema_editor.connection
    vendor = connection.vendor

    with connection.cursor() as cursor:
        _rename_table(connection, cursor, 'core_intento', 'intento')
        if _table_exists(connection, 'intento'):
            _rename_column(connection, cursor, 'intento', 'id', 'id_intento')
            _rename_column(connection, cursor, 'intento', 'persona_id', 'id_persona')
            _rename_column(connection, cursor, 'intento', 'test_id', 'id_test')
            _rename_column(connection, cursor, 'intento', 'postulacion_id', 'id_postulacion')
            _rename_column(connection, cursor, 'intento', 'duracion_minutos', 'duracion')

        _rename_table(connection, cursor, 'core_respuesta', 'respuesta')
        if _table_exists(connection, 'respuesta'):
            _rename_column(connection, cursor, 'respuesta', 'id', 'id_respuesta')
            _rename_column(connection, cursor, 'respuesta', 'intento_id', 'id_intento')
            _rename_column(connection, cursor, 'respuesta', 'pregunta_id', 'id_pregunta')

        # En PostgreSQL una base creada desde cero deja ``fecha`` como date;
        # el modelo actual usa DateTimeField. En produccion ya es timestamp.
        if vendor == 'postgresql':
            cursor.execute(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'intento' AND column_name = 'fecha'
                """
            )
            row = cursor.fetchone()
            if row and row[0] == 'date':
                cursor.execute(
                    'ALTER TABLE intento ALTER COLUMN fecha '
                    'TYPE timestamp with time zone '
                    'USING fecha::timestamp with time zone'
                )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_remove_intento_duracion_minutos_certificado_analisis_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='intento',
                    name='duracion_minutos',
                ),
                migrations.AddField(
                    model_name='intento',
                    name='duracion',
                    field=models.PositiveIntegerField(blank=True, db_column='duracion', null=True),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='fecha',
                    field=models.DateTimeField(auto_now_add=True),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='id',
                    field=models.AutoField(db_column='id_intento', primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='persona',
                    field=models.ForeignKey(db_column='id_persona', on_delete=django.db.models.deletion.CASCADE, related_name='intentos', to='core.persona'),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='postulacion',
                    field=models.ForeignKey(blank=True, db_column='id_postulacion', null=True, on_delete=django.db.models.deletion.CASCADE, to='core.postulacion'),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='puntaje_dimensiones',
                    field=models.TextField(blank=True, db_column='puntaje_dimensiones'),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='puntaje_total',
                    field=models.DecimalField(blank=True, db_column='puntaje_total', decimal_places=2, max_digits=6, null=True),
                ),
                migrations.AlterField(
                    model_name='intento',
                    name='test',
                    field=models.ForeignKey(db_column='id_test', on_delete=django.db.models.deletion.PROTECT, related_name='intentos', to='core.test'),
                ),
                migrations.AlterField(
                    model_name='respuesta',
                    name='id',
                    field=models.AutoField(db_column='id_respuesta', primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name='respuesta',
                    name='intento',
                    field=models.ForeignKey(db_column='id_intento', on_delete=django.db.models.deletion.CASCADE, related_name='respuestas', to='core.intento'),
                ),
                migrations.AlterField(
                    model_name='respuesta',
                    name='pregunta',
                    field=models.ForeignKey(db_column='id_pregunta', on_delete=django.db.models.deletion.PROTECT, to='core.pregunta'),
                ),
                migrations.AlterModelTable(
                    name='intento',
                    table='intento',
                ),
                migrations.AlterModelTable(
                    name='respuesta',
                    table='respuesta',
                ),
            ],
            database_operations=[
                migrations.RunPython(align_legacy_schema),
            ],
        ),
    ]
