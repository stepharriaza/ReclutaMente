"""Vistas de recuperación de contraseña para ReclutaMente."""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from core.auth_utils import (
    actualizar_contrasena,
    codificar_uid,
    decodificar_uid,
    generar_token_recuperacion,
    validar_contrasena,
    validar_token_recuperacion,
)
from core.correo import validar_correo_configurado
from core.models import Usuario

logger = logging.getLogger(__name__)


def _enviar_correo_recuperacion(request, usuario):
    uid = codificar_uid(usuario)
    token = generar_token_recuperacion(usuario)
    reset_url = request.build_absolute_uri(
        reverse('password_reset_confirm', args=[uid, token])
    )
    minutos = max(1, int(getattr(settings, 'PASSWORD_RESET_TIMEOUT', 3600) / 60))
    contexto = {
        'usuario': usuario,
        'reset_url': reset_url,
        'minutos': minutos,
    }
    asunto = 'Recupera tu contraseña - ReclutaMente'
    texto = render_to_string(
        'auth/emails/password_reset_email.txt', contexto, request=request
    )
    html = render_to_string(
        'auth/emails/password_reset_email.html', contexto, request=request
    )

    correo = EmailMultiAlternatives(
        asunto,
        texto,
        settings.DEFAULT_FROM_EMAIL,
        [usuario.email],
    )
    correo.attach_alternative(html, 'text/html')
    validar_correo_configurado()
    correo.send(fail_silently=False)


@never_cache
@sensitive_post_parameters('email')
@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if email:
            usuario = Usuario.objects.filter(
                email__iexact=email,
                activo=True,
            ).first()
            if usuario:
                try:
                    _enviar_correo_recuperacion(request, usuario)
                except Exception:
                    logger.exception(
                        'No se pudo enviar el correo de recuperación de contraseña.'
                    )
        return redirect('password_reset_done')

    return render(request, 'auth/password_reset_form.html')


@never_cache
@require_http_methods(['GET'])
def password_reset_done(request):
    return render(request, 'auth/password_reset_done.html')


@never_cache
@sensitive_post_parameters('password', 'password_confirm')
@require_http_methods(['GET', 'POST'])
def password_reset_confirm(request, uidb64, token):
    usuario = Usuario.objects.filter(pk=decodificar_uid(uidb64)).first()
    validlink = bool(
        usuario
        and usuario.activo
        and validar_token_recuperacion(usuario, token)
    )
    errores = []

    if request.method == 'POST' and validlink:
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        if not password or not password_confirm:
            errores.append('Ingresa la nueva contraseña y su confirmación.')
        elif password != password_confirm:
            errores.append('Las contraseñas no coinciden.')
        else:
            try:
                validar_contrasena(password, usuario)
            except ValidationError as exc:
                errores.extend(exc.messages)

        if not errores:
            try:
                actualizar_contrasena(usuario, password)
            except Exception:
                logger.exception(
                    'No se pudo actualizar la contraseña del usuario.'
                )
                errores.append(
                    'No se pudo actualizar la contraseña. Intenta nuevamente.'
                )
            else:
                return redirect('password_reset_complete')

    return render(
        request,
        'auth/password_reset_confirm.html',
        {
            'validlink': validlink,
            'errores': errores,
        },
    )


@never_cache
@require_http_methods(['GET'])
def password_reset_complete(request):
    return render(request, 'auth/password_reset_complete.html')
