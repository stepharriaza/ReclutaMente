from datetime import datetime

from django.db import models, transaction

from django.utils import timezone

from django.http import request

from django.shortcuts import get_object_or_404, render

from django.shortcuts import render, redirect

from core.models import Plaza, Empresa, Ticket, Persona, Usuario, PruebaGeneradaEmpresa

from core.correo import validar_correo_configurado

from core.models import InvitacionEvaluacion, Respuesta, Postulacion, Convocatoria, EstadoConvocatoria

from django.contrib.auth import logout

from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from django.contrib import messages

from django.core.mail import EmailMultiAlternatives

from django.core.validators import validate_email

from django.core.exceptions import ValidationError

from django.urls import reverse

from django.utils.http import url_has_allowed_host_and_scheme

from core.serializers import EmpresaSerializer  

from rest_framework.decorators import api_view, permission_classes

from rest_framework.permissions import AllowAny, IsAuthenticated

from rest_framework.response import Response

from rest_framework import status
from core.models import Categoria, EstadoTest, Test, Intento
from core.models import Certificado, EstadoIntento, AnalisisIA
from django.db.models import Q

from core.models import Bitacora

from django.contrib.auth import login as auth_login

from django.contrib.auth import authenticate 

from django.contrib.auth.decorators import login_required

from django.views.decorators.cache import never_cache

from django.utils import timezone

from google import genai

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from urllib.parse import quote
import csv
import json
import logging
import unicodedata
import uuid

import io

import re

import qrcode
import requests
from core.decorators import (

    solo_profesional,

    solo_empresa,

    solo_superadmin,

    get_recluta_user,

    )

from core.services import (

    COMPETENCIAS_EVALUACION,

    PERFILES_OBJETIVO,

    SESGOS_CALIFICACION,

    asistente_criterios_evaluacion,

    describir_sesgo_calificacion,

    evaluar_candidato_con_criterios_empresa,
    evaluar_candidato_estructurado,
    analizar_temperamento,
    generar_o_modificar_prueba,
    generar_pdf_certificado,
    resultado_temperamento_respaldo,

)

from core.services import generar_contenido_seguro

from core.agente_contexto import (

    construir_contexto_agente,

    construir_prompt_agente,

)

from core.auth_utils import (

    actualizar_contrasena,

    crear_o_actualizar_django_user,

    es_contrasena_hasheada,

    validar_contrasena,

    verificar_contrasena,

)


logger = logging.getLogger(__name__)




def _get_empresa_for_user(usuario):

    if not usuario:

        return None

    empresa = Empresa.objects.filter(usuario=usuario).first()

    if not empresa:

        empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario.nombre_usuario).first()

    if not empresa and usuario.email:

        empresa = Empresa.objects.filter(usuario__email=usuario.email).first()

    return empresa





def _get_persona_for_user(usuario):

    if not usuario:

        return None

    persona = Persona.objects.filter(usuario=usuario).first()

    if not persona:

        persona = Persona.objects.filter(usuario__nombre_usuario=usuario.nombre_usuario).first()

    if not persona and usuario.email:

        persona = Persona.objects.filter(usuario__email=usuario.email).first()

    return persona


def _intentos_completados_por_persona(plaza):

    intentos = (

        Intento.objects.filter(

            postulacion__convocatoria__plaza=plaza,

            estado=EstadoIntento.COMPLETADO,

        )

        .select_related(

            'persona',

            'persona__usuario',

            'test',

            'postulacion',

            'postulacion__convocatoria',

        )

        .prefetch_related('respuestas__pregunta')

        .order_by('persona_id', '-fecha', '-id')

    )



    agrupados = {}

    for intento in intentos:

        agrupados.setdefault(intento.persona_id, []).append(intento)

    return list(agrupados.values())





def _contexto_plaza_para_ia(plaza):

    return (

        f'Puesto: {plaza.nombre}\n'

        f'Descripción: {plaza.descripcion or "No especificada"}\n'

        f'Requisitos originales: {plaza.requisitos or "No especificados"}'

    )





def _perfiles_para_formulario():

    return [

        {

            'valor': clave,

            'etiqueta': descripcion.split(':')[0],

            'descripcion': descripcion,

        }

        for clave, descripcion in PERFILES_OBJETIVO.items()

    ]





def _competencias_para_formulario():

    return [

        {'valor': clave, 'etiqueta': etiqueta}

        for clave, etiqueta in COMPETENCIAS_EVALUACION.items()

    ]





def _sesgos_para_formulario():

    return [

        {

            'valor': clave,

            'etiqueta': clave.replace('_', ' ').capitalize(),

            'descripcion': descripcion,

        }

        for clave, descripcion in SESGOS_CALIFICACION.items()

    ]





def _componer_criterios(

    perfil='', competencias=None, otros='', criterios_texto=''

):

    partes = []

    if perfil in PERFILES_OBJETIVO:

        partes.append(f'Perfil buscado: {PERFILES_OBJETIVO[perfil]}')

    competencias = [

        clave for clave in (competencias or []) if clave in COMPETENCIAS_EVALUACION

    ]

    if competencias:

        etiquetas = [

            COMPETENCIAS_EVALUACION[clave] for clave in competencias

        ]

        partes.append('Competencias clave: ' + ', '.join(etiquetas))

    if otros:

        partes.append(f'Otros criterios: {otros}')

    if partes:

        return '\n'.join(partes)

    return criterios_texto





def _criterios_desde_formulario(request):

    perfil = request.POST.get('perfil_objetivo', '').strip()

    if perfil not in PERFILES_OBJETIVO:

        perfil = ''



    competencias = [

        clave

        for clave in request.POST.getlist('competencias')

        if clave in COMPETENCIAS_EVALUACION

    ]

    otros = request.POST.get('otros_criterios', '').strip()[:1000]

    criterios_texto = request.POST.get('criterios', '').strip()

    if criterios_texto:

        criterios = criterios_texto

    else:

        criterios = _componer_criterios(

            perfil, competencias, otros, criterios_texto

        )

    return criterios, perfil, competencias, otros





def _clave_seleccion_ia(plaza):

    return f'evaluacion_ia_plaza_{plaza.id}'





def _seleccion_ia_guardada(request, plaza):

    seleccion = request.session.get(_clave_seleccion_ia(plaza), {})

    return seleccion if isinstance(seleccion, dict) else {}





def _guardar_seleccion_ia(

    request,

    plaza,

    perfil,

    competencias,

    otros,

    sesgo,

    sesgo_detalle,

    criterios_texto='',

):

    request.session[_clave_seleccion_ia(plaza)] = {

        'perfil_objetivo': perfil,

        'competencias': competencias,

        'otros_criterios': otros,

        'sesgo': sesgo,

        'sesgo_detalle': sesgo_detalle,

        'criterios_texto': criterios_texto,

    }





def _construir_evidencia_candidato(intentos):

    persona = intentos[0].persona

    lineas = [f'Candidato: {persona.nombre}']



    for intento in intentos:

        lineas.append(f'Prueba: {intento.test.nombre}')

        lineas.append(f'ID de la prueba: {intento.id}')

        lineas.append(f'Fecha: {intento.fecha}')

        if intento.puntaje_total is None:

            lineas.append('Puntaje registrado: No disponible')

        else:

            lineas.append(f'Puntaje registrado: {intento.puntaje_total}')

        if intento.puntaje_dimensiones:

            lineas.append(f'Puntajes por dimensión: {intento.puntaje_dimensiones}')



        respuestas = list(intento.respuestas.all())

        if not respuestas:

            lineas.append('Respuestas: sin respuestas registradas.')

            continue



        lineas.append('Respuestas:')

        for respuesta in respuestas:

            dimension = (

                respuesta.dimension

                or respuesta.pregunta.dimension

                or 'General'

            )

            lineas.append(

                f'- [{dimension}] {respuesta.pregunta.texto_pregunta}: '

                f'{respuesta.texto_respuesta or "(sin respuesta)"}'

            )



    return '\n'.join(lineas)





def _dimensiones_intento(intento):

    """Devuelve el desglose por dimensión de un intento como dict numérico."""

    if not intento or not intento.puntaje_dimensiones:

        return {}

    try:

        datos = json.loads(intento.puntaje_dimensiones)

    except (TypeError, ValueError):

        return {}

    if not isinstance(datos, dict):

        return {}



    dimensiones = {}

    for nombre, valor in datos.items():

        try:

            dimensiones[str(nombre)] = float(valor)

        except (TypeError, ValueError):

            continue

    return dimensiones


def _es_prueba_temperamento(test_obj):
    nombre = unicodedata.normalize('NFKD', test_obj.nombre or '')
    nombre = ''.join(letra for letra in nombre if not unicodedata.combining(letra))
    return 'temperamento' in nombre.lower()


def _procesar_certificacion_temperamento(request, intento):
    """Analiza y certifica un intento de temperamento recién completado."""
    if not _es_prueba_temperamento(intento.test):
        return False

    puntajes = _dimensiones_intento(intento)
    if set(puntajes) != set(('C', 'S', 'F', 'M')):
        messages.warning(
            request,
            'Tus respuestas fueron guardadas, pero faltan dimensiones para '
            'generar la certificación de temperamento.',
        )
        return True

    try:
        try:
            resultados = analizar_temperamento(
                _construir_evidencia_candidato([intento]), puntajes
            )
            generado_con_ia = True
        except Exception:
            logger.exception('No fue posible analizar el temperamento con IA.')
            resultados = resultado_temperamento_respaldo(puntajes)
            generado_con_ia = False

        certificado, _ = Certificado.objects.get_or_create(
            intento=intento,
            defaults={
                'codigo_verificacion': (
                    f'RM-TEM-{uuid.uuid4().hex[:12].upper()}'
                ),
            },
        )
        certificado.resultados = resultados
        certificado.analisis = resultados.get('resumen', '')
        certificado.modelo_usado = resultados.get('modelo', '')
        certificado.pdf = reverse(
            'descargar_certificado', args=[certificado.id]
        )
        certificado.save()

        if generado_con_ia:
            messages.success(
                request,
                '¡Prueba finalizada! Tu análisis y certificación ya están disponibles.',
            )
        else:
            messages.warning(
                request,
                'Tu certificación fue generada con la interpretación de respaldo '
                'de ReclutaMente porque el agente de IA no estuvo disponible.',
            )
    except Exception:
        logger.exception('No fue posible guardar la certificación de temperamento.')
        messages.warning(
            request,
            'Tus respuestas fueron guardadas, pero no se pudo generar la '
            'certificación. Inténtalo nuevamente más tarde.',
        )

    return True




def _barras_dimensiones(intentos):

    """Agrupa los puntajes por dimensión y los normaliza para graficarlos."""

    totales = {}

    for intento in intentos or []:

        for nombre, valor in _dimensiones_intento(intento).items():

            totales[nombre] = totales.get(nombre, 0) + valor



    if not totales:

        return []



    maximo = max(totales.values()) or 1

    barras = []

    for nombre, valor in sorted(

        totales.items(), key=lambda elemento: elemento[1], reverse=True

    ):

        barras.append(

            {

                'nombre': nombre,

                'valor': round(valor, 1),

                'porcentaje': round((valor / maximo) * 100, 1),

            }

        )

    return barras





def _barras_pruebas(resultado):

    """Convierte el puntaje 0-100 de cada prueba en barras para la gráfica."""

    barras = []

    for prueba in (resultado or {}).get('pruebas') or []:

        try:

            valor = float(prueba.get('puntaje'))

        except (TypeError, ValueError):

            continue

        valor = max(0.0, min(100.0, valor))

        barras.append(

            {

                'nombre': prueba.get('test') or 'Prueba',

                'valor': round(valor, 1),

                'porcentaje': round(valor, 1),

            }

        )

    return barras





def _nivel_puntaje(puntaje):

    """Clasifica el puntaje global para dar color y contexto en el informe."""

    try:

        valor = float(puntaje)

    except (TypeError, ValueError):

        return {

            'etiqueta': 'Sin puntaje',

            'descripcion': 'La IA no asignó un puntaje global.',

            'color': '#6366f1',

        }



    if valor >= 80:

        return {

            'etiqueta': 'Desempeño alto',

            'descripcion': 'Puntaje alto: cumple ampliamente con el criterio evaluado.',

            'color': '#10b981',

        }

    if valor >= 60:

        return {

            'etiqueta': 'Desempeño medio',

            'descripcion': 'Puntaje medio: cumple parcialmente con el criterio evaluado.',

            'color': '#6366f1',

        }

    return {

        'etiqueta': 'Desempeño bajo',

        'descripcion': 'Puntaje bajo: hay brechas importantes frente al criterio evaluado.',

        'color': '#ef4444',

    }





def _puntaje_numerico(puntaje):

    try:

        return float(puntaje)

    except (TypeError, ValueError):

        return None





def _clave_orden_resultado(item):

    valor = _puntaje_numerico(item['resultado'].get('puntaje'))

    return (

        valor is None,

        -(valor or 0),

        item['persona'].nombre.lower(),

    )





