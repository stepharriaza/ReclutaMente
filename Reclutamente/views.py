from django.db import models
from django.http import request
from django.shortcuts import get_object_or_404, render
from django.shortcuts import render, redirect
from core.models import Plaza, Empresa, Ticket, Persona, Usuario, PruebaGeneradaEmpresa
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
from core.models import Certificado, EstadoIntento
from django.db.models import Q
from core.models import Bitacora
from django.contrib.auth import login as auth_login
from django.contrib.auth import authenticate 
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from google import genai
from django.conf import settings
from django.http import JsonResponse
from urllib.parse import quote
import json
import io
import re
import qrcode
from core.decorators import (
    solo_profesional,
    solo_empresa,
    solo_superadmin,
    get_recluta_user,
    )
from core.services import (
    evaluar_candidato_con_criterios_empresa,
    generar_o_modificar_prueba,
)
from core.services import generar_contenido_seguro


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
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            mensaje_usuario = data.get('mensaje', '')
            
            if not mensaje_usuario:
                return JsonResponse({'error': 'El mensaje está vacío.'}, status=400)
            
            prompt = f"Actúa como un asistente virtual experto en reclutamiento y soporte para la plataforma ReclutaMente. Responde de forma clara y profesional: {mensaje_usuario}"
            
            respuesta_texto = generar_contenido_seguro(prompt)
            
            return JsonResponse({'respuesta': respuesta_texto})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'Método no permitido'}, status=405)


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
        
        # 📝 AQUÍ SE REGISTRA EL CAMBIO EN LA BITÁCORA
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
                contrasena=contrasena_admin
            )
            
            empresa = Empresa.objects.create(
                nombre=nombre_empresa,
                plan=plan,
                telefono=telefono,
                usuario=nuevo_usuario
            )
            
            # 📝 REGISTRAMOS LA ACCIÓN EN LA BITÁCORA
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
                
                messages.success(request, '��Vacante actualizada exitosamente!')
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
        # Plazas vigentes (fecha l��mite mayor o igual a hoy, o sin fecha l��mite)
        vacantes_activas = Plaza.objects.filter(empresa=empresa).filter(
            Q(fecha_limite__gte=hoy) | Q(fecha_limite__isnull=True)
        ).prefetch_related('tests')
        
        # Plazas anteriores / vencidas (fecha l��mite menor a hoy)
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
                messages.success(request, '��Vacante creada exitosamente!')
                return redirect('empresa_vacantes')
            else:
                messages.error(request, 'Faltan datos obligatorios o no se encontr�� la empresa asociada.')
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
                    contrasena="Temp1234*" # Contraseña temporal inicial
                )

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

        messages.success(request, '¡Prueba finalizada! Tus resultados fueron guardados.')
        return redirect('home_profesionales')

    primera = preguntas.first()
    es_razonamiento = primera is not None and primera.texto_pregunta.strip().lower().endswith(('.png', '.jpg', '.jpeg'))
    if es_razonamiento:
        return render(request, "test_razonamiento.html", {"test": test_obj, "preguntas": preguntas})

    return render(request, "test.html", {"test": test_obj, "preguntas": preguntas})


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

    context = {
        'plaza': plaza,
        'empresa': empresa,
        'tests': tests,
        'invitaciones': invitaciones,
        'resultados': resultados,
    }
    return render(request, 'Empresas/invitar_participantes.html', context)


def evaluacion_invitacion(request, token):
    invitacion = get_object_or_404(InvitacionEvaluacion, token=token)
    next_url = reverse('evaluacion_invitacion', args=[token])

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


def login_view(request):
    next_url = _obtener_next(request)
    if request.method == 'POST':
        username_ingresado = request.POST.get('username')
        password_ingresada = request.POST.get('password')

        try:
            usuario_obj = Usuario.objects.filter(nombre_usuario=username_ingresado, contrasena=password_ingresada).first()
            if not usuario_obj:
                messages.error(request, 'Usuario o contraseña incorrectos.')
                return render(request, 'login.html')

            if not usuario_obj.activo:
                messages.error(request, 'Tu cuenta está desactivada. Contacta al administrador.')
                return render(request, 'login.html')

            from django.contrib.auth.models import User
            django_user, _ = User.objects.get_or_create(username=usuario_obj.nombre_usuario)
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

        try:
            usuario = Usuario.objects.create(
                nombre_usuario=username,
                email=email,
                contrasena=password,
                rol='profesional'
            )

            Persona.objects.create(
                nombre=nombre,
                email=email,
                usuario=usuario
            )

            from django.contrib.auth.models import User
            django_user, creado = User.objects.get_or_create(username=username)
            django_user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, django_user)

            messages.success(request, '��Cuenta creada correctamente! Bienvenido a ReclutaMente.')
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
            if contrasena_actual != usuario.contrasena:
                errores.append('La contraseña actual es incorrecta.')
            elif not contrasena_nueva or contrasena_nueva != contrasena_confirmar:
                errores.append('La nueva contraseña y su confirmación no coinciden.')

        if errores:
            for error in errores:
                messages.error(request, error)
        else:
            try:
                usuario.nombre_usuario = nombre_usuario
                usuario.email = email
                if contrasena_nueva:
                    usuario.contrasena = contrasena_nueva
                usuario.save()

                django_user = request.user
                django_user.username = nombre_usuario
                django_user.email = email
                django_user.save()

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
            if not cuenta or contrasena_actual != cuenta.contrasena:
                errores.append('La contraseña actual es incorrecta.')
            elif not contrasena_nueva or contrasena_nueva != contrasena_confirmar:
                errores.append('La nueva contraseña y su confirmación no coinciden.')

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
                    if contrasena_nueva:
                        cuenta.contrasena = contrasena_nueva
                    cuenta.save()

                    request.user.email = email
                    request.user.save()

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