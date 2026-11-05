"""Utilidades de configuración de correo."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def validar_correo_configurado():
    """Evita simular envíos con el backend de consola.

    Si el servidor no tiene EMAIL_HOST configurado, Django usa el backend de
    consola: el correo solo se imprime en el log y nunca llega al destinatario.
    Esta validación convierte ese fallo silencioso en un error visible.

    Para desarrollo sin SMTP se puede permitir el backend de consola con
    EMAIL_PERMITIR_CONSOLA=True en el entorno. En producción no debe activarse.
    """
    if not settings.EMAIL_BACKEND.endswith('console.EmailBackend'):
        return
    if getattr(settings, 'EMAIL_PERMITIR_CONSOLA', False):
        return
    raise ImproperlyConfigured(
        'El envío de correos no está configurado en este servidor: '
        'define EMAIL_HOST y las variables EMAIL_* en el entorno.'
    )