def _decorar_resultados_ia(resultados_ia):

    """Agrega los datos de gráficas y ordena los resultados para el informe."""

    for item in resultados_ia:

        item['nivel'] = _nivel_puntaje(item['resultado'].get('puntaje'))

        item['barras_pruebas'] = _barras_pruebas(item['resultado'])

        item['barras_dimensiones'] = _barras_dimensiones(item['intentos'])

        for detalle in item['pruebas_detalle']:

            intento = detalle.get('intento')

            detalle['barras_dimensiones'] = (

                _barras_dimensiones([intento]) if intento else []

            )



    resultados_ia.sort(key=_clave_orden_resultado)

    return resultados_ia





def _resultado_desde_analisis(analisis):

    """Reconstruye el resultado visible a partir de un análisis guardado."""

    perfil = analisis.perfil if isinstance(analisis.perfil, dict) else {}

    return {

        'puntaje': perfil.get('puntaje'),

        'recomendacion': perfil.get('recomendacion', ''),

        'fortalezas': perfil.get('fortalezas') or [],

        'brechas': perfil.get('brechas') or [],

        'informe': analisis.informe_texto or '',

        'pruebas': perfil.get('pruebas') or [],

        'modelo': analisis.modelo_usado or '',

    }


def _analisis_guardado(intentos):
    """Devuelve el análisis más reciente guardado para una persona.

    Se buscan todos los intentos de la persona y no solo el representante,
    para que una evaluación antigua no desaparezca si el candidato resuelve
    una prueba nueva y cambia el intento más reciente.
    """

    ids = [intento.id for intento in intentos if intento and intento.id]

    if not ids:
        return None

    return (
        AnalisisIA.objects.filter(intento_id__in=ids)
        .order_by('-id')
        .first()
    )


def _formatear_fecha_iso(valor):
    """Convierte una marca de tiempo ISO guardada en texto legible."""

    if not valor:
        return ''

    try:
        fecha = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return str(valor)

    if timezone.is_aware(fecha):
        fecha = timezone.localtime(fecha)

    return fecha.strftime('%d/%m/%Y %H:%M')


def _historial_analisis(analisis):
    """Devuelve las evaluaciones anteriores guardadas, listas para mostrar."""

    if not analisis or not isinstance(analisis.perfil, dict):
        return []

    historial = []

    for item in analisis.perfil.get('historial') or []:
        if not isinstance(item, dict):
            continue

        historial.append(
            {
                'puntaje': item.get('puntaje'),
                'recomendacion': item.get('recomendacion', ''),
                'criterios': item.get('criterios', ''),
                'sesgo': item.get('sesgo', ''),
                'sesgo_detalle': item.get('sesgo_detalle', ''),
                'informe': item.get('informe', ''),
                'modelo': item.get('modelo', ''),
                'fecha': _formatear_fecha_iso(item.get('evaluado_en')),
            }
        )

    return historial


FABRIC_CAMPOS_CSV = [
    'generado_en',
    'empresa_id',
    'empresa_nombre',
    'plaza_id',
    'plaza_nombre',
    'persona_id',
    'persona_nombre',
    'persona_email',
    'puntaje_ia',
    'recomendacion_ia',
    'fortalezas_ia',
    'brechas_ia',
    'informe_ia',
    'criterios',
    'sesgo',
    'sesgo_detalle',
    'intento_id',
    'test_id',
    'test_nombre',
    'fecha_intento',
    'puntaje_total',
    'puntaje_dimensiones_json',
    'prueba_puntaje_ia',
    'prueba_fortalezas_ia',
    'prueba_brechas_ia',
    'prueba_informe_ia',
]


def _datos_exportacion_fabric(plaza):
    """Arma el conjunto de resultados de una vacante para Microsoft Fabric."""
    grupos = _intentos_completados_por_persona(plaza)
    grupos.sort(key=lambda grupo: grupo[0].persona.nombre.lower())

    candidatos = []
    for intentos in grupos:
        representante = intentos[0]
        analisis = _analisis_guardado(intentos)
        perfil = (
            analisis.perfil
            if analisis and isinstance(analisis.perfil, dict)
            else {}
        )

        analisis_por_intento = {}
        for prueba in perfil.get('pruebas') or []:
            try:
                analisis_por_intento[int(prueba.get('intento_id'))] = prueba
            except (TypeError, ValueError):
                continue

        intentos_datos = []
        for intento in intentos:
            fecha = intento.fecha
            if fecha and timezone.is_aware(fecha):
                fecha = timezone.localtime(fecha)
            intentos_datos.append(
                {
                    'intento_id': intento.id,
                    'test_id': intento.test_id,
                    'test': intento.test.nombre if intento.test else '',
                    'fecha': fecha.isoformat() if fecha else '',
                    'puntaje_total': (
                        float(intento.puntaje_total)
                        if intento.puntaje_total is not None
                        else None
                    ),
                    'puntaje_dimensiones': _dimensiones_intento(intento),
                    'analisis_ia': analisis_por_intento.get(intento.id),
                }
            )

        candidatos.append(
            {
                'persona': {
                    'id': representante.persona_id,
                    'nombre': representante.persona.nombre,
                    'email': representante.persona.email,
                },
                'puntaje_ia': perfil.get('puntaje'),
                'recomendacion': perfil.get('recomendacion', ''),
                'fortalezas': perfil.get('fortalezas') or [],
                'brechas': perfil.get('brechas') or [],
                'informe': analisis.informe_texto if analisis else '',
                'criterios': perfil.get('criterios', ''),
                'sesgo': perfil.get('sesgo', ''),
                'sesgo_detalle': perfil.get('sesgo_detalle', ''),
                'intentos': intentos_datos,
            }
        )

    return {
        'generado_en': timezone.now().isoformat(),
        'empresa': {
            'id': plaza.empresa_id,
            'nombre': plaza.empresa.nombre if plaza.empresa else '',
        },
        'plaza': {
            'id': plaza.id,
            'nombre': plaza.nombre,
            'descripcion': plaza.descripcion or '',
        },
        'total_candidatos': len(candidatos),
        'candidatos': candidatos,
    }


def _filas_csv_fabric(datos):
    """Aplana el conjunto de datos en filas para CSV (una por intento)."""
    filas = []
    for candidato in datos.get('candidatos') or []:
        base = {
            'generado_en': datos.get('generado_en', ''),
            'empresa_id': (datos.get('empresa') or {}).get('id', ''),
            'empresa_nombre': (datos.get('empresa') or {}).get('nombre', ''),
            'plaza_id': (datos.get('plaza') or {}).get('id', ''),
            'plaza_nombre': (datos.get('plaza') or {}).get('nombre', ''),
            'persona_id': (candidato.get('persona') or {}).get('id', ''),
            'persona_nombre': (candidato.get('persona') or {}).get('nombre', ''),
            'persona_email': (candidato.get('persona') or {}).get('email', ''),
            'puntaje_ia': candidato.get('puntaje_ia', ''),
            'recomendacion_ia': candidato.get('recomendacion', ''),
            'fortalezas_ia': ' | '.join(candidato.get('fortalezas') or []),
            'brechas_ia': ' | '.join(candidato.get('brechas') or []),
            'informe_ia': candidato.get('informe', ''),
            'criterios': candidato.get('criterios', ''),
            'sesgo': candidato.get('sesgo', ''),
            'sesgo_detalle': candidato.get('sesgo_detalle', ''),
        }

        intentos = candidato.get('intentos') or [{}]
        for intento in intentos:
            analisis = intento.get('analisis_ia') or {}
            fila = dict(base)
            fila.update(
                {
                    'intento_id': intento.get('intento_id', ''),
                    'test_id': intento.get('test_id', ''),
                    'test_nombre': intento.get('test', ''),
                    'fecha_intento': intento.get('fecha', ''),
                    'puntaje_total': intento.get('puntaje_total', ''),
                    'puntaje_dimensiones_json': json.dumps(
                        intento.get('puntaje_dimensiones') or {},
                        ensure_ascii=False,
                    ),
                    'prueba_puntaje_ia': analisis.get('puntaje', ''),
                    'prueba_fortalezas_ia': ' | '.join(
                        analisis.get('fortalezas') or []
                    ),
                    'prueba_brechas_ia': ' | '.join(
                        analisis.get('brechas') or []
                    ),
                    'prueba_informe_ia': analisis.get('informe', ''),
                }
            )
            filas.append(fila)

    return filas


def _guardar_analisis_ia(

    intentos,

    criterios,

    resultado,

    plaza,

    sesgo='',

    sesgo_detalle='',

    perfil_objetivo='',

    competencias=None,

):

    representante = intentos[0]

    intentos_ids = [intento.id for intento in intentos]

    anterior = (
        AnalisisIA.objects.filter(intento_id__in=intentos_ids)
        .order_by('-id')
        .first()
    )

    historial = []

    if anterior and isinstance(anterior.perfil, dict):
        historial = [
            item
            for item in (anterior.perfil.get('historial') or [])
            if isinstance(item, dict)
        ]
        historial.append(
            {
                'evaluado_en': anterior.perfil.get('evaluado_en'),
                'puntaje': anterior.perfil.get('puntaje'),
                'recomendacion': anterior.perfil.get('recomendacion', ''),
                'criterios': anterior.perfil.get('criterios', ''),
                'sesgo': anterior.perfil.get('sesgo', ''),
                'sesgo_detalle': anterior.perfil.get('sesgo_detalle', ''),
                'informe': anterior.informe_texto or '',
                'modelo': anterior.modelo_usado or '',
            }
        )
        historial = historial[-5:]

    perfil = {

        'criterios': criterios,

        'sesgo': sesgo,

        'sesgo_detalle': sesgo_detalle,

        'perfil_objetivo': perfil_objetivo,

        'competencias': competencias or [],

        'puntaje': resultado.get('puntaje'),

        'recomendacion': resultado.get('recomendacion', ''),

        'fortalezas': resultado.get('fortalezas', []),

        'brechas': resultado.get('brechas', []),

        'pruebas': resultado.get('pruebas', []),

        'intentos': [intento.id for intento in intentos],

        'plaza_id': plaza.id,

        'evaluado_en': timezone.now().isoformat(),

        'historial': historial,

    }

    analisis, _ = AnalisisIA.objects.update_or_create(

        intento=representante,

        defaults={

            'perfil': perfil,

            'informe_texto': resultado.get('informe', ''),

            'modelo_usado': resultado.get('modelo', ''),

        },

    )

    return analisis




def _generar_qr_png(data):

    qr = qrcode.QRCode(version=1, box_size=10, border=4)

    qr.add_data(data)

    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()

    img.save(buffer, format='PNG')

    buffer.seek(0)

    return buffer





def _enviar_invitacion_evaluacion(request, invitacion):

    plaza = invitacion.plaza

    enlace = request.build_absolute_uri(

        reverse('evaluacion_invitacion', args=[invitacion.token])

    )

    asunto = f'Invitación a evaluación - {plaza.nombre}'

    mensaje_texto = (

        f'Hola,\n\n'

        f'{plaza.empresa.nombre} te invita a realizar la evaluación para la vacante '

        f'"{plaza.nombre}".\n\n'

        f'Para ingresar, abre el siguiente enlace e inicia sesión con el correo '

        f'{invitacion.email}:\n{enlace}\n\n'

        f'Si no tienes una cuenta, regístrate con este mismo correo para poder '

        f'ingresar a la evaluación.\n\n'

        f'El código QR adjunto también te lleva directamente a la evaluación.\n\n'

        f'ReclutaMente'

    )

    mensaje_html = (

        f'<p>Hola,</p>'

        f'<p><strong>{plaza.empresa.nombre}</strong> te invita a realizar la evaluación '

        f'para la vacante <strong>{plaza.nombre}</strong>.</p>'

        f'<p><a href="{enlace}">Ingresar a la evaluación</a></p>'

        f'<p>Inicia sesión o regístrate con el correo <strong>{invitacion.email}</strong> '

        f'para que tus resultados queden asociados a tu cuenta.</p>'

        f'<p>El código QR adjunto también te lleva directamente a la evaluación.</p>'

        f'<p>ReclutaMente</p>'

    )



    email = EmailMultiAlternatives(

        asunto,

        mensaje_texto,

        None,

        [invitacion.email],

    )

    email.attach_alternative(mensaje_html, 'text/html')

    qr_buffer = _generar_qr_png(enlace)

    email.attach(f'qr_{plaza.nombre[:30].replace(" ", "_")}.png', qr_buffer.getvalue(), 'image/png')

    validar_correo_configurado()

    email.send(fail_silently=False)

    return enlace





def _obtener_next(request, default=''):

    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if next_url and url_has_allowed_host_and_scheme(

        next_url,

        allowed_hosts={request.get_host()},

        require_https=request.is_secure(),

    ):

        return next_url

    return default





# --- Agente ---

