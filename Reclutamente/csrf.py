"""Manejo amistoso de fallos de CSRF.

Django, por defecto, muestra una página 403 con el motivo técnico. En la
práctica la causa habitual no es un ataque sino un formulario viejo: el
usuario dejó la pestaña abierta, usó "atrás" (bfcache) o envió el formulario
dos veces, y el token ya no coincide con la cookie.

Aquí se registra el fallo y se devuelve al usuario al formulario con un
mensaje, sin ejecutar ninguna acción.
"""

import logging

from django.contrib import messages
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

# Rutas donde se permite volver al mismo formulario.
_FORMULARIOS = ('/login/', '/registro/')


def csrf_failure(request, reason=''):
    logger.warning(
        'CSRF rechazado en %s (%s) por %s: %s',
        request.path,
        request.method,
        request.META.get('REMOTE_ADDR', '?'),
        reason,
    )

    try:
        messages.error(
            request,
            'El formulario estaba desactualizado por seguridad. '
            'Vuelve a intentarlo.',
        )
    except Exception:  # pragma: no cover - sesión no disponible
        pass

    destino = request.path if request.path in _FORMULARIOS else '/login/'
    return redirect(destino)
