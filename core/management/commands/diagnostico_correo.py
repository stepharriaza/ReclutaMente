"""Diagnostica la configuración de correo saliente de ReclutaMente."""

import smtplib
import ssl

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Revisa la configuración SMTP y, opcionalmente, envía un correo de '
        'prueba para confirmar que el servidor puede enviar correos.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            help='Correo destino para la prueba de envío.',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=20,
            help='Segundos de espera al conectar con el servidor SMTP (20 por defecto).',
        )

    def handle(self, *args, **options):
        backend = settings.EMAIL_BACKEND
        host = (settings.EMAIL_HOST or '').strip()
        port = settings.EMAIL_PORT
        use_tls = getattr(settings, 'EMAIL_USE_TLS', False)
        use_ssl = getattr(settings, 'EMAIL_USE_SSL', False)
        user = (settings.EMAIL_HOST_USER or '').strip()
        password = settings.EMAIL_HOST_PASSWORD or ''
        from_email = settings.DEFAULT_FROM_EMAIL

        self.stdout.write('Configuración de correo:')
        self.stdout.write(f'  EMAIL_BACKEND      : {backend}')
        self.stdout.write(f'  EMAIL_HOST         : {host or "(vacío)"}')
        self.stdout.write(f'  EMAIL_PORT         : {port}')
        self.stdout.write(f'  EMAIL_USE_TLS      : {use_tls}')
        self.stdout.write(f'  EMAIL_USE_SSL      : {use_ssl}')
        self.stdout.write(f'  EMAIL_HOST_USER    : {user or "(vacío)"}')
        self.stdout.write(
            f'  EMAIL_HOST_PASSWORD: '
            f'{"definida (" + str(len(password)) + " caracteres)" if password else "(vacía)"}'
        )
        self.stdout.write(f'  DEFAULT_FROM_EMAIL : {from_email}')
        self.stdout.write(f'  DEBUG              : {settings.DEBUG}')
        self.stdout.write('')

        if backend.endswith('console.EmailBackend'):
            raise CommandError(
                'El backend es de CONSOLA: los correos solo se imprimen en el '
                'servidor y no se envían. Define EMAIL_HOST (y las demás '
                'variables EMAIL_*) o EMAIL_BACKEND en el entorno del servidor. '
                'EMAIL_PERMITIR_CONSOLA=True solo debe usarse en desarrollo.'
            )

        if backend.endswith('locmem.EmailBackend') or backend.endswith(
            'filebased.EmailBackend'
        ):
            self.stdout.write(
                self.style.WARNING(
                    'El backend no envía correos reales; solo los guarda. '
                    'Configura EMAIL_HOST o EMAIL_BACKEND.'
                )
            )

        if not host:
            raise CommandError(
                'EMAIL_HOST está vacío. Sin servidor SMTP no se pueden enviar correos.'
            )

        self.stdout.write('Probando conexión SMTP...')
        try:
            if use_ssl or port == 465:
                server = smtplib.SMTP_SSL(
                    host,
                    port,
                    timeout=options['timeout'],
                    context=ssl.create_default_context(),
                )
            else:
                server = smtplib.SMTP(host, port, timeout=options['timeout'])
                server.ehlo()
                if use_tls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
            self.stdout.write(self.style.SUCCESS('  Conexión: OK'))
        except Exception as exc:
            raise CommandError(
                f'No se pudo conectar con {host}:{port} -> '
                f'{type(exc).__name__}: {exc}'
            ) from exc

        try:
            if user:
                server.login(user, password)
                self.stdout.write(self.style.SUCCESS('  Login: OK'))
            else:
                self.stdout.write('  Login: omitido (sin EMAIL_HOST_USER)')
        except Exception as exc:
            server.close()
            raise CommandError(
                f'Falló el login SMTP con {user} -> '
                f'{type(exc).__name__}: {exc}'
            ) from exc
        finally:
            try:
                server.quit()
            except Exception:
                pass

        destino = options.get('to')
        if not destino:
            self.stdout.write('')
            self.stdout.write(
                'La conexión funciona. Usa --to TU_CORREO para enviar una '
                'prueba real.'
            )
            return

        self.stdout.write('')
        self.stdout.write(f'Enviando correo de prueba a {destino}...')
        try:
            enviados = send_mail(
                'Prueba de correo - ReclutaMente',
                'Si recibes este mensaje, el envío de correos está configurado '
                'correctamente en este servidor.',
                None,
                [destino],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(
                f'El servidor SMTP aceptó la conexión pero el envío falló -> '
                f'{type(exc).__name__}: {exc}'
            ) from exc

        if enviados:
            self.stdout.write(
                self.style.SUCCESS(f'Correo de prueba enviado a {destino}.')
            )
        else:
            raise CommandError('El backend no envió ningún correo.')
