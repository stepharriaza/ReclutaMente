from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from core.models import Usuario, Persona, Empresa


def get_recluta_user(request):
    if not request.user.is_authenticated:
        return None
    user = Usuario.objects.filter(nombre_usuario=request.user.username).first()
    if not user:
        user = Usuario.objects.filter(email=request.user.email).first()
    return user


def rol_requerido(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            usuario = get_recluta_user(request)
            if not usuario:
                messages.error(request, 'Debes iniciar sesión para acceder a esta sección.')
                return redirect('login')

            rol = getattr(usuario, 'rol', None)

            # Si no tiene rol, intentar inferirlo desde Persona o Empresa
            if not rol:
                if Persona.objects.filter(usuario=usuario).exists():
                    rol = 'profesional'
                    usuario.rol = 'profesional'
                    usuario.save(update_fields=['rol'])
                elif Empresa.objects.filter(usuario=usuario).exists():
                    rol = 'empresa'
                    usuario.rol = 'empresa'
                    usuario.save(update_fields=['rol'])
                elif usuario.nombre_usuario == 'superadmin' or usuario.email and 'superadmin' in usuario.email:
                    rol = 'superadmin'
                    usuario.rol = 'superadmin'
                    usuario.save(update_fields=['rol'])
                else:
                    # si no se identifica
                    messages.error(request, 'No se pudo identificar tu rol. Contacta al administrador.')
                    return redirect('login')

            # Si el rol no coincide con el permitido para esta vista
            if rol not in roles:
                if rol == 'profesional':
                    return redirect('home_profesionales')
                elif rol == 'empresa':
                    return redirect('empresa_dashboard')
                elif rol == 'superadmin':
                    return redirect('superadmin_dashboard')
                return redirect('login')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


solo_profesional = rol_requerido('profesional')
solo_empresa = rol_requerido('empresa')
solo_superadmin = rol_requerido('superadmin')