from core.services import evaluar_candidato_con_criterios_empresa





def evaluar_candidato_view(request):

  if request.method == "POST":

    try:

      data = json.loads(request.body)

      respuestas = data.get("respuestas_candidato", "")

      criterios = data.get("criterios_vacante", "")



      if not respuestas or not criterios:

        return JsonResponse(

            {

                "error": (

                    "Las respuestas y los criterios son obligatorios para"

                    " evaluar."

                )

            },

            status=400,

        )



      resultado_analisis = evaluar_candidato_con_criterios_empresa(

          respuestas_candidato=respuestas,

          requisitos_vacante=criterios,

          nombre_archivo_guia="Test de Temperatura.pdf",

      )



      return JsonResponse(

          {

              "success": True,

              "mensaje": "¡Evaluación realizada con éxito!",

              "analisis": resultado_analisis,

          }

      )



    except Exception as e:

      return JsonResponse({"error": str(e)}, status=500)



  return JsonResponse({"error": "Método no permitido"}, status=405)





def api_agente_interactivo(request):

    if request.method == 'POST':

        try:

            data = json.loads(request.body)

            mensaje = data.get('mensaje', '')

            

            if not mensaje:

                return JsonResponse({'error': 'El mensaje está vacío.'}, status=400)

            

            # Prompt optimizado para que devuelva un formato estructurado o JSON limpio

            prompt = f"""

            Eres el agente interactivo de la plataforma ReclutaMente. El usuario dice: "{mensaje}".

            Si el usuario te pide explícitamente crear una prueba o rellenar un campo, responde estrictamente en formato JSON con estas llaves exactas (sin texto extra fuera del JSON):

            {{"accion": "crear_prueba", "puesto": "nombre detectado", "criterios": "criterios detectados", "respuesta_texto": "Mensaje para el usuario"}}

            Si es una consulta normal de chat o soporte, responde con este formato JSON:

            {{"accion": "chat", "respuesta_texto": "Tu respuesta aquí"}}

            """

            

            # ¡Usamos tu función de respaldo segura en lugar de llamar directo al cliente!

            respuesta_cruda = generar_contenido_seguro(prompt)

            

            # Limpiamos el texto por si Gemini incluye bloques de código markdown

            texto_limpio = respuesta_cruda.replace('```json', '').replace('```', '').strip()

            

            try:

                datos_json = json.loads(texto_limpio)

            except json.JSONDecodeError:

                # Si Gemini no devolvió un JSON perfecto, lo envolvemos como chat normal

                datos_json = {'accion': 'chat', 'respuesta_texto': respuesta_cruda}

            

            return JsonResponse(datos_json)

            

        except Exception as e:

            return JsonResponse({'accion': 'chat', 'respuesta_texto': f"Error en el servidor de IA: {str(e)}"})

            

    return JsonResponse({'error': 'Método no permitido'}, status=405)







def api_crear_prueba_ia(request):

    if request.method == 'POST':

        try:

            data = json.loads(request.body)

            puesto = data.get('puesto', '')

            criterios = data.get('criterios', '')

            

            if not puesto or not criterios:

                return JsonResponse({'error': 'El puesto y los criterios son obligatorios.'}, status=400)

            

            empresa_obj = Empresa.objects.get(usuario=request.user)

            

            prompt = f"""

            Eres el experto en diseño de talento humano y psicometría de la plataforma ReclutaMente.

            La empresa '{empresa_obj.nombre}' solicita crear una prueba o evaluación personalizada a la medida para el puesto de: '{puesto}'.

            Los requerimientos clave y competencias indispensables que la empresa desea evaluar son: {criterios}.

            

            Genera una prueba profesional y estructurada con instrucciones, casos prácticos y guía de respuestas en Markdown.

            """

            

            # ¡Llamamos a nuestra función blindada que maneja los modelos y reintentos solos!

            contenido_generado = generar_contenido_seguro(prompt)

            

            nueva_prueba = PruebaGeneradaEmpresa.objects.create(

                empresa=empresa_obj,

                puesto=puesto,

                criterios_requeridos=criterios,

                contenido_prueba=contenido_generado

            )

            

            return JsonResponse({

                'success': True,

                'mensaje': '¡Prueba generada y guardada con éxito!',

                'id_prueba': nueva_prueba.id,

                'contenido': contenido_generado

            })

            

        except Exception as e:

            return JsonResponse({'error': str(e)}, status=500)

            

    return JsonResponse({'error': 'Método no permitido'}, status=405)



def api_agente_ia(request):

    if request.method != 'POST':

        return JsonResponse({'error': 'Método no permitido'}, status=405)



    try:

        data = json.loads(request.body or '{}')

    except (json.JSONDecodeError, UnicodeDecodeError):

        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)



    if not isinstance(data, dict):

        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)



    mensaje_usuario = str(data.get('mensaje', '')).strip()

    if not mensaje_usuario:

        return JsonResponse({'error': 'El mensaje está vacío.'}, status=400)

    if len(mensaje_usuario) > 2000:

        return JsonResponse(

            {'error': 'El mensaje es demasiado largo.'}, status=400

        )



    contexto_pagina = data.get('contexto_pagina') or {}

    if isinstance(contexto_pagina, dict):

        ruta_pagina = (

            contexto_pagina.get('ruta')

            or contexto_pagina.get('path')

            or ''

        )

    elif isinstance(contexto_pagina, str):

        ruta_pagina = contexto_pagina

    else:

        ruta_pagina = ''

    if not ruta_pagina:

        ruta_pagina = data.get('ruta_pagina') or request.META.get(

            'HTTP_REFERER', ''

        )



    historial = data.get('historial', [])

    if not isinstance(historial, list):

        historial = []



    try:

        contexto = construir_contexto_agente(

            request,

            ruta_pagina=str(ruta_pagina),

            historial=historial,

        )

        prompt = construir_prompt_agente(mensaje_usuario, contexto)

        respuesta_texto = generar_contenido_seguro(prompt)

        return JsonResponse({'respuesta': respuesta_texto})

    except Exception as e:

        return JsonResponse({'error': str(e)}, status=500)





def agente_ia_analisis(request):

    resultado_ia = None

    texto_usuario = ""

    

    if request.method == 'POST':

        texto_usuario = request.POST.get('texto_a_analizar', '')

        

        if texto_usuario:

            try:

                prompt = f"Actúa como un experto en recursos humanos y reclutamiento de personal. Analiza el siguiente perfil o texto y da recomendaciones clave: {texto_usuario}"

                resultado_ia = generar_contenido_seguro(prompt)

            except Exception as e:

                resultado_ia = f"Ocurrió un error al comunicarse con la IA: {e}"

                

    return render(request, 'superAdmin/agente_ia.html', {

        'resultado_ia': resultado_ia,

        'texto_usuario': texto_usuario

    })



#---Fin agente ---



@login_required(login_url='login')

def superadmin_reporte_consumo(request, pk):

    empresa = get_object_or_404(Empresa, pk=pk)

    

    total_vacantes = empresa.vacante_set.count() if hasattr(empresa, 'vacante_set') else 0

    

    total_consultas_ia = 0 

    

    context = {

        'empresa': empresa,

        'total_vacantes': total_vacantes,

        'total_consultas_ia': total_consultas_ia,

    }

    return render(request, 'superadmin/superadmin_reporte_consumo.html', context)



# --- FUNCIÓN AUXILIAR PARA GUARDAR EN LA BITÁCORA ---

def registrar_en_bitacora(user, accion_desc, modulo_nombre="Gestión"):

    try:

        nombre_usuario = user.username if (user and user.is_authenticated) else 'Sistema'

        Bitacora.objects.create(

            usuario=nombre_usuario,

            accion=accion_desc,

            modulo=modulo_nombre

        )

    except Exception as e:

        print("Error al registrar en la bitácora:", e)







@login_required(login_url='login')

def superadmin_empresa_editar(request, pk):

    empresa = get_object_or_404(Empresa, pk=pk)

    

    if request.method == 'POST':

        empresa.nombre = request.POST.get('nombre')

        empresa.plan = request.POST.get('plan')

        empresa.telefono = request.POST.get('telefono')

        empresa.estado = request.POST.get('estado') 

        empresa.save()

        

        # ð AQUÍ SE REGISTRA EL CAMBIO EN LA BITÁCORA

        registrar_en_bitacora(

            request.user, 

            f"Modificó la empresa (Estado: {empresa.estado}): {empresa.nombre}",

            "Empresas"

        )

        

        messages.success(request, 'Empresa actualizada exitosamente.')

        return redirect('superadmin_empresas')

        

    context = {'empresa': empresa}

    return render(request, 'superadmin/superadmin_empresa_editar.html', context)



@login_required(login_url='login')

def superadmin_bitacora(request):

    try:

        usuario = request.GET.get('usuario', '').strip()

        fecha = request.GET.get('fecha', '').strip()



        bitacora_list = Bitacora.objects.all().order_by('-fecha_hora')



        if usuario:

            bitacora_list = bitacora_list.filter(usuario__icontains=usuario)



        if fecha:

            bitacora_list = bitacora_list.filter(fecha_hora__date=fecha)



    except Exception:

        bitacora_list = []



    context = {

        'bitacora_list': bitacora_list,

        'usuario_filtro': usuario,

        'fecha_filtro': fecha,

    }

    

    return render(request, 'superAdmin/superadmin_bitacora.html', context)







@login_required(login_url='login')

def superadmin_empresas(request):

    if request.method == 'POST':

        nombre_empresa = request.POST.get('nombre')

        plan = request.POST.get('plan')

        telefono = request.POST.get('telefono')

        

        nombre_usuario = request.POST.get('nombre_usuario')

        email_admin = request.POST.get('email_admin')

        contrasena_admin = request.POST.get('contrasena_admin')

        

        try:

            nuevo_usuario = Usuario.objects.create(

                nombre_usuario=nombre_usuario,

                email=email_admin,

                contrasena=''

            )

            actualizar_contrasena(nuevo_usuario, contrasena_admin)

            

            empresa = Empresa.objects.create(

                nombre=nombre_empresa,

                plan=plan,

                telefono=telefono,

                usuario=nuevo_usuario

            )

            

            # ð REGISTRAMOS LA ACCIÓN EN LA BITÁCORA

            registrar_en_bitacora(

                request.user, 

                f"Creó la empresa: {empresa.nombre}", 

                "Empresas"

            )

            

            messages.success(request, 'Empresa y usuario administrador creados exitosamente.')

            return redirect('superadmin_empresas')

            

        except Exception as e:

            print("--- ERROR AL CREAR EMPRESA Y USUARIO ---")

            print(e)

            messages.error(request, f'Error al registrar la empresa: {e}')

            

    # Resto del código de filtrado GET...  

# 2. CAPTURAR FILTROS GET

    nombre_filtro = request.GET.get('nombre', '')

    plan_filtro = request.GET.get('plan', '')

    

    # 3. CONSULTAR Y FILTRAR LAS EMPRESAS

    empresas = Empresa.objects.all()

    if nombre_filtro:

        empresas = empresas.filter(nombre__icontains=nombre_filtro)

    if plan_filtro:

        empresas = empresas.filter(plan__icontains=plan_filtro)

        

    # 4. CONTEXTO

    context = {

        'empresas': empresas,

        'nombre_filtro': nombre_filtro,

        'plan_filtro': plan_filtro,

    }

    

    return render(request, 'superadmin/superadmin_empresas.html', context)





#Empresas



@login_required(login_url='login')

def empresa_tickets(request):

    usuario_actual = request.user

    empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

    if not empresa:

        empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()



    if request.method == 'POST':

        tipo = request.POST.get('tipo', 'Soporte General')

        asunto = request.POST.get('asunto')

        prueba = request.POST.get('prueba', '')

        destino = request.POST.get('destino', 'N/A')

        

        # --- AQUÍ CAPTURAMOS LAS DOS FECHAS DEL CALENDARIO ---

        fecha_inicio = request.POST.get('fecha_inicio')

        fecha_fin = request.POST.get('fecha_fin')

        

        # Unimos ambas fechas en un solo texto amigable para tu variable rango_fechas

        if fecha_inicio and fecha_fin:

            rango_fechas = f"{fecha_inicio} al {fecha_fin}"

        elif fecha_inicio:

            rango_fechas = f"Desde el {fecha_inicio}"

        else:

            rango_fechas = "N/A"

            

        descripcion = request.POST.get('descripcion')

        

        if asunto and descripcion:

            try:

                conteo = Ticket.objects.filter(empresa=empresa).count() + 1 if empresa else 1

                codigo_ticket = f"TCK-{empresa.id if empresa else 0}-{conteo:03d}"



                Ticket.objects.create(

                    codigo=codigo_ticket,

                    empresa=empresa,

                    tipo=tipo,

                    asunto=asunto,

                    prueba=prueba,

                    destino=destino,

                    rango_fechas=rango_fechas,

                    descripcion=descripcion,

                    estado='Abierto'

                )

                messages.success(request, '¡Ticket enviado con éxito al Super Administrador!')

                return redirect('empresa_tickets')

            except Exception as e:

                messages.error(request, f'Error al registrar el ticket: {e}')

        else:

            messages.error(request, 'El asunto y la descripción son obligatorios.')



    tickets = Ticket.objects.filter(empresa=empresa).order_by('-fecha_creacion') if empresa else []



    context = {

        'empresa': empresa,

        'tickets': tickets,

    }

    return render(request, 'Empresas/tickets.html', context)

