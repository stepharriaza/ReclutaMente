from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_fix_core_analisisia_certificado_intento_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='certificado',
            name='analisis',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='certificado',
            name='modelo_usado',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='certificado',
            name='resultados',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
