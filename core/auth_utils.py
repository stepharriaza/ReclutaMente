"""Utilidades de autenticación y recuperación de contraseña."""

import hmac

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

User = get_user_model()


def es_contrasena_hasheada(valor):
    if not valor:
        return False
    try:
        identify_hasher(valor)
        return True
    except (TypeError, ValueError):
        return False


def verificar_contrasena(usuario, password):
    if not usuario or not password:
        return False
    almacenada = getattr(usuario, 'contrasena', '') or ''
    if not almacenada:
        return False
    if es_contrasena_hasheada(almacenada):
        return check_password(password, almacenada)
    return hmac.compare_digest(
        str(almacenada).encode('utf-8'),
        str(password).encode('utf-8'),
    )


def validar_contrasena(password, usuario=None, django_user=None):
    if not django_user:
        django_user = User(
            username=getattr(usuario, 'nombre_usuario', '') if usuario else '',
            email=getattr(usuario, 'email', '') if usuario else '',
        )
    validate_password(password, django_user)


def crear_o_actualizar_django_user(usuario, password=None, django_user=None):
    if not usuario:
        return None

    if django_user is None:
        django_user, _ = User.objects.get_or_create(
            username=usuario.nombre_usuario,
            defaults={'email': usuario.email},
        )

    campos = []
    if django_user.username != usuario.nombre_usuario:
        django_user.username = usuario.nombre_usuario
        campos.append('username')
    if usuario.email and django_user.email != usuario.email:
        django_user.email = usuario.email
        campos.append('email')

    if password:
        if (
            not django_user.has_usable_password()
            or not django_user.check_password(password)
        ):
            django_user.set_password(password)
            campos.append('password')

    if campos:
        django_user.save(update_fields=campos)
    return django_user


@transaction.atomic
def actualizar_contrasena(usuario, password_nueva, django_user=None):
    if not usuario or not password_nueva:
        raise ValidationError('La nueva contraseña es obligatoria.')

    usuario.contrasena = make_password(password_nueva)
    usuario.save(update_fields=['contrasena'])
    return crear_o_actualizar_django_user(
        usuario,
        password=password_nueva,
        django_user=django_user,
    )


def codificar_uid(usuario):
    return urlsafe_base64_encode(force_bytes(usuario.pk))


def decodificar_uid(uidb64):
    try:
        return int(force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError):
        return None


class UsuarioPasswordResetTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, usuario, timestamp):
        return (
            f'{usuario.pk}{usuario.contrasena}{usuario.email}'
            f'{usuario.activo}{timestamp}'
        )


usuario_password_reset_token = UsuarioPasswordResetTokenGenerator()


def generar_token_recuperacion(usuario):
    return usuario_password_reset_token.make_token(usuario)


def validar_token_recuperacion(usuario, token):
    if not usuario or not token:
        return False
    return usuario_password_reset_token.check_token(usuario, token)