@login_required(login_url='login')

def empresa_editar_vacante(request, pk):

    usuario_actual = request.user

    empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

    if not empresa:

        empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()



    vacante = get_object_or_404(Plaza, pk=pk, empresa=empresa)

    tests_disponibles = Test.objects.filter(estado=EstadoTest.PUBLICADO).order_by('nombre')



    if request.method == 'POST':

        nombre = request.POST.get('nombre') or request.POST.get('titulo') or request.POST.get('puesto')

        descripcion = request.POST.get('descripcion')

        requisitos = request.POST.get('requisitos', '')

        ubicacion = request.POST.get('ubicacion', '')

        modalidad = request.POST.get('modalidad', '')

        fecha_limite = request.POST.get('fecha_limite') or None  # <-- Capturamos la fecha enviada del formulario

        test_ids = request.POST.getlist('tests')

        

        try:

            if nombre:

                vacante.nombre = nombre

                vacante.descripcion = descripcion

                vacante.requisitos = requisitos

                vacante.ubicacion = ubicacion

                vacante.modalidad = modalidad

                vacante.fecha_limite = fecha_limite  # <-- Guardamos la fecha en la plaza

                vacante.save()

                if test_ids:

                    tests_seleccionados = Test.objects.filter(id__in=test_ids, estado=EstadoTest.PUBLICADO)

                    vacante.tests.set(tests_seleccionados)

                else:

                    vacante.tests.clear()

                

                messages.success(request, 'ï¿½ï¿½Vacante actualizada exitosamente!')

                return redirect('empresa_vacantes')

            else:

                messages.error(request, 'El nombre de la vacante es obligatorio.')

        except Exception as e:

            messages.error(request, f'Error al actualizar: {e}')



    context = {

        'vacante': vacante,

        'empresa': empresa,

        'tests': tests_disponibles,

        'tests_seleccionados': vacante.tests.values_list('id', flat=True),

    }

    return render(request, 'Empresas/editar_vacante.html', context)



@login_required(login_url='login')

def empresa_dashboard(request):

    try:

        usuario_actual = request.user

        

        # Intentamos localizar la empresa asociada a este usuario

        empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

        if not empresa:

            empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()

            

        hoy = timezone.now().date()

        

        if empresa:

            # Filtramos únicamente las plazas vigentes (fecha mayor o igual a hoy, o sin fecha límite)

            plazas_activas = Plaza.objects.filter(empresa=empresa).filter(

                Q(fecha_limite__gte=hoy) | Q(fecha_limite__isnull=True)

            )

        else:

            plazas_activas = Plaza.objects.none()

            

        total_vacantes = plazas_activas.count()

        

        # Obtenemos las más recientes ordenadas de forma descendente por ID o fecha de creación

        vacantes_recientes = plazas_activas.order_by('-id')[:5]



    except Exception as e:

        print("--- ERROR EN EMPRESA DASHBOARD ---", e)

        empresa = None

        total_vacantes = 0

        vacantes_recientes = []



    context = {

        'empresa': empresa,

        'total_vacantes': total_vacantes,

        'vacantes_recientes': vacantes_recientes,

    }

    return render(request, 'Empresas/dashboard.html', context)



@login_required(login_url='login')

def empresa_vacantes(request):

    usuario_actual = request.user

    empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

    if not empresa:

        empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()

        

    hoy = timezone.now().date()

    

    if empresa:

        # Plazas vigentes (fecha lï¿½ï¿½mite mayor o igual a hoy, o sin fecha lï¿½ï¿½mite)

        vacantes_activas = Plaza.objects.filter(empresa=empresa).filter(

            Q(fecha_limite__gte=hoy) | Q(fecha_limite__isnull=True)

        ).prefetch_related('tests')

        

        # Plazas anteriores / vencidas (fecha lï¿½ï¿½mite menor a hoy)

        vacantes_pasadas = Plaza.objects.filter(empresa=empresa, fecha_limite__lt=hoy).prefetch_related('tests')

    else:

        vacantes_activas = []

        vacantes_pasadas = []

        

    context = {

        'empresa': empresa,

        'vacantes': vacantes_activas,

        'vacantes_pasadas': vacantes_pasadas, # Historial

    }

    return render(request, 'Empresas/vacantes.html', context)



@login_required(login_url='login')

def empresa_crear_vacante(request):

    usuario_actual = request.user

    empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

    if not empresa:

        empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()



    tests_disponibles = Test.objects.filter(estado=EstadoTest.PUBLICADO).order_by('nombre')



    if request.method == 'POST':

        # Agregamos 'puesto' que es el nombre del input que viene de tu formulario HTML

        nombre = request.POST.get('nombre') or request.POST.get('titulo') or request.POST.get('puesto')

        descripcion = request.POST.get('descripcion')

        requisitos = request.POST.get('requisitos', '')

        ubicacion = request.POST.get('ubicacion', '')

        modalidad = request.POST.get('modalidad', '')

        fecha_limite = request.POST.get('fecha_limite') or None

        test_ids = request.POST.getlist('tests')

        

        try:

            if nombre and empresa:

                plaza = Plaza.objects.create(

                    nombre=nombre,

                    descripcion=descripcion,

                    requisitos=requisitos,

                    ubicacion=ubicacion,

                    modalidad=modalidad,

                    fecha_limite=fecha_limite,

                    empresa=empresa

                )

                if test_ids:

                    tests_seleccionados = Test.objects.filter(id__in=test_ids, estado=EstadoTest.PUBLICADO)

                    plaza.tests.set(tests_seleccionados)

                messages.success(request, 'ï¿½ï¿½Vacante creada exitosamente!')

                return redirect('empresa_vacantes')

            else:

                messages.error(request, 'Faltan datos obligatorios o no se encontrï¿½ï¿½ la empresa asociada.')

        except Exception as e:

            print("--- ERROR AL CREAR VACANTE ---", e)

            messages.error(request, f'Error al registrar la vacante: {e}')

            

    context = {

        'empresa': empresa,

        'tests': tests_disponibles,

    }

    return render(request, 'Empresas/crear_vacante.html', context)





@login_required(login_url='login')

def empresa_perfil(request):

    usuario_actual = request.user

    empresa = Empresa.objects.filter(usuario__nombre_usuario=usuario_actual.username).first()

    if not empresa and usuario_actual.email:

        empresa = Empresa.objects.filter(usuario__email=usuario_actual.email).first()

    if not empresa:

        empresa = Empresa.objects.first()



    if request.method == 'POST' and empresa:

        empresa.nombre = request.POST.get('nombre', empresa.nombre)

        empresa.telefono = request.POST.get('telefono', empresa.telefono)

        empresa.save()

        messages.success(request, 'Perfil corporativo actualizado correctamente.')

        return redirect('empresa_perfil')



    return render(request, 'Empresas/perfil.html', {'empresa': empresa})







def superadmin_dashboard(request):

    context = {

        'total_empresas': Empresa.objects.count(),

        'total_personas': Persona.objects.count(),

        'total_tests': Test.objects.count(),

        'total_intentos': Intento.objects.count(),

    }

    return render(request, 'superAdmin/superadmin_dashboard.html', context)



@login_required(login_url='login')

def superadmin_crear_profesional(request):

    if request.method == 'POST':

        nombre = request.POST.get('nombre')

        email = request.POST.get('email')

        telefono = request.POST.get('telefono', '')

        

        try:

            if nombre and email:

                # 1. Creamos un usuario asociado para el login

                # (Puedes usar el email o el nombre como username base)

                username_generado = email.split('@')[0]

                

                # Nos aseguramos de que el username sea único

                base_username = username_generado

                contador = 1

                while Usuario.objects.filter(nombre_usuario=username_generado).exists():

                    username_generado = f"{base_username}{contador}"

                    contador += 1



                nuevo_usuario = Usuario.objects.create(

                    nombre_usuario=username_generado,

                    email=email,

                    contrasena=''

                )

                actualizar_contrasena(nuevo_usuario, "Temp1234*")



                # 2. Creamos la Persona vinculada a ese usuario

                persona = Persona.objects.create(

                    nombre=nombre,

                    email=email,

                    telefono=telefono,

                    usuario=nuevo_usuario

                )

                

                # Registramos en la bitácora

                registrar_en_bitacora(

                    request.user, 

                    f"Creó al profesional: {persona.nombre} (Usuario: {username_generado})", 

                    "Profesionales"

                )

                

                messages.success(request, f'Profesional creado. Usuario de acceso: {username_generado} | Contraseña temporal: Temp1234*')

                return redirect('superadmin_profesionales')

                

        except Exception as e:

            print("--- ERROR AL CREAR PROFESIONAL ---")

            print(e)

            messages.error(request, f'Error al registrar el profesional: {e}')

            

    return render(request, 'superAdmin/superadmin_profesionales.html')





def home(request):

    return render(request, "home.html")



def catalogo(request):

    categorias = Categoria.objects.all()

    return render(request, "catalogo.html", {"categorias": categorias})



def _plantilla_test(preguntas):
    primera = preguntas.first() if hasattr(preguntas, "first") else None
    if primera is None:
        return "test.html"
    nombre = ""
    if getattr(primera, "test_id", None):
        nombre = (primera.test.nombre or "").lower()
    if "dass" in nombre:
        return "test_dass.html"
    if "frases incompletas" in nombre:
        return "test_frases.html"
    texto = (primera.texto_pregunta or "").strip()
    bajo = texto.lower()
    if "\n" not in texto and bajo.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "test_razonamiento.html"
    if "\n" in texto or len(texto) > 80 or "(a)" in bajo or "(b)" in bajo:
        return "test_opcion.html"
    return "test.html"


def tests_categoria(request, categoria_id):

    categoria = get_object_or_404(Categoria, id=categoria_id)

    tests = Test.objects.filter(categoria=categoria, estado=EstadoTest.PUBLICADO)

    return render(request, "tests_categoria.html", {"categoria": categoria, "tests": tests})



@login_required(login_url='login')

def test(request, test_id):

    test_obj = get_object_or_404(Test, id=test_id, estado=EstadoTest.PUBLICADO)

    preguntas = test_obj.preguntas.order_by('fila', 'id')

    if request.method == 'POST':

        usuario = get_recluta_user(request)

        persona = _get_persona_for_user(usuario)

        if not persona:

            messages.error(

                request,

                'Necesitas una cuenta de profesional para guardar tus resultados. '

                'Regístrate e ingresa nuevamente.',

            )

            return redirect('home_profesionales')



        # ESTO DEBE ESTAR AL MISMO NIVEL QUE EL 'if not persona:', FUERA DE ÉL

        postulacion = None

        plaza_id = request.session.get('plaza_evaluacion_id')

        

        if plaza_id:

            plaza = Plaza.objects.filter(id=plaza_id).first()

            if plaza and plaza.tests.filter(id=test_obj.id).exists():

                convocatoria, _ = Convocatoria.objects.get_or_create(

                    plaza=plaza,

                    nombre=f'Evaluación - {plaza.nombre}',

                    defaults={

                        'estado': EstadoConvocatoria.ABIERTA,

                        'requisito': plaza.requisitos,

                    },

                )

                postulacion, _ = Postulacion.objects.get_or_create(

                    persona=persona,

                    convocatoria=convocatoria,

                )



        # ð¡ï¸ BLINDAJE TOTAL: Si por alguna razón la sesión no tenía la plaza, 

        # buscamos la primera convocatoria abierta para este test o creamos una por defecto

        if not postulacion:

            convocatoria_defecto = Convocatoria.objects.filter(

                plaza__tests=test_obj, 

                estado=EstadoConvocatoria.ABIERTA

            ).first()

            

            if convocatoria_defecto:

                postulacion, _ = Postulacion.objects.get_or_create(

                    persona=persona,

                    convocatoria=convocatoria_defecto,

                )

            else:

                # Si de plano no hay ninguna convocatoria, creamos una de emergencia para que no falle

                plaza_emergencia = Plaza.objects.filter(tests=test_obj).first()

                if plaza_emergencia:

                    convocatoria_emergencia, _ = Convocatoria.objects.get_or_create(

                        plaza=plaza_emergencia,

                        nombre=f'Evaluación de Emergencia - {plaza_emergencia.nombre}',

                        defaults={'estado': EstadoConvocatoria.ABIERTA, 'requisito': plaza_emergencia.requisitos}

                    )

                    postulacion, _ = Postulacion.objects.get_or_create(

                        persona=persona,

                        convocatoria=convocatoria_emergencia,

                    )



        # Si aun así no se pudo obtener ninguna postulación, mandamos error amigable

        if not postulacion:

            messages.error(

                request,

                'No se encontró una plaza o postulación válida para esta evaluación. '

                'Por favor, ingresa nuevamente a través del enlace de la convocatoria o QR.',

            )

            return redirect('home_profesionales')



        total = 0

        dimensiones = {}

        pares = []

        for pregunta in preguntas:

            valor = request.POST.get(f'valor_{pregunta.id}')

            if valor is None:

                valor = request.POST.get(f'respuesta_{pregunta.id}')

            if valor is None:

                continue

            pares.append((pregunta, valor))

            if str(valor).isdigit():

                total += int(valor)

                if pregunta.dimension:

                    dimensiones[pregunta.dimension] = dimensiones.get(pregunta.dimension, 0) + int(valor)



        with transaction.atomic():

            intento = Intento.objects.create(

                persona=persona,

                test=test_obj,

                postulacion=postulacion,

                estado=EstadoIntento.COMPLETADO,

                puntaje_total=total,

                puntaje_dimensiones=json.dumps(dimensiones),

            )

            for pregunta, valor in pares:

                Respuesta.objects.create(

                    intento=intento,

                    pregunta=pregunta,

                    texto_respuesta=str(valor),

                    tipo='escala',

                    dimension=pregunta.dimension or '',

                )



        if _procesar_certificacion_temperamento(request, intento):
            return redirect('profesional_certificaciones')

        messages.success(request, '¡Respuestas enviadas correctamente! Tus resultados fueron guardados.')

        return redirect('home_profesionales')



    primera = preguntas.first()

    duracion_minutos = getattr(settings, 'DURACION_PRUEBA_MINUTOS', 10)

    contexto = {

        "test": test_obj,

        "preguntas": preguntas,

        "duracion_minutos": duracion_minutos,

    }

    return render(request, _plantilla_test(preguntas), contexto)



