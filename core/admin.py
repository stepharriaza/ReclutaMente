from django.contrib import admin

from .models import (
    AnalisisIA,
    Categoria,
    Certificado,
    Convocatoria,
    Empresa,
    Intento,
    Persona,
    Plaza,
    Postulacion,
    Pregunta,
    Respuesta,
    Test,
    Usuario,
)

admin.site.register(Usuario)
admin.site.register(Persona)
admin.site.register(Empresa)
admin.site.register(Categoria)
admin.site.register(Test)
admin.site.register(Pregunta)
admin.site.register(Plaza)
admin.site.register(Convocatoria)
admin.site.register(Postulacion)
admin.site.register(Intento)
admin.site.register(Respuesta)
admin.site.register(AnalisisIA)
admin.site.register(Certificado)