def iniciar_intento(request, test_id):

    if request.method != 'POST':

        return redirect('tests_categoria', categoria_id=Test.objects.get(id=test_id).categoria_id)



    test_obj = get_object_or_404(Test, id=test_id, estado=EstadoTest.PUBLICADO)

    usuario = get_recluta_user(request)

    if not usuario:

        return redirect('login')

    persona = _get_persona_for_user(usuario)

    if not persona:

        messages.error(request, 'No tienes un perfil de profesional asociado a esta cuenta.')

        return redirect('login')



    intento = Intento.objects.create(

        estado=EstadoIntento.INICIADO,

        persona=persona,

        test=test_obj,

    )

    return redirect('resolver_test', intento_id=intento.id)





def resolver_test(request, intento_id):

    intento = get_object_or_404(Intento, id=intento_id)

    test_obj = intento.test

    preguntas = test_obj.preguntas.order_by('fila', 'id')



    if request.method == 'POST':

        import json as _json



        dimensiones = {}

        total = 0



        for p in preguntas:

            valor = request.POST.get(f'valor_{p.id}') or request.POST.get(f'respuesta_{p.id}')

            if not valor:

                continue

            Respuesta.objects.create(

                texto_respuesta=valor,

                tipo='seleccion',

                dimension=p.dimension or '',

                intento=intento,

                pregunta=p,

            )

            try:

                num = int(valor)

                total += num

                if p.dimension:

                    dimensiones[p.dimension] = dimensiones.get(p.dimension, 0) + num

            except ValueError:

                pass



        from datetime import datetime

        ahora = datetime.now()

        minutos = int((ahora - intento.fecha.replace(tzinfo=None)).total_seconds() // 60)



        intento.duracion = max(minutos, 1)

        intento.puntaje_total = total if total else None

        intento.puntaje_dimensiones = _json.dumps(dimensiones) if dimensiones else ''

        intento.estado = EstadoIntento.COMPLETADO

        intento.save()



        if _procesar_certificacion_temperamento(request, intento):
            return redirect('profesional_certificaciones')

        messages.success(request, '¡Respuestas enviadas correctamente! Tus resultados fueron guardados.')

        return redirect('tests_categoria', categoria_id=test_obj.categoria_id)



    primera = preguntas.first()

    contexto = {

        "test": test_obj,

        "preguntas": preguntas,

        "intento": intento,

        "duracion_minutos": getattr(settings, 'DURACION_PRUEBA_MINUTOS', 10),

    }

    return render(request, _plantilla_test(preguntas), contexto)





def generar_qr_vacante(request, codigo_unico):

    plaza = get_object_or_404(Plaza, codigo_unico=codigo_unico)

    evaluation_url = request.build_absolute_uri(

        reverse('evaluar_vacante_protegida', args=[plaza.codigo_unico])

    )

    buffer = _generar_qr_png(evaluation_url)

    return HttpResponse(buffer.getvalue(), content_type='image/png')





@login_required(login_url='login')

def evaluar_vacante_protegida(request, codigo_unico):

    plaza = get_object_or_404(Plaza, codigo_unico=codigo_unico)

    usuario = get_recluta_user(request)

    if usuario and usuario.rol in ('empresa', 'superadmin'):

        messages.error(request, 'Solo los profesionales pueden rendir esta evaluación.')

        if usuario.rol == 'empresa':

            return redirect('empresa_dashboard')

        return redirect('superadmin_dashboard')

    tests = plaza.tests.filter(estado=EstadoTest.PUBLICADO).order_by('id')

    if tests.count() == 0:

        messages.warning(request, 'Esta vacante no tiene pruebas configuradas.')

        return redirect('home')

    request.session['plaza_evaluacion_id'] = plaza.id

    if tests.count() == 1:

        return redirect('test', test_id=tests.first().id)

    context = {

        'plaza': plaza,

        'tests': tests,

    }

    return render(request, 'Empresas/evaluacion_vacante.html', context)





@login_required(login_url='login')

def empresa_invitar_participantes(request, pk):

    usuario = get_recluta_user(request)

    empresa = _get_empresa_for_user(usuario)

    plaza = get_object_or_404(Plaza, pk=pk, empresa=empresa)

    tests = plaza.tests.filter(estado=EstadoTest.PUBLICADO).order_by('id')
    tests_asignados = plaza.tests.all().order_by('id')
    plaza_vencida = plaza.esta_vencida

    if request.method == 'POST' and plaza_vencida:
        messages.error(
            request,
            'La plaza está vencida; solo puedes consultar invitaciones y resultados.',
        )
        return redirect('empresa_invitar_participantes', pk=plaza.pk)

    if not tests.exists():
        messages.warning(request, 'Primero asigna al menos una prueba a esta vacante.')

        return redirect('empresa_editar_vacante', pk=plaza.pk)



    if request.method == 'POST':

        raw_emails = request.POST.get('emails', '')

        emails = [e.strip().lower() for e in re.split(r'[\s,;]+', raw_emails) if e.strip()]



        if not emails:

            messages.error(request, 'Ingresa al menos un correo electrónico.')

        else:

            enviados = 0

            errores = []

            for email in dict.fromkeys(emails):

                try:

                    validate_email(email)

                except ValidationError:

                    errores.append(f'{email} (formato inválido)')

                    continue



                invitacion, _ = InvitacionEvaluacion.objects.get_or_create(

                    plaza=plaza,

                    email=email,

                    defaults={'invitado_por': empresa},

                )

                try:

                    _enviar_invitacion_evaluacion(request, invitacion)

                    if not invitacion.enviado:

                        invitacion.enviado = True

                        invitacion.save(update_fields=['enviado'])

                    enviados += 1

                except Exception as exc:

                    errores.append(f'{email} ({exc})')



            if enviados:

                messages.success(request, f'Se enviaron {enviados} invitación(es) por correo.')

            if errores:

                messages.error(request, 'No se pudieron enviar: ' + ', '.join(errores))



        return redirect('empresa_invitar_participantes', pk=plaza.pk)

    invitaciones = plaza.invitaciones.order_by('-fecha_creacion')
    resultados = Intento.objects.filter(
        postulacion__convocatoria__plaza=plaza

    ).select_related(
        'persona', 'test', 'postulacion', 'postulacion__convocatoria'
    ).order_by('-fecha')

    seleccion_ia = _seleccion_ia_guardada(request, plaza)

    context = {

        'plaza': plaza,

        'empresa': empresa,

        'tests': tests,
        'invitaciones': invitaciones,

        'resultados': resultados,

        'perfiles': _perfiles_para_formulario(),

        'competencias_opciones': _competencias_para_formulario(),

        'sesgos': _sesgos_para_formulario(),

        'perfil_seleccionado': seleccion_ia.get('perfil_objetivo', ''),

        'competencias_seleccionadas': seleccion_ia.get('competencias', []),

        'otros_criterios': seleccion_ia.get('otros_criterios', ''),

        'sesgo_seleccionado': seleccion_ia.get('sesgo', 'equilibrado'),

        'sesgo_detalle': seleccion_ia.get('sesgo_detalle', ''),

    }

    return render(request, 'Empresas/invitar_participantes.html', context)


def empresa_evaluar_participantes_ia(request, pk):

    usuario = get_recluta_user(request)

    empresa = _get_empresa_for_user(usuario)

    if not empresa:

        messages.error(request, 'No se encontró una empresa asociada a tu cuenta.')

        return redirect('empresa_dashboard')



    plaza = get_object_or_404(Plaza, pk=pk, empresa=empresa)

    grupos = _intentos_completados_por_persona(plaza)

    grupos.sort(key=lambda grupo: grupo[0].persona.nombre.lower())



    seleccion_guardada = _seleccion_ia_guardada(request, plaza)

    if not seleccion_guardada:

        analisis_previo = (
            AnalisisIA.objects.filter(
                intento__postulacion__convocatoria__plaza=plaza
            )
            .order_by('-id')
            .first()
        )

        if analisis_previo and isinstance(analisis_previo.perfil, dict):

            perfil_previo = analisis_previo.perfil

            seleccion_guardada = {
                'perfil_objetivo': perfil_previo.get('perfil_objetivo', ''),
                'competencias': perfil_previo.get('competencias') or [],
                'sesgo': perfil_previo.get('sesgo', 'equilibrado'),
                'sesgo_detalle': perfil_previo.get('sesgo_detalle', ''),
                'criterios_texto': perfil_previo.get('criterios', ''),
            }



    if request.method == 'POST':

        criterios, perfil_objetivo, competencias, otros_criterios = (

            _criterios_desde_formulario(request)

        )

        sesgo = request.POST.get('sesgo', 'equilibrado')

        sesgo_detalle = request.POST.get('sesgo_detalle', '')

    else:

        perfil_objetivo = seleccion_guardada.get('perfil_objetivo', '')

        if perfil_objetivo not in PERFILES_OBJETIVO:

            perfil_objetivo = ''

        competencias = [

            clave

            for clave in seleccion_guardada.get('competencias', [])

            if clave in COMPETENCIAS_EVALUACION

        ]

        otros_criterios = seleccion_guardada.get('otros_criterios', '')

        criterios = seleccion_guardada.get('criterios_texto', '')

        if not criterios:

            criterios = _componer_criterios(

                perfil_objetivo,

                competencias,

                otros_criterios,

                (plaza.requisitos or ''),

            )

        sesgo = seleccion_guardada.get('sesgo', 'equilibrado')

        sesgo_detalle = seleccion_guardada.get('sesgo_detalle', '')



    criterios = (criterios or '').strip()

    sesgo = (sesgo or 'equilibrado').strip().lower()

    if sesgo not in SESGOS_CALIFICACION:

        sesgo = 'equilibrado'

    sesgo_detalle = (sesgo_detalle or '').strip()[:500]



    resultados_ia = []

    errores = []



    if request.method == 'POST':

        if not criterios:

            messages.error(

                request,

                'Selecciona un perfil, una competencia o escribe otros criterios.',

            )

        elif not grupos:

            messages.warning(

                request,

                'Todavía no hay participantes que hayan completado una prueba.',

            )

        else:

            _guardar_seleccion_ia(

                request,

                plaza,

                perfil_objetivo,

                competencias,

                otros_criterios,

                sesgo,

                sesgo_detalle,

                criterios,

            )

            contexto_plaza = _contexto_plaza_para_ia(plaza)

            for intentos in grupos:

                persona = intentos[0].persona

                try:

                    resultado = evaluar_candidato_estructurado(

                        respuestas_candidato=_construir_evidencia_candidato(intentos),

                        criterios=criterios,

                        contexto_plaza=contexto_plaza,

                        sesgo_calificacion=sesgo,

                        sesgo_detalle=sesgo_detalle,

                    )

                except Exception as exc:

                    errores.append({'persona': persona, 'error': str(exc)})

                    continue



                analisis = _guardar_analisis_ia(

                    intentos,

                    criterios,

                    resultado,

                    plaza,

                    sesgo=sesgo,

                    sesgo_detalle=sesgo_detalle,

                    perfil_objetivo=perfil_objetivo,

                    competencias=competencias,

                )



                intentos_por_id = {

                    intento.id: intento for intento in intentos

                }

                pruebas_detalle = [

                    {

                        'resultado': prueba,

                        'intento': intentos_por_id.get(

                            prueba.get('intento_id')

                        ),

                    }

                    for prueba in resultado.get('pruebas', [])

                ]

                resultados_ia.append(

                    {

                        'persona': persona,

                        'intentos': intentos,

                        'resultado': resultado,

                        'analisis': analisis,

                        'historial': _historial_analisis(analisis),

                        'sesgo': sesgo,

                        'sesgo_detalle': sesgo_detalle,

                        'perfil_objetivo': perfil_objetivo,

                        'competencias': competencias,

                        'otros_criterios': otros_criterios,

                        'pruebas_detalle': pruebas_detalle,

                    }

                )



            _decorar_resultados_ia(resultados_ia)

            if resultados_ia:

                messages.success(

                    request,

                    f'Se evaluaron {len(resultados_ia)} participante(s) correctamente.',

                )

            if errores:

                messages.error(

                    request,

                    f'No se pudieron evaluar {len(errores)} participante(s).',

                )



    candidatos = []

    for intentos in grupos:

        representante = intentos[0]

        analisis = _analisis_guardado(intentos)

        perfil_guardado = (

            analisis.perfil

            if analisis and isinstance(analisis.perfil, dict)

            else {}

        )

        candidatos.append(

            {

                'persona': representante.persona,

                'intentos': intentos,

                'analisis': analisis,

                'historial': _historial_analisis(analisis),

                'nivel': _nivel_puntaje(perfil_guardado.get('puntaje')),

                'barras_dimensiones': _barras_dimensiones(intentos),

            }

        )



    evaluados_ids = {item['persona'].id for item in resultados_ia}

    for candidato in candidatos:

        if candidato['persona'].id in evaluados_ids:

            continue

        analisis = candidato['analisis']

        if not analisis:

            continue



        intentos = candidato['intentos']

        intentos_por_id = {intento.id: intento for intento in intentos}

        resultado = _resultado_desde_analisis(analisis)

        pruebas_detalle = [

            {

                'resultado': prueba,

                'intento': intentos_por_id.get(prueba.get('intento_id')),

            }

            for prueba in resultado.get('pruebas') or []

        ]

        resultados_ia.append(

            {

                'persona': candidato['persona'],

                'intentos': intentos,

                'resultado': resultado,

                'analisis': analisis,

                'historial': candidato['historial'],

                'pruebas_detalle': pruebas_detalle,

            }

        )

    _decorar_resultados_ia(resultados_ia)



    candidatos_pendientes = [

        candidato for candidato in candidatos if not candidato['analisis']

    ]



    context = {

        'plaza': plaza,

        'empresa': empresa,

        'criterios': criterios,

        'sesgo': sesgo,

        'sesgo_detalle': sesgo_detalle,

        'sesgo_label': describir_sesgo_calificacion(sesgo, sesgo_detalle),

        'sesgos': _sesgos_para_formulario(),

        'perfiles': _perfiles_para_formulario(),

        'competencias_opciones': _competencias_para_formulario(),

        'perfil_objetivo': perfil_objetivo,

        'competencias_seleccionadas': competencias,

        'otros_criterios': otros_criterios,

        'candidatos': candidatos,

        'candidatos_pendientes': candidatos_pendientes,

        'total_candidatos': len(candidatos),

        'resultados_ia': resultados_ia,

        'errores': errores,
        'fabric_embed_url': getattr(
            settings, 'FABRIC_POWERBI_EMBED_URL', ''
        ),
        'fabric_workspace_url': getattr(
            settings, 'FABRIC_WORKSPACE_URL', ''
        ),
        'fabric_ingest_configurado': bool(
            getattr(settings, 'FABRIC_INGEST_URL', '')
        ),
    }

    return render(request, 'Empresas/evaluar_participantes_ia.html', context)





@login_required(login_url='login')

def api_asistente_criterios_evaluacion(request, pk):

    if request.method != 'POST':

        return JsonResponse({'error': 'Método no permitido'}, status=405)



    usuario = get_recluta_user(request)

    empresa = _get_empresa_for_user(usuario)

    if not empresa:

        return JsonResponse(

            {'error': 'No se encontró una empresa asociada a tu cuenta.'},

            status=403,

        )



    plaza = get_object_or_404(Plaza, pk=pk, empresa=empresa)



    try:

        data = json.loads(request.body or '{}')

    except json.JSONDecodeError:

        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)



    mensaje = str(data.get('mensaje', '')).strip()

    if not mensaje:

        return JsonResponse({'error': 'El mensaje está vacío.'}, status=400)

    if len(mensaje) > 2000:

        return JsonResponse(

            {'error': 'El mensaje es demasiado largo.'}, status=400

        )



    historial = data.get('historial', [])

    if not isinstance(historial, list):

        historial = []



    criterios_actuales = str(data.get('criterios', '')).strip()[:2000]

    sesgo_actual = str(data.get('sesgo', '')).strip()



    try:

        resultado = asistente_criterios_evaluacion(

            contexto_plaza=_contexto_plaza_para_ia(plaza),

            historial=historial,

            mensaje=mensaje,

            criterios_actuales=criterios_actuales,

            sesgo_actual=sesgo_actual,

        )

    except Exception as exc:

        return JsonResponse({'error': str(exc)}, status=500)



    seleccion = _seleccion_ia_guardada(request, plaza)

    criterios_guardados = (

        str(resultado.get('criterios') or '').strip()

        or seleccion.get('criterios_texto', '')

        or criterios_actuales

    )

    sesgo_guardado = (

        str(resultado.get('sesgo') or '').strip()

        or seleccion.get('sesgo', '')

        or sesgo_actual

        or 'equilibrado'

    )

    if sesgo_guardado not in SESGOS_CALIFICACION:

        sesgo_guardado = 'equilibrado'

    sesgo_detalle_guardado = str(

        resultado.get('sesgo_detalle')

        or seleccion.get('sesgo_detalle', '')

    ).strip()[:500]



    _guardar_seleccion_ia(

        request,

        plaza,

        seleccion.get('perfil_objetivo', ''),

        seleccion.get('competencias', []),

        seleccion.get('otros_criterios', ''),

        sesgo_guardado,

        sesgo_detalle_guardado,

        criterios_guardados[:2000],

    )



    return JsonResponse(resultado)


@login_required(login_url='login')
def empresa_exportar_evaluacion_fabric(request, pk):
    """Descarga los resultados de la vacante en CSV o JSON para Fabric."""
    usuario = get_recluta_user(request)
    empresa = _get_empresa_for_user(usuario)
    if not empresa:
        messages.error(
            request,
            'No se encontró una empresa asociada a tu cuenta.',
        )
        return redirect('empresa_dashboard')

    plaza = get_object_or_404(Plaza, pk=pk, empresa=empresa)
    datos = _datos_exportacion_fabric(plaza)

    formato = (request.GET.get('formato') or 'csv').strip().lower()
    marca = timezone.now().strftime('%Y%m%d_%H%M')
    nombre_base = f'evaluacion_ia_plaza_{plaza.id}_{marca}'

    if formato == 'json':
        response = JsonResponse(
            datos,
            json_dumps_params={'ensure_ascii': False, 'indent': 2},
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{nombre_base}.json"'
        )
        return response

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="{nombre_base}.csv"'
    )
    response.write('\ufeff')
    writer = csv.DictWriter(
        response,
        fieldnames=FABRIC_CAMPOS_CSV,
        extrasaction='ignore',
    )
    writer.writeheader()
    for fila in _filas_csv_fabric(datos):
        writer.writerow(fila)
    return response


@login_required(login_url='login')
def empresa_enviar_evaluacion_fabric(request, pk):
    """Envía el JSON de resultados al endpoint de ingesta de Fabric."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    usuario = get_recluta_user(request)
    empresa = _get_empresa_for_user(usuario)
    if not empresa:
        return JsonResponse(
            {'error': 'No se encontró una empresa asociada a tu cuenta.'},
            status=403,
        )

    plaza = get_object_or_404(Plaza, pk=pk, empresa=empresa)

    url_ingesta = getattr(settings, 'FABRIC_INGEST_URL', '')
    if not url_ingesta:
        return JsonResponse(
            {
                'error': (
                    'Falta configurar FABRIC_INGEST_URL en el servidor '
                    'para enviar datos a Microsoft Fabric.'
                )
            },
            status=400,
        )

    datos = _datos_exportacion_fabric(plaza)
    headers = {'Content-Type': 'application/json'}
    token = getattr(settings, 'FABRIC_INGEST_TOKEN', '')
    if token:
        headers['Authorization'] = f'Bearer {token}'

    try:
        respuesta = requests.post(
            url_ingesta,
            json=datos,
            headers=headers,
            timeout=30,
        )
        respuesta.raise_for_status()
    except Exception as exc:
        return JsonResponse(
            {'error': f'No se pudo enviar a Fabric: {exc}'},
            status=502,
        )

    return JsonResponse(
        {
            'ok': True,
            'mensaje': (
                f'Se enviaron {datos.get("total_candidatos", 0)} '
                'candidato(s) a Microsoft Fabric.'
            ),
        }
    )




def evaluacion_invitacion(request, token):

    invitacion = get_object_or_404(InvitacionEvaluacion, token=token)

    next_url = reverse('evaluacion_invitacion', args=[token])



    if invitacion.plaza.esta_vencida:

        request.session.pop('plaza_evaluacion_id', None)

        request.session.pop('invitacion_token', None)

        messages.warning(request, 'La convocatoria ha finalizado y ya no recibe evaluaciones.')

        return redirect('home')



    if invitacion.plaza.esta_vencida:
        request.session.pop('plaza_evaluacion_id', None)
        request.session.pop('invitacion_token', None)
        messages.warning(request, 'La convocatoria ha finalizado y ya no recibe evaluaciones.')
        return redirect('home')

    if not request.user.is_authenticated:

        messages.info(

            request,

            'Inicia sesión o regístrate con el correo invitado para ingresar a la evaluación.',

        )

        return redirect(

            f"{reverse('login')}?next={quote(next_url)}&email={quote(invitacion.email)}"

        )



    usuario = get_recluta_user(request)

    if not usuario:

        return redirect(

            f"{reverse('login')}?next={quote(next_url)}&email={quote(invitacion.email)}"

        )



    if usuario.rol in ('empresa', 'superadmin'):

        messages.error(request, 'Solo los profesionales pueden rendir esta evaluación.')

        if usuario.rol == 'empresa':

            return redirect('empresa_dashboard')

        return redirect('superadmin_dashboard')



    persona = _get_persona_for_user(usuario)

    emails_usuario = {

        e.lower() for e in [usuario.email, getattr(persona, 'email', '')] if e

    }

    if invitacion.email.lower() not in emails_usuario:

        messages.error(

            request,

            f'Esta invitación fue enviada a {invitacion.email}. '

            f'Inicia sesión con ese correo para rendir la evaluación.',

        )

        return redirect('home_profesionales')



    if not invitacion.usado:

        invitacion.usado = True

        invitacion.fecha_uso = timezone.now()

        invitacion.save(update_fields=['usado', 'fecha_uso'])



    request.session['plaza_evaluacion_id'] = invitacion.plaza_id

    request.session['invitacion_token'] = invitacion.token



    plaza = invitacion.plaza

    tests = plaza.tests.filter(estado=EstadoTest.PUBLICADO).order_by('id')

    if not tests.exists():

        messages.warning(request, 'Esta vacante no tiene pruebas configuradas.')

        return redirect('home_profesionales')



    if tests.count() == 1:

        return redirect('test', test_id=tests.first().id)



    context = {

        'plaza': plaza,

        'tests': tests,

        'invitacion': invitacion,

    }

    return render(request, 'Empresas/evaluacion_vacante.html', context)





@api_view(['GET', 'POST'])

@permission_classes([AllowAny]) 

def api_lista_empresas(request):

    if request.method == 'GET':

        empresas = Empresa.objects.all()

        serializer = EmpresaSerializer(empresas, many=True)

        return Response(serializer.data)

    

    elif request.method == 'POST':

        serializer = EmpresaSerializer(data=request.data)

        if serializer.is_valid():

            serializer.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





@api_view(['GET', 'POST'])

@permission_classes([AllowAny]) # Temporal para pruebas en Postman

def api_lista_tickets(request):

    if request.method == 'GET':

        serializer = TicketSerializer(TICKETS_MOCK, many=True)

        return Response(serializer.data)

    

    elif request.method == 'POST':

        serializer = TicketSerializer(data=request.data)

        if serializer.is_valid():

            nuevo_ticket = serializer.validated_data

            nuevo_ticket['id'] = len(TICKETS_MOCK) + 1

            TICKETS_MOCK.append(nuevo_ticket)

            return Response(nuevo_ticket, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





@never_cache

def login_view(request):

    next_url = _obtener_next(request)

    if request.method == 'POST':

        username_ingresado = request.POST.get('username')

        password_ingresada = request.POST.get('password')



        try:

            usuario_obj = Usuario.objects.filter(nombre_usuario=username_ingresado).first()

            if not usuario_obj or not verificar_contrasena(usuario_obj, password_ingresada):

                messages.error(request, 'Usuario o contraseña incorrectos.')

                return render(request, 'login.html')



            if not usuario_obj.activo:

                messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')

                return render(request, 'login.html')



            if es_contrasena_hasheada(usuario_obj.contrasena):

                django_user = crear_o_actualizar_django_user(

                    usuario_obj,

                    password=password_ingresada,

                )

            else:

                django_user = actualizar_contrasena(

                    usuario_obj,

                    password_ingresada,

                )

            django_user.backend = 'django.contrib.auth.backends.ModelBackend'

            auth_login(request, django_user)



            rol = getattr(usuario_obj, 'rol', None)



            if next_url and (

                rol == 'profesional'

                or Persona.objects.filter(usuario=usuario_obj).exists()

            ):

                return redirect(next_url)



            if rol == 'superadmin':

                return redirect('superadmin_dashboard')

            if rol == 'empresa':

                return redirect('empresa_dashboard')

            if rol == 'profesional':

                return redirect('home_profesionales')



            # Fallback por si hay cuentas antiguas sin rol

            if Empresa.objects.filter(usuario=usuario_obj).exists():

                return redirect('empresa_dashboard')

            if Persona.objects.filter(usuario=usuario_obj).exists():

                return redirect('home_profesionales')



            messages.error(request, 'No se pudo determinar el tipo de cuenta.')

            return redirect('login')



        except Exception as e:

            print("--- ERROR CRÍTICO EN LOGIN ---", e)

            messages.error(request, 'Ocurrió un error al iniciar sesión.')

            return render(request, 'login.html')



    return render(request, 'login.html')





def logout_view(request):

    logout(request)

    return redirect('login')



@never_cache

def registro_view(request):

    next_url = _obtener_next(request)

    if request.method == 'POST':

        username = request.POST.get('username', '').strip()

        nombre = request.POST.get('nombre', '').strip() or username

        email = request.POST.get('email', '').strip()

        password = request.POST.get('password', '')



        if not username or not email or not password:

            messages.error(request, 'Todos los campos son obligatorios.')

            return render(request, 'registro.html')



        if Usuario.objects.filter(nombre_usuario=username).exists():

            messages.error(request, 'Ese nombre de usuario ya está en uso.')

            return render(request, 'registro.html')



        if Usuario.objects.filter(email=email).exists():

            messages.error(request, 'Ese correo ya está registrado.')

            return render(request, 'registro.html')



        usuario = Usuario(

            nombre_usuario=username,

            email=email,

            contrasena='',

            rol='profesional',

        )

        try:

            validar_contrasena(password, usuario)

        except ValidationError as exc:

            for error in exc.messages:

                messages.error(request, error)

            return render(request, 'registro.html')



        try:

            usuario.save()

            Persona.objects.create(

                nombre=nombre,

                email=email,

                usuario=usuario

            )



            django_user = actualizar_contrasena(usuario, password)

            django_user.backend = 'django.contrib.auth.backends.ModelBackend'

            auth_login(request, django_user)



            messages.success(request, '¡Cuenta creada correctamente! Bienvenido a ReclutaMente.')

            return redirect(next_url or 'home_profesionales')



        except Exception as e:

            print("--- ERROR EN REGISTRO ---", e)

            messages.error(request, 'Ocurrió un error al crear la cuenta. Intenta nuevamente.')

            return render(request, 'registro.html')



    return render(request, 'registro.html')



# Vistas principales (SIN decoradores restrictivos por ahora)

def dashboard_general(request):

        # Usamos un bloque try-except por si la base de datos o las tablas aún no están migradas

        try:

            total_vacantes = Vacante.objects.count()

        except:

            total_vacantes = 0

        return render(request, 'core/dashboard_general.html', {'total_vacantes': total_vacantes})





def catalogo_plazas(request):

    try:

        # 1. Obtenemos los parámetros de filtro desde la URL (método GET)

        busqueda = request.GET.get('q', '').strip()

        ubicacion = request.GET.get('ubicacion', '').strip()

        modalidad = request.GET.get('modalidad', '').strip()



        # 2. Partimos de todas las vacantes ordenadas por fecha o ID (opcional)

        vacantes = Vacante.objects.all().order_by('-id')



        # 3. Aplicamos los filtros condicionales si el usuario escribió o seleccionó algo

        if busqueda:

            # Filtra por título o descripción usando Q para buscar en ambos campos

            vacantes = vacantes.filter(

                Q(titulo__icontains=busqueda) | Q(descripcion__icontains=busqueda)

            )

        

        if ubicacion:

            vacantes = vacantes.filter(ubicacion__icontains=ubicacion)

            

        if modalidad:

            vacantes = vacantes.filter(modalidad=modalidad)



    except Exception:

        vacantes = []



    # 4. Enviamos tanto las vacantes filtradas como los valores actuales para mantenerlos en los inputs

    context = {

        'vacantes': vacantes,

        'busqueda_filtro': busqueda,

        'ubicacion_filtro': ubicacion,

        'modalidad_filtro': modalidad,

    }

    

    return render(request, 'core/catalogo_plazFas.html', context)



def crear_vacante(request):

        if request.method == 'POST':

            puesto = request.POST.get('puesto')

            departamento = request.POST.get('departamento')

            try:

                empresa = Empresa.objects.first() 

                if not empresa:

                    empresa = Empresa.objects.create(nombre="Empresa Predeterminada")

                    

                Vacante.objects.create(

                    empresa=empresa,

                    puesto=puesto,

                    departamento=departamento,

                    estado='Activa'

                )

            except:

                pass # Evita errores si la base de datos aún no tiene tablas migradas

            return redirect('catalogo_plazas')

        

        return render(request, 'core/crear_vacante.html')



def organizacion(request):

        return render(request, 'core/organizacion.html')



def perfil(request):

        return render(request, 'core/perfil.html')



# --- VISTAS DE SUPERADMIN ---

@login_required(login_url='login')

def superadmin_tickets(request):

    # Procesar el formulario cuando el super admin responde o cambia el estado

    if request.method == 'POST':

        ticket_id = request.POST.get('ticket_id')

        nuevo_estado = request.POST.get('estado')

        respuesta = request.POST.get('respuesta_admin')



        try:

            ticket = Ticket.objects.get(id=ticket_id)

            if nuevo_estado:

                ticket.estado = nuevo_estado

            if respuesta is not None:

                ticket.respuesta_admin = respuesta

            ticket.save()

            messages.success(request, f'Ticket #{ticket.id} actualizado correctamente.')

            return redirect('superadmin_tickets')

        except Ticket.DoesNotExist:

            messages.error(request, 'El ticket no existe.')



    # Filtros de búsqueda

    codigo_filtro = request.GET.get('codigo', '')

    empresa_filtro = request.GET.get('empresa', '')

    estado_filtro = request.GET.get('estado', '')



    tickets = Ticket.objects.all().order_by('-fecha_creacion')



    if codigo_filtro:

        tickets = tickets.filter(codigo__icontains=codigo_filtro)

    if empresa_filtro:

        tickets = tickets.filter(empresa__nombre__icontains=empresa_filtro)

    if estado_filtro:

        tickets = tickets.filter(estado__icontains=estado_filtro)



    context = {

        'tickets': tickets,

        'codigo_filtro': codigo_filtro,

        'empresa_filtro': empresa_filtro,

        'estado_filtro': estado_filtro,

    }

    

    # <-- Aquí estaba el detalle: faltaba incluir el 'context' en el render

    return render(request, 'superAdmin/superadmin_tickets.html', context)





def superadmin_ticket_detalle(request, pk):

    # Busca el ticket usando el ID que viene en la URL

    ticket = get_object_or_404(Ticket, pk=pk)

    

    # Renderiza la plantilla enviándole el ticket

    return render(request, 'superAdmin/superadmin_ticket_detalle.html', {'ticket': ticket})





@login_required(login_url='login')

def superadmin_empresa_detalle(request, pk):

    empresa = get_object_or_404(Empresa, pk=pk)

    context = {'empresa': empresa}

    return render(request, 'superadmin/superadmin_empresa_detalle.html', context)



@login_required(login_url='login')

def superadmin_empresas_ia(request, pk):

    empresa = get_object_or_404(Empresa, pk=pk)

    context = {'empresa': empresa}

    return render(request, 'superadmin/superadmin_empresas_ia.html', context)





@login_required(login_url='login')

@login_required(login_url='login')

def superadmin_toggle_profesional(request, pk):

    persona = get_object_or_404(Persona, pk=pk)

    usuario = persona.usuario

    if request.method == 'POST':

        if usuario:

            usuario.activo = not bool(usuario.activo)

            usuario.save(update_fields=['activo'])

            if usuario.activo:

                estado = 'activada'

            else:

                estado = 'desactivada'

            registrar_en_bitacora(

                request.user,

                estado.capitalize() + " la cuenta del profesional: " + persona.nombre + " (" + usuario.nombre_usuario + ")",

                "Profesionales",

            )

            messages.success(request, 'Cuenta ' + estado + ' correctamente.')

        else:

            messages.error(request, 'No hay usuario asociado a este profesional.')

    return redirect('superadmin_profesionales')





def superadmin_profesionales(request):

    try:

        nombre_filtro = request.GET.get('nombre', '').strip()

        prueba_filtro = request.GET.get('prueba', '').strip()



        # Partimos de las personas (profesionales) registradas

        profesionales = Persona.objects.all().prefetch_related('intentos__test', 'intentos__certificado').order_by('-id')



        if nombre_filtro:

            profesionales = profesionales.filter(nombre__icontains=nombre_filtro)

            

        if prueba_filtro:

            profesionales = profesionales.filter(intentos__test__nombre__icontains=prueba_filtro).distinct()



    except Exception as e:

        print("Error al filtrar profesionales:", e)

        profesionales = []

        nombre_filtro = ''

        prueba_filtro = ''



    context = {

        'profesionales': profesionales, # Usamos la variable que tu HTML ya espera

        'nombre_filtro': nombre_filtro,

        'prueba_filtro': prueba_filtro,

    }

    

    return render(request, 'superAdmin/superadmin_profesionales.html', context)



@login_required(login_url='login')

def superadmin_perfil(request):

    usuario = get_recluta_user(request)



    if not usuario:

        messages.error(request, 'No se encontró tu cuenta de administrador.')

        return redirect('login')



    if request.method == 'POST':

        nombre_usuario = request.POST.get('nombre_usuario', '').strip()

        email = request.POST.get('email', '').strip()

        contrasena_actual = request.POST.get('contrasena_actual', '')

        contrasena_nueva = request.POST.get('contrasena_nueva', '')

        contrasena_confirmar = request.POST.get('contrasena_confirmar', '')



        errores = []



        if not nombre_usuario or not email:

            errores.append('El nombre de usuario y el correo son obligatorios.')



        if nombre_usuario and nombre_usuario != usuario.nombre_usuario:

            if Usuario.objects.filter(nombre_usuario=nombre_usuario).exclude(pk=usuario.pk).exists():

                errores.append('Ese nombre de usuario ya está en uso.')



        if email and email != usuario.email:

            if Usuario.objects.filter(email=email).exclude(pk=usuario.pk).exists():

                errores.append('Ese correo electrónico ya está registrado.')



        if contrasena_nueva or contrasena_confirmar or contrasena_actual:

            if not verificar_contrasena(usuario, contrasena_actual):

                errores.append('La contraseña actual es incorrecta.')

            elif not contrasena_nueva or contrasena_nueva != contrasena_confirmar:

                errores.append('La nueva contraseña y su confirmación no coinciden.')

            else:

                try:

                    validar_contrasena(

                        contrasena_nueva,

                        usuario,

                        django_user=request.user,

                    )

                except ValidationError as exc:

                    errores.extend(exc.messages)



        if errores:

            for error in errores:

                messages.error(request, error)

        else:

            try:

                usuario.nombre_usuario = nombre_usuario

                usuario.email = email

                usuario.save()



                django_user = request.user

                django_user.username = nombre_usuario

                django_user.email = email

                django_user.save()



                if contrasena_nueva:

                    actualizar_contrasena(

                        usuario,

                        contrasena_nueva,

                        django_user=django_user,

                    )



                registrar_en_bitacora(

                    request.user,

                    f"Actualizó su perfil de superadmin ({usuario.nombre_usuario})",

                    "Perfil"

                )

                messages.success(request, 'Perfil actualizado correctamente.')

            except Exception as e:

                messages.error(request, f'No se pudo actualizar el perfil: {e}')



        return redirect('superadmin_perfil')



    return render(request, 'superAdmin/superadmin_perfil.html', {'usuario': usuario})





def superadmin_ticket_cancelar(request, pk):

    ticket = get_object_or_404(Ticket, pk=pk)

    if request.method == 'POST':

        # Cambia el estado a cancelado o elimínalo según tu lógica

        ticket.estado = 'Cancelado' 

        ticket.save()

        # Redirige de vuelta a la lista de tickets

        return redirect('superadmin_tickets_lista') # Cambia esto por el nombre de tu vista de lista

    return redirect('superadmin_ticket_detalle', pk=pk)



def superadmin_ticket_modificar(request, pk):

    ticket = get_object_or_404(Ticket, pk=pk)

    

    if request.method == 'POST':

        # Capturamos los datos enviados por el formulario

        nuevo_estado = request.POST.get('estado')

        respuesta = request.POST.get('respuesta_admin')

        

        # Actualizamos el ticket si los campos tienen valor

        if nuevo_estado:

            ticket.estado = nuevo_estado

            

        if respuesta is not None:

            ticket.respuesta_admin = respuesta

            

        # Guardamos en la base de datos

        ticket.save()

        

        # Redirigimos de vuelta al listado de tickets del superadmin

        return redirect('superadmin_tickets')

        

    return render(request, 'superAdmin/superadmin_ticket_modificar.html', {'ticket': ticket})





@solo_profesional

def home_profesionales(request):

    usuario = get_recluta_user(request)

    if not usuario:

        return redirect('login')

    if not usuario.activo:

        messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')

        return redirect('login')

    if _get_empresa_for_user(usuario):

        return redirect('empresa_dashboard')

    persona = _get_persona_for_user(usuario)

    if not persona:

        messages.error(request, 'No tienes un perfil de profesional asociado a esta cuenta.')

        return redirect('login')

    intentos = []

    certificaciones = []

    try:

        intentos = list(persona.intentos.select_related('test','test__categoria').order_by('-fecha'))

    except Exception as e:

        print("--- ERROR EN PANEL DEL PROFESIONAL ---", e)

    try:

        certificaciones = Certificado.objects.filter(intento__persona=persona).select_related('intento','intento__test','intento__test__categoria')

    except Exception as e:

        print("--- ERROR AL OBTENER CERTIFICACIONES ---", e)

    total_completadas = sum(1 for i in intentos if i.estado == EstadoIntento.COMPLETADO)

    total_en_progreso = sum(1 for i in intentos if i.estado in (EstadoIntento.EN_PROGRESO, EstadoIntento.INICIADO))

    context = {'persona': persona, 'certificaciones': certificaciones, 'intentos': intentos, 'categorias': Categoria.objects.all(), 'total_certificaciones': len(certificaciones), 'total_completadas': total_completadas, 'total_en_progreso': total_en_progreso}

    return render(request, 'Profesionales/home_profesionales.html', context)





@solo_profesional

def profesional_perfil(request):

    usuario = get_recluta_user(request)

    if not usuario:

        return redirect('login')

    if not usuario.activo:

        messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')

        return redirect('login')

    if _get_empresa_for_user(usuario):

        return redirect('empresa_dashboard')

    persona = _get_persona_for_user(usuario)

    if not persona:

        messages.error(request, 'No tienes un perfil de profesional asociado a esta cuenta.')

        return redirect('login')



    if request.method == 'POST':

        nombre = request.POST.get('nombre', '').strip()

        email = request.POST.get('email', '').strip()

        telefono = request.POST.get('telefono', '').strip()

        contrasena_actual = request.POST.get('contrasena_actual', '')

        contrasena_nueva = request.POST.get('contrasena_nueva', '')

        contrasena_confirmar = request.POST.get('contrasena_confirmar', '')



        errores = []



        if not nombre or not email:

            errores.append('El nombre y el correo son obligatorios.')



        if email and email != persona.email:

            if Persona.objects.filter(email=email).exclude(pk=persona.pk).exists():

                errores.append('Ese correo electrónico ya está registrado por otro profesional.')



        cuenta = persona.usuario

        if contrasena_nueva or contrasena_confirmar or contrasena_actual:

            if not cuenta or not verificar_contrasena(cuenta, contrasena_actual):

                errores.append('La contraseña actual es incorrecta.')

            elif not contrasena_nueva or contrasena_nueva != contrasena_confirmar:

                errores.append('La nueva contraseña y su confirmación no coinciden.')

            else:

                try:

                    validar_contrasena(

                        contrasena_nueva,

                        cuenta,

                        django_user=request.user,

                    )

                except ValidationError as exc:

                    errores.extend(exc.messages)



        if errores:

            for error in errores:

                messages.error(request, error)

        else:

            try:

                persona.nombre = nombre

                persona.email = email

                persona.telefono = telefono

                persona.save()



                if cuenta:

                    cuenta.email = email

                    cuenta.save()



                    request.user.email = email

                    request.user.save()



                    if contrasena_nueva:

                        actualizar_contrasena(

                            cuenta,

                            contrasena_nueva,

                            django_user=request.user,

                        )



                messages.success(request, 'Perfil actualizado correctamente.')

            except Exception as e:

                messages.error(request, f'No se pudo actualizar el perfil: {e}')



        return redirect('profesional_perfil')



    try:

        intentos = list(

            persona.intentos.select_related('test', 'test__categoria').order_by('-fecha')

        )

        certificaciones = Certificado.objects.filter(intento__persona=persona).select_related(

            'intento', 'intento__test', 'intento__test__categoria'

        )

    except Exception as e:

        print("--- ERROR EN PERFIL DEL PROFESIONAL ---", e)

        intentos = []

        certificaciones = []



    total_completadas = sum(1 for i in intentos if i.estado == EstadoIntento.COMPLETADO)

    total_en_progreso = sum(1 for i in intentos if i.estado in (EstadoIntento.EN_PROGRESO, EstadoIntento.INICIADO))



    context = {

        'persona': persona,

        'certificaciones': certificaciones,

        'total_certificaciones': len(certificaciones),

        'total_completadas': total_completadas,

        'total_en_progreso': total_en_progreso,

    }

    return render(request, 'Profesionales/perfil.html', context)









@solo_profesional
def profesional_certificaciones(request):
    usuario = get_recluta_user(request)
    if not usuario:
        return redirect('login')
    if not usuario.activo:
        messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')
        return redirect('login')
    if _get_empresa_for_user(usuario):
        return redirect('empresa_dashboard')
    persona = _get_persona_for_user(usuario)
    if not persona:
        messages.error(request, 'No tienes un perfil de profesional asociado a esta cuenta.')
        return redirect('login')

    intentos = []
    certificaciones = []
    try:
        intentos = list(
            persona.intentos.select_related('test', 'test__categoria')
            .prefetch_related('respuestas', 'analisis_ia')
            .order_by('-fecha')
        )
    except Exception as e:
        print('--- ERROR EN CERTIFICACIONES DEL PROFESIONAL ---', e)

    try:
        certificaciones = Certificado.objects.filter(
            intento__persona=persona
        ).select_related('intento', 'intento__test', 'intento__test__categoria')
    except Exception as e:
        print('--- ERROR AL OBTENER CERTIFICACIONES ---', e)

    total_completadas = sum(1 for i in intentos if i.estado == EstadoIntento.COMPLETADO)
    total_en_progreso = sum(1 for i in intentos if i.estado in (EstadoIntento.EN_PROGRESO, EstadoIntento.INICIADO))
    total_certificaciones = certificaciones.count() if hasattr(certificaciones, 'count') else len(certificaciones)

    context = {
        'persona': persona,
        'intentos': intentos,
        'certificaciones': certificaciones,
        'total_intentos': len(intentos),
        'total_completadas': total_completadas,
        'total_en_progreso': total_en_progreso,
        'total_certificaciones': total_certificaciones,
        'EstadoIntento': EstadoIntento,
    }
    return render(request, 'Profesionales/certificaciones.html', context)


@solo_profesional
def descargar_certificado(request, certificado_id):
    usuario = get_recluta_user(request)
    persona = _get_persona_for_user(usuario)
    certificado = get_object_or_404(
        Certificado.objects.select_related(
            'intento', 'intento__persona', 'intento__test'
        ),
        id=certificado_id,
        intento__persona=persona,
    )

    contenido = generar_pdf_certificado(certificado)
    response = HttpResponse(contenido, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="certificado-{certificado.codigo_verificacion}.pdf"'
    )
    response['Content-Length'] = len(contenido)
    return response


def contacto_empresas(request):
    datos = {
        'nombre_empresa': '',
        'email': '',
        'telefono': '',
        'razon': '',
    }

    if request.method == 'POST':
        nombre_empresa = request.POST.get('nombre_empresa', '').strip()
        email_contacto = request.POST.get('email', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        razon = request.POST.get('razon', '').strip()

        datos = {
            'nombre_empresa': nombre_empresa,
            'email': email_contacto,
            'telefono': telefono,
            'razon': razon,
        }

        if not nombre_empresa or not email_contacto or not telefono or not razon:
            messages.error(request, 'Todos los campos son obligatorios.')
            return render(request, 'contacto.html', {'datos': datos})

        try:
            validate_email(email_contacto)
        except ValidationError:
            messages.error(request, 'Ingresa un correo electrónico válido.')
            return render(request, 'contacto.html', {'datos': datos})

        # Destinatario principal: el correo corporativo configurado para ReclutaMente.
        destinatarios = [getattr(settings, 'EMAIL_CONTACTO_RECLUTAMENTE', 'reeclutamente@gmail.com')]

        # Registramos también como ticket para trazabilidad en el panel SuperAdmin
        try:
            empresa_existente = Empresa.objects.filter(
                Q(nombre__iexact=nombre_empresa) | Q(usuario__email__iexact=email_contacto)
            ).first()
            conteo = Ticket.objects.count() + 1
            codigo_ticket = f"CONT-{conteo:03d}"
            while Ticket.objects.filter(codigo=codigo_ticket).exists():
                conteo += 1
                codigo_ticket = f"CONT-{conteo:03d}"

            Ticket.objects.create(
                codigo=codigo_ticket,
                empresa=empresa_existente,
                tipo='Soporte General',
                asunto=f"Contacto empresa: {nombre_empresa}",
                destino='Plataforma General',
                rango_fechas=telefono,
                descripcion=(
                    f"Empresa: {nombre_empresa}\n"
                    f"Correo: {email_contacto}\n"
                    f"Teléfono: {telefono}\n\n"
                    f"Motivo de contacto:\n{razon}"
                ),
                estado='Abierto',
            )
        except Exception as e:
            print('--- ERROR AL REGISTRAR TICKET DE CONTACTO ---', e)

        asunto_correo = f"[ReclutaMente] Solicitud de contacto corporativo: {nombre_empresa}"
        mensaje_texto = (
            f"Nueva solicitud de contacto para empresas en ReclutaMente.\n\n"
            f"Empresa: {nombre_empresa}\n"
            f"Correo electrónico: {email_contacto}\n"
            f"Teléfono: {telefono}\n\n"
            f"Razón de contacto:\n{razon}\n"
        )
        mensaje_html = (
            f"<div style='font-family: Inter, Arial, sans-serif; color: #18181b; max-width: 600px;'>"
            f"<h2 style='color: #1e1b4b; margin-bottom: 8px;'>Nueva solicitud de contacto corporativo</h2>"
            f"<p style='color: #52525b; font-size: 14px;'>Se ha recibido un mensaje desde el formulario de contacto para empresas en <strong>ReclutaMente</strong>.</p>"
            f"<hr style='border: none; border-top: 1px solid #e4e4e7; margin: 20px 0;'>"
            f"<p><strong>Nombre de la empresa:</strong> {nombre_empresa}</p>"
            f"<p><strong>Correo electrónico:</strong> <a href='mailto:{email_contacto}'>{email_contacto}</a></p>"
            f"<p><strong>Teléfono:</strong> {telefono}</p>"
            f"<p><strong>Razón por la que nos contacta:</strong></p>"
            f"<div style='background: #f4f4f5; padding: 14px; border-radius: 8px; white-space: pre-line;'>{razon}</div>"
            f"</div>"
        )

        try:
            correo = EmailMultiAlternatives(
                asunto_correo,
                mensaje_texto,
                None,
                destinatarios,
                reply_to=[email_contacto],
            )
            correo.attach_alternative(mensaje_html, 'text/html')
            correo.send(fail_silently=False)
            messages.success(
                request,
                '¡Gracias por contactarnos! Tu solicitud fue enviada al administrador y nos comunicaremos con tu empresa pronto.'
            )
            return redirect('contacto')
        except Exception as e:
            print('--- ERROR AL ENVIAR CORREO DE CONTACTO ---', e)
            messages.success(
                request,
                '¡Tu solicitud fue registrada correctamente! Nuestro equipo administrativo se pondrá en contacto con tu empresa pronto.'
            )
            return redirect('contacto')

    return render(request, 'contacto.html', {'datos': datos})


